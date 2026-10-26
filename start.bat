@echo off
setlocal
cd /d "%~dp0"
title Edu - AI Teaching Service
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
  echo [Edu] Python 3.10+ was not found.
  echo       Install it from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)

%PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo [Edu] Python 3.10 or newer is required. Current version:
  %PY_CMD% --version
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo [Edu] Existing virtual environment is broken, recreating...
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [Edu] Creating virtual environment...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :fail
)

set "VENV_PY=.venv\Scripts\python.exe"

if exist ".venv\.deps-ok" (
  "%VENV_PY%" -c "import fastapi, uvicorn, httpx, pptx" >nul 2>nul
  if errorlevel 1 del ".venv\.deps-ok"
)

if not exist ".venv\.deps-ok" (
  echo [Edu] Installing Python dependencies ^(first run only^)...
  "%VENV_PY%" -m pip install --disable-pip-version-check --timeout 30 -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
  if errorlevel 1 (
    echo [Edu] Mirror failed, retrying with the default PyPI index...
    "%VENV_PY%" -m pip install --disable-pip-version-check --timeout 30 -r requirements.txt
  )
  if errorlevel 1 goto :fail
  echo ok> ".venv\.deps-ok"
)

if not exist "web\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [Edu] The frontend is not built yet and npm was not found.
    echo       Install Node.js 18+ from https://nodejs.org/ and run start.bat again.
    pause
    exit /b 1
  )
  echo [Edu] Building the frontend ^(first run only^)...
  pushd web
  if not exist "node_modules" call npm install --registry=https://registry.npmmirror.com --no-audit --no-fund
  if errorlevel 1 goto :fail_pop
  call npm run build
  if errorlevel 1 goto :fail_pop
  popd
)

echo.
echo [Edu] Starting server. Press Ctrl+C to stop.
echo.
"%VENV_PY%" -m server.main
if errorlevel 1 goto :fail
exit /b 0

:fail_pop
popd
:fail
echo.
echo [Edu] Startup failed. See the messages above.
pause
exit /b 1
