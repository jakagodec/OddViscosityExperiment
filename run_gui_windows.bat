@echo off
rem Double-click to start the GUI on Windows (installs everything on the first start).
cd /d "%~dp0"

where uv >nul 2>nul || set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
    echo uv is not installed. Install it in PowerShell with:
    echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

rem Keep the environment on the local disk: the repository may live on a network
rem drive shared with macOS, where a .venv would be slow and clash between systems.
if not defined UV_PROJECT_ENVIRONMENT set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\OddViscosityExperiment\venv"
set "VIRTUAL_ENV="

uv run odd-viscosity-gui
if errorlevel 1 pause
