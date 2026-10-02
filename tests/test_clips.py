"""Transcript clips and clip collections.

Uses the local SQLite database like the other tests and removes every fixture it creates.
"""
import os, sys, uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
import pytest
from fastapi.testclient import TestClient
from database import (init_database, create_lecture, save_transcript_segment, finalize_lecture, get_lecture_by_id, update_lecture,
                      delete_note, create_clip, get_clip, list_clips, delete_clip, create_collection, get_collection,
                      add_clip_to_collection, remove_collection_item, reorder_collection, collection_source, delete_collection, format_clock)
import server

init_database()


@pytest.fixture
def made():
    """Track fixtures for cleanup: recordings, clips, collections."""
    created = {"lectures": [], "clips": [], "collections": []}
    yield created
    for collection_id in created["collections"]: delete_collection(collection_id)
    for clip_id in created["clips"]: delete_clip(clip_id)
    for lecture_id in created["lectures"]: delete_note(lecture_id)


def recording(made, title, spans, empty=()):
    """Create a finished recording whose segments have the given (start, end) times; returns the lecture dict."""
    lecture_id = create_lecture(f"clip-test-{uuid.uuid4()}", title)
    for index, (start, end) in enumerate(spans, 1):
        save_transcript_segment(lecture_id, index, start, end, "" if index in empty else f"{title} sentence {index}.")
    finalize_lecture(lecture_id)
    made["lectures"].append(lecture_id)
    return get_lecture_by_id(lecture_id)


def chunked(count, start=0.0):
    """Recorder-style windows: 4 s long, starting every 3.5 s (0.5 s overlap)."""
    return [(start + i * 3.5, start + i * 3.5 + 4.0) for i in range(count)]


def clip(made, lecture, segments, **kwargs):
    result = create_clip(lecture["id"], [segment["id"] for segment in segments], **kwargs)
    made["clips"].append(result["id"])
    return result


def test_clip_from_one_recording_snapshots_range_and_never_touches_transcript(made):
    lecture = recording(made, "Source A", chunked(8))
    before = get_lecture_by_id(lecture["id"])
    saved = clip(made, lecture, lecture["segments"][2:5], title="  Gradient descent  ")
    picked = lecture["segments"][2:5]
    assert saved["lecture_id"] == lecture["id"] and saved["source_title"] == "Source A" and not saved["source_deleted"]
    assert saved["segment_ids"] == [segment["id"] for segment in picked]
    assert saved["start_seconds"] == picked[0]["start_seconds"] == 7.0 and saved["end_seconds"] == picked[-1]["end_seconds"] == 18.0
    assert saved["text"] == "\n\n".join(segment["text"] for segment in picked)
    assert saved["title"] == "Gradient descent" and saved["created_at"]
    after = get_lecture_by_id(lecture["id"])
    assert after["segments"] == before["segments"] and after["full_transcript"] == before["full_transcript"]


def test_collection_from_multiple_recordings_keeps_order_and_exact_timestamps(made):
    # The example from the feature request: three sources, three ranges.
    a = recording(made, "Source A", [(747.0, 751.5), (751.0, 790.0), (789.5, 842.0), (841.5, 845.0)])
    b = recording(made, "Source B", [(2532.0, 2561.5), (2561.0, 2590.0)])
    c = recording(made, "Source C", [(3700.0, 3751.5), (3751.0, 3800.0), (3799.5, 3840.0)])
    collection = create_collection("Machine Learning Revision"); made["collections"].append(collection["id"])
    clips = [clip(made, a, a["segments"][1:3], collection_id=collection["id"]),
             clip(made, b, b["segments"], collection_id=collection["id"]),
             clip(made, c, c["segments"][1:3], collection_id=collection["id"])]
    ranges = [(format_clock(item["start_seconds"]), format_clock(item["end_seconds"])) for item in clips]
    assert ranges == [("00:12:31", "00:14:02"), ("00:42:12", "00:43:10"), ("01:02:31", "01:04:00")]

    full = get_collection(collection["id"])
    assert [item["clip"]["source_title"] for item in full["items"]] == ["Source A", "Source B", "Source C"]
    assert [item["position"] for item in full["items"]] == [1, 2, 3] and full["clip_count"] == 3
    assert full["total_seconds"] == pytest.approx(91 + 58 + 89)
    source = collection_source(collection["id"])
    assert source["transcript"].startswith("[1. Source A · 00:12:31–00:14:02]\nSource A sentence 2.")
    assert "[3. Source C · 01:02:31–01:04:00]" in source["transcript"]

    items = [item["item_id"] for item in full["items"]]
    reordered = reorder_collection(collection["id"], [items[2], items[0], items[1]])
    assert [item["clip"]["source_title"] for item in reordered["items"]] == ["Source C", "Source A", "Source B"]
    with pytest.raises(ValueError): reorder_collection(collection["id"], items[:2])
    with pytest.raises(ValueError): reorder_collection(collection["id"], [items[0], items[0], items[1]])

    # Removing a clip from the collection keeps the clip and its recording.
    after_remove = remove_collection_item(collection["id"], items[0])
    assert [item["clip"]["source_title"] for item in after_remove["items"]] == ["Source C", "Source B"]
    assert get_clip(clips[0]["id"]) and get_lecture_by_id(a["id"])
    assert add_clip_to_collection(collection["id"], clips[1]["id"])["clip_count"] == 2  # already present: no duplicate


