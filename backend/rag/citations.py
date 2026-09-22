"""Database-backed citation resolution. Model output never supplies locations."""
from __future__ import annotations
from database import SessionLocal, RagChunk, Lecture
from .prompts import citation_id, source_label
def resolve_chunks(rows):
    return [{"citation_id":citation_id(row),"chunk_id":row["id"],"source_type":"transcript" if row["source_kind"]=="transcript" else "document","source_name":row["title"],"title":row["title"],"document_id":row["lecture_id"] if row["source_kind"]=="markdown" else None,"lecture_id":row["lecture_id"] if row["source_kind"]=="transcript" else None,"line_start":row.get("line_start"),"line_end":row.get("line_end"),"char_start":row.get("char_start"),"char_end":row.get("char_end"),"timestamp_start":row.get("start_seconds"),"timestamp_end":row.get("end_seconds"),"segment_ids":row.get("segment_ids"),"content":row["content"],"snippet":row["content"][:280],"label":source_label(row)} for row in rows]
def resolve_citation(source_id):
    if not isinstance(source_id,str) or len(source_id)<2 or source_id[0] not in "CT" or not source_id[1:].isdigit():return None
    session=SessionLocal()
    try:
        found=session.query(RagChunk,Lecture).join(Lecture,Lecture.id==RagChunk.lecture_id).filter(RagChunk.id==int(source_id[1:])).first()
        if not found:return None
        chunk,lecture=found
        if (source_id[0]=="C") != (chunk.source_kind=="markdown"):return None
        return resolve_chunks([{"id":chunk.id,"lecture_id":chunk.lecture_id,"content":chunk.content,"source_kind":chunk.source_kind,"line_start":chunk.line_start,"line_end":chunk.line_end,"char_start":chunk.char_start,"char_end":chunk.char_end,"start_seconds":chunk.start_seconds,"end_seconds":chunk.end_seconds,"segment_ids":chunk.segment_ids,"title":lecture.title,"source_relative_path":lecture.source_relative_path}])[0]
    finally:session.close()
