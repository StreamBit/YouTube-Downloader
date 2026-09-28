import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
folder = root / 'dist/YouTube Downloader'
archive = root / 'dist/YouTube-Downloader-Windows-x64.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.name != 'settings.json':
            output.write(path, path.relative_to(folder.parent))
with zipfile.ZipFile(archive) as output:
    bad = output.testzip()
    if bad:
        raise RuntimeError(f'Archive verification failed: {bad}')
with archive.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
archive.with_suffix('.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
print(f'{archive}\n{archive.stat().st_size / 1024 / 1024:.1f} MB\nSHA256: {checksum}')
