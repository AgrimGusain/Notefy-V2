(function () { const app = window.AudioNotes = window.AudioNotes || {};
  app.updateLiveStatusUI = function (stateName, message = '') {
    const { liveStatusPill, liveStatusText, btnRecord, btnStop, btnStartWelcome } = app.dom;
    liveStatusPill.className = `live-status-pill ${stateName}`; liveStatusText.textContent = message;
    const ready = stateName === 'ready' || stateName === 'connected';
    btnRecord.hidden = !ready; btnRecord.disabled = !ready; btnStartWelcome.disabled = !ready;
    btnStop.hidden = stateName !== 'recording'; btnStop.disabled = stateName !== 'recording';
    document.body.classList.toggle('recording', stateName === 'recording');
  };
  app.addLiveTranscriptSegment = function (data) {
    if (app.state.receivedSequences.has(data.sequence)) return; app.state.receivedSequences.add(data.sequence);
    app.dom.transcriptPlaceholder.hidden = true; const segment = document.createElement('article'); segment.className = 'transcript-segment';
    segment.innerHTML = `<div class="transcript-timestamp">${app.formatTimestamp(data.start_seconds)} — ${app.formatTimestamp(data.end_seconds)}</div><div class="transcript-text"></div>`;
    segment.querySelector('.transcript-text').textContent = data.text || '(no text)'; app.dom.transcriptContainer.appendChild(segment);
  };
  app.connectWebSocket = function () {
    if (app.state.isUnloading) return; const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'; const ws = new WebSocket(`${protocol}//${location.host}/ws`); app.state.ws = ws; app.updateLiveStatusUI('connecting', 'Connecting…');
    ws.onopen = () => { app.state.connectionState = 'connected'; app.state.reconnectDelay = 1000; app.state.reconnectAttempts = 0; if (app.state.recordingState === 'idle') app.updateLiveStatusUI('ready', 'Ready to record'); };
    ws.onmessage = event => { try { app.handleServerMessage(JSON.parse(event.data)); } catch (error) { console.error('Failed to parse WebSocket message', error); } };
    ws.onclose = () => { app.state.ws = null; app.state.connectionState = 'disconnected'; app.updateLiveStatusUI('error', 'Connection lost'); if (!app.state.isUnloading) { app.state.reconnectAttempts++; setTimeout(app.connectWebSocket, Math.min(app.state.reconnectDelay * 2 ** (app.state.reconnectAttempts - 1), app.state.maxReconnectDelay)); } };
  };
  app.sendCommand = function (command) { if (!app.state.ws || app.state.ws.readyState !== WebSocket.OPEN || app.state.pendingCommand) return; app.state.pendingCommand = true; app.state.ws.send(JSON.stringify(command)); };
  app.handleServerMessage = function (data) {
    if (data.type === 'connection' && data.state === 'ready') { app.state.recordingState = 'idle'; app.updateLiveStatusUI('ready', 'Ready to record'); return; }
    if (data.type === 'partial_transcript') return app.addLiveTranscriptSegment(data);
    if (data.type === 'summary_complete') { if (app.state.activeViewId === 'view-live') { app.dom.liveSummaryContent.innerHTML = app.safeMarkdownToHTML(data.summary_markdown); app.dom.liveSummaryCard.hidden = false; app.dom.liveDivider.hidden = false; } return; }
    if (data.type === 'error') { app.state.pendingCommand = false; app.updateLiveStatusUI('error', `Error: ${data.message || 'Unknown'}`); return; }
    if (data.type !== 'status') return;
    app.state.pendingCommand = false; const s = data.state;
    if (s === 'recording') { app.state.recordingState = 'recording'; app.state.activeSessionId = data.session_id; app.state.recordingStartedAt = Date.now(); app.startTimer(); app.dom.sessionLabel.textContent = String(data.session_id || 'live').slice(-6); app.state.receivedSequences.clear(); app.dom.transcriptContainer.innerHTML = ''; app.dom.transcriptPlaceholder.hidden = false; app.dom.transcriptContainer.appendChild(app.dom.transcriptPlaceholder); app.dom.liveSummaryCard.hidden = true; app.dom.liveDivider.hidden = true; app.updateLiveStatusUI('recording', 'Live'); if (app.state.activeViewId !== 'view-live') app.showView('view-live'); }
    else if (s === 'stopping') { app.stopTimer(); app.state.recordingState = 'stopping'; app.updateLiveStatusUI('processing', 'Stopping capture…'); }
    else if (s === 'transcribing') { app.state.recordingState = 'transcribing'; app.updateLiveStatusUI('processing', 'Transcribing…'); }
    else if (s === 'summarizing') { app.state.recordingState = 'summarizing'; app.updateLiveStatusUI('processing', 'Preparing notes…'); }
    else if (s === 'complete') { app.state.recordingState = 'complete'; app.updateLiveStatusUI('ready', 'Recording complete'); app.fetchLectures(); setTimeout(() => { if (app.state.recordingState === 'complete') { app.state.recordingState = 'idle'; app.updateLiveStatusUI('ready', 'Ready to record'); } }, 3000); }
  };
})();
