param([string]$Python = 'python', [string]$BuildRoot = '')
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$projectRoot = Split-Path $sourceRoot -Parent
if (-not $BuildRoot) { $BuildRoot = Join-Path $projectRoot 'portable' }
& (Join-Path $sourceRoot 'native\build.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
& $Python (Join-Path $sourceRoot 'package_runtime.py') $projectRoot $BuildRoot
if ($LASTEXITCODE -ne 0) { throw 'Runtime bundling failed' }
Copy-Item -LiteralPath (Join-Path $sourceRoot 'native\VoiceChanger.exe') -Destination $BuildRoot -Force
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$redist = Get-ChildItem -LiteralPath (Join-Path $vs 'VC\Redist\MSVC') -Directory | Where-Object { $_.Name -match '^\d' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'x64')) } | Sort-Object Name -Descending | Select-Object -First 1
if ($redist) {
    $crt = Get-ChildItem -LiteralPath (Join-Path $redist.FullName 'x64') -Directory -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
    if ($crt) { Get-ChildItem -LiteralPath $crt.FullName -Filter '*.dll' | Copy-Item -Destination (Join-Path $BuildRoot 'app\_runtime') -Force }
}
Write-Output $BuildRoot
