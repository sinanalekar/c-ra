# VERITAS environment packaging pipeline (Windows)
# Produces the NSIS installer with the Tauri shell + React UI +
# PyInstaller backend sidecar (all five engine adapters inside).
#
# Requirements: Python (with fastapi/uvicorn/pyinstaller), Node,
# Rust GNU toolchain, mingw-w64 binutils (dlltool) on PATH.
param([string]$MingwBin = "$env:TEMP\opencode\mingw64\mingw64\bin")

$ErrorActionPreference = "Stop"

Write-Output "[1/4] backend tests"
Set-Location $PSScriptRoot\..
python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

Write-Output "[2/4] UI build"
Push-Location ui
npm install --no-audit --no-fund
npm run build
Pop-Location

Write-Output "[3/4] backend sidecar (PyInstaller onefile)"
python -m PyInstaller --onefile --name veritas-backend `
  --distpath src-tauri\bin --workpath build\pyinstaller `
  --specpath build --hidden-import environment.app `
  --hidden-import environment.engines tools\backend_entry.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }
$triple = (rustc -vV | Select-String "host:").ToString().Split(":")[1].Trim()
Move-Item "src-tauri\bin\veritas-backend.exe" `
  "src-tauri\bin\veritas-backend-$triple.exe" -Force

Write-Output "[4/4] Tauri build (installer)"
$env:PATH = "$MingwBin;$env:PATH"
npx tauri build

Write-Output "Done. Installer:"
Get-ChildItem src-tauri\target\release\bundle\nsis\*.exe |
  Select-Object FullName, @{N = "MiB"; E = {
    [math]::Round($_.Length / 1MB, 1) } }
