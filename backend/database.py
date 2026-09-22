"""
Database module for Audio-Notes application.

Provides SQLAlchemy models and persistence functions for lectures and transcript segments.
Uses SQLite with safe configuration for FastAPI async/background thread usage.
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint, Boolean, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import os
import uuid
import shutil

Base = declarative_base()

# ===== Models =====

class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, index=True)  # recording, transcribing, complete, error
    full_transcript = Column(Text, nullable=True)
    summary_markdown = Column(Text, nullable=True)  # done
    error_message = Column(Text, nullable=True)
    is_manually_edited = Column(Boolean, nullable=False, default=False)
    is_favorite = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Workspace metadata.  These are deliberately on the established lecture
    # table so recorded lectures and handwritten Markdown notes share one API.
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True, index=True)
    source_type = Column(String(20), nullable=False, default="native")
    source_path = Column(Text, nullable=True)
    source_relative_path = Column(Text, nullable=True)

    # Relationship
    segments = relationship("TranscriptSegment", back_populates="lecture", cascade="all, delete-orphan")

    def to_dict(self, include_segments: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "id": self.id,
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "full_transcript": self.full_transcript,
            "summary_markdown": self.summary_markdown,
            "error_message": self.error_message,
            "is_manually_edited": bool(self.is_manually_edited),
            "is_favorite": bool(self.is_favorite),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "folder_id": self.folder_id,
            "source_type": self.source_type or "native",
            "source_path": self.source_path,
            "source_relative_path": self.source_relative_path,
        }
        if include_segments:
            result["segments"] = [seg.to_dict() for seg in sorted(self.segments, key=lambda s: s.sequence_number)]
        return result


class Folder(Base):
    """A recursively nested workspace folder."""
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True, index=True)
    source_type = Column(String(20), nullable=False, default="native")
    source_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

    parent = relationship("Folder", remote_side=[id], backref="children")

    def to_dict(self, children_count: Optional[int] = None) -> Dict[str, Any]:
        data = {"id": self.id, "name": self.name, "parent_id": self.parent_id,
                "source_type": self.source_type or "native", "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
        if children_count is not None:
            data["children_count"] = children_count
        return data


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    start_seconds = Column(Float, nullable=False)
    end_seconds = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationship
    lecture = relationship("Lecture", back_populates="segments")

    # Unique constraint
    __table_args__ = (
        UniqueConstraint('lecture_id', 'sequence_number', name='uq_lecture_sequence'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "lecture_id": self.lecture_id,
            "sequence_number": self.sequence_number,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "text": self.text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RagChunk(Base):
    """Rebuildable retrieval index; canonical content remains in lectures."""
    __tablename__ = "rag_chunks"
    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_kind = Column(String(20), nullable=False, index=True)
    segment_id = Column(Integer, ForeignKey("transcript_segments.id"), nullable=True)
    sequence_number = Column(Integer, nullable=True)
    start_seconds = Column(Float, nullable=True)
    end_seconds = Column(Float, nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    # JSON array.  A transcript chunk can span several immutable segments.
    segment_ids = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)
    embedding_model = Column(String(120), nullable=True)
    embedding_dimensions = Column(Integer, nullable=True)
    folder_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("lecture_id", "source_kind", "chunk_index", "content_hash", name="uq_rag_chunk_content"),)


# ===== Database Setup =====

def get_database_path() -> str:
    """Return absolute path to database file, robust regardless of working directory."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.abspath(os.path.join(base_dir, "..", "data"))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "audio_notes.db")


def create_engine_and_session():
    """
    Create SQLAlchemy engine and session factory.

    Uses StaticPool and check_same_thread=False for safe FastAPI usage with
    background threads and async context.
    """
    db_path = get_database_path()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False  # Set to True for SQL debugging
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


# Global session factory
engine, SessionLocal = create_engine_and_session()


