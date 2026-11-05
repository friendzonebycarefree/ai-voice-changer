$ErrorActionPreference = 'Stop'
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Install Visual Studio C++ Build Tools and Windows SDK.' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$sourceDir = $PSScriptRoot
$bat = Join-Path $sourceDir 'compile.cmd'
@"
@echo off
call "$vcvars" >nul
cd /d "$sourceDir"
cl /nologo /utf-8 /std:c++20 /O2 /EHsc /MD /LD audio_engine.cpp /link /OUT:audio_engine.dll ole32.lib uuid.lib avrt.lib
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /O2 /EHsc /MT /DUNICODE /D_UNICODE launcher.cpp /link /SUBSYSTEM:WINDOWS /OUT:VoiceChanger.exe shell32.lib user32.lib
"@ | Set-Content -LiteralPath $bat -Encoding ascii
& $bat
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
