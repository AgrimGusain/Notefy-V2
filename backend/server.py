from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import sys
import asyncio
import json
import logging
import time
import whisper
from typing import Optional, List
from pathlib import PurePosixPath

# Add backend directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recorder import SystemAudioRecorder
from database import (
    init_database,
    create_lecture,
    save_transcript_segment,
    update_lecture_status,
    finalize_lecture,
    get_lecture_by_id,
    list_lectures,
    search_lectures,
    update_lecture,
    list_folders, create_folder, update_folder, delete_folder, folder_children,
    create_note, delete_note,
)
from summarizer import summarize_transcript
from ai.manager import generate as generate_ai_notes, AIGenerationError
from ai.external import test_connection as test_external_connection, ExternalAIError
from ai.settings import get_preferences, save_preferences, get_api_key
from rag.indexer import index_lecture, remove_lecture_from_index, rebuild_index
from rag.retriever import index_status
from rag.service import answer_question
from rag.citations import resolve_citation

# Set up logging for events
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

# ----- FastAPI Lifespan for Database Initialization -----

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("Initializing database...")
    init_database()
    # Existing notes may predate the RAG feature and therefore have no chunks
    # yet. Rebuild at startup so "Ask your notes" searches the whole local
    # archive without requiring a hidden/manual maintenance step.
    try:
        indexed_chunks = await asyncio.to_thread(rebuild_index)
        logger.info("Search index ready (%s chunks)", indexed_chunks)
    except Exception:
        # A broken index must not prevent the core notes application from
        # starting; the RAG rebuild endpoint remains available for recovery.
        logger.exception("Could not rebuild search index at startup")
    logger.info("Application startup complete")
    yield
    logger.info("Application shutdown")

app = FastAPI(lifespan=lifespan)

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize recorder
recorder = SystemAudioRecorder(output_dir=os.path.join(os.path.dirname(__file__), "../data/recordings"))

# Keep lazy Whisper model loading untouched for the next phase
model = None

def get_model():
    global model
    if model is None:
        logger.info("Loading Whisper model (base)...")
        model = whisper.load_model("base")
        logger.info("Whisper model loaded")
    return model

# ----- WebSocket Client Registry -----

# Thread-safe set of connected WebSocket clients for broadcasting
_ws_clients: set[WebSocket] = set()
_ws_clients_lock = asyncio.Lock()

async def register_client(ws: WebSocket):
    async with _ws_clients_lock:
        _ws_clients.add(ws)

async def unregister_client(ws: WebSocket):
    async with _ws_clients_lock:
        _ws_clients.discard(ws)

async def broadcast(message: dict):
    """Send a JSON message to every connected WebSocket client.
    Silently drops any client whose send fails (already disconnected)."""
    payload = json.dumps(message)
    async with _ws_clients_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            # Client gone; unregister lazily
            await unregister_client(ws)

# ----- Overlap Deduplication -----

def remove_overlap(prev_text: str, new_text: str, max_overlap_words: int = 8) -> str:
    """Remove duplicated word sequences at the boundary between consecutive
    chunks.  The recorder overlaps by 0.5 s on 4 s chunks, so only a short
    phrase can repeat.  We find the longest suffix of *prev_text* (up to
    *max_overlap_words*) that matches a prefix of *new_text* and strip that
    prefix from the new text.

    Only exact, contiguous word matches count — this never removes
    non-matching words.
    """
    if not prev_text or not new_text:
        return new_text

    prev_words = prev_text.strip().split()
    new_words = new_text.strip().split()

    if not prev_words or not new_words:
        return new_text

    best = 0
    # Check suffix lengths from 1..max_overlap_words of prev against prefix of new
    check_len = min(len(prev_words), len(new_words), max_overlap_words)
    for k in range(1, check_len + 1):
        suffix = [w.lower().strip(".,!?;:") for w in prev_words[-k:]]
        prefix = [w.lower().strip(".,!?;:") for w in new_words[:k]]
        if suffix == prefix:
            best = k

    if best > 0:
        return " ".join(new_words[best:])
    return new_text

