# Kept for existing instructions: builds, load-tests and installs the LibreCAD
# menu plugin via scripts/build_librecad_plugin.py.
param(
    [string]$QtRoot = "C:\Qt\5.15.2\msvc2019_64"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
& $python (Join-Path $repoRoot "scripts\build_librecad_plugin.py") --qt-root $QtRoot --smoke --install
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build/install failed with exit code $LASTEXITCODE"
}
Write-Host "Restart LibreCAD and open the Plugins menu: Import PDF (BlueCollar)..."
