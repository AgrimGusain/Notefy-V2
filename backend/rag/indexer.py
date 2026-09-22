from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from sqlalchemy import text
from database import SessionLocal, Lecture, RagChunk, TranscriptSegment
from .chunking import transcript_chunks, markdown_chunks
from .embeddings import get_embedding_provider

def _hash(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _delete_fts(session, ids: list[int]) -> None:
    for chunk_id in ids: session.execute(text("DELETE FROM rag_chunks_fts WHERE chunk_id = :id"), {"id": chunk_id})

def remove_lecture_from_index(lecture_id: int) -> None:
    session = SessionLocal()
    try:
        ids = [row[0] for row in session.query(RagChunk.id).filter_by(lecture_id=lecture_id)]
        _delete_fts(session, ids); session.query(RagChunk).filter_by(lecture_id=lecture_id).delete(synchronize_session=False); session.commit()
    except Exception: session.rollback(); raise
    finally: session.close()

def index_lecture(lecture_id: int, embedding_provider=None) -> int:
    """Incremental source index: unchanged chunks retain their embedding."""
    session = SessionLocal()
    try:
        lecture = session.get(Lecture, lecture_id)
        if not lecture: return 0
        segments = session.query(TranscriptSegment).filter_by(lecture_id=lecture_id).order_by(TranscriptSegment.sequence_number).all()
        chunks = transcript_chunks(segments) + (markdown_chunks(lecture.summary_markdown) if lecture.summary_markdown else [])
        provider = embedding_provider or get_embedding_provider()
        existing = {(item.source_kind, item.content_hash): item for item in session.query(RagChunk).filter_by(lecture_id=lecture_id).all()}
        desired = [(chunk, _hash(chunk.content)) for chunk in chunks]
        positions = [i for i, (chunk, digest) in enumerate(desired) if (chunk.source_kind, digest) not in existing]
        vectors = dict(zip(positions, provider.embed_documents([desired[i][0].content for i in positions]))) if positions else {}
        retained, now = set(), datetime.now(timezone.utc)
        for position, (chunk, digest) in enumerate(desired):
            key = (chunk.source_kind, digest); row = existing.get(key); retained.add(key)
            if row is None:
                vector = vectors.get(position)
                row = RagChunk(lecture_id=lecture.id, chunk_index=position, content=chunk.content, content_hash=digest, source_kind=chunk.source_kind, segment_id=chunk.segment_id, sequence_number=chunk.sequence_number, start_seconds=chunk.start_seconds, end_seconds=chunk.end_seconds, line_start=chunk.line_start, line_end=chunk.line_end, char_start=chunk.char_start, char_end=chunk.char_end, segment_ids=json.dumps(chunk.segment_ids), embedding=json.dumps(vector) if vector else None, embedding_model=getattr(provider, "model", None), embedding_dimensions=len(vector) if vector else None, folder_id=lecture.folder_id, updated_at=now, indexed_at=now)
                session.add(row); session.flush()
            else:
                row.chunk_index, row.folder_id, row.updated_at = position, lecture.folder_id, now
                row.segment_id, row.sequence_number, row.start_seconds, row.end_seconds = chunk.segment_id, chunk.sequence_number, chunk.start_seconds, chunk.end_seconds
                row.line_start, row.line_end, row.char_start, row.char_end, row.segment_ids = chunk.line_start, chunk.line_end, chunk.char_start, chunk.char_end, json.dumps(chunk.segment_ids)
            session.execute(text("DELETE FROM rag_chunks_fts WHERE chunk_id = :id"), {"id": row.id})
            session.execute(text("INSERT INTO rag_chunks_fts(title,content,chunk_id) VALUES (:title,:content,:id)"), {"title": lecture.title or "Untitled", "content": row.content, "id": row.id})
        stale = [row for key, row in existing.items() if key not in retained]
        _delete_fts(session, [row.id for row in stale])
        for row in stale: session.delete(row)
        session.commit(); return len(chunks)
    except Exception: session.rollback(); raise
    finally: session.close()

def index_all_content() -> int:
    session = SessionLocal()
    try: ids = [item[0] for item in session.query(Lecture.id).all()]
    finally: session.close()
    return sum(index_lecture(item) for item in ids)

def rebuild_index() -> int: return index_all_content()
