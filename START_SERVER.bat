@echo off
echo ============================================
echo   Audio-Notes Server Startup
echo ============================================
echo.
echo Starting server at http://localhost:8000
echo.
echo Keep this window open while using Audio-Notes
echo Press Ctrl+C to stop the server
echo.
echo ============================================
echo.

cd /d "%~dp0"

REM Check for virtual environment in parent directory or current directory
if exist "..\venv\Scripts\python.exe" (
    echo Using virtual environment at ..\venv
    "..\venv\Scripts\python.exe" -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
) else if exist "venv\Scripts\python.exe" (
    echo Using virtual environment at venv
    "venv\Scripts\python.exe" -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
) else (
    echo Using system Python / uvicorn
    uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
)

pause
