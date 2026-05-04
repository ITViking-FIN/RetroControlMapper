# build.ps1 — build RetroControlMapper.exe via PyInstaller.
#
# Usage:  .\build.ps1
# Output: dist\RetroControlMapper.exe
#
# Prerequisites: Python 3.14 on PATH (via the `py` launcher), all the
# runtime deps from requirements.txt installed, and PyInstaller installed
# (this script will install/upgrade it if missing).
#
# After this builds, hand the .exe to Stream IS's installer build —
# installer\build-installer.ps1 (when that lands).

$ErrorActionPreference = 'Stop'

# Ensure pyinstaller is available. Pinned to >=6 because earlier majors
# have known bugs with --onefile + pystray on Windows 11.
Write-Host "==> Ensuring PyInstaller is installed..."
py -m pip install --upgrade 'pyinstaller>=6.0,<7.0'

# Clean previous build artefacts. PyInstaller's --clean only purges its
# own caches; we also wipe build/ and dist/ to make this fully
# reproducible.
if (Test-Path build) {
    Write-Host "==> Removing old build/ ..."
    Remove-Item -Recurse -Force build
}
if (Test-Path dist) {
    Write-Host "==> Removing old dist/ ..."
    Remove-Item -Recurse -Force dist
}

# Build.
Write-Host "==> Running PyInstaller..."
py -m PyInstaller --clean rbcf.spec

# Surface the result.
$exe = "dist\RetroControlMapper.exe"
if (Test-Path $exe) {
    $size = (Get-Item $exe).Length / 1MB
    Write-Host ""
    Write-Host "Built $exe  ($([math]::Round($size, 1)) MB)"
    Write-Host "  Test:                  .\$exe"
    Write-Host "  Hand to installer:     pass to installer\build-installer.ps1"
} else {
    Write-Error "PyInstaller did not produce the expected .exe at $exe"
    exit 1
}
