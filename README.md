# YouTube Downloader

A portable Windows desktop app for saving YouTube videos and audio. Run **YouTube Downloader.exe** from the release folder. Keep the `engine`, `_internal`, and `tools` folders beside it. No Python installation is needed for the packaged app.

## Using the app

1. Paste a YouTube video, Shorts, or playlist URL. The preview loads automatically.
2. Choose Video or Audio, a file type, quality, and an existing output folder.
3. Enable Playlist mode if you want every item in the linked playlist.
4. Click Run. For several links, open Add bulk URLs, enter one URL per line, save the list, and click Bulk Run.

Audio starts with WAV. The smaller progress bar shows the current stage; the larger bar estimates the entire run, including conversion and finalization. Downloading, conversion, and finalization can take different amounts of time, so the estimate is not an ETA.

Cancel stops the run and keeps completed files. Open output folder opens the chosen folder. Run details show failures and warnings; Retry failed retries failed items with the original run settings. Existing destination files are skipped. Filenames include video IDs to distinguish identical titles. Playlist output is numbered inside a playlist folder. Videos repeated across the queue are downloaded once.

Preferences are saved in `settings.json` beside the app. URLs, the bulk list, and run details are never saved as preferences. The app starts in dark mode; the toggle at the top right changes and remembers the theme. Keep the portable folder somewhere writable.

The starting window size follows the layout and the screen's available space, including display scaling and the taskbar. It opens without scrollbars when the layout fits. Smaller screens keep scrolling available so every control remains reachable.

## Formats and quality

- Video: MP4, MKV, WebM, MOV. Resolution is a maximum; the app uses the best source at or below it and never upscales.
- Audio: WAV, MP3, M4A, AAC, FLAC, Ogg Vorbis, Opus.
- WAV/FLAC: source sample rate with 16-bit output, or explicit 16/24-bit presets. Lossless conversion cannot restore detail absent from YouTube's source audio.
- MP4/MOV use H.264 and AAC for compatibility. Compatible source tracks are copied; other tracks are converted. MKV preserves source codecs. WebM uses compatible video and Opus audio.
- The best available source audio accompanies video. Re-encoding may take time, particularly for high-resolution WebM output.

The first version supports publicly accessible videos and playlists. Login-required videos, DRM, and in-progress livestream recording are outside its scope. YouTube may rate-limit requests or require sign-in; those failures appear in run details. Preview availability does not guarantee a video is downloadable. YouTube changes can require updating yt-dlp and rebuilding the engine.

## Development

Python 3.14 and Windows x64 were used for this build.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app\main.py
.\.venv\Scripts\python.exe -m pytest -q
```

Place Windows x64 builds of `ffmpeg.exe`, `ffprobe.exe`, and `deno.exe` in `tools`. The bundled FFmpeg must include libx264, libvpx, libopus, libvorbis, and libmp3lame.

The packaged Gyan FFmpeg 7.0.2 full build points to [this FFmpeg source revision](https://github.com/FFmpeg/FFmpeg/tree/e3a61e9103). See `THIRD_PARTY_NOTICES.md` for the build release and source-distribution note.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

The result is `dist\YouTube Downloader`. The GUI and downloader run in separate processes. A Windows Job Object terminates downloader children on cancellation, including FFmpeg and Deno. Each run uses an isolated temporary folder under its output directory, removed after the worker exits. Completed files are moved into place only after conversion succeeds. If Windows or the app crashes, a leftover `.ytd-work-*` folder can be removed after confirming the app is closed.
