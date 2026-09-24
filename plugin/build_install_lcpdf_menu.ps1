param(
    [string]$QtRoot = "C:\Qt\5.15.2\msvc2019_64",
    [string]$VsVcVars = "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginProj = Join-Path $repoRoot "plugin\lcpdf_menu\lcpdf_menu.pro"
$buildDir = Join-Path $repoRoot "plugin\lcpdf_menu"

if (-not (Test-Path $pluginProj)) {
    throw "Plugin project file not found: $pluginProj"
}
if (-not (Test-Path (Join-Path $QtRoot "bin\qmake.exe"))) {
    throw "qmake not found under QtRoot: $QtRoot"
}
if (-not (Test-Path $VsVcVars)) {
    throw "vcvars64.bat not found: $VsVcVars"
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "LibreCAD\plugins"
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$qmake = Join-Path $QtRoot "bin\qmake.exe"

$cmd = @(
    "call `"$VsVcVars`"",
    "cd /d `"$buildDir`"",
    "`"$qmake`" `"$pluginProj`"",
    "nmake /nologo clean",
    "nmake /nologo"
) -join " && "

Write-Host "Building plugin..."
cmd /c $cmd
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build failed with exit code $LASTEXITCODE"
}

$candidateDlls = @()
$candidateDlls += Get-ChildItem -Path $buildDir -Filter "bc_lcpdf_menu*.dll" -ErrorAction SilentlyContinue
$candidateDlls += Get-ChildItem -Path (Join-Path $buildDir "release") -Filter "bc_lcpdf_menu*.dll" -ErrorAction SilentlyContinue
$candidateDlls = $candidateDlls | Sort-Object LastWriteTime -Descending
if ($candidateDlls.Count -eq 0) {
    throw "Built plugin DLL not found."
}

$builtDll = $candidateDlls[0].FullName
$docs = [Environment]::GetFolderPath("MyDocuments")
$targetDirs = @(
    (Join-Path $docs "LibreCAD\plugins"),
    (Join-Path $docs "librecad\plugins"),
    (Join-Path $env:USERPROFILE ".librecad\plugins")
)
if (-not [string]::IsNullOrWhiteSpace($InstallDir) -and ($targetDirs -notcontains $InstallDir)) {
    $targetDirs += $InstallDir
}

foreach ($dir in $targetDirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Copy-Item -LiteralPath $builtDll -Destination (Join-Path $dir ([IO.Path]::GetFileName($builtDll))) -Force
    Copy-Item -LiteralPath $builtDll -Destination (Join-Path $dir "bc_lcpdf_menu.dll") -Force
    Write-Host "Installed plugin to: $dir"
}

Write-Host "Restart LibreCAD. The importer is now available under both the 'Plugins' and 'Tools' menus."
