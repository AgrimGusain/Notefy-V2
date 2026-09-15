# Phase 7 Testing Guide

Quick reference for testing the new pastel frontend redesign.

## Setup

```bash
cd D:\Chrome-Summarizer\Audio-Notes

# Install dependencies (if not already installed)
pip install -r requirements.txt

# Start the server
uvicorn backend.server:app --reload
```

## Access the Application

Open your browser to: **http://localhost:8000**

---

## What You Should See

### On First Load

1. **Sidebar (left, 280px wide)**
   - 📚 "Audio Notes" header
   - Green "🎙️ New recording" button
   - Navigation: Recent / All lectures / Favorites (Soon)
   - Search box
   - List of your existing lectures (if any)

2. **Main Area (right)**
   - Welcome card saying "Welcome to Audio Notes"
   - Blue "🎙️ Start Capture" button

3. **Colors**
   - Warm cream background (#fcfcfb)
   - Soft pastel accents (mint, lavender, blush, sky blue)
   - Muted, calm tones throughout

---

## Test Scenarios

### 1. Browse Existing Lectures

**Steps:**
1. Look at the sidebar lecture list
2. Click any lecture

**Expected:**
- Lecture loads in main area
- Shows title, date, and status badge at top
- Displays AI summary (cream-colored card with ✨)
- Shows full transcript below with timestamps
- Selected lecture highlights in pale blue in sidebar

---

### 2. Search Lectures

**Steps:**
1. Type in the search box (e.g., "python" or "test")
2. Wait 300ms

**Expected:**
- Lecture list updates with matching results
- Shows "Searching..." briefly
- Displays matches or "Your recorded lectures will appear here" if none

**Clear search:**
- Delete search text → returns to full list

---

### 3. Record New Lecture

**Steps:**
1. Play some system audio (YouTube, music, anything)
2. Click "🎙️ Start Capture" (from welcome screen or live view)
3. Wait 4-5 seconds
4. Watch transcript segments appear in real-time
5. Click "⏹ Stop Capture"
6. Wait for processing to complete

**Expected:**
- View switches to "Live Recording"
- Status pill at top shows state:
  - "Recording system audio..." (pink/blush)
  - "Stopping capture..." (lavender)
  - "Processing transcripts..." (lavender)
  - "Creating structured notes..." (lavender)
  - "Recording complete" (mint green)
- Transcript segments appear with timestamps
- After ~5-10 seconds: AI summary appears (cream card)
- New lecture appears in sidebar list

---

### 4. Test Responsive Layout

**Steps:**
1. Resize browser window to ~768px width

**Expected:**
- Layout adjusts
- Sidebar may collapse or stack
- Content remains readable
- No horizontal scrolling

---

### 5. Test Connection

**Steps:**
1. Open browser DevTools (F12) → Network tab
2. Refresh page
3. Look for WebSocket connection to `ws://localhost:8000/ws`

**Expected:**
- Status pill shows "Connecting..." → "Ready to record"
- Green/mint color when connected
- Start button becomes enabled

**Test reconnection:**
1. Stop the server (Ctrl+C in terminal)
2. Watch status pill turn red "Connection lost"
3. Restart server
4. Should reconnect automatically

---

## Visual Quality Check

✅ **Colors are muted and calm** (not bright/neon)  
✅ **Shadows are subtle** (barely visible)  
✅ **Corners are rounded** (soft, not sharp)  
✅ **Text is readable** (good contrast)  
✅ **Spacing feels generous** (not cramped)  
✅ **Interface feels organized** (clear hierarchy)

---

## Common Issues

### "Module not found: soundcard"
```bash
pip install soundcard soundfile
```

### "No audio captured"
- Ensure system audio is playing
- Check default speaker in Windows sound settings
- Volume should be audible (not muted)

### "Connection lost" immediately
- Check if port 8000 is available
- Try: `netstat -ano | findstr :8000`
- Another process might be using the port

### Search doesn't work
- Type at least 2-3 characters
- Wait 300ms for debounce
- Check browser console (F12) for errors

---

## What's Different from Before

### Old UI (Phase 1-6)
- Single view (live recording only)
- No lecture library
- No search
- Basic purple/blue colors
- Centered layout
- Couldn't access past recordings from UI

### New UI (Phase 7)
- Three views (Welcome, Live, Archive Detail)
- Full lecture library in sidebar
- Real-time search
- Calm pastel colors
- Desktop-app layout with sidebar
- Click any lecture to view
- Professional, organized feel

---

## Quick Reference: Color Meanings

| Color | Meaning |
|-------|---------|
| 🟢 Mint green | Ready, success, complete |
| 🟣 Lavender | Processing, transcribing |
| 🔴 Blush pink | Recording, danger (stop) |
| 🔵 Sky blue | Selected item |
| 🟡 Cream | AI summary highlight |

---

## Keyboard Tips

- **Tab**: Navigate between buttons
- **Enter**: Activate focused button
- **Escape**: (not implemented yet)
- Mouse is primary interaction method

---

## Next Steps After Testing

If everything works:
1. ✅ Phase 7 complete!
2. Consider Phase 8 features (edit, delete, favorites, export)
3. Gather user feedback
4. Polish based on real usage

If issues found:
1. Check browser console (F12) for errors
2. Check server terminal for errors
3. Verify all dependencies installed
4. Try different browser
5. Report specific issue for fixing

---

**Happy Testing!** 🎉

The interface should feel calm, organized, and easy to use without reading documentation.
