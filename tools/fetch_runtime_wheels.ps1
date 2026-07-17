# fetch_runtime_wheels.ps1
# Windows convenience wrapper around the canonical transactional installer.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\tools\fetch_runtime_wheels.ps1
#
# Copyright 2024-2026 BlueCollar Systems — BUILT. NOT BOUGHT.

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Preflight = Join-Path $RepoRoot 'preflight_check.py'
if (-not (Test-Path -LiteralPath $Preflight -PathType Leaf)) {
    throw "LibreCAD PDF Importer preflight was not found: $Preflight"
}

Push-Location -LiteralPath $RepoRoot
try {
    python $Preflight --install
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime dependency preflight failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "Runtime dependencies passed the canonical isolated probe."
