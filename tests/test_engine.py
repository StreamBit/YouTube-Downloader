import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yt_dlp

import backend
from core import AUDIO_FORMATS, VIDEO_FORMATS, EXTENSIONS, qualities

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp('media') / 'sample.mkv'
    subprocess.run([str(ROOT / 'tools/ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
        '-t', '1', '-c:v', 'libvpx-vp9', '-c:a', 'libopus', str(path)], check=True, creationflags=backend.NO_WINDOW)
    return path


@pytest.mark.parametrize('mode,fmt', [('Audio', f) for f in AUDIO_FORMATS] + [('Video', f) for f in VIDEO_FORMATS])
def test_download_conversion_and_duplicate_skip(mode, fmt, clip, tmp_path, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def extract_info(self, *_, **kwargs):
            info = {'id': 'jNQXAC9IVRw', 'title': 'Test: clip?', 'duration': 1}
            if kwargs.get('download'):
                self.process_ie_result(info, True)
            return info
        def process_ie_result(self, info, download):
            dest = Path(self.opts['outtmpl'].replace('%(ext)s', 'mkv'))
            shutil.copy2(clip, dest)
            for hook in self.opts['progress_hooks']:
                hook({'status': 'downloading', 'downloaded_bytes': 10, 'total_bytes': 20})
                hook({'status': 'finished'})
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', FakeYoutubeDL)
    events = []
    monkeypatch.setattr(backend, 'emit', lambda event, **data: events.append((event, data)))
    temp = tmp_path / 'work'
    temp.mkdir()
    request = {'folder': str(tmp_path), 'temp': str(temp), 'mode': mode, 'format': fmt, 'quality': qualities(mode, fmt)[0]}
    item = {'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw'}
    status, path = backend.download_one(item, request, 0, 1)
    assert status == 'success' and Path(path).stat().st_size > 0
    info = json.loads(subprocess.check_output([str(ROOT / 'tools/ffprobe.exe'), '-v', 'error', '-show_streams', '-of', 'json', path], creationflags=backend.NO_WINDOW))
    types = {s['codec_type'] for s in info['streams']}
    assert types == ({'audio'} if mode == 'Audio' else {'audio', 'video'})
    if fmt == 'MP4':
        assert {s['codec_name'] for s in info['streams']} == {'h264', 'aac'}
    assert events[-1][1]['stage'] == 'Finalizing'
    status, again = backend.download_one(item, request, 1, 1)
    assert status == 'skipped' and path == again


def test_queue_deduplicates_single_and_playlist_and_continues_errors(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, _):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def extract_info(self, url, **_):
            if 'badlist' in url:
                raise RuntimeError('Unavailable playlist')
            return {'title': 'My playlist', 'entries': [{'id': 'jNQXAC9IVRw'}, {'id': 'BaW_jenozKc'}]}
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', FakeYoutubeDL)
    queue = backend.resolve_queue({'playlist': True, 'urls': ['https://youtu.be/jNQXAC9IVRw', 'https://youtube.com/playlist?list=goodlist', 'https://youtube.com/playlist?list=badlist']})
    assert len(queue) == 3
    assert queue[1]['index'] == 2
    assert queue[2]['error'] == 'Unavailable playlist'


def test_retry_reexpands_failed_playlist_and_cleans_each_file(tmp_path, monkeypatch):
    items = [{'url': 'https://youtu.be/jNQXAC9IVRw'}]
    monkeypatch.setattr(backend, 'resolve_queue', lambda _: items)
    def fake_download(item, request, index, total):
        work = Path(request['temp']) / str(index)
        work.mkdir()
        (work / 'source.webm').write_bytes(b'temporary')
        return 'success', 'saved.wav'
    monkeypatch.setattr(backend, 'download_one', fake_download)
    events = []
    monkeypatch.setattr(backend, 'emit', lambda kind, **data: events.append((kind, data)))
    backend.run({'temp': str(tmp_path), 'retry_items': [{'url': 'https://youtube.com/playlist?list=test', 'expand': True}]})
    assert events[-1][1]['success'] == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Objects')
def test_cancel_terminates_child_process():
    code = "import sys,time,subprocess; sys.path.insert(0,'app'); import backend; backend.contain_children(); child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(child.pid,flush=True); time.sleep(60)"
    parent = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True, cwd=ROOT, creationflags=backend.NO_WINDOW)
    handle = None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        pid = int(parent.stdout.readline().strip())
        handle = kernel.OpenProcess(0x100000, False, pid)
        assert handle
        parent.kill()
        parent.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if parent.poll() is None:
            parent.kill()
        if handle:
            kernel.CloseHandle(handle)
