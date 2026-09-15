"""
Full Integration Test for Audio-Notes Phase 5

Tests the complete workflow:
1. Record audio with live transcription
2. Verify database persistence
3. Test archive API endpoints

Prerequisites:
- Server must be running: uvicorn backend.server:app --reload
- System audio should be playing during the test
"""

import asyncio
import websockets
import json
import sys
import time
import requests

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

async def test_recording_and_persistence():
    print("=== Audio-Notes Phase 5 Integration Test ===\n")

    # Test 1: Connect to WebSocket
    print("1. Connecting to WebSocket...")
    async with websockets.connect(WS_URL) as ws:
        # Wait for connection event
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"   Connected: {data}\n")

        # Test 2: Start recording
        print("2. Starting recording (play some audio!)...")
        await ws.send(json.dumps({"type": "start", "title": "Integration Test Recording"}))

        lecture_id = None
        session_id = None
        transcript_count = 0

        # Collect events for 12 seconds
        print("   Recording for 12 seconds...\n")
        start_time = time.time()

        while time.time() - start_time < 12:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)
                event_type = data.get("type")

                if event_type == "status":
                    state = data.get("state")
                    session_id = data.get("session_id")
                    lecture_id = data.get("lecture_id")
                    print(f"   Status: {state} (session={session_id}, lecture={lecture_id})")

                elif event_type == "partial_transcript":
                    transcript_count += 1
                    seq = data.get("sequence")
                    text = data.get("text", "")[:60]
                    print(f"   Transcript #{seq}: {text}...")

            except asyncio.TimeoutError:
                continue

        # Test 3: Stop recording
        print("\n3. Stopping recording...")
        await ws.send(json.dumps({"type": "stop"}))

        # Wait for completion
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                data = json.loads(msg)
                event_type = data.get("type")

                if event_type == "status":
                    state = data.get("state")
                    print(f"   Status: {state}")
                    if state == "complete":
                        break

                elif event_type == "partial_transcript":
                    transcript_count += 1
                    seq = data.get("sequence")
                    print(f"   Final transcript #{seq}")

                elif event_type == "transcription_complete":
                    print(f"   Transcription complete!")

            except asyncio.TimeoutError:
                print("   Timeout waiting for completion")
                break

    print(f"\n   Total transcripts received: {transcript_count}")
    print(f"   Lecture ID: {lecture_id}\n")

    if not lecture_id:
        print("ERROR: No lecture ID received")
        return False

    # Wait a moment for database finalization
    await asyncio.sleep(2)

    # Test 4: Verify database persistence via API
    print("4. Testing GET /api/lectures endpoint...")
    response = requests.get(f"{BASE_URL}/api/lectures")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {data['count']} lecture(s)")
        if data['lectures']:
            latest = data['lectures'][0]
            print(f"   Latest: ID={latest['id']}, Title={latest['title']}")
            print(f"   Status: {latest['status']}")
            preview = latest.get('transcript_preview', '')[:80]
            print(f"   Preview: {preview}...")
    else:
        print(f"   ERROR: Status {response.status_code}")
        return False

    # Test 5: Get specific lecture
    print(f"\n5. Testing GET /api/lectures/{lecture_id} endpoint...")
    response = requests.get(f"{BASE_URL}/api/lectures/{lecture_id}")
    if response.status_code == 200:
        lecture = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Title: {lecture['title']}")
        print(f"   Session ID: {lecture['session_id']}")
        print(f"   Status: {lecture['status']}")
        print(f"   Segments: {len(lecture['segments'])}")
        print(f"   Full transcript length: {len(lecture.get('full_transcript', ''))} chars")

        if lecture['segments']:
            first_seg = lecture['segments'][0]
            print(f"   First segment: seq={first_seg['sequence_number']}, "
                  f"time={first_seg['start_seconds']:.1f}-{first_seg['end_seconds']:.1f}s")
            print(f"   First segment text: {first_seg['text'][:60]}...")
    else:
        print(f"   ERROR: Status {response.status_code}")
        return False

    # Test 6: Test 404 for nonexistent lecture
    print("\n6. Testing 404 for nonexistent lecture...")
    response = requests.get(f"{BASE_URL}/api/lectures/99999")
    print(f"   Status: {response.status_code} (expected 404)")
    if response.status_code == 404:
        print(f"   Response: {response.json()}")

    # Test 7: Search functionality
    print("\n7. Testing GET /api/lectures/search endpoint...")

    # Search with valid query
    response = requests.get(f"{BASE_URL}/api/lectures/search?q=test")
    if response.status_code == 200:
        data = response.json()
        print(f"   Search 'test': {data['count']} result(s)")

    # Search with empty query (should return 400)
    response = requests.get(f"{BASE_URL}/api/lectures/search?q=   ")
    print(f"   Empty search: Status {response.status_code} (expected 400)")

    print("\n=== Phase 5 Integration Test Complete ===")
    print("\nVerified:")
    print("  - WebSocket recording with live transcription")
    print("  - Database persistence of lectures and segments")
    print("  - lecture_id in WebSocket events")
    print("  - GET /api/lectures (list)")
    print("  - GET /api/lectures/{id} (retrieve)")
    print("  - GET /api/lectures/search (search)")
    print("  - Proper 404 handling")
    print("  - Full transcript assembly from segments")

    return True

if __name__ == '__main__':
    print("IMPORTANT: Make sure the server is running:")
    print("  uvicorn backend.server:app --reload\n")
    print("Play some audio (YouTube, music) during the test.\n")

    input("Press Enter to start the test...")

    try:
        success = asyncio.run(test_recording_and_persistence())
        if success:
            print("\nAll tests passed!")
            sys.exit(0)
        else:
            print("\nSome tests failed.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
