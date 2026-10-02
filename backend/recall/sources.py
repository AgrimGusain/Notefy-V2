"""Study material for Active Recall: scope resolution and source passages.

Notes and recordings are read from the existing RAG index (rag_chunks), so
every passage already carries a database-resolvable citation ID (C<id> for a
Markdown chunk, T<id> for a transcript chunk). Clip collections are read from
their saved clips (K<clip id>), which link to the exact recording range.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import random
import re

from database import SessionLocal, Lecture, Folder, RagChunk, Clip, ClipCollection, _descendant_ids
from rag.citations import resolve_citation
from rag.prompts import citation_id
from rag.retriever import search_chunks
from ai.synthesis import clock

SCOPE_TYPES = ("all", "notes", "folder", "lecture", "collection")
MAX_NOTES = 200
MIN_PASSAGE_WORDS = 25
MAX_CONTEXT_CHARS = 7_000


@dataclass(frozen=True)
class Passage:
    ref: str            # citation ID: C12 / T7 (RAG chunk) or K3 (clip)
    kind: str           # markdown | transcript | clip
    lecture_id: int | None
    title: str
    heading: str | None
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None

    @property
    def label(self) -> str:
        if self.kind == "markdown":
            # A note's top heading usually repeats its title; only name a section when it adds something.
            heading = (self.heading or "").lstrip("#").strip()
            return f"{self.title} § {heading}" if heading and heading.lower() != self.title.strip().lower() else self.title
        return f"{self.title} · {clock(self.start_seconds or 0)}–{clock(self.end_seconds or 0)}"


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def resolve_scope(scope_type: str, ids: list[int]) -> dict:
    """Validate a scope and describe it. Raises LookupError (missing item) or ValueError (bad request)."""
    if scope_type not in SCOPE_TYPES:
        raise ValueError("Choose what to study: all notes, notes, a folder, a lecture or a clip collection")
    session = SessionLocal()
    try:
        if scope_type == "all":
            return {"scope_type": "all", "scope_ids": [], "title": "All notes"}
        if not ids:
            raise ValueError("Choose what to study")
        if scope_type == "notes":
            ids = list(dict.fromkeys(ids))
            if len(ids) > MAX_NOTES: raise ValueError(f"Choose at most {MAX_NOTES} notes")
            found = {row.id: row.title for row in session.query(Lecture).filter(Lecture.id.in_(ids))}
            if len(found) != len(ids): raise LookupError("One or more selected notes no longer exist")
            titles = [found[item] or "Untitled" for item in ids]
            return {"scope_type": "notes", "scope_ids": ids, "title": titles[0] if len(ids) == 1 else f"{len(ids)} notes · {titles[0]}, …"}
        if len(ids) != 1:
            raise ValueError("Choose one item to study")
        model = {"folder": Folder, "lecture": Lecture, "collection": ClipCollection}[scope_type]
        row = session.get(model, ids[0])
        if not row: raise LookupError(f"That {scope_type} no longer exists")
        name = getattr(row, "name", None) or getattr(row, "title", None) or "Untitled"
        return {"scope_type": scope_type, "scope_ids": ids, "title": f"{scope_type.capitalize()} · {name}"}
    finally:
        session.close()


def _scope_lecture_ids(session, scope_type: str, ids: list[int]) -> list[int] | None:
    if scope_type == "all": return None
    if scope_type in ("notes", "lecture"): return list(ids)
    folders = {ids[0], *_descendant_ids(session, ids[0])}
    return [row[0] for row in session.query(Lecture.id).filter(Lecture.folder_id.in_(folders))]


def candidate_passages(scope_type: str, ids: list[int]) -> list[Passage]:
    """Every passage in scope a question may be written from."""
    session = SessionLocal()
    try:
        if scope_type == "collection":
            collection = session.get(ClipCollection, ids[0])
            if not collection: raise LookupError("That collection no longer exists")
            return [_clip_passage(item.clip) for item in collection.items if item.clip.text.strip()]
        lecture_ids = _scope_lecture_ids(session, scope_type, ids)
        query = session.query(RagChunk, Lecture).join(Lecture, Lecture.id == RagChunk.lecture_id)
        if lecture_ids is not None:
            if not lecture_ids: return []
            query = query.filter(RagChunk.lecture_id.in_(lecture_ids))
        rows = query.order_by(RagChunk.lecture_id, RagChunk.chunk_index).all()
    finally:
        session.close()
    # A recording's written notes are the distilled version of its transcript: study those when they exist.
    has_notes = {chunk.lecture_id for chunk, _ in rows if chunk.source_kind == "markdown"}
    passages = [_chunk_passage(chunk, lecture) for chunk, lecture in rows
                if chunk.source_kind == "markdown" or chunk.lecture_id not in has_notes]
    substantial = [item for item in passages if _words(item.text) >= MIN_PASSAGE_WORDS]
    return substantial or [item for item in passages if item.text.strip()]


def _chunk_passage(chunk: RagChunk, lecture: Lecture) -> Passage:
    ref = citation_id({"id": chunk.id, "source_kind": chunk.source_kind})
    return Passage(ref, "markdown" if chunk.source_kind == "markdown" else "transcript", chunk.lecture_id, lecture.title or "Untitled",
                   chunk.heading, chunk.content, chunk.start_seconds, chunk.end_seconds)


def _clip_passage(clip: Clip) -> Passage:
    title = (clip.lecture.title if clip.lecture else clip.source_title) or "Untitled recording"
    return Passage(f"K{clip.id}", "clip", clip.lecture_id, title, clip.title, clip.text, clip.start_seconds, clip.end_seconds)


MAX_PASSAGE_REUSE = 3


def choose_seed(passages: list[Passage], ref_counts: dict, lecture_counts: dict, rng: random.Random, exclude: set[str] = frozenset()) -> Passage | None:
    """Spread questions over the scope: unused passages first, from the least-asked note or recording.

    Small scopes may revisit a passage (a different question type or angle) up to MAX_PASSAGE_REUSE times.
    """
    pool = [item for item in passages if item.ref not in exclude and ref_counts.get(item.ref, 0) < MAX_PASSAGE_REUSE]
    if not pool: return None
    rank = lambda item: (ref_counts.get(item.ref, 0), lecture_counts.get(item.lecture_id, 0))
    best = min(rank(item) for item in pool)
    return rng.choice([item for item in pool if rank(item) == best])


def question_context(seed: Passage, passages: list[Passage]) -> list[Passage]:
    """The seed plus closely related material from the same source, found with the existing hybrid RAG search."""
    chosen, used = [seed], len(seed.text)
    if seed.kind == "clip":
        # Clips are short by design; give a very short clip its neighbour in collection order.
        index = passages.index(seed)
        if _words(seed.text) < 60 and index + 1 < len(passages):
            chosen.append(passages[index + 1])
        return chosen
    in_scope = {item.ref: item for item in passages}
    query = " ".join(filter(None, [seed.heading, " ".join(seed.text.split()[:60])]))
    for row in search_chunks(query, top_k=4, lecture_id=seed.lecture_id):
        ref = citation_id(row)
        related = in_scope.get(ref)
        if related and ref != seed.ref and used + len(related.text) <= MAX_CONTEXT_CHARS:
            chosen.append(related); used += len(related.text)
        if len(chosen) == 3: break
    return chosen


def load_passages(refs: list[str]) -> list[Passage]:
    """Re-read a question's sources from the database for grading. Missing sources are left out."""
    chunk_ids = [int(ref[1:]) for ref in refs if ref[:1] in "CT" and ref[1:].isdigit()]
    clip_ids = [int(ref[1:]) for ref in refs if ref[:1] == "K" and ref[1:].isdigit()]
    session = SessionLocal()
    try:
        found = {}
        if chunk_ids:
            for chunk, lecture in session.query(RagChunk, Lecture).join(Lecture, Lecture.id == RagChunk.lecture_id).filter(RagChunk.id.in_(chunk_ids)):
                passage = _chunk_passage(chunk, lecture); found[passage.ref] = passage
        if clip_ids:
            for clip in session.query(Clip).filter(Clip.id.in_(clip_ids)):
                passage = _clip_passage(clip); found[passage.ref] = passage
        return [found[ref] for ref in refs if ref in found]
    finally:
        session.close()


def citation_for(source: dict) -> dict:
    """A clickable, database-resolved citation for a stored source reference."""
    ref, label = source["ref"], source.get("label") or source["ref"]
    if ref[:1] in "CT":
        resolved = resolve_citation(ref)
        return {**resolved, "label": label} if resolved else {"citation_id": ref, "label": label, "missing": True}
    session = SessionLocal()
    try:
        clip = session.get(Clip, int(ref[1:])) if ref[1:].isdigit() else None
        if not clip: return {"citation_id": ref, "label": label, "missing": True}
        return {"citation_id": ref, "source_type": "clip", "label": label, "lecture_id": clip.lecture_id, "source_deleted": clip.lecture_id is None,
                "segment_ids": json.loads(clip.segment_ids), "timestamp_start": clip.start_seconds, "timestamp_end": clip.end_seconds,
                "snippet": clip.text[:280], "href": f"#note/{clip.lecture_id}/t/{clip.start_seconds:g}-{clip.end_seconds:g}" if clip.lecture_id else None}
    finally:
        session.close()
