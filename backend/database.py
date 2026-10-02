"""
Database module for Audio-Notes application.

Provides SQLAlchemy models and persistence functions for lectures and transcript segments.
Uses SQLite with safe configuration for FastAPI async/background thread usage.
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint, Boolean, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import os
import json
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
    # No delete cascade: deleting a recording detaches its clips (lecture_id -> NULL) but keeps them.
    clips = relationship("Clip", back_populates="lecture")

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
    # Markdown only: JSON array of rendered-note block IDs (rag/blocks.py) and the section heading.
    block_ids = Column(Text, nullable=True)
    heading = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)
    embedding_model = Column(String(120), nullable=True)
    embedding_dimensions = Column(Integer, nullable=True)
    folder_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("lecture_id", "source_kind", "chunk_index", "content_hash", name="uq_rag_chunk_content"),)


class Clip(Base):
    """A saved, contiguous transcript range from one recording.

    Timing and text are snapshots taken from the transcript segments when the
    clip is created, so later transcript edits or deleting the recording never
    change a saved clip.  The transcript itself is only read, never written.
    """
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=True, index=True)  # NULL once the recording is deleted
    segment_ids = Column(Text, nullable=False)  # JSON array of transcript_segments.id, in transcript order
    start_seconds = Column(Float, nullable=False)
    end_seconds = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    title = Column(String(500), nullable=True)
    source_title = Column(String(500), nullable=True)  # recording title at clip time, shown if the recording is deleted
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

    lecture = relationship("Lecture", back_populates="clips")
    items = relationship("ClipCollectionItem", back_populates="clip", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lecture_id": self.lecture_id,
            "source_title": self.lecture.title if self.lecture else self.source_title,
            "source_deleted": self.lecture_id is None,
            "segment_ids": json.loads(self.segment_ids),
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "duration_seconds": round(self.end_seconds - self.start_seconds, 3),
            "text": self.text,
            "title": self.title,
            "collections": [{"id": item.collection.id, "title": item.collection.title} for item in self.items],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClipCollection(Base):
    """An ordered set of clips, possibly from many recordings."""
    __tablename__ = "clip_collections"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship("ClipCollectionItem", back_populates="collection", cascade="all, delete-orphan",
                         order_by="(ClipCollectionItem.position, ClipCollectionItem.id)")

    def to_dict(self, include_items: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id, "title": self.title, "description": self.description,
            "clip_count": len(self.items),
            "total_seconds": round(sum(item.clip.end_seconds - item.clip.start_seconds for item in self.items), 3),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            data["items"] = [{"item_id": item.id, "position": index + 1, "clip": item.clip.to_dict()} for index, item in enumerate(self.items)]
        return data


class ClipCollectionItem(Base):
    """Membership of a clip in a collection; removing it never deletes the clip."""
    __tablename__ = "clip_collection_items"

    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey("clip_collections.id"), nullable=False, index=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    collection = relationship("ClipCollection", back_populates="items")
    clip = relationship("Clip", back_populates="items")
    __table_args__ = (UniqueConstraint("collection_id", "clip_id", name="uq_collection_clip"),)


class RecallSession(Base):
    """An Active Recall study session over a chosen scope of notes, recordings or clips.

    Only what is needed to resume and review a session is stored: the scope,
    the questions, the student's answers and the grades.  Sources are kept as
    references (RAG citation IDs / clip IDs), not copies of the notes, and API
    keys, provider URLs and raw prompts are never stored.
    """
    __tablename__ = "recall_sessions"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)  # scope label at creation, e.g. "Folder · Operating Systems"
    scope_type = Column(String(20), nullable=False)  # all | notes | folder | lecture | collection
    scope_ids = Column(Text, nullable=False, default="[]")  # JSON array of lecture/folder/collection IDs
    question_types = Column(Text, nullable=False)  # JSON array: short_answer, conceptual, application
    target_count = Column(Integer, nullable=False, default=8)
    model = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active | ended
    summary = Column(Text, nullable=True)  # JSON snapshot of the results, written when the session ends
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    questions = relationship("RecallQuestion", back_populates="session", cascade="all, delete-orphan", order_by="RecallQuestion.position")

    def to_dict(self, include_questions: bool = False, reveal: bool = False) -> Dict[str, Any]:
        outcomes = [question.outcome() for question in self.questions]
        data = {
            "id": self.id, "title": self.title, "scope_type": self.scope_type, "scope_ids": json.loads(self.scope_ids or "[]"),
            "question_types": json.loads(self.question_types), "target_count": self.target_count, "model": self.model, "status": self.status,
            "question_count": len(self.questions), "outcomes": {name: outcomes.count(name) for name in RECALL_OUTCOMES},
            "summary": json.loads(self.summary) if self.summary else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }
        if include_questions:
            data["questions"] = [question.to_dict(reveal=reveal or self.status == "ended") for question in self.questions]
        return data


RECALL_VERDICTS = ("correct", "partially_correct", "incorrect")
RECALL_OUTCOMES = RECALL_VERDICTS + ("skipped", "revealed", "pending")


class RecallQuestion(Base):
    """One generated question; expected points stay hidden from the client until revealed."""
    __tablename__ = "recall_questions"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("recall_sessions.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    question_type = Column(String(20), nullable=False)
    topic = Column(String(200), nullable=True)
    question = Column(Text, nullable=False)
    expected_points = Column(Text, nullable=False)  # JSON array of points stated in the sources
    explanation = Column(Text, nullable=True)
    sources = Column(Text, nullable=False)  # JSON array of {"ref": "C12"|"T7"|"K3", "label": str, "cited": bool}; all are used for grading
    skipped = Column(Boolean, nullable=False, default=False)
    revealed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    session = relationship("RecallSession", back_populates="questions")
    attempts = relationship("RecallAttempt", back_populates="question", cascade="all, delete-orphan", order_by="RecallAttempt.id")

    def outcome(self) -> str:
        """How the question counts: the last answer given before the explanation was revealed."""
        graded = [attempt for attempt in self.attempts if not attempt.after_reveal]
        if graded: return graded[-1].verdict
        if self.revealed: return "revealed"
        return "skipped" if self.skipped else "pending"

    def counted_attempt(self) -> Optional["RecallAttempt"]:
        graded = [attempt for attempt in self.attempts if not attempt.after_reveal]
        return graded[-1] if graded else None

    def to_dict(self, reveal: bool = False) -> Dict[str, Any]:
        show = reveal or self.revealed
        counted = self.counted_attempt()
        return {
            "id": self.id, "position": self.position, "question_type": self.question_type, "topic": self.topic, "question": self.question,
            "sources": json.loads(self.sources), "skipped": bool(self.skipped), "revealed": bool(self.revealed), "outcome": self.outcome(),
            "score": counted.score if counted else 0.0,
            "expected_points": json.loads(self.expected_points) if show else None, "explanation": self.explanation if show else None,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RecallAttempt(Base):
    """A graded answer. Retries add attempts; nothing is overwritten."""
    __tablename__ = "recall_attempts"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("recall_questions.id"), nullable=False, index=True)
    answer = Column(Text, nullable=False)
    verdict = Column(String(20), nullable=False)
    score = Column(Float, nullable=False)
    feedback = Column(Text, nullable=False)
    correct_points = Column(Text, nullable=False, default="[]")
    missing_points = Column(Text, nullable=False, default="[]")
    misconceptions = Column(Text, nullable=False, default="[]")
    source_refs = Column(Text, nullable=False, default="[]")  # citation refs the grader pointed to, a subset of the question's sources
    after_reveal = Column(Boolean, nullable=False, default=False)  # practice after seeing the answer; not counted in the score
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    question = relationship("RecallQuestion", back_populates="attempts")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "answer": self.answer, "verdict": self.verdict, "score": self.score, "feedback": self.feedback,
            "correct_points": json.loads(self.correct_points), "missing_points": json.loads(self.missing_points),
            "misconceptions": json.loads(self.misconceptions), "source_refs": json.loads(self.source_refs), "after_reveal": bool(self.after_reveal),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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

    Uses SQLAlchemy's default pool so each worker thread (asyncio.to_thread)
    gets its own connection. A single shared connection (StaticPool) let
    concurrent requests interleave cursors and corrupt each other's result
    rows. check_same_thread=False allows pooled connections to move between
    threads; the busy timeout makes concurrent writers wait instead of failing.
    """
    db_path = get_database_path()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
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
        rag_additions = {"line_start": "INTEGER", "line_end": "INTEGER", "char_start": "INTEGER", "char_end": "INTEGER", "segment_ids": "TEXT", "block_ids": "TEXT", "heading": "TEXT"}
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
    Search lectures by title, transcript, AI summary, or segment text.

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
            (Lecture.full_transcript.ilike(search_pattern)) |
            (Lecture.summary_markdown.ilike(search_pattern))
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