# ----- Service Functions -----

async def do_start_recording():
    return await asyncio.to_thread(recorder.start_recording)

async def do_stop_recording():
    return await asyncio.to_thread(recorder.stop_recording)

# ----- Session State -----

# Track the active lecture ID and transcription task
_current_lecture_id: Optional[int] = None
_transcription_task: Optional[asyncio.Task] = None

# ----- Transcription Worker -----

async def transcription_worker(session_id: str, lecture_id: int, title: Optional[str] = None):
    """Consume audio chunks from recorder.audio_queue in order, transcribe each
    with Whisper, persist to database, and broadcast partial_transcript events."""

    logger.info(f"[{session_id}] Transcription worker started for lecture_id={lecture_id}")
    prev_text = ""   # rolling previous-chunk text for overlap dedup

    try:
        while True:
            # Poll the queue without blocking the event loop
            chunk = None
            try:
                chunk = await asyncio.to_thread(recorder.audio_queue.get, timeout=0.5)
            except Exception:
                # queue.Empty on timeout — check whether we should keep waiting
                if not recorder.is_recording and recorder.audio_queue.empty():
                    if recorder.last_error:
                        logger.error(f"[{session_id}] Capture error detected: {recorder.last_error}")

                        # Save error to database
                        await asyncio.to_thread(
                            finalize_lecture,
                            lecture_id,
                            status="error",
                            error_message=recorder.last_error
                        )

                        await broadcast({
                            "type": "error",
                            "message": f"Audio capture failed: {recorder.last_error}",
                            "code": "capture_error",
                            "session_id": session_id,
                            "lecture_id": lecture_id,
                        })
                        return
                continue

            # Ignore chunks from a different session (defensive)
            if chunk.get("session_id") != session_id:
                continue

            wav_path = chunk.get("wav_path")
            sequence = chunk.get("sequence", 0)
            start_secs = chunk.get("start_seconds", 0.0)
            end_secs = chunk.get("end_seconds", 0.0)
            is_final = chunk.get("is_final", False)

            # Pure sentinel (no audio data) — just marks end of stream
            if wav_path is None:
                logger.info(f"[{session_id}] Received end-of-stream sentinel (seq {sequence})")
                break

            # Transcribe the WAV chunk
            try:
                t0 = time.perf_counter()
                result = await asyncio.to_thread(_transcribe_chunk, wav_path)
                elapsed = time.perf_counter() - t0

                raw_text = result.get("text", "").strip()
                deduped_text = remove_overlap(prev_text, raw_text)

                logger.info(
                    f"[{session_id}] Chunk {sequence} transcribed in {elapsed:.2f}s "
                    f"({start_secs:.1f}–{end_secs:.1f}s) — "
                    f"{len(raw_text.split())} words raw, {len(deduped_text.split())} after dedup"
                )

                # Persist segment to database (idempotent)
                save_success = await asyncio.to_thread(
                    save_transcript_segment,
                    lecture_id,
                    sequence,
                    start_secs,
                    end_secs,
                    deduped_text
                )

                if not save_success:
                    logger.error(f"[{session_id}] Failed to save segment {sequence} to database")
                    await broadcast({
                        "type": "error",
                        "message": f"Database error: failed to save segment {sequence}",
                        "code": "database_error",
                        "session_id": session_id,
                        "lecture_id": lecture_id,
                    })
                    # Continue despite database error to preserve live transcription

                # Broadcast partial transcript
                await broadcast({
                    "type": "partial_transcript",
                    "session_id": session_id,
                    "lecture_id": lecture_id,
                    "sequence": sequence,
                    "start_seconds": start_secs,
                    "end_seconds": end_secs,
                    "text": deduped_text,
                    "is_final_chunk": is_final,
                })

                prev_text = raw_text  # keep raw text for next overlap comparison

            except Exception as e:
                logger.error(f"[{session_id}] Chunk {sequence} transcription failed: {e}")
                await broadcast({
                    "type": "error",
                    "message": f"Transcription failed for chunk {sequence}",
                    "code": "transcription_error",
                    "session_id": session_id,
                    "lecture_id": lecture_id,
                })
                # Continue with the next chunk — don't abort the session

            if is_final:
                break

        # All chunks processed - finalize lecture and generate summary
        logger.info(f"[{session_id}] Finalizing lecture {lecture_id}")
        await asyncio.to_thread(finalize_lecture, lecture_id, status="complete")
        # Derived index work is deliberately after recording finalization.
        await asyncio.to_thread(index_lecture, lecture_id)

        await broadcast({
            "type": "transcription_complete",
            "session_id": session_id,
            "lecture_id": lecture_id,
            "message": "All audio chunks transcribed.",
        })

        # Generate summary
        await _generate_and_save_summary(session_id, lecture_id, title)

    except Exception as e:
        logger.error(f"[{session_id}] Transcription worker failed: {e}")
        await asyncio.to_thread(
            finalize_lecture,
            lecture_id,
            status="error",
            error_message=str(e)
        )

