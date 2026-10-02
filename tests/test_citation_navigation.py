"""Citation → rendered-note navigation metadata.

The backend (rag/blocks.py) and the frontend renderer (frontend/js/app.js)
must assign identical block IDs, otherwise a citation cannot find its block.
"""
import json, os, shutil, subprocess, sys, uuid
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import pytest
from database import init_database, create_note, delete_note
from rag.blocks import markdown_blocks, slugify
from rag.chunking import markdown_chunks
from rag.indexer import index_lecture, remove_lecture_from_index
from rag.retriever import search_chunks
from rag.citations import resolve_citation

NOTE = "Intro line\r\n## Process States\r\nA process can be running, ready or blocked.\n- Ready: waiting for the CPU\n- Blocked: waiting for I/O\n\n## Process States\n# Top\n### Café & Ünïcode — test\ntext\n"

def test_block_ids_are_section_scoped_and_unique():
    ids = [block.id for block in markdown_blocks(NOTE)]
    assert ids == ["top--1", "process-states", "process-states--1", "process-states--2", "process-states--3",
                   "process-states-2", "top-2", "café-ünïcode-test", "café-ünïcode-test--1"]
    assert slugify("  **Bold** heading! ") == "bold-heading" and slugify("!!!") == "section"

def test_editing_one_section_keeps_other_block_ids():
    before = {b.line: b.id for b in markdown_blocks("# A\nx\n# B\ny\nz\n")}
    after = [b.id for b in markdown_blocks("# A\nx\nnew line\nanother\n# B\ny\nz\n")]
    assert "b--1" in after and "b--2" in after and before[5] == "b--2"

@pytest.mark.skipif(not shutil.which("node"), reason="node is required to run the frontend renderer")
def test_frontend_renderer_emits_the_same_block_ids():
    script = """
const fs=require('fs');const stub=new Proxy(function(){},{get:(t,k)=>k==='addEventListener'?()=>{}:stub,apply:()=>stub});
global.window={};global.document={getElementById:()=>stub,querySelectorAll:()=>[],addEventListener:()=>{},createElement:()=>stub,body:stub,head:stub};
try{eval(fs.readFileSync(process.argv[1],'utf8'));}catch(_){/* app.js wires DOM events after defining the renderer */}
const html=window.AudioNotes.safeMarkdownToHTML(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify([...html.matchAll(/data-line="(\\d+)" data-block-id="([^"]*)"/g)].map(m=>[Number(m[1]),m[2]])));
"""
    result = subprocess.run(["node", "-e", script, os.path.join(ROOT, "frontend", "js", "app.js")], input=NOTE.encode("utf-8"), capture_output=True, check=True)
    assert json.loads(result.stdout.decode("utf-8")) == [[b.line, b.id] for b in markdown_blocks(NOTE)]

def test_chunks_carry_block_ids_and_heading():
    chunk = markdown_chunks("# OS\n## Process States\nA process can be...\nIt moves between states.\n")[0]
    assert chunk.block_ids == ("os", "process-states", "process-states--1", "process-states--2") and chunk.heading == "OS"

def test_resolved_citations_for_heading_paragraph_and_multiline_ranges():
    init_database()
    markdown = "## Process States\nA process can be running or ready.\nScheduling moves it between those states.\n"
    note = create_note(f"citation nav {uuid.uuid4()}", summary_markdown=markdown)
    try:
        index_lecture(note["id"])
        row = search_chunks("process states scheduling", lecture_id=note["id"])[0]
        citation = resolve_citation(f"C{row['id']}")
        assert citation["document_id"] == note["id"] and citation["source_type"] == "document"
        # heading + paragraph + multi-line range, all addressable by stable IDs
        assert citation["block_ids"] == ["process-states", "process-states--1", "process-states--2"]
        assert citation["heading"] == "Process States" and citation["section_id"] == "process-states"
        assert (citation["line_start"], citation["line_end"]) == (1, 3)
        # Existing metadata is preserved.
        assert {"chunk_id", "label", "snippet", "content", "char_start", "char_end", "timestamp_start"} <= citation.keys()
    finally:
        remove_lecture_from_index(note["id"]); delete_note(note["id"])

def test_invalid_and_deleted_citations_resolve_to_none():
    assert resolve_citation("X1") is None and resolve_citation("C") is None and resolve_citation("Cabc") is None
    init_database(); note = create_note(f"citation gone {uuid.uuid4()}", summary_markdown="# Gone\nSoon deleted.\n")
    index_lecture(note["id"]); chunk_id = search_chunks("deleted", lecture_id=note["id"])[0]["id"]
    assert resolve_citation(f"T{chunk_id}") is None  # wrong source kind
    remove_lecture_from_index(note["id"]); delete_note(note["id"])
    assert resolve_citation(f"C{chunk_id}") is None
