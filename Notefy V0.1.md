# Notefy V0.1: Real-Time Lecture Transcription & Summarization

A standalone web application that captures Windows system audio (WASAPI loopback), transcribes it in real-time using OpenAI Whisper, and generates structured lecture notes automatically.

**Current Status:** V0.1 MVP Complete - Full recording, transcription, summarization, and archive system in place.

---

## Features

### ✅ Core Functionality
- **Native Windows Audio Capture** - Records system audio directly via WASAPI loopback (no Virtual Audio Cable required).
- **Real-Time Transcription** - Live Whisper transcription with 4-second chunks and 0.5s overlap for word-perfect accuracy.
- **Automatic Summarization** - Structured Markdown lecture notes generated from transcripts (sections include Overview, Key Concepts, Details, Definitions/Formulas, Action Items).
- **SQLite Archive** - Permanent storage of all lectures, transcripts, and summaries.
- **WebSocket UI** - Live updates as transcription and summarization happen.
- **Search** - Full-text search across all lecture archives.

### 🎯 Use Cases
- Record online lectures, webinars, or tutorials
- Capture meeting discussions with automatic notes
- Archive video content with searchable transcripts
- Study from structured notes instead of raw transcripts

---

## Quick Start

### Prerequisites
- Python 3.9+
- FFmpeg (Required for audio processing)
  - Windows: Download from https://ffmpeg.org/download.html and add to PATH or place `ffmpeg.exe` in the project directory.

### Installation & Launch
```bash
# 1. Activate virtual environment (if using the root venv)
# Windows CMD / PowerShell:
..\venv\Scripts\activate

# 2. Install dependencies (if not already installed)
pip install -r requirements.txt

# 3. Start server (Initializes database on first run)
uvicorn backend.server:app --reload
# Or directly run the updated batch script:
START_SERVER.bat
```

### Usage Workflow
1. Open browser to `http://localhost:8000`
2. Play audio on your system (YouTube, meeting, etc.)
3. Click **Start Capture**
4. Watch live transcripts appear in real-time
5. Click **Stop Capture**
6. Wait 5-10 seconds for automatic summarization
7. View structured lecture notes natively in the browser

---

## Configuration: Summarization Provider

Set the `AUDIO_NOTES_SUMMARIZER` environment variable to choose your summarization method:

```bash
# Local fallback (default, no API key needed, uses heuristic extraction)
export AUDIO_NOTES_SUMMARIZER=local

# Anthropic Claude (best quality, requires API key)
export AUDIO_NOTES_SUMMARIZER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI GPT-4 (requires API key)
export AUDIO_NOTES_SUMMARIZER=openai
export OPENAI_API_KEY=sk-...
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (WebSocket)                  │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Controls  │  │ Live Transcript│ │ Archive Search  │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │ WebSocket
┌────────────────────────────┴────────────────────────────────┐
│              FastAPI Server (backend/server.py)             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │   Recorder   │→ │   Whisper    │→ │  Summarizer      │ │
│  │(WASAPI Loop) │  │(Transcription)│  │(Structured Notes)│ │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────┐
│           SQLite Database (data/audio_notes.db)             │
│  ┌──────────────────┐           ┌────────────────────────┐ │
│  │     Lectures     │───────────│  Transcript Segments   │ │
│  │ • full_transcript│           │ • sequence, timestamps │ │
│  │ • summary_markdown│          │ • deduplicated text    │ │
│  └──────────────────┘           └────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## API Endpoints & WebSocket

### REST Archive Access
- `GET /api/lectures?limit=50&offset=0` - List lectures
- `GET /api/lectures/{lecture_id}` - Get specific lecture with transcription and summary
- `GET /api/lectures/search?q=search term` - Search across all lectures

### WebSocket Events (Client <-> Server)
- **Commands:** `{"type": "start", "title": "Optional Title"}`, `{"type": "stop"}`, `{"type": "ping"}`
- **Responses:** 
  - `{"type": "connection", "state": "ready"}`
  - `{"type": "status", "state": "recording|stopping|transcribing|summarizing|complete"}`
  - `{"type": "partial_transcript", "sequence": 1, "text": "...", "start_seconds": 0.0}`
  - `{"type": "summary_complete", "summary_markdown": "..."}`
  - `{"type": "error", "message": "..."}`

---

## File Structure

```
Notefy (Audio-Notes)/
├── backend/
│   ├── server.py           # FastAPI server + WebSocket
│   ├── recorder.py         # WASAPI loopback capture
│   ├── database.py         # SQLAlchemy models + persistence
│   └── summarizer.py       # Configurable summarization interface
├── frontend/
│   └── index.html          # WebSocket client + live UI
├── data/
│   ├── audio_notes.db      # SQLite static & generated database
│   └── recordings/         # WAV chunk files (temporary storage)
├── tests/                  # Integration & unit test suite
├── requirements.txt
└── Notefy V0.1.md          # Complete MVP Documentation
```
