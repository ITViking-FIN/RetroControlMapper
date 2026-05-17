# build.ps1 - build RetroControlMapper.exe via PyInstaller.
#
# Usage:  .\build.ps1
# Output: dist\RetroControlMapper.exe
#
# Prerequisites: Python 3.14 on PATH (via the `py` launcher), all the
# runtime deps from requirements.txt installed, and PyInstaller installed
# (this script will install/upgrade it if missing).
#
# After this builds, hand the .exe to the installer build script:
# installer\build-installer.ps1.

$ErrorActionPreference = 'Stop'

# v0.1.6: pre-build smoke test. Fail the build if the headline feature
# (bindings_lookup -> bindings_db) regresses end-to-end. v0.1.5 shipped
# this feature 0% functional because nothing caught the key-normaliser
# gap; this gate makes sure we don't repeat that.
Write-Host "==> Running bindings_lookup smoke test..."
py tests\smoke_bindings_lookup.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "bindings_lookup smoke test failed - refusing to build a regressed release."
    exit $LASTEXITCODE
}

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
$exe = 'dist\RetroControlMapper.exe'
if (Test-Path $exe) {
    $size = (Get-Item $exe).Length / 1MB
    $sizeStr = [math]::Round($size, 1)
    Write-Host ""
    Write-Host "Built $exe ($sizeStr MB)"
    Write-Host "  Hand to installer: pass to installer\build-installer.ps1"
} else {
    Write-Error "PyInstaller did not produce the expected .exe at $exe"
    exit 1
}