def _transcribe_chunk(wav_path: str) -> dict:
    """Run Whisper on a single WAV file.  Called inside asyncio.to_thread so it
    does not block the event loop."""
    w_model = get_model()
    return w_model.transcribe(wav_path)

# ----- Summarization -----

async def _generate_and_save_summary(session_id: str, lecture_id: int, title: Optional[str] = None):
    """
    Generate structured summary from full transcript and save to database.

    Runs after transcription is complete. Broadcasts summarizing status,
    generates summary, saves to database, and broadcasts completion.
    """
    try:
        # Broadcast summarizing status
        await asyncio.to_thread(update_lecture_status, lecture_id, "summarizing")

        await broadcast({
            "type": "status",
            "state": "summarizing",
            "message": "Creating structured lecture notes...",
            "session_id": session_id,
            "lecture_id": lecture_id,
        })

        logger.info(f"[{session_id}] Generating summary for lecture {lecture_id}")

        # Get full transcript from database
        lecture = await asyncio.to_thread(get_lecture_by_id, lecture_id)

        if not lecture:
            logger.error(f"[{session_id}] Lecture {lecture_id} not found for summarization")
            await broadcast({
                "type": "error",
                "message": "Failed to retrieve lecture for summarization",
                "code": "summarization_error",
                "session_id": session_id,
                "lecture_id": lecture_id,
            })
            return

        full_transcript = lecture.get("full_transcript", "")
        lecture_title = title or lecture.get("title")

        # Generate summary (runs in thread pool to avoid blocking)
        summary_start = time.perf_counter()
        summary_markdown = await asyncio.to_thread(
            summarize_transcript,
            full_transcript,
            lecture_title
        )
        summary_elapsed = time.perf_counter() - summary_start

        logger.info(f"[{session_id}] Summary generated in {summary_elapsed:.2f}s")

        # Save summary to database
        from database import SessionLocal, Lecture

        def _save_summary():
            session = SessionLocal()
            try:
                lec = session.query(Lecture).filter_by(id=lecture_id).first()
                if lec:
                    # A manual document is authoritative. A future regeneration
                    # must not silently replace study notes authored by the user.
                    if lec.is_manually_edited:
                        return True
                    lec.summary_markdown = summary_markdown
                    lec.status = "complete"
                    session.commit()
                    return True
                return False
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()

        save_success = await asyncio.to_thread(_save_summary)

        if not save_success:
            raise Exception("Failed to save summary to database")
        # Include the newly saved Markdown summary in the derived index.
        await asyncio.to_thread(index_lecture, lecture_id)

        # Broadcast summary completion
        await broadcast({
            "type": "summary_complete",
            "session_id": session_id,
            "lecture_id": lecture_id,
            "summary_markdown": summary_markdown,
        })

        logger.info(f"[{session_id}] Summary saved for lecture {lecture_id}")

    except Exception as e:
        logger.error(f"[{session_id}] Summary generation failed: {e}")

        # Save error but keep lecture as complete (transcription succeeded)
        try:
            from database import SessionLocal, Lecture

            def _save_error():
                session = SessionLocal()
                try:
                    lec = session.query(Lecture).filter_by(id=lecture_id).first()
                    if lec:
                        lec.status = "complete"  # Transcription succeeded
                        if not lec.error_message:
                            lec.error_message = f"Summarization failed: {str(e)}"
                        else:
                            lec.error_message += f" | Summarization: {str(e)}"
                        session.commit()
                finally:
                    session.close()

            await asyncio.to_thread(_save_error)
        except Exception as db_error:
            logger.error(f"[{session_id}] Failed to save summarization error: {db_error}")

        # Broadcast error
        await broadcast({
            "type": "error",
            "message": f"Summary generation failed: {str(e)}",
            "code": "summarization_error",
            "session_id": session_id,
            "lecture_id": lecture_id,
        })

