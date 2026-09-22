"""SQLite-backed vector index abstraction; SQLite remains metadata authority."""
from __future__ import annotations
import json
from database import SessionLocal, RagChunk, Lecture
from .retriever import cosine_similarity

class SQLiteVectorStore:
    def search(self, query_embedding: list[float], top_k: int = 20, *, folder_id=None, lecture_id=None, source_type=None) -> list[dict]:
        if not query_embedding: return []
        session = SessionLocal()
        try:
            query = session.query(RagChunk, Lecture).join(Lecture, Lecture.id == RagChunk.lecture_id).filter(RagChunk.embedding.isnot(None))
            if folder_id is not None: query = query.filter(RagChunk.folder_id == folder_id)
            if lecture_id is not None: query = query.filter(RagChunk.lecture_id == lecture_id)
            if source_type is not None: query = query.filter(RagChunk.source_kind == source_type)
            rows = []
            for chunk, lecture in query.all():
                try: score = cosine_similarity(query_embedding, json.loads(chunk.embedding))
                except (ValueError, TypeError): continue
                if score > 0: rows.append({"id": chunk.id, "lecture_id": chunk.lecture_id, "segment_id": chunk.segment_id, "sequence_number": chunk.sequence_number, "start_seconds": chunk.start_seconds, "end_seconds": chunk.end_seconds, "line_start": chunk.line_start, "line_end": chunk.line_end, "char_start":chunk.char_start, "char_end":chunk.char_end, "segment_ids":chunk.segment_ids, "content":chunk.content, "source_kind":chunk.source_kind, "folder_id":chunk.folder_id, "embedding":chunk.embedding, "title":lecture.title, "source_type":lecture.source_type, "source_relative_path":lecture.source_relative_path, "semantic_score":score})
            return sorted(rows, key=lambda item: item["semantic_score"], reverse=True)[:top_k]
        finally: session.close()
