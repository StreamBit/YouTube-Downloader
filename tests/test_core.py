import json
import pytest

from core import Settings, conversion_args, normalize_url, parse_bulk, safe_name


def test_url_normalization_and_playlist_policy():
    assert normalize_url('https://youtu.be/BaW_jenozKc?t=12') == 'https://www.youtube.com/watch?v=BaW_jenozKc'
    assert normalize_url('https://www.youtube.com/watch?v=BaW_jenozKc&list=PL123', False).endswith('v=BaW_jenozKc')
    with pytest.raises(ValueError, match='Enable Playlist'):
        normalize_url('https://www.youtube.com/playlist?list=PL123', False)


@pytest.mark.parametrize('url', ['file:///C:/test', 'https://youtube.com.evil.com/watch?v=BaW_jenozKc', 'https://evil.com', 'https://youtube.com/@channel', 'https://youtube.com/watch?v=short', 'https://user:pass@youtube.com/watch?v=BaW_jenozKc', 'https://youtube.com:bad/watch?v=BaW_jenozKc'])
def test_reject_invalid_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_bulk_deduplicates_equivalent_links_and_reports_line():
    urls, errors, duplicates = parse_bulk('https://youtu.be/BaW_jenozKc\n\nhttps://youtube.com/watch?v=BaW_jenozKc\ninvalid')
    assert len(urls) == 1
    assert duplicates == 1
    assert errors[0].startswith('Line 4:')


def test_settings_exclude_urls_and_recover_from_bad_data(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"mode":"Audio","format":"WAV","quality":"Source matched","dark":false,"urls":["secret"],"folder":null}')
    settings = Settings.load(path)
    assert settings.dark is False
    assert settings.folder == ''
    settings.save(path)
    assert 'urls' not in json.loads(path.read_text())
    path.write_text('broken')
    assert Settings.load(path) == Settings()


@pytest.mark.parametrize('title', ['CON', 'A/B:C?D', '..', 'LPT1.txt', 'trailing. ', 'x' * 200])
def test_windows_filenames(title):
    result = safe_name(title)
    assert not any(c in result for c in '<>:"/\\|?*')
    assert result and len(result) <= 96 and not result.endswith(('.', ' '))


def test_audio_and_video_encoding_policy():
    probe = {'streams': [{'codec_type': 'audio', 'codec_name': 'opus', 'sample_rate': '48000'}, {'codec_type': 'video', 'codec_name': 'vp9'}]}
    wav = conversion_args('Audio', 'WAV', 'Source matched', probe)
    assert 'pcm_s16le' in wav and '48000' in wav and '-b:a' not in wav
    assert 'pcm_s24le' in conversion_args('Audio', 'WAV', '24-bit / 48 kHz', probe)
    mp4 = conversion_args('Video', 'MP4', '1080p', probe)
    assert 'libx264' in mp4 and 'aac' in mp4 and '320k' in mp4
    assert conversion_args('Video', 'MKV', '1080p', probe)[-2:] == ['-c', 'copy']