# ----- WebSocket Endpoint -----

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _transcription_task, _current_lecture_id

    await websocket.accept()
    await register_client(websocket)
    logger.info("WebSocket connected")

    # Send ready event immediately
    await websocket.send_text(json.dumps({"type": "connection", "state": "ready"}))

    try:
        while True:
            text_data = await websocket.receive_text()

            try:
                data = json.loads(text_data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format",
                    "code": "invalid_json",
                }))
                continue

            if not isinstance(data, dict):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Payload must be a JSON object",
                    "code": "invalid_payload",
                }))
                continue

            msg_type = data.get("type")
            if not msg_type:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Missing 'type' field",
                    "code": "missing_type",
                }))
                continue

            # --- ping ---------------------------------------------------------
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            # --- start --------------------------------------------------------
            elif msg_type == "start":
                # Prevent concurrent sessions
                if recorder.is_recording:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "A recording is already active.",
                        "code": "recording_already_active",
                    }))
                    continue

                # Block if a previous transcription worker is still draining
                if _transcription_task is not None and not _transcription_task.done():
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Previous session is still transcribing. Please wait.",
                        "code": "previous_session_busy",
                    }))
                    continue

                # Start recording
                recording_result = await do_start_recording()
                session_id = recording_result.get("session_id")

                # Get optional title from client
                title = data.get("title")

                # Create lecture in database
                try:
                    lecture_id = await asyncio.to_thread(create_lecture, session_id, title)
                    _current_lecture_id = lecture_id
                    logger.info(f"WebSocket Start: Session {session_id} started, lecture_id={lecture_id}")
                except Exception as e:
                    logger.error(f"Failed to create lecture in database: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Failed to create lecture record",
                        "code": "database_error",
                    }))
                    # Stop recording since we can't persist
                    await do_stop_recording()
                    continue

                await broadcast({
                    "type": "status",
                    "state": "recording",
                    "message": "Recording started",
                    "session_id": session_id,
                    "lecture_id": lecture_id,
                })

                # Spawn the transcription worker
                _transcription_task = asyncio.create_task(
                    transcription_worker(session_id, lecture_id, title)
                )

            # --- stop ---------------------------------------------------------
            elif msg_type == "stop":
                if not recorder.is_recording:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "No active recording to stop.",
                        "code": "no_active_recording",
                    }))
                    continue

                # 1) Tell clients we are stopping capture
                await broadcast({
                    "type": "status",
                    "state": "stopping",
                    "message": "Stopping recording...",
                })

                # 2) Stop the recorder (non-blocking; flushes remaining audio)
                stop_result = await do_stop_recording()
                session_id = stop_result.get("session_id")
                logger.info(f"WebSocket Stop: Session {session_id} capture stopped")

                # 3) Update lecture status to transcribing
                if _current_lecture_id:
                    await asyncio.to_thread(update_lecture_status, _current_lecture_id, "transcribing")

                # 4) Tell clients we are now transcribing remaining chunks
                await broadcast({
                    "type": "status",
                    "state": "transcribing",
                    "message": "Processing remaining audio chunks...",
                    "session_id": session_id,
                    "lecture_id": _current_lecture_id,
                })

                # 5) Surface capture errors if the recorder thread hit one
                if recorder.last_error:
                    if _current_lecture_id:
                        await asyncio.to_thread(
                            finalize_lecture,
                            _current_lecture_id,
                            status="error",
                            error_message=recorder.last_error
                        )
                    await broadcast({
                        "type": "error",
                        "message": f"Audio capture error: {recorder.last_error}",
                        "code": "capture_error",
                        "session_id": session_id,
                        "lecture_id": _current_lecture_id,
                    })

                # 6) Wait for the transcription worker to drain all chunks
                if _transcription_task is not None:
                    await _transcription_task

                # 7) Send final complete after all chunks are transcribed
                await broadcast({
                    "type": "status",
                    "state": "complete",
                    "message": "Recording stopped and all chunks transcribed.",
                    "session_id": session_id,
                    "lecture_id": _current_lecture_id,
                })

            # --- unknown ------------------------------------------------------
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Unsupported event type: {msg_type}",
                    "code": "unsupported_event",
                }))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Internal server error",
                "code": "internal_error",
            }))
        except Exception:
            pass
    finally:
        await unregister_client(websocket)

