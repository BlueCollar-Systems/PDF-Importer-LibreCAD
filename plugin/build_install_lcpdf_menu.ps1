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
$buildDir = Join-Path $repoRoot "plugin\lcpdf_menu"
$candidateDlls = @()
$candidateDlls += Get-ChildItem -Path $buildDir -Filter "bc_lcpdf_menu*.dll" -ErrorAction SilentlyContinue
$candidateDlls += Get-ChildItem -Path (Join-Path $buildDir "release") -Filter "bc_lcpdf_menu*.dll" -ErrorAction SilentlyContinue
$candidateDlls = $candidateDlls | Sort-Object LastWriteTime -Descending
if ($candidateDlls.Count -gt 0) {
    $builtDll = $candidateDlls[0].FullName
    $docs = [Environment]::GetFolderPath("MyDocuments")
    $targetDirs = @(
        (Join-Path $docs "LibreCAD\plugins"),
        (Join-Path $docs "librecad\plugins"),
        (Join-Path $env:USERPROFILE ".librecad\plugins"),
        "C:\Program Files\LibreCAD\resources\plugins",
        "C:\Program Files\LibreCAD\plugins"
    )

    foreach ($dir in $targetDirs) {
        if (Test-Path (Split-Path -Parent $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Copy-Item -LiteralPath $builtDll -Destination (Join-Path $dir ([IO.Path]::GetFileName($builtDll))) -Force
            Copy-Item -LiteralPath $builtDll -Destination (Join-Path $dir "bc_lcpdf_menu.dll") -Force
            Write-Host "Installed plugin to: $dir"
        }
    }
}

Write-Host "Restart LibreCAD. The importer is now available under both the 'Plugins' and 'Tools' menus."
