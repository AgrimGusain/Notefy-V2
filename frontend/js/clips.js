(function () {
  // Transcript clips: select segments of an open recording, save them as clips, and arrange clips from any recordings into collections.
  // The backend computes clip timing and text from the stored segments; the transcript itself is never modified.
  const app = window.AudioNotes = window.AudioNotes || {};
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const request = async (url, { method = 'GET', body } = {}) => {
    const response = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
    return data;
  };
  app.formatClock = seconds => { const total = Math.floor(seconds || 0); return [Math.floor(total / 3600), Math.floor(total % 3600 / 60), total % 60].map(part => String(part).padStart(2, '0')).join(':'); };
  const formatDuration = seconds => { const total = Math.round(seconds || 0), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = total % 60; return h ? `${h}h ${m}m` : m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`; };
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

  // ===== Selecting transcript segments on an open recording =====
  const selection = { lectureId: null, ids: new Set(), anchor: null };
  let collectionsCache = [];

  const clippableSegments = () => (app.state.activeLecture?.segments || []).filter(segment => segment.text && segment.text.trim());
  const segmentElements = () => Array.from(document.querySelectorAll('#detail-transcript-container .transcript-segment.is-clippable'));
  // Selected segments grouped into contiguous runs; each run becomes one clip so its timestamps stay exact.
  function selectedRuns() {
    const runs = []; let current = [];
    clippableSegments().forEach(segment => { if (selection.ids.has(segment.id)) current.push(segment); else if (current.length) { runs.push(current); current = []; } });
    if (current.length) runs.push(current);
    return runs;
  }

  app.decorateTranscriptForClips = function (lecture) {
    if (selection.lectureId !== lecture.id) { selection.lectureId = lecture.id; selection.ids.clear(); selection.anchor = null; }
    const clippable = new Set(clippableSegments().map(segment => segment.id));
    const byId = new Map((lecture.segments || []).map(segment => [segment.id, segment]));
    document.querySelectorAll('#detail-transcript-container .transcript-segment[data-segment-id]').forEach(element => {
      const id = Number(element.dataset.segmentId); if (!clippable.has(id)) return;
      element.classList.add('is-clippable');
      const button = document.createElement('button'); button.type = 'button'; button.className = 'clip-toggle'; button.dataset.segmentId = id;
      button.setAttribute('aria-label', `Select ${app.formatClock(byId.get(id).start_seconds)} for a clip (Shift-click to select a range)`); button.title = 'Select for a clip · Shift-click selects a range';
      button.innerHTML = '<i data-lucide="scissors"></i>';
      element.querySelector('.transcript-timestamp').prepend(button);
    });
    for (const id of [...selection.ids]) if (!clippable.has(id)) selection.ids.delete(id);
    syncSelection(); loadClipMarks(lecture.id); app.refreshIcons();
  };

  function toggleSegment(id, extend) {
    const order = clippableSegments().map(segment => segment.id);
    if (extend && selection.anchor != null && order.includes(selection.anchor)) {
      const [from, to] = [order.indexOf(selection.anchor), order.indexOf(id)].sort((a, b) => a - b);
      order.slice(from, to + 1).forEach(segmentId => selection.ids.add(segmentId));
    } else if (selection.ids.has(id)) selection.ids.delete(id);
    else selection.ids.add(id);
    selection.anchor = id; syncSelection();
  }

  function clearSelection() { selection.ids.clear(); selection.anchor = null; syncSelection(); }

  async function loadClipMarks(lectureId) {
    try {
      const { clips } = await request(`/api/clips?lecture_id=${lectureId}`);
      if (app.state.activeLecture?.id !== lectureId) return;
      const counts = new Map(); clips.forEach(clip => clip.segment_ids.forEach(id => counts.set(id, (counts.get(id) || 0) + 1)));
      segmentElements().forEach(element => { const count = counts.get(Number(element.dataset.segmentId)) || 0; element.classList.toggle('has-clip', count > 0); element.title = count ? `In ${plural(count, 'saved clip')}` : ''; });
    } catch (_) { /* marks are a convenience; the transcript works without them */ }
  }

  // --- The floating clip tray ---
  let tray = null;
  function buildTray() {
    tray = document.createElement('section'); tray.className = 'clip-tray'; tray.hidden = true; tray.setAttribute('aria-label', 'Clip selection');
    tray.innerHTML = `<div class="clip-tray-head"><span class="clip-tray-mark" aria-hidden="true"><i data-lucide="scissors"></i></span><div class="clip-tray-summary" aria-live="polite"><strong></strong><small></small></div><button class="clip-tray-clear" type="button" aria-label="Clear selection" title="Clear selection">×</button></div>
      <div class="clip-chips" aria-label="Selected segments — remove one before saving"></div><p class="clip-tray-note" hidden></p>
      <div class="clip-tray-form"><input class="clip-title-input" maxlength="500" placeholder="Label (optional)" aria-label="Clip label"><select class="clip-collection-select" aria-label="Add to collection"></select><input class="clip-new-collection" maxlength="255" placeholder="New collection name" aria-label="New collection name" hidden><button class="clip-save" type="button"><i data-lucide="scissors"></i><span>Save clip</span></button></div>`;
    document.body.appendChild(tray);
    tray.querySelector('.clip-tray-clear').onclick = clearSelection;
    tray.querySelector('.clip-chips').onclick = event => { const chip = event.target.closest('[data-remove]'); if (!chip) return; selection.ids.delete(Number(chip.dataset.remove)); syncSelection(); };
    const select = tray.querySelector('.clip-collection-select'), newName = tray.querySelector('.clip-new-collection');
    select.onchange = () => { newName.hidden = select.value !== 'new'; if (!newName.hidden) newName.focus(); };
    tray.querySelector('.clip-save').onclick = saveSelection;
    tray.addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.matches('input')) { event.preventDefault(); saveSelection(); } if (event.key === 'Escape') clearSelection(); });
    app.refreshIcons();
  }

  async function refreshCollectionOptions() {
    try { collectionsCache = (await request('/api/collections')).collections; } catch (_) { /* keep the previous list */ }
    if (!tray) return;
    const select = tray.querySelector('.clip-collection-select'), current = select.value;
    select.innerHTML = `<option value="">No collection</option>${collectionsCache.map(item => `<option value="${item.id}">${escape(item.title)}</option>`).join('')}<option value="new">+ New collection…</option>`;
    if ([...select.options].some(option => option.value === current)) select.value = current;
  }

  function syncSelection() {
    segmentElements().forEach(element => { const on = selection.ids.has(Number(element.dataset.segmentId)); element.classList.toggle('is-selected', on); element.querySelector('.clip-toggle')?.setAttribute('aria-pressed', String(on)); });
    if (!tray) buildTray();
    const visible = selection.ids.size > 0 && app.state.activeViewId === 'view-detail' && app.state.activeLecture?.id === selection.lectureId;
    const wasHidden = tray.hidden; tray.hidden = !visible;
    if (!visible) return;
    if (wasHidden) refreshCollectionOptions();
    const runs = selectedRuns(), segments = runs.flat(), first = segments[0], last = segments[segments.length - 1];
    const seconds = runs.reduce((sum, run) => sum + run[run.length - 1].end_seconds - run[0].start_seconds, 0);
    tray.querySelector('.clip-tray-summary strong').textContent = `${plural(segments.length, 'segment')} · ${app.formatClock(first.start_seconds)} – ${app.formatClock(last.end_seconds)}`;
    tray.querySelector('.clip-tray-summary small').textContent = `${formatDuration(seconds)} from “${app.state.activeLecture.title || 'Untitled recording'}”`;
    tray.querySelector('.clip-chips').innerHTML = segments.map(segment => `<button type="button" class="clip-chip" data-remove="${segment.id}" aria-label="Remove ${app.formatClock(segment.start_seconds)} from the selection">${app.formatClock(segment.start_seconds)}<span aria-hidden="true">×</span></button>`).join('');
    const note = tray.querySelector('.clip-tray-note');
    note.hidden = runs.length < 2; note.textContent = `The selection has gaps, so it will be saved as ${runs.length} separate clips — each keeps exact timestamps.`;
    tray.querySelector('.clip-save span').textContent = runs.length > 1 ? `Save ${runs.length} clips` : 'Save clip';
  }

  async function saveSelection() {
    const runs = selectedRuns(), lecture = app.state.activeLecture, button = tray.querySelector('.clip-save');
    if (!runs.length || !lecture || button.disabled) return;
    const select = tray.querySelector('.clip-collection-select'), newName = tray.querySelector('.clip-new-collection'), label = tray.querySelector('.clip-title-input').value.trim();
    if (select.value === 'new' && !newName.value.trim()) { newName.focus(); return showToast('Name the new collection first.', { error: true }); }
    button.disabled = true; tray.classList.add('is-saving');
    try {
      let collection = collectionsCache.find(item => String(item.id) === select.value) || null;
      if (select.value === 'new') { collection = await request('/api/collections', { method: 'POST', body: { title: newName.value.trim() } }); newName.value = ''; newName.hidden = true; }
      const saved = [];
      for (const [index, run] of runs.entries()) {
        const title = label ? (runs.length > 1 ? `${label} (${index + 1}/${runs.length})` : label) : null;
        saved.push(await request('/api/clips', { method: 'POST', body: { lecture_id: lecture.id, segment_ids: run.map(segment => segment.id), title, collection_id: collection?.id ?? null } }));
      }
      const savedIds = new Set(saved.flatMap(clip => clip.segment_ids));
      segmentElements().filter(element => savedIds.has(Number(element.dataset.segmentId))).forEach(element => { element.classList.remove('just-clipped'); void element.offsetWidth; element.classList.add('just-clipped'); setTimeout(() => element.classList.remove('just-clipped'), 1200); });
      tray.querySelector('.clip-title-input').value = '';
      clearSelection(); loadClipMarks(lecture.id);
      const range = saved.length === 1 ? ` · ${app.formatClock(saved[0].start_seconds)}–${app.formatClock(saved[0].end_seconds)}` : '';
      showToast(`Saved ${plural(saved.length, 'clip')}${range}${collection ? ` to “${collection.title}”` : ''}`, { action: collection ? 'View collection' : 'View clips', onAction: () => app.openClips(collection?.id ?? null) });
      if (collection) select.value = String(collection.id);
      refreshCollectionOptions();
    } catch (error) { showToast(`Couldn't save the clip: ${error.message}`, { error: true }); }
    finally { button.disabled = false; tray.classList.remove('is-saving'); }
  }

  // --- Confirmation toast (with an optional action) ---
  let toastTimer = null;
  function showToast(text, { action, onAction, error = false } = {}) {
    let toast = $('clip-toast');
    if (!toast) { toast = document.createElement('div'); toast.id = 'clip-toast'; toast.setAttribute('role', 'status'); document.body.appendChild(toast); }
    toast.className = `clip-toast${error ? ' is-error' : ''}`; toast.innerHTML = `<span></span>${action ? '<button type="button"></button>' : ''}`;
    toast.querySelector('span').textContent = text;
    if (action) { const button = toast.querySelector('button'); button.textContent = action; button.onclick = () => { toast.remove(); onAction(); }; }
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.remove(), error ? 5000 : 4500);
  }

  // ===== Clips & collections view =====
  const view = { collectionId: null };

  app.openClips = function (collectionId = null, { push = true } = {}) {
    return app.attemptNavigation(() => {
      const hash = collectionId ? `#collection/${collectionId}` : '#clips';
      if (push && location.hash !== hash) history.pushState(null, '', hash);
      view.collectionId = collectionId;
      app.showView('view-clips');
      document.querySelectorAll('.nav-link').forEach(link => link.classList.toggle('active', link.id === 'nav-clips'));
      return renderClipsView();
    });
  };

  app.openClipSource = function (clip) {
    if (clip.source_deleted) return;
    app.attemptNavigation(() => { app.state.pendingCitation = { source_type: 'transcript', lecture_id: clip.lecture_id, segment_ids: clip.segment_ids, timestamp_start: clip.start_seconds, timestamp_end: clip.end_seconds }; app.loadLectureDetail(clip.lecture_id); });
  };

  async function renderClipsView() {
    const list = $('clip-list'); list.setAttribute('aria-busy', 'true');
    if (!list.children.length) list.innerHTML = '<li class="skeleton-card" aria-hidden="true"></li><li class="skeleton-card" aria-hidden="true"></li>';
    try {
      const [{ collections }, data] = await Promise.all([request('/api/collections'), view.collectionId ? request(`/api/collections/${view.collectionId}`) : request('/api/clips')]);
      collectionsCache = collections;
      renderSidebar(collections);
      if (view.collectionId) renderCollection(data); else renderAllClips(data.clips);
    } catch (error) {
      if (view.collectionId && /not found/i.test(error.message)) { showToast('That collection no longer exists.', { error: true }); history.replaceState(null, '', '#clips'); view.collectionId = null; return renderClipsView(); }
      list.innerHTML = `<li class="clips-empty"><h2>Couldn't load clips.</h2><p>${escape(error.message)}</p></li>`;
    } finally { list.setAttribute('aria-busy', 'false'); }
  }

  function renderSidebar(collections) {
    const nav = $('collection-list');
    nav.innerHTML = `<button type="button" class="collection-link ${view.collectionId ? '' : 'active'}" data-collection=""><span>All clips</span></button>` + (collections.length
      ? collections.map(item => `<button type="button" class="collection-link ${view.collectionId === item.id ? 'active' : ''}" data-collection="${item.id}"><span>${escape(item.title)}</span><small>${plural(item.clip_count, 'clip')} · ${formatDuration(item.total_seconds)}</small></button>`).join('')
      : '<p class="collection-empty">No collections yet.</p>');
    nav.querySelectorAll('[data-collection]').forEach(button => button.onclick = () => app.openClips(button.dataset.collection ? Number(button.dataset.collection) : null));
  }

  function setHeader(eyebrow, titleHtml, summary, actionsHtml = '') {
    $('clips-eyebrow').textContent = eyebrow; $('clips-heading').innerHTML = titleHtml; $('clips-summary').textContent = summary; $('clips-header-actions').innerHTML = actionsHtml;
  }

  const sourceCount = clips => new Set(clips.map(clip => clip.lecture_id ?? `deleted-${clip.source_title}`)).size;

  function renderAllClips(clips) {
    setHeader('Clip library', 'All <em>clips.</em>', clips.length ? `${plural(clips.length, 'clip')} from ${plural(sourceCount(clips), 'recording')}` : '');
    renderList(clips.map(clip => ({ clip })), false);
  }

  function renderCollection(collection) {
    const clips = collection.items.map(item => item.clip);
    setHeader('Collection', `${escape(collection.title)}<em>.</em>`, collection.items.length ? `${plural(collection.clip_count, 'clip')} · ${formatDuration(collection.total_seconds)} · from ${plural(sourceCount(clips), 'recording')}` : '',
      `${collection.items.length ? '<button class="capture-stamp synth-open" type="button" data-collection-action="synthesize">✦ Combine into notes</button>' : ''}<button class="paper-button" type="button" data-collection-action="rename">Rename</button><button class="paper-button danger" type="button" data-collection-action="delete">Delete collection</button>`);
    $('clips-header-actions').querySelector('[data-collection-action="synthesize"]')?.addEventListener('click', () => openSynthesis(collection));
    $('clips-header-actions').querySelector('[data-collection-action="rename"]').onclick = () => inlineRename($('clips-heading'), collection.title, async title => { await request(`/api/collections/${collection.id}`, { method: 'PATCH', body: { title } }); renderClipsView(); });
    $('clips-header-actions').querySelector('[data-collection-action="delete"]').onclick = async () => {
      if (!await confirmDialog('Delete this collection?', `“${collection.title}” will be removed. Its clips and their recordings are kept.`, 'Delete collection')) return;
      await request(`/api/collections/${collection.id}`, { method: 'DELETE' }); showToast('Collection deleted. Its clips are still in your library.'); app.openClips(null);
    };
    renderList(collection.items, true, collection);
  }

  function renderList(entries, inCollection, collection) {
    const list = $('clip-list'), context = inCollection ? `collection-${collection.id}` : 'all';
    list.classList.toggle('is-ordered', inCollection);
    // Cards animate in when switching lists, not after every reorder/rename.
    if (list.dataset.context !== context) { list.dataset.context = context; list.classList.remove('is-entering'); void list.offsetWidth; list.classList.add('is-entering'); setTimeout(() => list.classList.remove('is-entering'), 700); }
    if (!entries.length) {
      list.innerHTML = inCollection
        ? '<li class="clips-empty"><h2>This collection is empty.</h2><p>Add clips from <strong>All clips</strong>, or choose this collection when saving a clip from a recording.</p></li>'
        : '<li class="clips-empty"><h2>No clips yet.</h2><p>Open a recording, select transcript segments with <span class="clip-inline-icon">✂</span> (Shift-click selects a range), and save them as a clip.</p></li>';
      return;
    }
    list.innerHTML = entries.map((entry, index) => clipCard(entry, index, entries.length, inCollection)).join('');
    app.refreshIcons();
    list.querySelectorAll('.clip-card').forEach(card => wireCard(card, entries.find(entry => String(entry.clip.id) === card.dataset.clipId), inCollection, collection));
    if (inCollection) wireDragAndDrop(list, collection);
  }

  function clipCard({ clip, item_id, position }, index, total, inCollection) {
    const memberships = clip.collections.map(item => `<span class="clip-membership">${escape(item.title)}</span>`).join('');
    const addOptions = collectionsCache.filter(item => !clip.collections.some(member => member.id === item.id)).map(item => `<option value="${item.id}">${escape(item.title)}</option>`).join('');
    return `<li class="clip-card" data-clip-id="${clip.id}" ${inCollection ? `data-item-id="${item_id}" draggable="true"` : ''} style="--i:${Math.min(index, 8)}">
      ${inCollection ? `<div class="clip-order"><span class="clip-handle" title="Drag to reorder" aria-hidden="true">⋮⋮</span><span class="clip-position">${String(position).padStart(2, '0')}</span></div>` : ''}
      <div class="clip-body">
        <div class="clip-meta">${clip.source_deleted ? `<span class="clip-source is-deleted" title="The original recording was deleted; this clip keeps its saved text and timestamps.">${escape(clip.source_title || 'Untitled recording')} · recording deleted</span>` : `<button type="button" class="clip-source" data-action="source" title="Open the recording at this clip"><i data-lucide="audio-lines"></i>${escape(clip.source_title || 'Untitled recording')}</button>`}<span class="clip-range">${app.formatClock(clip.start_seconds)} – ${app.formatClock(clip.end_seconds)}</span><span class="clip-duration">${formatDuration(clip.duration_seconds)}</span></div>
        <h3 class="clip-label">${escape(clip.title || 'Untitled clip')}</h3>
        <p class="clip-text">${escape(clip.text.replace(/\s+/g, ' '))}</p>
        <button type="button" class="clip-expand" data-action="expand" hidden>Show full text</button>
        <div class="clip-actions">
          ${inCollection
            ? `<button type="button" class="paper-button" data-action="up" ${index === 0 ? 'disabled' : ''} aria-label="Move up">↑</button><button type="button" class="paper-button" data-action="down" ${index === total - 1 ? 'disabled' : ''} aria-label="Move down">↓</button><button type="button" class="paper-button" data-action="rename">Rename</button><button type="button" class="paper-button" data-action="remove">Remove from collection</button>`
            : `${memberships}${addOptions ? `<select class="clip-add-select" data-action="add" aria-label="Add to collection"><option value="">+ Add to collection…</option>${addOptions}</select>` : ''}<button type="button" class="paper-button" data-action="rename">Rename</button><button type="button" class="paper-button danger" data-action="delete">Delete clip</button>`}
        </div>
      </div></li>`;
  }

  function wireCard(card, entry, inCollection, collection) {
    const { clip } = entry, text = card.querySelector('.clip-text'), expand = card.querySelector('[data-action="expand"]');
    requestAnimationFrame(() => { if (text.scrollHeight > text.clientHeight + 2) expand.hidden = false; });
    expand.onclick = () => { const open = card.classList.toggle('is-expanded'); expand.textContent = open ? 'Show less' : 'Show full text'; };
    card.querySelector('[data-action="source"]')?.addEventListener('click', () => app.openClipSource(clip));
    card.querySelector('[data-action="rename"]').onclick = () => inlineRename(card.querySelector('.clip-label'), clip.title || '', async title => { await request(`/api/clips/${clip.id}`, { method: 'PATCH', body: { title } }); renderClipsView(); }, { allowEmpty: true, placeholder: 'Untitled clip' });
    card.querySelector('[data-action="delete"]')?.addEventListener('click', async () => {
      if (!await confirmDialog('Delete this clip?', `The clip is removed from your library and from ${plural(clip.collections.length, 'collection')}. The original recording is not affected.`, 'Delete clip')) return;
      await request(`/api/clips/${clip.id}`, { method: 'DELETE' }); showToast('Clip deleted.'); renderClipsView();
    });
    card.querySelector('[data-action="add"]')?.addEventListener('change', async event => {
      const target = collectionsCache.find(item => String(item.id) === event.target.value); if (!target) return;
      await request(`/api/collections/${target.id}/items`, { method: 'POST', body: { clip_id: clip.id } }); showToast(`Added to “${target.title}”`, { action: 'View collection', onAction: () => app.openClips(target.id) }); renderClipsView();
    });
    if (!inCollection) return;
    card.querySelector('[data-action="remove"]').onclick = async () => { await request(`/api/collections/${collection.id}/items/${entry.item_id}`, { method: 'DELETE' }); showToast('Removed from the collection. The clip is still in All clips.'); renderClipsView(); };
    const move = offset => { const ids = collection.items.map(item => item.item_id), from = ids.indexOf(entry.item_id), to = from + offset; if (to < 0 || to >= ids.length) return; [ids[from], ids[to]] = [ids[to], ids[from]]; saveOrder(collection, ids, entry.item_id); };
    card.querySelector('[data-action="up"]').onclick = () => move(-1);
    card.querySelector('[data-action="down"]').onclick = () => move(1);
  }

  async function saveOrder(collection, itemIds, focusItemId) {
    try {
      const updated = await request(`/api/collections/${collection.id}/order`, { method: 'PUT', body: { item_ids: itemIds } });
      renderCollection(updated);
      if (focusItemId) { const card = document.querySelector(`.clip-card[data-item-id="${focusItemId}"]`); card?.classList.add('just-moved'); card?.querySelector('[data-action="up"]:not(:disabled), [data-action="down"]:not(:disabled)')?.focus(); }
    } catch (error) { showToast(`Couldn't reorder: ${error.message}`, { error: true }); renderClipsView(); }
  }

  function wireDragAndDrop(list, collection) {
    let dragged = null;
    list.querySelectorAll('.clip-card[draggable]').forEach(card => {
      card.addEventListener('dragstart', event => { dragged = card; card.classList.add('is-dragging'); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', card.dataset.itemId); });
      card.addEventListener('dragend', () => { card.classList.remove('is-dragging'); list.querySelectorAll('.drop-before,.drop-after').forEach(el => el.classList.remove('drop-before', 'drop-after')); dragged = null; });
      card.addEventListener('dragover', event => { if (!dragged || dragged === card) return; event.preventDefault(); const after = event.clientY > card.getBoundingClientRect().top + card.offsetHeight / 2; card.classList.toggle('drop-after', after); card.classList.toggle('drop-before', !after); });
      card.addEventListener('dragleave', () => card.classList.remove('drop-before', 'drop-after'));
      card.addEventListener('drop', event => {
        event.preventDefault(); if (!dragged || dragged === card) return;
        const ids = collection.items.map(item => item.item_id).filter(id => String(id) !== dragged.dataset.itemId);
        const index = ids.indexOf(Number(card.dataset.itemId)) + (card.classList.contains('drop-after') ? 1 : 0);
        ids.splice(index, 0, Number(dragged.dataset.itemId)); saveOrder(collection, ids, Number(dragged.dataset.itemId));
      });
    });
  }

  // --- Combine a collection's clips into one grounded note (POST /api/collections/:id/synthesize, then POST /api/notes) ---
  function openSynthesis(collection) {
    const modal = document.createElement('div'); modal.className = 'ai-modal';
    modal.innerHTML = `<section class="ai-panel synth-panel" role="dialog" aria-modal="true" aria-labelledby="synth-title">
      <h2 id="synth-title">✦ Combine into notes</h2>
      <p>Only the ticked clips are sent, in this order. Every point in the result cites the recording and time it came from, and nothing outside these clips may be added.</p>
      <fieldset class="synth-clips"><legend>Clips · ${escape(collection.title)}</legend>${collection.items.map(({ clip, position }) => `<label><input type="checkbox" value="${clip.id}" checked><span class="synth-clip-pos">${String(position).padStart(2, '0')}</span><span>${escape(clip.title || 'Untitled clip')}<small>${escape(clip.source_title || 'Untitled recording')}${clip.source_deleted ? ' (recording deleted)' : ''} · ${app.formatClock(clip.start_seconds)}–${app.formatClock(clip.end_seconds)}</small></span></label>`).join('')}</fieldset>
      <label>Extra instructions (optional)<textarea id="synth-instructions" maxlength="2000" placeholder="e.g. Focus on the maths and keep it short"></textarea></label>
      <label>Provider<select id="synth-provider"><option value="external">External LLM — writes combined notes</option><option value="local">Local — quotes key sentences from each clip, no rewriting</option></select></label>
      <div id="synth-external"><div class="ai-grid"><label>Model<input id="synth-model" placeholder="openai/gpt-oss-120b"></label><label>Base URL<input id="synth-url" placeholder="https://api.groq.com/openai/v1"></label></div><label>API Key<input id="synth-key" type="password" autocomplete="new-password" placeholder="Saved securely on this computer"></label><label class="ai-save-key"><input id="synth-save-settings" type="checkbox" checked> Save model, URL, and API key securely on this computer</label><p class="ai-key-hint" id="synth-key-hint"></p></div>
      <div class="ai-status" id="synth-status" aria-live="polite"></div>
      <div class="ai-actions"><button type="button" id="synth-cancel">Cancel</button><button type="button" class="primary" id="synth-generate">Generate notes ✦</button></div>
      <div class="ai-preview" id="synth-preview" hidden><div class="synth-grounding" id="synth-grounding"></div><div class="markdown-body synth-result" id="synth-result"></div><p class="synth-source" id="synth-source"></p><div class="ai-actions"><button type="button" id="synth-regenerate">Regenerate</button><button type="button" class="primary" id="synth-save">Save as note</button></div></div>
    </section>`;
    document.body.appendChild(modal);
    const panel = modal.querySelector('.ai-panel'), field = id => panel.querySelector(`#${id}`), status = text => { field('synth-status').textContent = text; };
    const provider = field('synth-provider');
    let hasSavedKey = false, result = null, busy = false;
    provider.onchange = () => { field('synth-external').hidden = provider.value === 'local'; };
    app.loadAISettings?.().then(settings => { field('synth-model').value = settings.model || ''; field('synth-url').value = settings.base_url || ''; hasSavedKey = !!settings.has_api_key; field('synth-key-hint').textContent = hasSavedKey ? 'A key is securely saved in your operating system credential vault. Enter a new key only to replace it.' : 'Your API key is saved only in your operating system credential vault.'; }).catch(error => { field('synth-key-hint').textContent = error.message; });
    field('synth-cancel').onclick = () => modal.remove();

    const generate = async () => {
      if (busy) return;
      const clipIds = [...panel.querySelectorAll('.synth-clips input:checked')].map(input => Number(input.value));
      if (!clipIds.length) return status('Tick at least one clip.');
      const external = provider.value === 'external', key = field('synth-key').value.trim(), model = field('synth-model').value.trim(), base_url = field('synth-url').value.trim();
      if (external && !key && !hasSavedKey) return status('An API key is required for the external provider — or choose Local.');
      busy = true; panel.querySelectorAll('button').forEach(button => { button.disabled = true; }); panel.classList.add('is-busy');
      status(external ? `Combining ${plural(clipIds.length, 'clip')} with ${model || 'the external model'}…` : `Compiling ${plural(clipIds.length, 'clip')}…`);
      try {
        if (external && field('synth-save-settings').checked) { const settings = await app.saveAISettings({ model, base_url, api_key: key || null }); hasSavedKey = !!settings.has_api_key; }
        const response = await fetch(`/api/collections/${collection.id}/synthesize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clip_ids: clipIds, provider: provider.value, api_key: key, model, base_url, instructions: field('synth-instructions').value, fallback_to_local: false }) });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || data.detail || 'Could not combine the clips.');
        result = data; showPreview(data); status('Preview ready. Review it, then save it as a note.');
      } catch (error) { status(error.message); }
      finally { busy = false; panel.querySelectorAll('button').forEach(button => { button.disabled = false; }); panel.classList.remove('is-busy'); }
    };

    const showPreview = data => {
      field('synth-preview').hidden = false;
      field('synth-result').innerHTML = app.safeMarkdownToHTML(data.summary_markdown);
      const grounding = data.grounding, problems = [];
      if (grounding.uncited.length) problems.push(`<p><strong>${plural(grounding.uncited.length, 'point')} ${grounding.uncited.length === 1 ? 'cites' : 'cite'} no clip</strong> and may not come from your recordings:</p><ul>${grounding.uncited.map(item => `<li>${escape(item.text)}</li>`).join('')}</ul>`);
      if (grounding.weakly_supported.length) problems.push(`<p><strong>${plural(grounding.weakly_supported.length, 'point')} ${grounding.weakly_supported.length === 1 ? 'uses wording not found in the clip it cites' : 'use wording not found in the clips they cite'}</strong> — check them:</p><ul>${grounding.weakly_supported.map(item => `<li>${escape(item.text)}${item.unsupported_terms.length ? ` <em>(${escape(item.unsupported_terms.join(', '))})</em>` : ''}</li>`).join('')}</ul>`);
      if (grounding.dropped_citations) problems.push(`<p>${plural(grounding.dropped_citations, 'citation')} to clips that were not supplied ${grounding.dropped_citations === 1 ? 'was' : 'were'} removed.</p>`);
      const box = field('synth-grounding'); box.classList.toggle('has-problems', problems.length > 0);
      box.innerHTML = problems.length ? problems.join('') : '<p>✓ Every point cites a clip, and its wording matches the cited clip.</p>';
      field('synth-source').textContent = data.source === 'external' ? `Written by ${data.model || 'the external model'} from ${plural(data.clips.length, 'clip')}.` : data.source === 'local_fallback' ? `External AI unavailable (${data.fallback_reason}); compiled locally from the clips instead.` : `Compiled locally: key sentences quoted from each clip.`;
      field('synth-save').textContent = problems.length ? 'Save anyway' : 'Save as note';
      field('synth-preview').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    };

    field('synth-generate').onclick = generate; field('synth-regenerate').onclick = generate;
    field('synth-save').onclick = async () => {
      if (!result || busy) return; busy = true; field('synth-save').disabled = true; status('Saving note…');
      try {
        const note = await request('/api/notes', { method: 'POST', body: { title: result.title, summary_markdown: result.summary_markdown } });
        modal.remove(); await app.refreshWorkspace?.(); app.loadLectureDetail(note.id);
        showToast(`Created “${note.title}” from ${plural(result.clips.length, 'clip')}`);
      } catch (error) { status(`Couldn't save the note: ${error.message}`); busy = false; field('synth-save').disabled = false; }
    };
    provider.focus();
  }

  function inlineRename(element, current, save, { allowEmpty = false, placeholder = '' } = {}) {
    const input = document.createElement('input'); input.className = 'clip-rename-input'; input.value = current; input.placeholder = placeholder; input.maxLength = 500; input.setAttribute('aria-label', 'New name');
    const original = element.innerHTML; element.replaceChildren(input); input.focus(); input.select();
    let done = false;
    const finish = async commit => {
      if (done) return; done = true;
      const value = input.value.trim();
      if (!commit || value === current.trim() || (!value && !allowEmpty)) { element.innerHTML = original; return; }
      try { await save(value); } catch (error) { element.innerHTML = original; showToast(`Couldn't rename: ${error.message}`, { error: true }); }
    };
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); finish(true); } if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); finish(false); } });
    input.addEventListener('blur', () => finish(true));
  }

  function confirmDialog(title, message, confirmLabel) {
    return new Promise(resolve => {
      const modal = document.createElement('div'); modal.className = 'editor-modal';
      modal.innerHTML = `<div class="editor-dialog" role="alertdialog" aria-modal="true" aria-labelledby="clip-confirm-title"><h2 id="clip-confirm-title"></h2><p></p><div class="dialog-actions"><button class="editor-button" type="button">Cancel</button><button class="editor-button save" type="button"></button></div></div>`;
      modal.querySelector('h2').textContent = title; modal.querySelector('p').textContent = message; const [cancel, confirm] = modal.querySelectorAll('button'); confirm.textContent = confirmLabel;
      const close = value => { modal.remove(); resolve(value); };
      cancel.onclick = () => close(false); confirm.onclick = () => close(true);
      modal.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); close(false); } });
      document.body.appendChild(modal); cancel.focus();
    });
  }

  // ===== Wiring =====
  const showView = app.showView;
  app.showView = function (viewId) { showView(viewId); syncSelection(); };

  document.addEventListener('DOMContentLoaded', () => {
    const transcript = $('detail-transcript-container');
    transcript.addEventListener('click', event => { const toggle = event.target.closest('.clip-toggle'); if (toggle) toggleSegment(Number(toggle.dataset.segmentId), event.shiftKey); });
    // Selecting text across transcript lines selects those segments for a clip.
    transcript.addEventListener('mouseup', event => {
      if (event.target.closest('button')) return;
      setTimeout(() => {
        const text = window.getSelection(); if (!text || text.isCollapsed || !text.rangeCount) return;
        const range = text.getRangeAt(0), hits = segmentElements().filter(element => range.intersectsNode(element.querySelector('.transcript-text')));
        if (!hits.length) return;
        hits.forEach(element => selection.ids.add(Number(element.dataset.segmentId)));
        selection.anchor = Number(hits[hits.length - 1].dataset.segmentId); syncSelection();
      });
    });
    $('nav-clips').addEventListener('click', () => app.openClips(null));
    $('new-collection-form').addEventListener('submit', async event => {
      event.preventDefault(); const input = $('new-collection-title'), title = input.value.trim(); if (!title) return input.focus();
      try { const created = await request('/api/collections', { method: 'POST', body: { title } }); input.value = ''; showToast(`Created “${created.title}”`); app.openClips(created.id); }
      catch (error) { showToast(`Couldn't create the collection: ${error.message}`, { error: true }); }
    });
  });
})();
