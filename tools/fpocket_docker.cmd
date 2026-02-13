@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Docker-backed fpocket wrapper for Windows.
REM Accepts the same args as fpocket, e.g.: fpocket_docker.cmd -f C:\path\input.pdb

set "INPUT_FILE="
set "PREV="
for %%A in (%*) do (
    if /I "!PREV!"=="-f" set "INPUT_FILE=%%~fA"
    set "PREV=%%~A"
)

if "%INPUT_FILE%"=="" (
    echo [ERROR] Missing -f input file argument.
    exit /b 2
)

if not exist "%INPUT_FILE%" (
    echo [ERROR] Input file not found: %INPUT_FILE%
    exit /b 3
)

set "BASENAME=%~nx1"
if /I "%~1"=="-f" (
    set "BASENAME=%~nx2"
)
if "%BASENAME%"=="" set "BASENAME=input.pdb"

copy /Y "%INPUT_FILE%" "%CD%\%BASENAME%" >nul
if errorlevel 1 (
    echo [ERROR] Could not stage input into run directory.
    exit /b 4
)

docker run --rm -v "%CD%:/work" -w /work fpocket/fpocket fpocket -f "%BASENAME%"
set "RC=%ERRORLEVEL%"

del /Q "%CD%\%BASENAME%" >nul 2>nul

exit /b %RC%
