from __future__ import annotations
from sqlalchemy import text
from database import SessionLocal
from .embeddings import get_embedding_provider
import json, math, os, re

_STOP_WORDS={"a","an","and","are","as","at","be","by","for","from","how","i","in","is","it","of","on","or","the","to","what","when","where","which","who","why","with"}
def cosine_similarity(left, right):
    if not left or len(left)!=len(right): return 0.0
    denominator=math.sqrt(sum(x*x for x in left))*math.sqrt(sum(x*x for x in right))
    return sum(a*b for a,b in zip(left,right))/denominator if denominator else 0.0
def _filters(folder_id,lecture_id,source_type):
    where, params=[],{}
    if folder_id is not None: where.append("c.folder_id = :folder_id");params["folder_id"]=folder_id
    if lecture_id is not None: where.append("c.lecture_id = :lecture_id");params["lecture_id"]=lecture_id
    if source_type is not None: where.append("c.source_kind = :source_type");params["source_type"]=source_type
    return where,params
def fts_search(query,*,top_k=20,folder_id=None,lecture_id=None,source_type=None):
    terms=[part.lower() for part in re.findall(r"[A-Za-z0-9]+",query) if part.lower() not in _STOP_WORDS]
    if not terms:return []
    where,params=_filters(folder_id,lecture_id,source_type);params.update({"query":" OR ".join(f'{term}*' for term in terms[:12]),"limit":top_k})
    sql="""SELECT c.id,c.lecture_id,c.segment_id,c.sequence_number,c.start_seconds,c.end_seconds,c.line_start,c.line_end,c.char_start,c.char_end,c.segment_ids,c.content,c.source_kind,c.folder_id,c.embedding,l.title,l.source_type,l.source_relative_path,bm25(rag_chunks_fts) score FROM rag_chunks_fts f JOIN rag_chunks c ON c.id=f.chunk_id JOIN lectures l ON l.id=c.lecture_id WHERE """+" AND ".join(["rag_chunks_fts MATCH :query"]+where)+" ORDER BY score LIMIT :limit"
    session=SessionLocal()
    try:return [dict(row)|{"fts_score":-float(row["score"])} for row in session.execute(text(sql),params).mappings().all()]
    finally:session.close()
def semantic_search(query,*,top_k=20,folder_id=None,lecture_id=None,source_type=None):
    from .vector_store import SQLiteVectorStore
    return SQLiteVectorStore().search(get_embedding_provider().embed_query(query),top_k,folder_id=folder_id,lecture_id=lecture_id,source_type=source_type)
def hybrid_rank(results,query_embedding=None,keyword_weight=.45,semantic_weight=.55):
    if not results:return []
    maximum=max((item.get("fts_score",item.get("score",0.0)) for item in results),default=1) or 1
    for item in results:
        keyword=item.get("fts_score",item.get("score",0.0))/maximum; semantic=item.get("semantic_score",0.0)
        if not semantic and query_embedding and item.get("embedding"):semantic=cosine_similarity(query_embedding,json.loads(item["embedding"]))
        item["combined_score"]=keyword_weight*keyword+semantic_weight*semantic
    return sorted(results,key=lambda item:item["combined_score"],reverse=True)
def search_chunks(query,*,top_k=6,candidate_limit=50,folder_id=None,lecture_id=None,source_type=None):
    fts=fts_search(query,top_k=int(os.getenv("RAG_FTS_TOP_K",candidate_limit)),folder_id=folder_id,lecture_id=lecture_id,source_type=source_type)
    semantic=semantic_search(query,top_k=int(os.getenv("RAG_VECTOR_TOP_K",candidate_limit)),folder_id=folder_id,lecture_id=lecture_id,source_type=source_type)
    combined={}
    for item in fts+semantic:
        old=combined.setdefault(item["id"],item.copy());old.update({key:value for key,value in item.items() if value is not None})
    alpha=float(os.getenv("RAG_HYBRID_ALPHA",".4"));ranked=hybrid_rank(list(combined.values()),get_embedding_provider().embed_query(query),alpha,1-alpha)
    return [item for item in ranked if item["combined_score"]>=float(os.getenv("RAG_MIN_SCORE",".08"))][:top_k]
def index_status():
    session=SessionLocal()
    try:
        row=session.execute(text("SELECT count(*) chunks,count(DISTINCT lecture_id) documents,max(indexed_at) last_indexed FROM rag_chunks")).mappings().one()
        return {"index_status":"ready","indexed_chunks":row["chunks"],"source_documents":row["documents"],"embedding_model":get_embedding_provider().model,"last_indexed_at":row["last_indexed"],"last_error":None}
    finally:session.close()
