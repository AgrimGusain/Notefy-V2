#!/bin/bash
echo "============================================"
echo "  Audio-Notes Server Startup"
echo "============================================"
echo ""
echo "Starting server at http://localhost:8000"
echo ""
echo "Keep this terminal open while using Audio-Notes"
echo "Press Ctrl+C to stop the server"
echo ""
echo "============================================"
echo ""

cd "$(dirname "$0")"

if [ -f "../venv/Scripts/python.exe" ]; then
    echo "Using virtual environment at ../venv"
    ../venv/Scripts/python.exe -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
elif [ -f "../venv/bin/python" ]; then
    echo "Using virtual environment at ../venv"
    ../venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
elif [ -f "venv/Scripts/python.exe" ]; then
    echo "Using virtual environment at venv"
    venv/Scripts/python.exe -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
elif [ -f "venv/bin/python" ]; then
    echo "Using virtual environment at venv"
    venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
else
    echo "Using system uvicorn"
    uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
fi
