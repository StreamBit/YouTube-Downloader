from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

AUDIO_FORMATS = ['WAV', 'MP3', 'M4A', 'AAC', 'FLAC', 'Ogg Vorbis', 'Opus']
VIDEO_FORMATS = ['MP4', 'MKV', 'WebM', 'MOV']
RESOLUTIONS = ['Best available', '2160p', '1440p', '1080p', '720p', '480p', '360p', '240p', '144p']
EXTENSIONS = {'Ogg Vorbis': 'ogg', 'M4A': 'm4a', 'Opus': 'opus'}


def qualities(mode: str, fmt: str) -> list[str]:
    if mode == 'Video':
        return RESOLUTIONS.copy()
    if fmt in ('WAV', 'FLAC'):
        return ['Source matched', '16-bit / 44.1 kHz', '16-bit / 48 kHz', '24-bit / 48 kHz']
    if fmt == 'Opus':
        return ['192 kbps', '256 kbps', '128 kbps', '96 kbps', '64 kbps']
    if fmt == 'Ogg Vorbis':
        return ['High (quality 6)', 'Maximum (quality 10)', 'Standard (quality 4)', 'Small (quality 2)']
    return ['320 kbps', '256 kbps', '192 kbps', '128 kbps', '96 kbps']


def normalize_url(text: str, playlist: bool = True) -> str:
    text = text.strip()
    if text.startswith(('youtube.com/', 'www.youtube.com/', 'youtu.be/', 'm.youtube.com/', 'music.youtube.com/')):
        text = 'https://' + text
    p = urlparse(text)
    if p.scheme not in ('http', 'https') or p.username or p.password or p.port:
        raise ValueError('Enter a YouTube video or playlist URL.')
    host = (p.hostname or '').lower()
    query = parse_qs(p.query)
    vid = None
    if host == 'youtu.be':
        vid = p.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if p.path == '/watch':
            vid = query.get('v', [None])[0]
        elif p.path.startswith(('/shorts/', '/live/', '/embed/')):
            vid = p.path.split('/')[2]
        elif p.path != '/playlist':
            raise ValueError('Use a video or playlist URL, rather than a channel URL.')
    else:
        raise ValueError('Only YouTube video and playlist URLs are supported.')
    if vid and not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
        raise ValueError('This YouTube video ID is incomplete or invalid.')
    list_id = query.get('list', [None])[0]
    if list_id and not re.fullmatch(r'[A-Za-z0-9_-]+', list_id):
        raise ValueError('This playlist ID is invalid.')
    if not vid and not list_id:
        raise ValueError('The URL needs a video or playlist ID.')
    if not playlist and not vid:
        raise ValueError('Enable Playlist mode to download a playlist-only URL.')
    args = {}
    if vid:
        args['v'] = vid
    if list_id and playlist:
        args['list'] = list_id
    return 'https://www.youtube.com/' + ('watch?' if vid else 'playlist?') + urlencode(args)


def parse_bulk(text: str) -> tuple[list[str], list[str], int]:
    urls, errors, seen = [], [], set()
    duplicates = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            url = normalize_url(line)
            if url in seen:
                duplicates += 1
            else:
                urls.append(url)
                seen.add(url)
        except ValueError as e:
            errors.append(f'Line {number}: {e}')
    return urls, errors, duplicates


def safe_name(value: str, limit: int = 95) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:limit].rstrip(' .') or 'Untitled'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        value = '_' + value
    return value


@dataclass
class Settings:
    dark: bool = True
    mode: str = ''
    format: str = ''
    quality: str = ''
    folder: str = ''
    playlist: bool = False

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            defaults = cls()
            clean = {f.name: data[f.name] for f in fields(cls)
                     if f.name in data and type(data[f.name]) is type(getattr(defaults, f.name))}
            result = cls(**clean)
            formats = AUDIO_FORMATS if result.mode == 'Audio' else VIDEO_FORMATS if result.mode == 'Video' else []
            if result.format not in formats:
                result.format = ''
            if result.quality not in qualities(result.mode, result.format):
                result.quality = ''
            if result.mode not in ('Audio', 'Video'):
                result.mode = ''
            return result
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(self), indent=2), encoding='utf-8')
        temp.replace(path)


def conversion_args(mode: str, fmt: str, quality: str, probe: dict) -> list[str]:
    streams = probe.get('streams', [])
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
    video = next((s for s in streams if s.get('codec_type') == 'video'), {})
    if mode == 'Audio':
        args = ['-vn', '-map', '0:a:0']
        codec = {'WAV': 'pcm_s16le', 'FLAC': 'flac', 'MP3': 'libmp3lame', 'M4A': 'aac', 'AAC': 'aac', 'Ogg Vorbis': 'libvorbis', 'Opus': 'libopus'}[fmt]
        args += ['-c:a', codec]
        if fmt in ('WAV', 'FLAC'):
            bits = 24 if quality.startswith('24-bit') else 16
            rate = int(audio.get('sample_rate') or 48000) if quality == 'Source matched' else 44100 if '44.1' in quality else 48000
            args += ['-ar', str(rate)]
            if fmt == 'WAV':
                args[args.index('pcm_s16le')] = 'pcm_s24le' if bits == 24 else 'pcm_s16le'
            else:
                args += ['-sample_fmt', 's32' if bits == 24 else 's16']
        elif fmt == 'Ogg Vorbis':
            args += ['-q:a', re.search(r'quality (\d+)', quality).group(1)]
        else:
            args += ['-b:a', quality.split()[0] + 'k']
        if fmt == 'M4A':
            args += ['-movflags', '+faststart']
        return args
    args = ['-map', '0:v:0', '-map', '0:a:0']
    if fmt == 'MKV':
        return args + ['-c', 'copy']
    if fmt == 'WebM':
        if video.get('codec_name') in ('vp8', 'vp9', 'av1'):
            args += ['-c:v', 'copy']
        else:
            args += ['-c:v', 'libvpx-vp9', '-crf', '28', '-b:v', '0']
        return args + (['-c:a', 'copy'] if audio.get('codec_name') == 'opus' else ['-c:a', 'libopus', '-b:a', '192k'])
    args += ['-c:v', 'copy'] if video.get('codec_name') == 'h264' else ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p']
    args += ['-c:a', 'copy'] if audio.get('codec_name') == 'aac' else ['-c:a', 'aac', '-b:a', '320k']
    return args + ['-movflags', '+faststart']
