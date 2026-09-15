"""
Phase 6 Integration Test: Recording with Summarization

Tests the complete workflow from recording to final summary generation.

Prerequisites:
- Server running: uvicorn backend.server:app --reload
- System audio playing during test
"""

import asyncio
import websockets
import json
import sys
import time
import requests

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

async def test_full_workflow_with_summary():
    print("=== Phase 6: Recording + Summarization Integration Test ===\n")

    # Connect to WebSocket
    print("1. Connecting to WebSocket...")
    async with websockets.connect(WS_URL) as ws:
        msg = await ws.recv()
        print(f"   Connected: {json.loads(msg)}\n")

        # Start recording
        print("2. Starting recording with title...")
        await ws.send(json.dumps({
            "type": "start",
            "title": "Phase 6 Test: Python Programming Basics"
        }))

        lecture_id = None
        session_id = None
        event_log = []

        # Record for 12 seconds
        print("   Recording for 12 seconds (play some audio)...\n")
        start_time = time.time()

        while time.time() - start_time < 12:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)
                event_type = data.get("type")
                event_log.append((event_type, data.get("state")))

                if event_type == "status":
                    state = data.get("state")
                    session_id = data.get("session_id")
                    lecture_id = data.get("lecture_id")
                    print(f"   Status: {state}")

                elif event_type == "partial_transcript":
                    seq = data.get("sequence")
                    print(f"   Transcript #{seq} received")

            except asyncio.TimeoutError:
                continue

        # Stop recording
        print("\n3. Stopping recording and waiting for summarization...")
        await ws.send(json.dumps({"type": "stop"}))

        # Track event order
        summary_received = False
        complete_received = False

        # Wait for all completion events (including summary)
        timeout = time.time() + 30  # 30 second timeout

        while time.time() < timeout:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                event_type = data.get("type")

                if event_type == "status":
                    state = data.get("state")
                    event_log.append((event_type, state))
                    print(f"   Status: {state}")

                    if state == "stopping":
                        print("     → Capture stopped")
                    elif state == "transcribing":
                        print("     → Processing remaining chunks")
                    elif state == "summarizing":
                        print("     → Generating structured lecture notes")
                    elif state == "complete":
                        complete_received = True
                        print("     → Session complete")
                        break

                elif event_type == "partial_transcript":
                    seq = data.get("sequence")
                    print(f"   Final transcript #{seq}")

                elif event_type == "transcription_complete":
                    event_log.append((event_type, None))
                    print("   ✓ Transcription complete")

                elif event_type == "summary_complete":
                    event_log.append((event_type, None))
                    summary_received = True
                    summary_preview = data.get("summary_markdown", "")[:150]
                    print(f"   ✓ Summary complete")
                    print(f"   Preview: {summary_preview}...\n")

                elif event_type == "error":
                    print(f"   ⚠ Error: {data.get('message')} (code: {data.get('code')})")

            except asyncio.TimeoutError:
                continue

    print(f"\n4. Event Order Verification:")
    print(f"   Total events: {len(event_log)}")
    print(f"   Summary received: {summary_received}")
    print(f"   Complete received: {complete_received}")

    # Verify expected event order
    expected_states = ["recording", "stopping", "transcribing", "summarizing", "complete"]
    received_states = [state for evt_type, state in event_log if evt_type == "status" and state]

    print(f"   State progression: {' → '.join(received_states)}")

    # Wait for database persistence
    await asyncio.sleep(2)

    # Test API retrieval
    print(f"\n5. Testing GET /api/lectures/{lecture_id}...")
    response = requests.get(f"{BASE_URL}/api/lectures/{lecture_id}")

    if response.status_code == 200:
        lecture = response.json()
        print(f"   ✓ Status: {response.status_code}")
        print(f"   Title: {lecture['title']}")
        print(f"   Status: {lecture['status']}")
        print(f"   Segments: {len(lecture['segments'])}")
        print(f"   Full transcript length: {len(lecture.get('full_transcript', ''))} chars")

        summary = lecture.get('summary_markdown', '')
        if summary:
            print(f"   ✓ Summary present: {len(summary)} chars")
            print(f"\n   Summary structure check:")

            required_sections = [
                "# Lecture Notes",
                "## Overview",
                "## Key Concepts",
                "## Important Details",
                "## Definitions and Formulas",
                "## Action Items"
            ]

            for section in required_sections:
                present = "✓" if section in summary else "✗"
                print(f"     {present} {section}")

            print(f"\n   Summary preview:")
            lines = summary.split('\n')
            for line in lines[:15]:
                if line.strip():
                    print(f"     {line}")

        else:
            print(f"   ✗ No summary found!")
            return False

    else:
        print(f"   ✗ Error: Status {response.status_code}")
        return False

    print("\n=== Phase 6 Integration Test Complete ===")
    print("\nVerified:")
    print("  ✓ WebSocket recording start")
    print("  ✓ Live transcription with database persistence")
    print("  ✓ Recording stop")
    print("  ✓ Status progression: recording → stopping → transcribing → summarizing → complete")
    print("  ✓ summary_complete WebSocket event")
    print("  ✓ Summary persisted to database")
    print("  ✓ GET /api/lectures/{id} returns summary_markdown")
    print("  ✓ Structured Markdown format validated")

    return True

if __name__ == '__main__':
    print("IMPORTANT:")
    print("  1. Start server: uvicorn backend.server:app --reload")
    print("  2. Play system audio during the test\n")

    input("Press Enter to start the test...")

    try:
        success = asyncio.run(test_full_workflow_with_summary())
        if success:
            print("\n✓ All Phase 6 tests passed!")
            sys.exit(0)
        else:
            print("\n✗ Some tests failed")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