# ----- Archive API Endpoints -----

@app.post("/api/ai/summarize")
async def ai_summarize(payload: dict = Body(...)):
    """Generate a preview only; notes are persisted only through PATCH on Accept."""
    lecture_id = payload.get("lecture_id")
    provider = payload.get("provider", "external")
    if not isinstance(lecture_id, int):
        return JSONResponse(status_code=422, content={"success": False, "error_code": "INVALID_REQUEST", "message": "A valid lecture ID is required."})
    if provider not in {"external", "local"}:
        return JSONResponse(status_code=422, content={"success": False, "error_code": "INVALID_REQUEST", "message": "Choose an AI provider."})
    lecture = await asyncio.to_thread(get_lecture_by_id, lecture_id)
    if not lecture:
        return JSONResponse(status_code=404, content={"success": False, "error_code": "LECTURE_NOT_FOUND", "message": "Lecture not found."})
    try:
        result = await generate_ai_notes(
            provider=provider, transcript=lecture.get("full_transcript") or "", title=lecture.get("title"),
            api_key=get_api_key(payload.get("api_key")), model=payload.get("model") or get_preferences()["model"], base_url=payload.get("base_url") or get_preferences()["base_url"],
            prompt=payload.get("prompt"), fallback_to_local=bool(payload.get("fallback_to_local", True)),
        )
        return JSONResponse(content={"success": True, **result})
    except AIGenerationError as exc:
        message = str(exc)
        code = "AI_GENERATION_FAILED" if message == "External and local AI generation failed." else "AI_GENERATION_ERROR"
        return JSONResponse(status_code=400, content={"success": False, "error_code": code, "message": message})
    except Exception:
        logger.exception("AI generation failed without logging request credentials")
        return JSONResponse(status_code=500, content={"success": False, "error_code": "AI_GENERATION_FAILED", "message": "AI generation failed."})


