"""Adapter for the application's existing local summarizer."""
import asyncio
from summarizer import summarize_transcript


async def generate(*, transcript: str, title: str | None, **_: str) -> str:
    result = await asyncio.to_thread(summarize_transcript, transcript, title, "local")
    if not result or not result.strip():
        raise RuntimeError("Local AI returned an empty response")
    return result.strip()
