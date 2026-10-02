"""Stitches a recording session's chunked WAV files into one continuous,
playable file so the frontend can serve real audio for a lecture.

Each chunk overlaps the previous one by OVERLAP_SEC (see recorder.py) to
avoid cutting words mid-transcription; that overlap must be trimmed here or
playback would stutter/repeat at every chunk boundary.
"""
import glob
import os
import re

import numpy as np
import soundfile as sf

RECORDINGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "recordings"))
OVERLAP_SEC = 0.5


def _chunk_paths(session_id: str) -> list:
    pattern = os.path.join(RECORDINGS_DIR, f"session_{session_id}_chunk_*.wav")

    def sequence(path):
        match = re.search(r"_chunk_(\d+)\.wav$", path)
        return int(match.group(1)) if match else 0

    return sorted(glob.glob(pattern), key=sequence)


def build_lecture_audio(session_id: str):
    """Return the path to a stitched WAV for this session, building and
    caching it on first request. Returns None if no audio chunks exist."""
    cached_path = os.path.join(RECORDINGS_DIR, f"session_{session_id}_full.wav")
    if os.path.exists(cached_path):
        return cached_path

    chunk_paths = _chunk_paths(session_id)
    if not chunk_paths:
        return None

    frames, rate = [], None
    for index, path in enumerate(chunk_paths):
        data, sample_rate = sf.read(path, dtype="float32")
        rate = rate or sample_rate
        if index > 0:
            trim_frames = int(OVERLAP_SEC * sample_rate)
            data = data[trim_frames:]
        frames.append(data)

    stitched = np.concatenate(frames, axis=0) if frames else np.empty((0,), dtype=np.float32)
    sf.write(cached_path, stitched, rate)
    return cached_path


def remove_lecture_audio_cache(session_id: str) -> None:
    """Delete the stitched playback file built by build_lecture_audio (a derived cache; the recorded chunks are untouched)."""
    try:
        os.remove(os.path.join(RECORDINGS_DIR, f"session_{session_id}_full.wav"))
    except FileNotFoundError:
        pass
