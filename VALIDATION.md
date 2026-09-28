# Validation

Tested on Windows 10 x64, September 28, 2026.

- 43 automated checks passed: URL validation, duplicate handling, settings privacy and recovery, required fields, mode/format switching, bulk input, thumbnail handling, progress completion, queue expansion/retries, filename sanitization, Windows process-tree cancellation, and startup window sizing.
- Startup sizing was checked against large and small work areas, including secondary monitors with positive and negative coordinates. The complete layout opens without scrollbars when space permits; smaller work areas retain scrolling and keep the window within the screen.
- Real FFmpeg conversions passed for all 11 supported formats. Output streams were checked with FFprobe. MP4 output was verified to contain H.264 video and AAC audio. Existing outputs were preserved and skipped.
- A short public YouTube video was downloaded successfully as WAV and MP4.
- The packaged engine completed a WAV download without using the development Python interpreter.
- An interface-to-packaged-engine smoke test loaded the title, channel, duration, and thumbnail, created WAV output, reported completion, and removed its temporary directory.
- Dark and light interfaces were rendered and visually inspected. The packaged Windows app was opened and its native accessibility tree and live preview inspected.

The desktop capture tool could not capture this Windows build, so visual review used Qt-rendered screenshots. Live large-playlist downloads and downloads requiring sign-in were not tested. Playlist expansion, deduplication, failure isolation, and retry behavior were checked with controlled fixtures.

Run `python -m pytest -q` using the project virtual environment for offline checks. `scripts/smoke_gui.py` runs a network smoke test against the packaged engine; it writes its report and screenshot to `artifacts` and removes downloaded test media afterward.
