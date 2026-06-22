# fetch_runtime_wheels.ps1
# Vendor PyMuPDF + ezdxf wheels into ./lib for offline release zips.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\tools\fetch_runtime_wheels.ps1
#
# Copyright 2024-2026 BlueCollar Systems — BUILT. NOT BOUGHT.

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LibDir = Join-Path $RepoRoot 'lib'
$TempDir = Join-Path $env:TEMP ('bc_lc_wheels_' + [guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Force -Path $LibDir | Out-Null
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

Write-Host "Installing runtime wheels into lib/ ..."
python -m pip install --upgrade pip | Out-Null
python -m pip install --target $LibDir --upgrade --no-cache-dir "PyMuPDF>=1.24,<2.0" ezdxf

@'
Vendored Python wheels for LibreCAD PDF Importer release builds.

Installed by tools/fetch_runtime_wheels.ps1:
  PyMuPDF (fitz)
  ezdxf
'@ | Set-Content -Path (Join-Path $LibDir 'THIRD_PARTY_NOTICES.txt') -Encoding UTF8

Write-Host "Runtime wheels ready in:"
Write-Host "  $LibDir"

Remove-Item -Recurse -Force $TempDir
