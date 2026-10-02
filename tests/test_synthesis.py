"""AI synthesis of clip collections: grounding, ordering and citations.

The external model is replaced by a fake that records the prompt it receives,
so these tests check exactly what is sent and how the answer is post-processed.
"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
import pytest
from fastapi.testclient import TestClient
from database import (init_database, create_lecture, save_transcript_segment, finalize_lecture, get_lecture_by_id, delete_note,
                      create_clip, delete_clip, create_collection, get_collection, delete_collection, reorder_collection)
from ai import external, synthesis
from ai.manager import AIGenerationError
from rag.retriever import search_chunks
from rag.indexer import remove_lecture_from_index
import server

init_database()

TEXT = {
    "Source A": ["Gradient descent updates the weights by stepping against the gradient.", "The gradient points uphill on the loss surface."],
    "Source B": ["The learning rate controls the step size of each update.", "A rate that is too large makes training diverge."],
    "Source C": ["Momentum averages past gradients to speed up training.", "It damps oscillations across narrow valleys."],
}
# The feature request's example ranges: 12:31–14:02, 42:12–43:10, 01:02:31–01:04:00.
SPANS = {"Source A": [(751.0, 790.0), (789.5, 842.0)], "Source B": [(2532.0, 2561.5), (2561.0, 2590.0)], "Source C": [(3751.0, 3800.0), (3799.5, 3840.0)]}

FAKE_ANSWER = """```markdown
# Gradient Descent

## The update rule
Gradient descent updates the weights by stepping against the gradient [[K1]].

- The learning rate controls the step size of each update. [[K2]]
- Momentum averages past gradients to speed up training. [[K3]][[K1]]
- Adam was introduced by Kingma and Ba in 2014. [[K9]]
- Backpropagation applies the chain rule through convolutional layers. [[K2]]
Transformers replaced recurrent networks entirely.
```"""


@pytest.fixture
def world():
    made = {"lectures": [], "clips": [], "collections": []}
    sources = {}
    for title, spans in SPANS.items():
        lecture_id = create_lecture(f"synth-{uuid.uuid4()}", title)
        for index, ((start, end), text) in enumerate(zip(spans, TEXT[title]), 1):
            save_transcript_segment(lecture_id, index, start, end, text)
        finalize_lecture(lecture_id); made["lectures"].append(lecture_id)
        sources[title] = get_lecture_by_id(lecture_id)
    collection = create_collection("Machine Learning Revision"); made["collections"].append(collection["id"])
    clips = {}
    for title, lecture in sources.items():
        clips[title] = create_clip(lecture["id"], [segment["id"] for segment in lecture["segments"]], collection_id=collection["id"])
        made["clips"].append(clips[title]["id"])
    outsider_lecture = create_lecture(f"synth-{uuid.uuid4()}", "Unrelated"); made["lectures"].append(outsider_lecture)
    save_transcript_segment(outsider_lecture, 1, 0, 4, "SECRET-UNSELECTED text about databases."); finalize_lecture(outsider_lecture)
    outsider = create_clip(outsider_lecture, [get_lecture_by_id(outsider_lecture)["segments"][0]["id"]]); made["clips"].append(outsider["id"])
    yield {"collection": collection, "clips": clips, "sources": sources, "outsider": outsider}
    for collection_id in made["collections"]: delete_collection(collection_id)
    for clip_id in made["clips"]: delete_clip(clip_id)
    for lecture_id in made["lectures"]: delete_note(lecture_id)


@pytest.fixture
def fake_model(monkeypatch):
    calls = []
    async def generate(*, api_key, model, base_url, system_prompt, user_prompt):
        calls.append({"system": system_prompt, "user": user_prompt, "model": model}); return FAKE_ANSWER
    monkeypatch.setattr(external, "generate", generate)
    return calls


def run(collection_id, **kwargs):
    options = dict(clip_ids=None, provider="external", api_key="key", model="test-model", base_url=None, instructions=None, fallback_to_local=False)
    options.update(kwargs)
    return asyncio.run(synthesis.synthesize(collection_id=collection_id, **options))


def test_sends_only_selected_clips_in_collection_order(world, fake_model):
    run(world["collection"]["id"], instructions="Keep it short")
    sent = fake_model[0]["user"]
    assert fake_model[0]["system"] == synthesis.SYSTEM_PROMPT and "Use only information stated in the clips" in fake_model[0]["system"]
    positions = [sent.index(f"[CLIP K{n}]\nRecording: Source {letter}") for n, letter in ((1, "A"), (2, "B"), (3, "C"))]
    assert positions == sorted(positions)
    assert "Time: 12:31–14:02" in sent and "Time: 42:12–43:10" in sent and "Time: 01:02:31–01:04:00" in sent
    assert all(text in sent for texts in TEXT.values() for text in texts)
    assert "SECRET-UNSELECTED" not in sent and "Keep it short" in sent


def test_citations_are_rebuilt_from_clip_metadata(world, fake_model):
    result = run(world["collection"]["id"])
    md, a, b, c = result["summary_markdown"], *(world["sources"][title]["id"] for title in ("Source A", "Source B", "Source C"))
    assert result["title"] == "Gradient Descent" and md.startswith("# Gradient Descent\n\n> Combined from 3 clips")
    assert f"stepping against the gradient [Source A · 12:31](#note/{a}/t/751-842)." in md
    assert f"[Source B · 42:12](#note/{b}/t/2532-2590)" in md
    assert f"[Source C · 01:02:31](#note/{c}/t/3751-3840) [Source A · 12:31](#note/{a}/t/751-842)" in md
    assert "[[K" not in md and "K9" not in md and "```" not in md
    sources = md.split("## Sources\n")[1].strip().splitlines()
    assert [line.split(" ")[1] for line in sources] == ["[Source", "[Source", "[Source"] and "Source A" in sources[0] and "Source C" in sources[2]
    assert [clip["label"] for clip in result["clips"]] == ["Source A · 12:31", "Source B · 42:12", "Source C · 01:02:31"]


def test_grounding_report_flags_claims_not_in_the_clips(world, fake_model):
    report = run(world["collection"]["id"])["grounding"]
    assert report["dropped_citations"] == 1 and not report["ok"]
    uncited = [item["text"] for item in report["uncited"]]
    assert "Adam was introduced by Kingma and Ba in 2014." in uncited  # its only citation (K9) was not a supplied clip
    assert "Transformers replaced recurrent networks entirely." in uncited
    weak = report["weakly_supported"]
    assert len(weak) == 1 and "Backpropagation" in weak[0]["text"] and "convolutional" in weak[0]["unsupported_terms"]
    assert not any("learning rate" in text for text in uncited + [item["text"] for item in weak])  # supported, cited lines are not flagged


def test_subset_keeps_collection_order_and_reorder_is_respected(world, fake_model):
    clips, collection = world["clips"], world["collection"]
    run(collection["id"], clip_ids=[clips["Source C"]["id"], clips["Source A"]["id"]])
    sent = fake_model[-1]["user"]
    assert sent.index("Recording: Source A") < sent.index("Recording: Source C") and "Source B" not in sent
    items = get_collection(collection["id"])["items"]
    reorder_collection(collection["id"], [items[2]["item_id"], items[0]["item_id"], items[1]["item_id"]])
    run(collection["id"])
    sent = fake_model[-1]["user"]
    assert sent.index("[CLIP K1]\nRecording: Source C") < sent.index("[CLIP K2]\nRecording: Source A") < sent.index("[CLIP K3]\nRecording: Source B")
    with pytest.raises(ValueError): run(collection["id"], clip_ids=[world["outsider"]["id"]])
    with pytest.raises(ValueError): run(collection["id"], clip_ids=[])
    with pytest.raises(LookupError): run(99_999_999)


def test_deleted_recording_keeps_a_plain_citation(world, fake_model):
    delete_note(world["sources"]["Source C"]["id"])
    md = run(world["collection"]["id"])["summary_markdown"]
    assert "[Source C · 01:02:31 · recording deleted]" in md and f"#note/{world['sources']['Source C']['id']}/" not in md


def test_local_mode_is_extractive_and_fully_cited(world, monkeypatch):
    async def must_not_call(**_): raise AssertionError("local mode must not call the external model")
    monkeypatch.setattr(external, "generate", must_not_call)
    result = run(world["collection"]["id"], provider="local")
    assert result["source"] == "local" and result["grounding"]["ok"]
    bullets = [line for line in result["summary_markdown"].splitlines() if line.startswith("- ")]
    assert len(bullets) == 6 and all("](#note/" in line for line in bullets)
    assert all(any(sentence.rstrip(".") in line for texts in TEXT.values() for sentence in texts) for line in bullets)


def test_external_failure_and_fallback(world, monkeypatch):
    async def fail(**_): raise external.ExternalAIError("External provider rate limit reached.")
    monkeypatch.setattr(external, "generate", fail)
    with pytest.raises(AIGenerationError, match="rate limit"): run(world["collection"]["id"])
    fallback = run(world["collection"]["id"], fallback_to_local=True)
    assert fallback["source"] == "local_fallback" and "rate limit" in fallback["fallback_reason"] and fallback["grounding"]["ok"]


def test_api_preview_then_normal_note(world, fake_model):
    client = TestClient(server.app)
    collection_id = world["collection"]["id"]
    preview = client.post(f"/api/collections/{collection_id}/synthesize", json={"provider": "external", "api_key": "key", "model": "test-model"})
    assert preview.status_code == 200 and preview.json()["success"] and preview.json()["title"] == "Gradient Descent"
    assert client.post("/api/collections/99999999/synthesize", json={"provider": "local"}).status_code == 404
    assert client.post(f"/api/collections/{collection_id}/synthesize", json={"provider": "nope"}).status_code == 422
    assert client.post(f"/api/collections/{collection_id}/synthesize", json={"provider": "local", "clip_ids": "1"}).status_code == 422
    empty = create_collection("Empty")
    try: assert client.post(f"/api/collections/{empty['id']}/synthesize", json={"provider": "local"}).status_code == 400
    finally: delete_collection(empty["id"])
    note = client.post("/api/notes", json={"title": preview.json()["title"], "summary_markdown": preview.json()["summary_markdown"]}).json()
    try:
        saved = get_lecture_by_id(note["id"])
        assert saved["summary_markdown"] == preview.json()["summary_markdown"] and saved["source_type"] == "native"
        assert search_chunks("learning rate step size", lecture_id=note["id"])  # indexed like any other note
    finally:
        remove_lecture_from_index(note["id"]); delete_note(note["id"])