@app.post("/api/ai/test")
async def ai_test(payload: dict = Body(...)):
    """Safely verify external credentials without returning provider response data."""
    api_key, model = get_api_key(payload.get("api_key")), payload.get("model") or get_preferences()["model"]
    if not isinstance(api_key, str) or not api_key.strip() or not isinstance(model, str) or not model.strip():
        return JSONResponse(status_code=422, content={"success": False, "message": "API key and model are required."})
    try:
        await test_external_connection(api_key=api_key, model=model, base_url=payload.get("base_url") or get_preferences()["base_url"])
        return JSONResponse(content={"success": True, "message": "External AI connection verified."})
    except ExternalAIError as exc:
        return JSONResponse(status_code=400, content={"success": False, "message": exc.safe_message})
    except Exception:
        logger.exception("AI connection test failed without logging request credentials")
        return JSONResponse(status_code=500, content={"success": False, "message": "Could not verify the external AI connection."})

@app.get("/api/ai/preferences")
async def ai_preferences():
    """Never returns the secret; only whether the OS vault has one."""
    return await asyncio.to_thread(get_preferences)

@app.post("/api/ai/preferences")
async def save_ai_preferences(payload: dict = Body(...)):
    model, base_url, api_key = payload.get("model"), payload.get("base_url"), payload.get("api_key")
    if model is not None and (not isinstance(model, str) or not model.strip()): raise HTTPException(422, "Model must be a non-empty string")
    if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()): raise HTTPException(422, "Base URL must be a non-empty string")
    if api_key is not None and not isinstance(api_key, str): raise HTTPException(422, "API key must be a string")
    try: return await asyncio.to_thread(save_preferences, model=model, base_url=base_url, api_key=api_key)
    except RuntimeError as exc: raise HTTPException(503, str(exc))

@app.post("/api/ai/ask")
async def ai_ask(payload: dict = Body(...)):
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(422, "A non-empty question is required")
    if len(question) > 2000: raise HTTPException(422, "Question is too long")
    provider = payload.get("provider", "external")
    if provider not in {"external", "local"}: raise HTTPException(422, "Choose an AI provider")
    top_k = payload.get("top_k", 6)
    if not isinstance(top_k, int) or not 1 <= top_k <= 12: raise HTTPException(422, "top_k must be between 1 and 12")
    for key in ("folder_id", "lecture_id"):
        if payload.get(key) is not None and not isinstance(payload[key], int): raise HTTPException(422, f"{key} must be an integer or null")
    source_type = payload.get("source_type")
    if source_type is not None and source_type not in {"transcript", "markdown"}: raise HTTPException(422, "Invalid source type")
    try:
        preferences = get_preferences()
        return await answer_question(question=question.strip(), provider=provider, api_key=get_api_key(payload.get("api_key")), model=payload.get("model") or preferences["model"], base_url=payload.get("base_url") or preferences["base_url"], fallback_to_local=bool(payload.get("fallback_to_local", True)), top_k=top_k, folder_id=payload.get("folder_id"), lecture_id=payload.get("lecture_id"), source_type=source_type)
    except AIGenerationError as exc:
        return JSONResponse(status_code=400, content={"success":False, "message":str(exc)})

@app.get("/api/rag/status")
async def rag_status():
    return await asyncio.to_thread(index_status)

@app.post("/api/rag/rebuild")
async def rag_rebuild():
    try: return {"success": True, "indexed_chunks": await asyncio.to_thread(rebuild_index)}
    except Exception:
        logger.exception("RAG rebuild failed")
        raise HTTPException(500, "Could not rebuild the retrieval index")

@app.get("/api/rag/citations/{citation_id}")
async def rag_citation(citation_id: str):
    """Return a database-resolved source location for direct navigation."""
    citation = await asyncio.to_thread(resolve_citation, citation_id)
    if not citation: raise HTTPException(404, "Citation source no longer exists")
    return citation

# ----- Workspace API -----

def _workspace_error(exc: Exception):
    message = str(exc) or "Workspace operation failed"
    raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 500, detail=message)

@app.get("/api/folders")
async def get_folders():
    return {"folders": await asyncio.to_thread(list_folders)}

@app.get("/api/folders/{folder_id:int}/children")
async def get_folder_children(folder_id: int):
    return await asyncio.to_thread(folder_children, folder_id)

