[CmdletBinding()]
param([string] $OutputDir)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Builder = Join-Path $PSScriptRoot 'build_release.py'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    if (Get-Command python -ErrorAction SilentlyContinue) { $Python = 'python' }
    else { throw 'Python not found. Install Python 3.12 or run install_demo.bat.' }
}
$BuildArgs = @($Builder)
if ($OutputDir) { $BuildArgs += @('--output-dir', $OutputDir) }
& $Python @BuildArgs
if ($LASTEXITCODE -ne 0) { throw 'Release build failed. See output above.' }
