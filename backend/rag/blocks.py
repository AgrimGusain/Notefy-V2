"""Stable block identifiers for rendered Markdown notes.

The frontend renderer (``app.safeMarkdownToHTML`` in frontend/js/app.js) emits
one block per non-blank source line and tags it with ``data-block-id``.  This
module mirrors that algorithm exactly so citations can name the rendered block
they point to.  Keep the two implementations in sync.

IDs are derived from the enclosing heading rather than line numbers, so editing
one section does not change the IDs of blocks in other sections:

    ## Process States        -> "process-states"
    A process can be...      -> "process-states--1"
    - Ready                  -> "process-states--2"

Blocks before the first heading belong to the reserved "top" section. Lines
inside a fenced code block are never headings, so a "# comment" in code does
not start a new section.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import unicodedata

TOP_SECTION = "top"
# The character class mirrors JavaScript's "." so both sides agree on what is a heading.
_HEADING = re.compile(r"^(#{1,6})\s+([^\r\n\u2028\u2029]*)$")
# CommonMark fences, as in the renderer: an opener of 3+ backticks/tildes (optional info string),
# closed by a line of the same character, at least as long, with nothing after it.
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")


@dataclass(frozen=True)
class Block:
    id: str
    line: int  # 1-indexed source line
    section_id: str
    heading: str | None  # text of the enclosing heading, None before the first heading


def slugify(text: str) -> str:
    """Lowercase, keep Unicode letters/marks/numbers, join words with '-'."""
    kept = "".join(ch for ch in text.lower() if ch in "_-" or ch.isspace() or unicodedata.category(ch)[0] in "LMN")
    slug = re.sub(r"-+", "-", re.sub(r"\s+", "-", kept.strip())).strip("-")
    return slug or "section"


def source_lines(markdown: str) -> list[str]:
    # Matches the renderer: split on "\n" and drop a trailing "\r" (CRLF files).
    return [line[:-1] if line.endswith("\r") else line for line in (markdown or "").split("\n")]


def markdown_blocks(markdown: str) -> list[Block]:
    used, blocks = {TOP_SECTION}, []
    section, heading, count = TOP_SECTION, None, 0
    fence = None
    for index, raw in enumerate(source_lines(markdown)):
        if not raw.strip():
            continue
        opened = None if fence else _FENCE_OPEN.match(raw)
        if fence:
            closing = _FENCE_CLOSE.match(raw)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
        elif opened:
            fence = opened.group(1)
        match = None if fence or opened else _HEADING.match(raw)
        if match:
            base = candidate = slugify(match.group(2))
            suffix = 2
            while candidate in used:
                candidate = f"{base}-{suffix}"; suffix += 1
            used.add(candidate)
            section, heading, count = candidate, match.group(2).strip(), 0
            blocks.append(Block(section, index + 1, section, heading))
        else:
            count += 1
            blocks.append(Block(f"{section}--{count}", index + 1, section, heading))
    return blocks