@app.get("/api/workspace/root")
async def get_workspace_root():
    return await asyncio.to_thread(folder_children, None)

@app.post("/api/folders")
async def post_folder(payload: dict = Body(...)):
    name, parent_id = payload.get("name"), payload.get("parent_id")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255: raise HTTPException(422, "A folder name is required")
    if parent_id is not None and not isinstance(parent_id, int): raise HTTPException(422, "parent_id must be an integer or null")
    if payload.get("source_type", "native") not in {"native", "linked", "imported"}: raise HTTPException(422, "Invalid source type")
    try:
        return await asyncio.to_thread(create_folder, name, parent_id, payload.get("source_type", "native"))
    except Exception as exc: _workspace_error(exc)

@app.patch("/api/folders/{folder_id:int}")
async def patch_folder(folder_id: int, payload: dict = Body(...)):
    changes = {key: payload[key] for key in ("name", "parent_id") if key in payload}
    if not changes: raise HTTPException(400, "No folder changes supplied")
    if "name" in changes and (not isinstance(changes["name"], str) or not changes["name"].strip()): raise HTTPException(422, "A folder name is required")
    try:
        result = await asyncio.to_thread(update_folder, folder_id, changes)
        if not result: raise HTTPException(404, "Folder not found")
        return result
    except HTTPException: raise
    except Exception as exc: _workspace_error(exc)

@app.delete("/api/folders/{folder_id:int}")
async def remove_folder(folder_id: int, delete_contents: bool = False):
    try:
        # capture source IDs before cascading deletion so no stale chunks remain
        from database import SessionLocal, Lecture
        session = SessionLocal()
        try: source_ids = [item[0] for item in session.query(Lecture.id).filter(Lecture.folder_id == folder_id).all()]
        finally: session.close()
        if not await asyncio.to_thread(delete_folder, folder_id, delete_contents): raise HTTPException(404, "Folder not found")
        for source_id in source_ids: await asyncio.to_thread(remove_lecture_from_index, source_id)
        if delete_contents: await asyncio.to_thread(rebuild_index)
        return {"success": True}
    except HTTPException: raise
    except Exception as exc: _workspace_error(exc)

@app.post("/api/notes")
async def post_note(payload: dict = Body(...)):
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip(): raise HTTPException(422, "A note title is required")
    if payload.get("source_type", "native") not in {"native", "linked", "imported"}: raise HTTPException(422, "Invalid source type")
    try:
        note = await asyncio.to_thread(create_note, title, payload.get("folder_id"), payload.get("summary_markdown", ""), payload.get("source_type", "native"), payload.get("source_relative_path"))
        await asyncio.to_thread(index_lecture, note["id"])
        return note
    except Exception as exc: _workspace_error(exc)

@app.delete("/api/notes/{note_id:int}")
async def remove_note(note_id: int):
    await asyncio.to_thread(remove_lecture_from_index, note_id)
    if not await asyncio.to_thread(delete_note, note_id): raise HTTPException(404, "Note not found")
    return {"success": True}

def _safe_relative_path(filename: str) -> Optional[PurePosixPath]:
    path = PurePosixPath((filename or "").replace("\\", "/"))
    if not path.name or path.suffix.lower() != ".md" or path.is_absolute() or ".." in path.parts: return None
    return path

@app.post("/api/import/markdown")
async def import_markdown(files: List[UploadFile] = File(...)):
    """Import copies only. Paths are validated and never written to the host filesystem."""
    created, folder_cache = [], {}
    for upload in files:
        path = _safe_relative_path(upload.filename or "")
        if not path: continue
        parent_id = None
        traversed = []
        for segment in path.parts[:-1]:
            traversed.append(segment); key = "/".join(traversed)
            if key not in folder_cache:
                folder_cache[key] = await asyncio.to_thread(create_folder, segment, parent_id, "imported")
            parent_id = folder_cache[key]["id"]
        raw = await upload.read()
        try: content = raw.decode("utf-8")
        except UnicodeDecodeError: content = raw.decode("utf-8", errors="replace")
        title = path.stem.replace("_", " ").replace("-", " ")
        note = await asyncio.to_thread(create_note, title, parent_id, content, "imported", str(path))
        await asyncio.to_thread(index_lecture, note["id"])
        created.append(note)
    if not created: raise HTTPException(422, "Select one or more Markdown (.md) files")
    return {"notes": created, "count": len(created)}

