$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements.txt first.' }
# Keep unrelated native libraries on the host PATH out of the portable bundle.
$env:PATH = "$(Split-Path -Parent $python);$env:SystemRoot\System32;$env:SystemRoot"
foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe', 'deno.exe')) {
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot "tools\$tool"))) { throw "Missing tools\$tool" }
}
& $python -c "import sys; sys.path.insert(0,'app'); from PySide6.QtWidgets import QApplication; from main import app_icon; app=QApplication([]); app_icon().pixmap(64,64).save('artifacts/app.ico')"
& $python scripts/collect_licenses.py
& $python -m PyInstaller --noconfirm --onedir --windowed --name 'YouTube Downloader' --icon artifacts/app.ico --paths app app/main.py
if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }
& $python -m PyInstaller --noconfirm --onedir --console --name engine --paths app --collect-all yt_dlp --collect-all yt_dlp_ejs app/backend.py
if ($LASTEXITCODE -ne 0) { throw 'Engine build failed.' }
$package = Join-Path $projectRoot 'dist\YouTube Downloader'
Copy-Item -LiteralPath (Join-Path $projectRoot 'dist\engine') -Destination $package -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $package 'tools') -Force | Out-Null
foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe', 'deno.exe')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "tools\$tool") -Destination (Join-Path $package 'tools') -Force
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md'), (Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md') -Destination $package -Force
if (Test-Path -LiteralPath (Join-Path $projectRoot 'licenses')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot 'licenses') -Destination $package -Recurse -Force
}
Write-Output "Portable app: $package"
