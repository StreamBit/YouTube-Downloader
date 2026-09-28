from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from core import EXTENSIONS, conversion_args, normalize_url, safe_name

ROOT = Path(sys.executable).parent.parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_job = None


def contain_children():
    """Closing the worker also closes any FFmpeg or JavaScript child process."""
    global _job
    if os.name != 'nt':
        return
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong), ('Flags', wintypes.DWORD), ('Min', ctypes.c_size_t), ('Max', ctypes.c_size_t), ('Active', wintypes.DWORD), ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t), ('JobMemory', ctypes.c_size_t), ('PeakProcessMemory', ctypes.c_size_t), ('PeakJobMemory', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.Basic.Flags = 0x2000
    if not _job or not kernel.SetInformationJobObject(_job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(_job, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), 'Could not create a safe worker process group')


def emit(event, **data):
    print(json.dumps({'event': event, **data}, ensure_ascii=True), flush=True)


class Logger:
    def debug(self, message):
        pass

    def warning(self, message):
        emit('warning', message=message)

    def error(self, message):
        emit('warning', message=message)


def options():
    return {'quiet': True, 'no_warnings': False, 'logger': Logger(), 'ffmpeg_location': str(TOOLS),
            'js_runtimes': {'deno': {'path': str(TOOLS / 'deno.exe')}},
            'socket_timeout': 20, 'retries': 3, 'fragment_retries': 3, 'windowsfilenames': True,
            'cachedir': False, 'noplaylist': True, 'remote_components': set()}


def metadata(request):
    import yt_dlp
    url = normalize_url(request['url'])
    playlist_only = '/playlist?' in url
    opts = options()
    opts.update({'skip_download': True, 'extract_flat': 'in_playlist', 'playlistend': 1, 'noplaylist': not playlist_only})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError('No video information was returned.')
    thumbnail = info.get('thumbnail')
    if not thumbnail and info.get('thumbnails'):
        thumbnail = info['thumbnails'][-1]['url']
    emit('metadata', title=info.get('title', 'Untitled'), channel=info.get('channel') or info.get('uploader') or 'YouTube',
         duration=info.get('duration'), thumbnail=thumbnail,
         resolutions=sorted({int(f['height']) for f in info.get('formats', []) if f.get('height') and f.get('vcodec') != 'none'}, reverse=True),
         playlist=playlist_only)


def resolve_queue(request):
    import yt_dlp
    queue, seen = [], set()
    for raw in request['urls']:
        url = normalize_url(raw, request['playlist'])
        if request['playlist'] and 'list=' in url:
            emit('preparing', message='Preparing playlist…')
            opts = options() | {'extract_flat': 'in_playlist', 'noplaylist': False, 'ignoreerrors': True}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:
                queue.append({'url': url, 'error': str(e), 'expand': True})
                continue
            if not info:
                queue.append({'url': url, 'error': 'Could not read this playlist.', 'expand': True})
                continue
            entries = info.get('entries') or []
            if not entries:
                queue.append({'url': url, 'error': 'This playlist has no available videos.', 'expand': True})
            for index, entry in enumerate(entries, 1):
                if not entry:
                    queue.append({'url': url, 'error': f'Playlist item {index} is unavailable.', 'expand': True})
                    continue
                vid = entry.get('id')
                key = f'https://www.youtube.com/watch?v={vid}'
                if vid and key not in seen:
                    seen.add(key)
                    queue.append({'url': key, 'playlist_title': info.get('title', 'Playlist'), 'index': index})
        else:
            key = normalize_url(url, False)
            if key not in seen:
                seen.add(key)
                queue.append({'url': key})
    return queue


def download_one(item, request, index, total):
    import yt_dlp
    work = Path(request['temp']) / str(index)
    work.mkdir(parents=True)
    fraction = 0.0
    def progress(stage, part=None):
        nonlocal fraction
        if part is not None:
            fraction = max(fraction, min(part, .99))
        emit('progress', stage=stage, fraction=fraction, index=index, total=total, indeterminate=part is None)
    progress('Preparing')
    opts = options()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(item['url'], download=False)
    if not info:
        raise RuntimeError('The video is unavailable.')
    if info.get('is_live'):
        raise RuntimeError('This video is still live. Try again after the broadcast ends.')
    title = info.get('title') or info['id']
    emit('current', title=title, index=index, total=total)
    folder = Path(request['folder'])
    prefix = ''
    if item.get('playlist_title'):
        folder /= safe_name(item['playlist_title'], 65)
        prefix = f"{item['index']:03d} - "
    folder.mkdir(parents=True, exist_ok=True)
    ext = EXTENSIONS.get(request['format'], request['format'].lower())
    destination = folder / f"{prefix}{safe_name(title)} [{safe_name(info['id'])}].{ext}"
    if destination.exists():
        return 'skipped', str(destination)
    tracks = {}
    expected_tracks = max(1, len(info.get('requested_formats') or [])) if request['mode'] == 'Video' else 1
    def hook(data):
        key = data.get('filename', 'source')
        if data['status'] == 'downloading':
            size = data.get('total_bytes') or data.get('total_bytes_estimate')
            # The last fifth is reserved for conversion and finalization.
            if size:
                tracks[key] = min(1, data.get('downloaded_bytes', 0) / size)
            part = .78 * sum(tracks.values()) / max(expected_tracks, len(tracks)) if size else None
            progress('Downloading', part)
        elif data['status'] == 'finished':
            tracks[key] = 1
            part = .78 * sum(tracks.values()) / max(expected_tracks, len(tracks))
            progress('Preparing conversion' if part >= .78 else 'Downloading', part)
    quality = request['quality']
    cap = '' if quality == 'Best available' else f'[height<={int(quality.rstrip("p"))}]' if request['mode'] == 'Video' else ''
    opts.update({'format': 'bestaudio/best' if request['mode'] == 'Audio' else f'bestvideo{cap}+bestaudio/best{cap}',
                 'outtmpl': str(work / 'source.%(ext)s'), 'merge_output_format': 'mkv', 'progress_hooks': [hook],
                 'postprocessor_hooks': [lambda d: progress('Combining video and audio' if d.get('postprocessor') == 'Merger' else 'Preparing conversion', .80)], 'overwrites': False})
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(item['url'], download=True)
    sources = [p for p in work.glob('source.*') if p.suffix not in ('.part', '.ytdl') and '.f' not in p.name]
    if not sources:
        raise RuntimeError('The download did not produce a media file.')
    source = max(sources, key=lambda p: p.stat().st_size)
    probe_result = subprocess.run([str(TOOLS / 'ffprobe.exe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(source)], capture_output=True, text=True, creationflags=NO_WINDOW, check=True)
    probe = json.loads(probe_result.stdout)
    duration = float(probe.get('format', {}).get('duration') or info.get('duration') or 0)
    output = work / ('finished.' + ext)
    args = [str(TOOLS / 'ffmpeg.exe'), '-nostdin', '-hide_banner', '-loglevel', 'error', '-n', '-i', str(source)]
    args += conversion_args(request['mode'], request['format'], quality, probe)
    args += ['-metadata', 'title=' + title, '-progress', 'pipe:1', str(output)]
    progress('Converting', .82)
    with (work / 'ffmpeg.log').open('w+', encoding='utf-8') as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8', creationflags=NO_WINDOW)
        for line in process.stdout:
            if line.startswith('out_time_us=') and duration:
                try:
                    progress('Converting', .82 + .16 * min(float(line.split('=')[1]) / 1_000_000 / duration, 1))
                except ValueError:
                    pass
        if process.wait():
            errors.seek(0)
            raise RuntimeError(errors.read()[-2000:] or 'Conversion failed.')
    progress('Finalizing', .99)
    if not output.exists() or not output.stat().st_size:
        raise RuntimeError('Conversion produced an empty file.')
    try:
        output.rename(destination)
    except FileExistsError:
        return 'skipped', str(destination)
    return 'success', str(destination)


def run(request):
    if request.get('retry_items'):
        queue = []
        expanded = set()
        for item in request['retry_items']:
            if item.get('expand'):
                if item['url'] not in expanded:
                    queue.extend(resolve_queue(request | {'urls': [item['url']]}))
                    expanded.add(item['url'])
            else:
                queue.append(item)
    else:
        queue = resolve_queue(request)
    if not queue:
        raise RuntimeError('No downloadable videos were found in this run.')
    counts = {'success': 0, 'failed': 0, 'skipped': 0}
    failures = []
    emit('queue', total=len(queue))
    for index, item in enumerate(queue):
        emit('current', title=item['url'], index=index, total=len(queue))
        try:
            if item.get('error'):
                raise RuntimeError(item['error'])
            status, path = download_one(item, request, index, len(queue))
            counts[status] += 1
            emit('item_done', status=status, path=path, index=index, total=len(queue))
        except Exception as e:
            counts['failed'] += 1
            failures.append(item)
            emit('item_done', status='failed', message=str(e), url=item['url'], index=index, total=len(queue))
        finally:
            shutil.rmtree(Path(request['temp']) / str(index), ignore_errors=True)
    emit('done', **counts, failures=failures)


def main():
    try:
        contain_children()
        request = json.loads(sys.stdin.readline())
        if request['action'] == 'metadata':
            metadata(request)
        else:
            run(request)
    except Exception as e:
        emit('error', message=str(e))
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
