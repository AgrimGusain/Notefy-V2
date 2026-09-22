# Audio Notes

Audio Notes is a local-first Markdown knowledge workspace. It combines nested folders, notebook-style notes, Markdown import/editing, favorites, AI summaries, and optional audio transcription in one private localhost app.

Your notes, recordings, database, and any AI API key stay on your computer. This repository is the application source code; it is not a hosted service.

## What you need

- Git
- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org/download.html) available on your `PATH` for audio/Whisper workflows
- A Chromium-based browser (Chrome or Edge) for **Open Folder** and saving linked Markdown files back to disk

Audio capture availability depends on your operating system and configured audio devices. Markdown notes and imported files work without recording.

## Install and run

Clone the repository:

```bash
git clone https://github.com/AgrimGusain/Notefy-V2.git
cd Notefy-V2
```

Create and activate a virtual environment.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run this once in a PowerShell window:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the app:

```bash
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```

Then visit [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. Keep the terminal open while you use the app. Press `Ctrl+C` to stop it.

On Windows, after dependencies are installed, you can also double-click `START_SERVER.bat`.

## First use

- Create native folders and notes directly in Audio Notes.
- Choose **Open Folder** to work with an existing Markdown directory without copying it. The browser asks you to select and authorize that folder; edits can be saved back to its `.md` files.
- Choose **Import Markdown** to create Audio Notes-managed copies of one or more Markdown files.
- Open the AI summary action or **Ask your notes** to use a compatible external provider. The first use defaults to Groq (`https://api.groq.com/openai/v1`) and `openai/gpt-oss-120b`; you can change either value. Selecting **Save model, URL, and API key securely** stores the key in your operating system credential vault, never in the project files or browser storage.

## Local data and privacy

Runtime data is intentionally excluded from Git:

- `data/audio_notes.db` contains your local workspace metadata.
- `data/recordings/` contains local recordings.
- `.env` can contain private local configuration or API keys.

Do not commit your database, recordings, API keys, or virtual environment. If you want to back up your workspace, make a private copy of the `data/` directory outside this repository.

## Troubleshooting

**`uvicorn` is not found** — activate the virtual environment and run `pip install -r requirements.txt` again.

**Audio transcription does not start** — verify FFmpeg is installed and available with `ffmpeg -version`, then check that your audio device permissions and configuration allow capture.

**Open Folder is unavailable** — use Chrome or Edge and access the app through `http://127.0.0.1:8000`. Other browsers can still use **Import Markdown**.

**Port 8000 is busy** — choose another port, for example:

```bash
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8001 --reload
```

## Development checks

```bash
python -m compileall backend
```

## Hybrid RAG and exact citations

Ask your notes combines SQLite FTS5 keyword matches with dependency-free local semantic embeddings. Markdown chunks retain original line and character ranges; transcript chunks retain source segment IDs and actual timestamps. The model sees only opaque source IDs, and the API resolves every displayed location from SQLite.

Optional configuration: `RAG_CHUNK_SIZE` (default `500` words), `RAG_CHUNK_OVERLAP` (`75`), `RAG_FTS_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_HYBRID_ALPHA` (`.4` lexical weighting), `RAG_MIN_SCORE` (`.08`), `EMBEDDING_PROVIDER` (`local` or `disabled`), and `EMBEDDING_MODEL`. Rebuild with `POST /api/rag/rebuild`; unchanged chunks retain their embeddings. A one-time `data/audio_notes.db.pre-rag-citations-backup` is created before this schema extension.

The app is designed for local, single-user use. Please open an issue with your operating system, Python version, browser, and the full non-sensitive error message if you encounter a problem.
