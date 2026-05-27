@echo off
chcp 65001 >nul 2>&1
REM TokioAI CLI - Windows Setup v4.1
REM Works on Windows 10/11 with Python 3.10+

echo.
echo ====================================================
echo   TOKIOAI - Autonomous AI Agent - Setup v4.1
echo ====================================================
echo.

REM -------- Check Python --------
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python not found. Install from https://python.org
        echo         Make sure to check "Add Python to PATH" during install!
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

REM Check version
%PYTHON% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ required
    %PYTHON% --version
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VER=%%i
echo [OK] Python %PY_VER%

REM -------- Create venv --------
if exist .venv (
    echo -- Removing old virtual environment...
    rmdir /s /q .venv
)

echo -- Creating virtual environment...
%PYTHON% -m venv .venv
if not exist .venv\Scripts\activate.bat (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

REM -------- Activate --------
call .venv\Scripts\activate.bat
echo [OK] Virtual environment activated

REM -------- Upgrade pip --------
echo -- Upgrading pip and setuptools...
pip install --upgrade pip setuptools wheel --quiet
echo [OK] pip upgraded

REM -------- Install TokioAI CLI --------
echo -- Installing TokioAI CLI...

pip install -e ".[all]" --quiet 2>nul
if %errorlevel% equ 0 (
    echo [OK] All providers installed (Claude, OpenAI, Gemini, SSH)
) else (
    echo -- Some optional deps failed, trying base + individual providers...
    pip install -e . --quiet
    pip install anthropic --quiet 2>nul && echo   [OK] Anthropic (Claude) || echo   [WARN] Anthropic failed (optional)
    pip install openai --quiet 2>nul && echo   [OK] OpenAI || echo   [WARN] OpenAI failed (optional)
    pip install google-genai --quiet 2>nul && echo   [OK] Gemini || echo   [WARN] Gemini failed (optional)
    pip install paramiko --quiet 2>nul && echo   [OK] SSH (paramiko) || echo   [WARN] paramiko failed (optional)
)

REM -------- Install Windows extras --------
pip install pyreadline3 --quiet 2>nul && echo [OK] readline support

echo.
echo ====================================================
echo   [OK] TokioAI CLI v4.1 installed!
echo ====================================================
echo.

REM -------- Config check --------
if exist "%USERPROFILE%\.tokioai\.env" (
    echo [OK] Config found: %USERPROFILE%\.tokioai\.env
) else (
    echo -- First time? Let's configure your AI provider...
    echo.
    python -m tokioai_cli --setup
)

echo.
echo ====================================================
echo   Quick start:
echo.
echo     .venv\Scripts\activate
echo     tokioai                      # interactive
echo     tokio                        # same thing
echo     tokioai -m gemini31          # use Gemini 3.1
echo     tokioai -p                   # persistent mode
echo     tokioai --setup              # reconfigure
echo ====================================================
echo.
echo IMPORTANT: Always activate the venv first!
echo   .venv\Scripts\activate
echo.
pause
