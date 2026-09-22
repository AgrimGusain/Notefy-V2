"""Deterministic extraction/chunking that keeps source metadata intact."""
from __future__ import annotations
from dataclasses import dataclass
import re
import os

@dataclass(frozen=True)
class Chunk:
    content: str; source_kind: str; segment_id: int | None = None
    sequence_number: int | None = None; start_seconds: float | None = None; end_seconds: float | None = None
    line_start: int | None = None; line_end: int | None = None
    char_start: int | None = None; char_end: int | None = None
    segment_ids: tuple[int, ...] = ()

def _settings() -> tuple[int, int]:
    return int(os.getenv("RAG_CHUNK_SIZE", "500")), int(os.getenv("RAG_CHUNK_OVERLAP", "75"))

def _words(value: str) -> int: return len(re.findall(r"\S+", value))

def transcript_chunks(segments) -> list[Chunk]:
    size, overlap = _settings()
    usable = [segment for segment in segments if segment.text and segment.text.strip()]
    result, start = [], 0
    while start < len(usable):
        selected, count, end = [], 0, start
        while end < len(usable):
            next_count = _words(usable[end].text)
            if selected and count + next_count > size: break
            selected.append(usable[end]); count += next_count; end += 1
        if not selected: selected, end = [usable[start]], start + 1
        content = "\n\n".join(item.text for item in selected)
        result.append(Chunk(content, "transcript", selected[0].id, selected[0].sequence_number,
                            selected[0].start_seconds, selected[-1].end_seconds,
                            segment_ids=tuple(item.id for item in selected)))
        if end >= len(usable): break
        # Overlap only on complete timestamped segments, never invented time ranges.
        keep, back = 0, end
        while back > start and keep < overlap:
            back -= 1; keep += _words(usable[back].text)
        start = max(back, start + 1)
    return result

def markdown_chunks(markdown: str) -> list[Chunk]:
    # Keep original newlines and offsets; citation ranges are recorded here, never reconstructed later.
    size, overlap = _settings(); lines = (markdown or "").splitlines(keepends=True)
    result, start, heading = [], 0, ""
    while start < len(lines):
        while start < len(lines) and not lines[start].strip(): start += 1
        if start >= len(lines): break
        end, count, current_heading = start, 0, heading
        while end < len(lines):
            raw = lines[end]; stripped = raw.strip()
            if re.match(r"^#{1,6}\s+", stripped): current_heading = stripped
            words = _words(raw)
            if end > start and count + words > size: break
            count += words; end += 1
        content = "".join(lines[start:end])
        if content.strip():
            # Heading is context only when it is actually part of the cited line range.
            result.append(Chunk(content, "markdown", line_start=start + 1, line_end=end,
                                char_start=sum(len(item) for item in lines[:start]), char_end=sum(len(item) for item in lines[:end])))
        heading = current_heading
        if end >= len(lines): break
        keep, back = 0, end
        while back > start and keep < overlap:
            back -= 1; keep += _words(lines[back])
        start = max(back, start + 1)
    return result
