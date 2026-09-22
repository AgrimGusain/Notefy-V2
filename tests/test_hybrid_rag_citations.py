import os, sys, uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from database import init_database, create_note, create_lecture, save_transcript_segment, finalize_lecture, delete_note
from rag.chunking import markdown_chunks, transcript_chunks
from rag.indexer import index_lecture, remove_lecture_from_index
from rag.retriever import fts_search, semantic_search, search_chunks
from rag.citations import resolve_citation

def test_exact_document_lines_and_hybrid_citation():
    chunks=markdown_chunks("one\ntwo\nthree\nfour\nfive\n")
    assert chunks[0].line_start == 1 and chunks[0].line_end == 5
    init_database(); note=create_note("citation " + str(uuid.uuid4()), summary_markdown="# OS\nStarvation means a process waits indefinitely while others receive resources.\n")
    try:
        index_lecture(note["id"])
        lexical=fts_search("starvation", lecture_id=note["id"]); semantic=semantic_search("process waits forever", lecture_id=note["id"])
        assert lexical and semantic
        row=search_chunks("process waits forever", lecture_id=note["id"])[0]
        citation=resolve_citation("C" + str(row["id"]))
        assert citation["line_start"] == 1 and citation["line_end"] == 2 and citation["document_id"] == note["id"]
    finally: remove_lecture_from_index(note["id"]); delete_note(note["id"])

def test_transcript_range_is_from_segments():
    init_database(); lecture=create_lecture("citation-" + str(uuid.uuid4()), "Lecture")
    save_transcript_segment(lecture, 1, 0, 5, "Hello")
    save_transcript_segment(lecture, 2, 5, 10, "Process scheduling")
    save_transcript_segment(lecture, 3, 10, 15, "CPU scheduling")
    finalize_lecture(lecture)
    try:
        index_lecture(lecture); row=search_chunks("CPU scheduling", lecture_id=lecture)[0]
        citation=resolve_citation("T" + str(row["id"]))
        assert citation["timestamp_start"] == 0 and citation["timestamp_end"] == 15
    finally: remove_lecture_from_index(lecture)