def init_database():
    """Create all tables. Call during FastAPI startup."""
    Base.metadata.create_all(bind=engine)
    # SQLite's create_all does not add columns to existing tables. Keep this
    # lightweight migration idempotent so archived lectures remain intact.
    existing = {column["name"] for column in inspect(engine).get_columns("lectures")}
    additions = {
        "is_manually_edited": "BOOLEAN NOT NULL DEFAULT 0",
        "is_favorite": "BOOLEAN NOT NULL DEFAULT 0",
        "updated_at": "DATETIME",
        "folder_id": "INTEGER",
        "source_type": "VARCHAR(20) NOT NULL DEFAULT 'native'",
        "source_path": "TEXT",
        "source_relative_path": "TEXT",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE lectures ADD COLUMN {name} {definition}"))
        rag_columns = {column["name"] for column in inspect(engine).get_columns("rag_chunks")}
        rag_additions = {"line_start": "INTEGER", "line_end": "INTEGER", "char_start": "INTEGER", "char_end": "INTEGER", "segment_ids": "TEXT"}
        if any(name not in rag_columns for name in rag_additions):
            backup = get_database_path() + ".pre-rag-citations-backup"
            if os.path.exists(get_database_path()) and not os.path.exists(backup):
                shutil.copy2(get_database_path(), backup)
        for name, definition in rag_additions.items():
            if name not in rag_columns:
                connection.execute(text(f"ALTER TABLE rag_chunks ADD COLUMN {name} {definition}"))
        # FTS remains derived and can always be rebuilt from RagChunk records.
        connection.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(title, content, chunk_id UNINDEXED)"))
    print(f"Database initialized at: {get_database_path()}")


# ===== Repository Functions =====

def create_lecture(session_id: str, title: Optional[str] = None) -> int:
    """
    Create a new lecture record.

    Returns the lecture ID.
    """
    session = SessionLocal()
    try:
        lecture = Lecture(
            session_id=session_id,
            title=title or f"Lecture {session_id}",
            status="recording",
            created_at=datetime.now(timezone.utc)
        )
        session.add(lecture)
        session.commit()
        lecture_id = lecture.id
        return lecture_id
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def save_transcript_segment(
    lecture_id: int,
    sequence_number: int,
    start_seconds: float,
    end_seconds: float,
    text: str
) -> bool:
    """
    Save a transcript segment. Idempotent: returns True if saved or already exists.

    Returns False only on unrecoverable errors.
    """
    session = SessionLocal()
    try:
        # Check if segment already exists
        existing = session.query(TranscriptSegment).filter_by(
            lecture_id=lecture_id,
            sequence_number=sequence_number
        ).first()

        if existing:
            # Already exists, idempotent success
            return True

        segment = TranscriptSegment(
            lecture_id=lecture_id,
            sequence_number=sequence_number,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=text,
            created_at=datetime.now(timezone.utc)
        )
        session.add(segment)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error saving transcript segment: {e}")
        return False
    finally:
        session.close()


def update_lecture_status(lecture_id: int, status: str, error_message: Optional[str] = None):
    """Update lecture status and optionally set error message."""
    session = SessionLocal()
    try:
        lecture = session.query(Lecture).filter_by(id=lecture_id).first()
        if lecture:
            lecture.status = status
            lecture.updated_at = datetime.now(timezone.utc)
            if error_message:
                lecture.error_message = error_message
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def finalize_lecture(lecture_id: int, status: str = "complete", error_message: Optional[str] = None):
    """
    Finalize a lecture: build full_transcript from segments, set ended_at, update status.
    """
    session = SessionLocal()
    try:
        lecture = session.query(Lecture).filter_by(id=lecture_id).first()
        if not lecture:
            return

        # Retrieve all segments in order
        segments = session.query(TranscriptSegment).filter_by(
            lecture_id=lecture_id
        ).order_by(TranscriptSegment.sequence_number).all()

        # Build full transcript
        full_text = "\n\n".join(seg.text for seg in segments if seg.text.strip())

        lecture.full_transcript = full_text
        lecture.ended_at = datetime.now(timezone.utc)
        lecture.status = status
        lecture.updated_at = datetime.now(timezone.utc)
        if error_message:
            lecture.error_message = error_message

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_lecture_by_id(lecture_id: int) -> Optional[Dict[str, Any]]:
    """Get a single lecture with segments by ID."""
    session = SessionLocal()
    try:
        lecture = session.query(Lecture).filter_by(id=lecture_id).first()
        if not lecture:
            return None
        return lecture.to_dict(include_segments=True)
    finally:
        session.close()


def get_lecture_by_session_id(session_id: str) -> Optional[Dict[str, Any]]:
    """Get a single lecture by session_id."""
    session = SessionLocal()
    try:
        lecture = session.query(Lecture).filter_by(session_id=session_id).first()
        if not lecture:
            return None
        return lecture.to_dict(include_segments=False)
    finally:
        session.close()


def list_lectures(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List lectures, newest first, with transcript preview."""
    session = SessionLocal()
    try:
        lectures = session.query(Lecture).order_by(
            Lecture.created_at.desc()
        ).limit(limit).offset(offset).all()

        results = []
        for lecture in lectures:
            data = lecture.to_dict(include_segments=False)
            # Add preview
            if lecture.full_transcript:
                preview = lecture.full_transcript[:200]
                if len(lecture.full_transcript) > 200:
                    preview += "..."
                data["transcript_preview"] = preview
            else:
                data["transcript_preview"] = None
            results.append(data)

        return results
    finally:
        session.close()


def search_lectures(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Search lectures by title, full_transcript, or segment text.

    Uses safe parameterized queries with LIKE.
    """
    if not query or not query.strip():
        return []

    session = SessionLocal()
    try:
        search_pattern = f"%{query}%"

        # Search in lectures table
        lecture_matches = session.query(Lecture).filter(
            (Lecture.title.ilike(search_pattern)) |
            (Lecture.full_transcript.ilike(search_pattern))
        ).order_by(Lecture.created_at.desc()).limit(limit).all()

        # Also search in segments
        segment_matches = session.query(Lecture).join(TranscriptSegment).filter(
            TranscriptSegment.text.ilike(search_pattern)
        ).distinct().order_by(Lecture.created_at.desc()).limit(limit).all()

        # Combine and deduplicate
        all_lectures = {lec.id: lec for lec in lecture_matches}
        for lec in segment_matches:
            all_lectures[lec.id] = lec

        results = []
        for lecture in sorted(all_lectures.values(), key=lambda x: x.created_at, reverse=True)[:limit]:
            data = lecture.to_dict(include_segments=False)
            # Add preview
            if lecture.full_transcript:
                preview = lecture.full_transcript[:200]
                if len(lecture.full_transcript) > 200:
                    preview += "..."
                data["transcript_preview"] = preview
            else:
                data["transcript_preview"] = None
            results.append(data)

        return results
    finally:
        session.close()


def update_lecture(lecture_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Persist user-owned lecture edits without changing recording state."""
    session = SessionLocal()
    try:
        lecture = session.query(Lecture).filter_by(id=lecture_id).first()
        if not lecture:
            return None

        allowed = {"title", "summary_markdown", "is_favorite", "is_manually_edited", "folder_id", "source_type", "source_path", "source_relative_path"}
        for key in allowed.intersection(changes):
            setattr(lecture, key, changes[key])

        if "segments" in changes:
            segments = changes["segments"]
            by_sequence = {segment.sequence_number: segment for segment in lecture.segments}
            for item in segments:
                sequence = item.get("sequence_number")
                if not isinstance(sequence, int) or sequence not in by_sequence:
                    continue
                value = item.get("text")
                if isinstance(value, str):
                    by_sequence[sequence].text = value
            lecture.full_transcript = "\n\n".join(
                segment.text for segment in sorted(lecture.segments, key=lambda item: item.sequence_number)
                if segment.text.strip()
            )

        lecture.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(lecture)
        return lecture.to_dict(include_segments=True)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ===== Workspace repository functions =====

def _folder_counts(session, folder: Folder) -> int:
    return session.query(Folder).filter(Folder.parent_id == folder.id).count() + session.query(Lecture).filter(Lecture.folder_id == folder.id).count()


def list_folders() -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        folders = session.query(Folder).order_by(Folder.name.collate("NOCASE")).all()
        return [folder.to_dict(_folder_counts(session, folder)) for folder in folders]
    finally:
        session.close()


def get_folder(folder_id: int) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        folder = session.get(Folder, folder_id)
        return folder.to_dict(_folder_counts(session, folder)) if folder else None
    finally:
        session.close()


def create_folder(name: str, parent_id: Optional[int] = None, source_type: str = "native", source_path: Optional[str] = None) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        if parent_id is not None and not session.get(Folder, parent_id):
            raise ValueError("Parent folder not found")
        folder = Folder(name=name.strip(), parent_id=parent_id, source_type=source_type, source_path=source_path)
        session.add(folder); session.commit(); session.refresh(folder)
        return folder.to_dict(0)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def _descendant_ids(session, folder_id: int) -> set[int]:
    found, pending = set(), [folder_id]
    while pending:
        current = pending.pop()
        for child_id, in session.query(Folder.id).filter(Folder.parent_id == current):
            if child_id not in found:
                found.add(child_id); pending.append(child_id)
    return found


def update_folder(folder_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        folder = session.get(Folder, folder_id)
        if not folder: return None
        if "parent_id" in changes:
            parent_id = changes["parent_id"]
            if parent_id == folder_id or (parent_id is not None and parent_id in _descendant_ids(session, folder_id)):
                raise ValueError("A folder cannot be moved inside itself")
            if parent_id is not None and not session.get(Folder, parent_id): raise ValueError("Destination folder not found")
            folder.parent_id = parent_id
        if "name" in changes: folder.name = changes["name"].strip()
        folder.updated_at = datetime.now(timezone.utc); session.commit(); session.refresh(folder)
        return folder.to_dict(_folder_counts(session, folder))
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def delete_folder(folder_id: int, delete_contents: bool = False) -> bool:
    """Safe by default: reject non-empty folders; explicit cascade is opt-in."""
    session = SessionLocal()
    try:
        folder = session.get(Folder, folder_id)
        if not folder: return False
        descendants = _descendant_ids(session, folder_id)
        notes = session.query(Lecture).filter(Lecture.folder_id.in_({folder_id, *descendants})).all()
        if (descendants or notes) and not delete_contents: raise ValueError("Folder is not empty")
        if delete_contents:
            for note in notes: session.delete(note)
            for current_id in descendants: session.delete(session.get(Folder, current_id))
        session.delete(folder); session.commit(); return True
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def folder_children(folder_id: Optional[int]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        folders = session.query(Folder).filter(Folder.parent_id == folder_id).order_by(Folder.name.collate("NOCASE")).all()
        notes = session.query(Lecture).filter(Lecture.folder_id == folder_id).order_by(Lecture.updated_at.desc(), Lecture.created_at.desc()).all()
        return {"folders": [item.to_dict(_folder_counts(session, item)) for item in folders], "notes": [item.to_dict() for item in notes]}
    finally: session.close()


def create_note(title: str, folder_id: Optional[int] = None, summary_markdown: str = "", source_type: str = "native", source_relative_path: Optional[str] = None) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        if folder_id is not None and not session.get(Folder, folder_id): raise ValueError("Folder not found")
        now = datetime.now(timezone.utc)
        note = Lecture(session_id=f"note-{uuid.uuid4()}", title=title.strip(), status="complete", summary_markdown=summary_markdown, folder_id=folder_id, source_type=source_type, source_relative_path=source_relative_path, created_at=now, updated_at=now)
        session.add(note); session.commit(); session.refresh(note); return note.to_dict(True)
    except Exception:
        session.rollback(); raise
    finally: session.close()


def delete_note(note_id: int) -> bool:
    session = SessionLocal()
    try:
        note = session.get(Lecture, note_id)
        if not note: return False
        session.delete(note); session.commit(); return True
    except Exception:
        session.rollback(); raise
    finally: session.close()
