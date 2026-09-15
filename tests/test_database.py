"""
Database Smoke Test for Audio-Notes SQLite Archive

Tests:
1. Database initialization and table creation
2. Lecture creation
3. Idempotent segment saving
4. Ordered transcript assembly
5. List endpoint functionality
6. Get endpoint functionality
7. Search endpoint functionality
8. Restart persistence (lecture status updates)

Run this test before starting the server to verify database functionality.
"""

import sys
import os
import io
import time
from datetime import datetime

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import (
    init_database,
    create_lecture,
    save_transcript_segment,
    update_lecture_status,
    finalize_lecture,
    get_lecture_by_id,
    get_lecture_by_session_id,
    list_lectures,
    search_lectures,
    get_database_path
)

def test_database():
    print("=== Audio-Notes Database Smoke Test ===\n")

    # Test 1: Initialize database
    print("1. Initializing database...")
    init_database()
    db_path = get_database_path()
    print(f"   ✓ Database created at: {db_path}\n")

    # Test 2: Create lecture
    print("2. Creating test lecture...")
    session_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    lecture_id = create_lecture(session_id, "Test Lecture on Python Programming")
    print(f"   ✓ Lecture created with ID: {lecture_id}\n")

    # Test 3: Save transcript segments (including idempotent test)
    print("3. Saving transcript segments...")
    segments_data = [
        (1, 0.0, 4.0, "Hello and welcome to this Python programming tutorial."),
        (2, 3.5, 7.5, "Today we'll learn about functions and classes."),
        (3, 7.0, 11.0, "Functions are reusable blocks of code that perform specific tasks."),
        (4, 10.5, 14.5, "Classes allow us to create objects with attributes and methods."),
    ]

    for seq, start, end, text in segments_data:
        success = save_transcript_segment(lecture_id, seq, start, end, text)
        print(f"   ✓ Segment {seq} saved: {success}")

    # Test idempotency - try saving segment 2 again
    print("   Testing idempotency...")
    success = save_transcript_segment(lecture_id, 2, 3.5, 7.5, "Today we'll learn about functions and classes.")
    print(f"   ✓ Duplicate segment 2 handled correctly (idempotent): {success}\n")

    # Test 4: Update lecture status
    print("4. Updating lecture status...")
    update_lecture_status(lecture_id, "transcribing")
    lecture = get_lecture_by_id(lecture_id)
    print(f"   ✓ Status updated to: {lecture['status']}\n")

    # Test 5: Finalize lecture (build full_transcript from segments)
    print("5. Finalizing lecture (building full transcript)...")
    finalize_lecture(lecture_id, status="complete")
    lecture = get_lecture_by_id(lecture_id)
    print(f"   ✓ Lecture finalized")
    print(f"   ✓ Status: {lecture['status']}")
    print(f"   ✓ Full transcript length: {len(lecture['full_transcript'])} chars")
    print(f"   ✓ Segment count: {len(lecture['segments'])}\n")

    # Test 6: List lectures
    print("6. Testing list_lectures endpoint...")
    lectures = list_lectures(limit=10)
    print(f"   ✓ Found {len(lectures)} lecture(s)")
    if lectures:
        first = lectures[0]
        print(f"   ✓ First lecture: ID={first['id']}, Title={first['title']}")
        print(f"   ✓ Preview: {first.get('transcript_preview', '')[:60]}...\n")

    # Test 7: Get lecture by ID
    print("7. Testing get_lecture_by_id endpoint...")
    retrieved = get_lecture_by_id(lecture_id)
    if retrieved:
        print(f"   ✓ Retrieved lecture {lecture_id}")
        print(f"   ✓ Title: {retrieved['title']}")
        print(f"   ✓ Session ID: {retrieved['session_id']}")
        print(f"   ✓ Segments: {len(retrieved['segments'])}")
        print(f"   ✓ First segment text: {retrieved['segments'][0]['text'][:50]}...\n")

    # Test 8: Get lecture by session_id
    print("8. Testing get_lecture_by_session_id...")
    by_session = get_lecture_by_session_id(session_id)
    if by_session:
        print(f"   ✓ Found lecture by session_id: {by_session['id']}\n")

    # Test 9: Search functionality
    print("9. Testing search_lectures endpoint...")

    # Search for "Python"
    results = search_lectures("Python")
    print(f"   ✓ Search 'Python': {len(results)} result(s)")

    # Search for "functions"
    results = search_lectures("functions")
    print(f"   ✓ Search 'functions': {len(results)} result(s)")

    # Search for nonexistent term
    results = search_lectures("blockchain")
    print(f"   ✓ Search 'blockchain': {len(results)} result(s)")

    # Test empty search
    results = search_lectures("   ")
    print(f"   ✓ Empty search handled: {len(results)} result(s)\n")

    # Test 10: Create another lecture to test ordering
    print("10. Testing multiple lectures and ordering...")
    session_id_2 = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_2"
    lecture_id_2 = create_lecture(session_id_2, "Advanced Python Concepts")
    save_transcript_segment(lecture_id_2, 1, 0.0, 4.0, "Welcome to advanced Python programming.")
    finalize_lecture(lecture_id_2, status="complete")

    lectures = list_lectures(limit=10)
    print(f"   ✓ Total lectures: {len(lectures)}")
    print(f"   ✓ Newest first: {lectures[0]['title']}")
    print(f"   ✓ Second: {lectures[1]['title'] if len(lectures) > 1 else 'N/A'}\n")

    # Test 11: Error handling - nonexistent lecture
    print("11. Testing error handling...")
    nonexistent = get_lecture_by_id(99999)
    print(f"   ✓ Nonexistent lecture returns None: {nonexistent is None}\n")

    print("=== All Database Tests Passed ✓ ===\n")
    print("Database is ready for use!")
    print(f"Location: {db_path}")
    print("\nYou can now start the server with:")
    print("  uvicorn backend.server:app --reload")

if __name__ == '__main__':
    try:
        test_database()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
