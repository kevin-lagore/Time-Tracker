@echo off
echo === Push-to-Talk Work Log Setup ===
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ and add to PATH.
    pause
    exit /b 1
)

:: Create venv
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

:: Activate and install
echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

:: Copy config if not exists
if not exist ".env" (
    echo Copying .env.example to .env...
    copy .env.example .env
    echo [!] Edit .env and set your API tokens.
)

if not exist "config.yaml" (
    echo Copying config.yaml.example to config.yaml...
    copy config.yaml.example config.yaml
)

:: Create directories
if not exist "audio_captures" mkdir audio_captures
if not exist "data" mkdir data
if not exist "logs" mkdir logs

:: Run doctor
echo.
echo Running system checks...
python -m app doctor

echo.
echo Setup complete. Edit .env with your API tokens, then:
echo   1. Double-click ahk\pushtotalk.ahk to start recording
echo   2. Run: python -m app editor   to start the web editor
echo.
pause