@app.get("/api/lectures")
async def get_lectures(limit: int = 50, offset: int = 0):
    """List lectures, newest first, with transcript preview."""
    try:
        lectures = await asyncio.to_thread(list_lectures, limit, offset)
        return JSONResponse(content={"lectures": lectures, "count": len(lectures)})
    except Exception as e:
        logger.error(f"Error listing lectures: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve lectures")

@app.get("/api/lectures/{lecture_id:int}")
async def get_lecture(lecture_id: int):
    """Get a single lecture with full transcript and segments."""
    try:
        lecture = await asyncio.to_thread(get_lecture_by_id, lecture_id)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found")
        return JSONResponse(content=lecture)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving lecture {lecture_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve lecture")

@app.patch("/api/lectures/{lecture_id:int}")
async def patch_lecture(lecture_id: int, payload: dict = Body(...)):
    """Update editable lecture fields and favorite metadata in one API."""
    allowed = {"title", "summary_markdown", "segments", "is_favorite", "is_manually_edited", "folder_id"}
    changes = {key: value for key, value in payload.items() if key in allowed}
    if not changes:
        raise HTTPException(status_code=400, detail="No editable lecture fields supplied")
    if "title" in changes and (not isinstance(changes["title"], str) or not changes["title"].strip()):
        raise HTTPException(status_code=422, detail="Title must be a non-empty string")
    if "summary_markdown" in changes and not isinstance(changes["summary_markdown"], str):
        raise HTTPException(status_code=422, detail="Summary must be a string")
    if "segments" in changes and not isinstance(changes["segments"], list):
        raise HTTPException(status_code=422, detail="Segments must be a list")
    if "is_favorite" in changes and not isinstance(changes["is_favorite"], bool):
        raise HTTPException(status_code=422, detail="Favorite must be a boolean")
    if "folder_id" in changes and changes["folder_id"] is not None and not isinstance(changes["folder_id"], int):
        raise HTTPException(status_code=422, detail="folder_id must be an integer or null")

    try:
        lecture = await asyncio.to_thread(update_lecture, lecture_id, changes)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found")
        if {"title", "summary_markdown", "segments", "folder_id"}.intersection(changes):
            await asyncio.to_thread(index_lecture, lecture_id)
        return JSONResponse(content=lecture)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating lecture {lecture_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update lecture")

@app.get("/api/lectures/search")
async def search_lectures_endpoint(q: str = ""):
    """Search lectures by title, full_transcript, or segment text."""
    if not q or not q.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Search query cannot be empty"}
        )

    try:
        results = await asyncio.to_thread(search_lectures, q.strip())
        return JSONResponse(content={"lectures": results, "count": len(results), "query": q})
    except Exception as e:
        logger.error(f"Error searching lectures: {e}")
        raise HTTPException(status_code=500, detail="Search failed")

# ----- Static Frontend -----

html_path = os.path.join(os.path.dirname(__file__), "../frontend/index.html")
frontend_path = os.path.join(os.path.dirname(__file__), "../frontend")

# The frontend is split into focused presentation and behavior files.  Keep the
# existing page and API routes intact while exposing only those static assets.
app.mount("/css", StaticFiles(directory=os.path.join(frontend_path, "css")), name="frontend-css")
app.mount("/js", StaticFiles(directory=os.path.join(frontend_path, "js")), name="frontend-js")

@app.get("/")
def read_root():
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