def test_adjacent_segments_and_invalid_selections(made):
    lecture = recording(made, "Adjacent", chunked(6), empty={4})
    segments = lecture["segments"]
    adjacent = clip(made, lecture, segments[0:2])
    assert (adjacent["start_seconds"], adjacent["end_seconds"]) == (0.0, 7.5)  # first start .. last end, overlap included once
    # An empty (silent) segment between two selected ones does not break contiguity.
    across_silence = clip(made, lecture, [segments[2], segments[4]])
    assert across_silence["segment_ids"] == [segments[2]["id"], segments[4]["id"]]
    assert (across_silence["start_seconds"], across_silence["end_seconds"]) == (7.0, 18.0)
    other = recording(made, "Other", chunked(2))
    for bad in ([segments[0]["id"], segments[2]["id"]],          # gap
                [segments[0]["id"], other["segments"][0]["id"]],  # another recording
                [segments[1]["id"], segments[1]["id"]],           # duplicate
                [segments[3]["id"]]):                             # empty segment
        with pytest.raises(ValueError): create_clip(lecture["id"], bad)
    assert create_clip(99_999_999, [segments[0]["id"]]) is None


def test_long_selection(made):
    lecture = recording(made, "Long lecture", chunked(400, start=10.0))
    saved = clip(made, lecture, lecture["segments"])
    assert len(saved["segment_ids"]) == 400 and saved["start_seconds"] == 10.0
    assert saved["end_seconds"] == lecture["segments"][-1]["end_seconds"] == 10.0 + 399 * 3.5 + 4.0
    assert format_clock(saved["end_seconds"]) == "00:23:30" and saved["text"].count("\n\n") == 399


def test_deleting_a_clip_removes_it_from_collections_only(made):
    lecture = recording(made, "Keep me", chunked(3))
    collection = create_collection("Revision"); made["collections"].append(collection["id"])
    saved = clip(made, lecture, lecture["segments"][:1], collection_id=collection["id"])
    assert delete_clip(saved["id"]) and get_clip(saved["id"]) is None
    assert get_collection(collection["id"])["clip_count"] == 0
    assert len(get_lecture_by_id(lecture["id"])["segments"]) == 3


def test_deleting_the_recording_keeps_clip_snapshot(made):
    lecture = recording(made, "Deleted source", chunked(3))
    collection = create_collection("Revision"); made["collections"].append(collection["id"])
    saved = clip(made, lecture, lecture["segments"][1:3], collection_id=collection["id"])
    response = TestClient(server.app).delete(f"/api/notes/{lecture['id']}")  # the app's real delete path
    assert response.status_code == 200 and get_lecture_by_id(lecture["id"]) is None
    survivor = get_clip(saved["id"])
    assert survivor["lecture_id"] is None and survivor["source_deleted"] and survivor["source_title"] == "Deleted source"
    assert (survivor["text"], survivor["start_seconds"], survivor["end_seconds"], survivor["segment_ids"]) == (saved["text"], saved["start_seconds"], saved["end_seconds"], saved["segment_ids"])
    assert get_collection(collection["id"])["items"][0]["clip"]["id"] == saved["id"]
    assert list_clips(lecture["id"]) == []


def test_editing_the_transcript_later_does_not_change_saved_clip(made):
    lecture = recording(made, "Edited", chunked(2))
    saved = clip(made, lecture, lecture["segments"])
    update_lecture(lecture["id"], {"segments": [{"sequence_number": 1, "text": "Rewritten."}]})
    assert get_clip(saved["id"])["text"] == saved["text"]


def test_clip_api(made):
    client = TestClient(server.app)
    lecture = recording(made, "API source", chunked(4))
    ids = [segment["id"] for segment in lecture["segments"]]
    created = client.post("/api/clips", json={"lecture_id": lecture["id"], "segment_ids": ids[1:3], "title": "Key idea"})
    assert created.status_code == 200; made["clips"].append(created.json()["id"])
    assert client.post("/api/clips", json={"lecture_id": lecture["id"], "segment_ids": [ids[0], ids[2]]}).status_code == 400
    assert client.post("/api/clips", json={"lecture_id": lecture["id"], "segment_ids": []}).status_code == 422
    assert client.post("/api/clips", json={"lecture_id": 99_999_999, "segment_ids": ids[:1]}).status_code == 404
    assert client.get(f"/api/clips?lecture_id={lecture['id']}").json()["clips"][0]["title"] == "Key idea"
    assert client.patch(f"/api/clips/{created.json()['id']}", json={"title": "Renamed"}).json()["title"] == "Renamed"

    collection = client.post("/api/collections", json={"title": "API collection"}).json(); made["collections"].append(collection["id"])
    assert client.post("/api/collections", json={"title": "  "}).status_code == 422
    added = client.post(f"/api/collections/{collection['id']}/items", json={"clip_id": created.json()["id"]}).json()
    assert added["clip_count"] == 1
    assert client.post(f"/api/collections/{collection['id']}/items", json={"clip_id": 99_999_999}).status_code == 404
    assert client.put(f"/api/collections/{collection['id']}/order", json={"item_ids": [12345]}).status_code == 400
    assert client.get(f"/api/collections/{collection['id']}/source").json()["transcript"].startswith("[1. API source · 00:00:03–00:00:11 · Renamed]")
    assert client.delete(f"/api/collections/{collection['id']}/items/{added['items'][0]['item_id']}").json()["clip_count"] == 0
    assert client.delete(f"/api/collections/{collection['id']}/items/{added['items'][0]['item_id']}").status_code == 404
    assert client.delete(f"/api/collections/{collection['id']}").status_code == 200 and client.get(f"/api/clips/{created.json()['id']}").status_code == 200