# ===== Clips and collections =====

def format_clock(seconds: float) -> str:
    """HH:MM:SS, the format clips and collections are displayed in."""
    total = int(seconds or 0)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _clippable_segments(lecture: Lecture) -> List[TranscriptSegment]:
    # Empty segments (silence) can't be selected; a clip spanning one is still contiguous audio.
    return [segment for segment in sorted(lecture.segments, key=lambda item: item.sequence_number) if segment.text and segment.text.strip()]


def create_clip(lecture_id: int, segment_ids: List[int], title: Optional[str] = None, collection_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Save a contiguous range of a recording's transcript. Returns None if the recording does not exist.

    Timing and text come from the stored segments, never from the client.
    """
    if not segment_ids or len(set(segment_ids)) != len(segment_ids):
        raise ValueError("Select one or more distinct transcript segments")
    session = SessionLocal()
    try:
        lecture = session.get(Lecture, lecture_id)
        if not lecture:
            return None
        ordered = _clippable_segments(lecture)
        if not ordered:
            raise ValueError("This note has no transcript to clip")
        index_of = {segment.id: index for index, segment in enumerate(ordered)}
        if any(segment_id not in index_of for segment_id in segment_ids):
            raise ValueError("Every selected segment must be a transcript segment of this recording")
        indexes = sorted(index_of[segment_id] for segment_id in segment_ids)
        if indexes[-1] - indexes[0] != len(indexes) - 1:
            raise ValueError("Clip segments must be contiguous; save separate ranges as separate clips")
        chosen = ordered[indexes[0]:indexes[-1] + 1]
        collection = None
        if collection_id is not None:
            collection = session.get(ClipCollection, collection_id)
            if not collection:
                raise ValueError("Collection not found")
        now = datetime.now(timezone.utc)
        clip = Clip(lecture_id=lecture.id, segment_ids=json.dumps([segment.id for segment in chosen]),
                    start_seconds=chosen[0].start_seconds, end_seconds=chosen[-1].end_seconds,
                    text="\n\n".join(segment.text.strip() for segment in chosen),
                    title=(title or "").strip() or None, source_title=lecture.title, created_at=now, updated_at=now)
        session.add(clip)
        if collection:
            _append_to_collection(session, collection, clip)
        session.commit(); session.refresh(clip)
        return clip.to_dict()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def list_clips(lecture_id: Optional[int] = None) -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        query = session.query(Clip)
        if lecture_id is not None:
            query = query.filter(Clip.lecture_id == lecture_id)
        return [clip.to_dict() for clip in query.order_by(Clip.created_at.desc(), Clip.id.desc()).all()]
    finally:
        session.close()


def get_clip(clip_id: int) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        clip = session.get(Clip, clip_id)
        return clip.to_dict() if clip else None
    finally:
        session.close()


def update_clip(clip_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Only the label is editable; range and text are fixed at creation."""
    session = SessionLocal()
    try:
        clip = session.get(Clip, clip_id)
        if not clip:
            return None
        if "title" in changes:
            clip.title = (changes["title"] or "").strip() or None
        clip.updated_at = datetime.now(timezone.utc)
        session.commit(); session.refresh(clip)
        return clip.to_dict()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def delete_clip(clip_id: int) -> bool:
    """Deletes the clip and its collection memberships; the recording is untouched."""
    session = SessionLocal()
    try:
        clip = session.get(Clip, clip_id)
        if not clip:
            return False
        session.delete(clip); session.commit(); return True
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def _append_to_collection(session, collection: ClipCollection, clip: Clip) -> ClipCollectionItem:
    position = max((item.position for item in collection.items), default=-1) + 1
    item = ClipCollectionItem(collection=collection, clip=clip, position=position)
    session.add(item)
    collection.updated_at = datetime.now(timezone.utc)
    return item


def list_collections() -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        return [collection.to_dict() for collection in session.query(ClipCollection).order_by(ClipCollection.title.collate("NOCASE")).all()]
    finally:
        session.close()


def create_collection(title: str, description: Optional[str] = None) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        collection = ClipCollection(title=title.strip(), description=(description or "").strip() or None, created_at=now, updated_at=now)
        session.add(collection); session.commit(); session.refresh(collection)
        return collection.to_dict(include_items=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def get_collection(collection_id: int) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        collection = session.get(ClipCollection, collection_id)
        return collection.to_dict(include_items=True) if collection else None
    finally:
        session.close()


def update_collection(collection_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        collection = session.get(ClipCollection, collection_id)
        if not collection:
            return None
        if "title" in changes:
            collection.title = changes["title"].strip()
        if "description" in changes:
            collection.description = (changes["description"] or "").strip() or None
        collection.updated_at = datetime.now(timezone.utc)
        session.commit(); session.refresh(collection)
        return collection.to_dict(include_items=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def delete_collection(collection_id: int) -> bool:
    """Deletes the collection and its memberships; the clips themselves remain."""
    session = SessionLocal()
    try:
        collection = session.get(ClipCollection, collection_id)
        if not collection:
            return False
        session.delete(collection); session.commit(); return True
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def add_clip_to_collection(collection_id: int, clip_id: int) -> Optional[Dict[str, Any]]:
    """Append a clip to a collection. Adding a clip that is already there is a no-op."""
    session = SessionLocal()
    try:
        collection, clip = session.get(ClipCollection, collection_id), session.get(Clip, clip_id)
        if not collection:
            return None
        if not clip:
            raise ValueError("Clip not found")
        if not any(item.clip_id == clip_id for item in collection.items):
            _append_to_collection(session, collection, clip)
            session.commit(); session.refresh(collection)
        return collection.to_dict(include_items=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def remove_collection_item(collection_id: int, item_id: int) -> Optional[Dict[str, Any]]:
    """Remove a clip from a collection without deleting the clip or its recording."""
    session = SessionLocal()
    try:
        collection = session.get(ClipCollection, collection_id)
        item = session.get(ClipCollectionItem, item_id)
        if not collection or not item or item.collection_id != collection_id:
            return None
        collection.items.remove(item)
        collection.updated_at = datetime.now(timezone.utc)
        session.commit(); session.refresh(collection)
        return collection.to_dict(include_items=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def reorder_collection(collection_id: int, item_ids: List[int]) -> Optional[Dict[str, Any]]:
    """Set the clip order. item_ids must list every item of the collection exactly once."""
    session = SessionLocal()
    try:
        collection = session.get(ClipCollection, collection_id)
        if not collection:
            return None
        by_id = {item.id: item for item in collection.items}
        if len(item_ids) != len(by_id) or set(item_ids) != set(by_id):
            raise ValueError("The new order must list every clip in the collection exactly once")
        for position, item_id in enumerate(item_ids):
            by_id[item_id].position = position
        collection.updated_at = datetime.now(timezone.utc)
        session.commit(); session.expire_all()
        return session.get(ClipCollection, collection_id).to_dict(include_items=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def collection_source(collection_id: int) -> Optional[Dict[str, Any]]:
    """The collection as one ordered, source-labelled transcript.

    This is the input format the existing AI layer accepts (ai.manager.generate
    takes a transcript string), so a collection can later feed note generation
    or active recall without further data work.
    """
    collection = get_collection(collection_id)
    if not collection:
        return None
    blocks = []
    for item in collection["items"]:
        clip = item["clip"]
        label = f"[{item['position']}. {clip['source_title'] or 'Deleted recording'} · {format_clock(clip['start_seconds'])}–{format_clock(clip['end_seconds'])}"
        label += f" · {clip['title']}]" if clip["title"] else "]"
        blocks.append(f"{label}\n{clip['text']}")
    return {"collection_id": collection["id"], "title": collection["title"], "clip_count": collection["clip_count"],
            "transcript": "\n\n".join(blocks), "clips": [item["clip"] for item in collection["items"]]}


# ===== Active Recall =====

def create_recall_session(title: str, scope_type: str, scope_ids: List[int], question_types: List[str], target_count: int, model: Optional[str]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        row = RecallSession(title=title[:500], scope_type=scope_type, scope_ids=json.dumps(scope_ids), question_types=json.dumps(question_types),
                            target_count=target_count, model=(model or None) and model[:200], created_at=now, updated_at=now)
        session.add(row); session.commit(); session.refresh(row)
        return row.to_dict(include_questions=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def list_recall_sessions(limit: int = 30) -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        return [row.to_dict() for row in session.query(RecallSession).order_by(RecallSession.created_at.desc(), RecallSession.id.desc()).limit(limit)]
    finally:
        session.close()


def get_recall_session(session_id: int, reveal: bool = False) -> Optional[Dict[str, Any]]:
    """reveal=True includes hidden expected points; only for server-side use."""
    session = SessionLocal()
    try:
        row = session.get(RecallSession, session_id)
        return row.to_dict(include_questions=True, reveal=reveal) if row else None
    finally:
        session.close()


def recall_question_record(question_id: int) -> Optional[Dict[str, Any]]:
    """Server-side view of a question, including the hidden expected points."""
    session = SessionLocal()
    try:
        question = session.get(RecallQuestion, question_id)
        if not question: return None
        return {**question.to_dict(reveal=True), "session_id": question.session_id, "session_status": question.session.status}
    finally:
        session.close()


def add_recall_question(session_id: int, *, question_type: str, topic: str, question: str, expected_points: List[str], explanation: str, sources: List[Dict[str, str]]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        row = session.get(RecallSession, session_id)
        if not row: raise LookupError("Recall session not found")
        item = RecallQuestion(session_id=session_id, position=len(row.questions) + 1, question_type=question_type, topic=topic[:200], question=question,
                              expected_points=json.dumps(expected_points), explanation=explanation, sources=json.dumps(sources))
        session.add(item); row.updated_at = datetime.now(timezone.utc); session.commit(); session.refresh(item)
        return item.to_dict()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def add_recall_attempt(question_id: int, *, answer: str, verdict: str, score: float, feedback: str, correct_points: List[str],
                       missing_points: List[str], misconceptions: List[str], source_refs: List[str]) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        question = session.get(RecallQuestion, question_id)
        if not question: return None
        if verdict not in RECALL_VERDICTS: raise ValueError("Unknown verdict")
        session.add(RecallAttempt(question_id=question_id, answer=answer, verdict=verdict, score=score, feedback=feedback,
                                  correct_points=json.dumps(correct_points), missing_points=json.dumps(missing_points),
                                  misconceptions=json.dumps(misconceptions), source_refs=json.dumps(source_refs), after_reveal=bool(question.revealed)))
        question.session.updated_at = datetime.now(timezone.utc); session.commit(); session.refresh(question)
        return question.to_dict()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def mark_recall_question(question_id: int, *, skipped: Optional[bool] = None, revealed: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        question = session.get(RecallQuestion, question_id)
        if not question: return None
        if skipped: question.skipped = True
        if revealed: question.revealed = True
        question.session.updated_at = datetime.now(timezone.utc); session.commit(); session.refresh(question)
        return question.to_dict()
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def end_recall_session(session_id: int, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        row = session.get(RecallSession, session_id)
        if not row: return None
        now = datetime.now(timezone.utc)
        row.status, row.summary, row.ended_at, row.updated_at = "ended", json.dumps(summary), row.ended_at or now, now
        session.commit(); session.refresh(row)
        return row.to_dict(include_questions=True)
    except Exception:
        session.rollback(); raise
    finally:
        session.close()


def delete_recall_session(session_id: int) -> bool:
    session = SessionLocal()
    try:
        row = session.get(RecallSession, session_id)
        if not row: return False
        session.delete(row); session.commit(); return True
    except Exception:
        session.rollback(); raise
    finally:
        session.close()
