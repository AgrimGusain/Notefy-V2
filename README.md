# Audio Notes

> A quiet, local-first workspace for turning lectures, recordings, and Markdown into a searchable notebook.
Audio Notes keeps notes, recordings, database data, and AI credentials on your computer. The interface is built around warm paper tones, filed-note navigation, and a small set of focused tools rather than a hosted dashboard.

## Features

- Nested folders and notebook-style notes
- Markdown import, editing, and linked-folder workflows
- Audio capture with optional Whisper transcription
- AI summaries and an "Ask your notes" search experience
- Favorites for keeping important lectures close
- Exact citations for Markdown lines and transcript timestamps

## How It Works

Create a note in the workspace, import an existing Markdown file, or start a recording. Audio is transcribed locally when configured, and notes can be summarized or searched through the archive. The app runs on localhost for a single user.

## Architecture
The backend is a FastAPI application with SQLite persistence. The frontend is a dependency-light HTML, CSS, and JavaScript single-page interface served by the backend. WebSockets carry live recording and transcription updates; REST endpoints handle notes, folders, AI actions, and search.

## RAG / AI
“Ask your notes” combines SQLite FTS5 keyword retrieval with dependency-free local semantic embeddings. Markdown chunks retain line and character ranges; transcript chunks retain source segment IDs and timestamps. The model receives opaque source IDs, and the API resolves citations from SQLite.

Optional settings include `RAG_CHUNK_SIZE` (default `500` words), `RAG_CHUNK_OVERLAP` (`75`), `RAG_FTS_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_HYBRID_ALPHA` (`.4` lexical weighting), `RAG_MIN_SCORE` (`.08`), `EMBEDDING_PROVIDER` (`local` or `disabled`), and `EMBEDDING_MODEL`. Rebuild the index with `POST /api/rag/rebuild`.
## Installation

### Requirements

- Git
- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org/download.html) on `PATH` for audio and Whisper workflows
- Chrome or Edge for **Open Folder** and saving linked Markdown files

```bash
git clone https://github.com/AgrimGusain/Notefy-V2.git
cd Notefy-V2
```

### Windows PowerShell
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configuration
The first external AI setup defaults to Groq at `https://api.groq.com/openai/v1` with `openai/gpt-oss-120b`; both values can be changed. Choosing **Save model, URL, and API key securely** stores the key in the operating system credential vault, not in project files or browser storage.

Runtime data is intentionally excluded from Git. `data/audio_notes.db` stores workspace metadata, `data/recordings/` stores local recordings, and `.env` may contain private configuration. Keep these files and your virtual environment out of commits.
## Running the Application

```bash
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). On Windows, `START_SERVER.bat` starts the same local server after dependencies are installed.
## Project Structure

```text
backend/              FastAPI server, persistence, recording, AI, and RAG
frontend/             Audio Notes interface, styles, and browser behavior
data/                 Local runtime data and recordings
tests/                Database, RAG, summarization, and WebSocket tests
requirements.txt      Python dependencies
```

## Usage
1. Create native folders and notes directly in the workspace.
2. Use **Open Folder** to edit an existing Markdown directory without copying it.
3. Use **Import Markdown** for Audio Notes-managed copies.
4. Record a lecture, review the transcript, then summarize or ask questions across the archive.
5. Star important lectures to collect them in **Favorites**.

## Development Checks
```bash
python -m compileall backend
```

For audio issues, verify `ffmpeg -version` and device permissions. If port `8000` is busy, start the app on another port such as `8001`.

## Future Improvements

- Richer local model choices and offline summarization
- More export formats for notes and citations
- Additional keyboard-first archive workflows

## License

Audio Notes is released under the [MIT License](LICENSE).
