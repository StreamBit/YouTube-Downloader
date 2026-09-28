# Third-party components

This package uses the following open-source projects. License texts are in `licenses`; project and source links are below.

- PySide6 / Qt 6.11.2: LGPLv3 / GPLv3 / commercial terms. https://www.qt.io/licensing/ and https://code.qt.io/cgit/pyside/pyside-setup.git/
- Python 3.14: PSF License. https://www.python.org/downloads/source/
- yt-dlp 2026.08.19: Unlicense. https://github.com/yt-dlp/yt-dlp
- yt-dlp-ejs 0.8.0: Unlicense. https://github.com/yt-dlp/ejs
- FFmpeg 7.0.2 full build: GPLv3 build from Gyan. Build release: https://github.com/GyanD/codexffmpeg/releases/tag/7.0.2. FFmpeg source used for this build: https://github.com/FFmpeg/FFmpeg/tree/e3a61e9103.
- Deno 2.9.7: MIT License and bundled third-party licenses. https://github.com/denoland/deno
- PyInstaller: GPLv2 with an exception allowing distribution of bundled applications. https://pyinstaller.org/en/stable/license.html

The FFmpeg source link identifies the upstream FFmpeg revision. It does not cover every external library statically linked into Gyan's full build, and this package does not include a verified complete corresponding source bundle for those executables.

Qt is dynamically linked in `_internal`; users can replace those libraries with compatible versions. The downloader and FFmpeg are separate executables. Preserve license notices when redistributing. Consult the upstream source and license terms for source-distribution obligations when sharing bundled binaries.
