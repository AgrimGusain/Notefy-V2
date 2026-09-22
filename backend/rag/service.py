from __future__ import annotations
from .retriever import search_chunks
from .prompts import build, citation_id, parse_response
from .citations import resolve_chunks
from ai.manager import generate_grounded

async def answer_question(*,question,provider,api_key,model,base_url,fallback_to_local,top_k,folder_id,lecture_id,source_type):
    results=search_chunks(question,top_k=top_k,folder_id=folder_id,lecture_id=lecture_id,source_type=source_type)
    if not results:return {"success":True,"answer":"I couldn't find this information in your notes.","citations":[],"retrieval":{"mode":"hybrid","top_k":top_k,"index_status":"ready"}}
    system,prompt=build(question,results)
    generated=await generate_grounded(provider=provider,api_key=api_key,model=model,base_url=base_url,system_prompt=system,user_prompt=prompt,fallback_to_local=fallback_to_local)
    answer,chosen=parse_response(generated["answer"],{citation_id(row) for row in results});by_id={citation_id(row):row for row in results}
    return {"success":True,"answer":answer,"citations":resolve_chunks([by_id[item] for item in chosen]),"retrieval":{"mode":"hybrid","top_k":top_k,"source":generated["source"]}}
