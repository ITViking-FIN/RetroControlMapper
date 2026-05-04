# build-installer.ps1 - thin wrapper around iscc.exe.
# Run from this directory (installer\).
#
# Prerequisites:
#   1. Stream PI's ..\build.ps1 has produced ..\dist\RetroControlMapper.exe.
#   2. Inno Setup 6+ is installed and iscc.exe is on PATH.
#   3. RetroControlMapper.ico has been generated (see README.md step 2)
#      OR SetupIconFile in the .iss has been commented out.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$exe = Join-Path $here '..\dist\RetroControlMapper.exe'
if (-not (Test-Path $exe)) {
    Write-Error "Application binary not found at $exe. Run ..\build.ps1 first."
    exit 1
}

$iss = Join-Path $here 'RetroControlMapper.iss'
if (-not (Test-Path $iss)) {
    Write-Error "Inno script not found at $iss."
    exit 1
}

# Locate iscc.exe — prefer PATH, fall back to standard install location.
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $candidates = @(
        'C:\Program Files (x86)\Inno Setup 6\iscc.exe',
        'C:\Program Files\Inno Setup 6\iscc.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $iscc = $c; break }
    }
}
if (-not $iscc) {
    Write-Error "iscc.exe not found. Install Inno Setup 6+ from https://jrsoftware.org/isdl.php and ensure iscc.exe is on PATH."
    exit 1
}

Write-Host "Compiling $iss with $iscc ..."
& $iscc $iss
if ($LASTEXITCODE -ne 0) {
    Write-Error "iscc.exe exited with code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$out = Join-Path $here 'output\RetroControlMapper_0.1.0_setup.exe'
if (Test-Path $out) {
    Write-Host ""
    Write-Host "Installer built successfully:" -ForegroundColor Green
    Write-Host "  $out"
} else {
    Write-Warning "iscc reported success but expected output not found at $out"
}
