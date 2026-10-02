(function () {
  // Active Recall: one question at a time, written and graded only from the material the student chose.
  // The server owns grounding, grading and storage (backend/recall/); this file renders the study session.
  // Routes: #recall (set up a session, past sessions) and #recall/<id> (a session, or its results once ended).
  const app = window.AudioNotes = window.AudioNotes || {};
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
  const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Errors carry the server's message and, for state conflicts (409), its code.
  async function request(url, { method = 'GET', body } = {}) {
    const response = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) {
      const error = new Error(data.message || (typeof data.detail === 'string' ? data.detail : 'Request failed'));
      error.status = response.status; error.code = data.code; throw error;
    }
    return data;
  }

  const TYPES = {
    short_answer: { label: 'Short answer', hint: 'Recall a fact, term or definition' },
    conceptual: { label: 'Conceptual', hint: 'Explain why or how; compare ideas' },
    application: { label: 'Application', hint: 'Apply an idea to a new situation' },
  };
  const VERDICTS = {
    correct: { mark: '✓', label: 'Correct' },
    partially_correct: { mark: '◐', label: 'Partially correct' },
    incorrect: { mark: '✗', label: 'Incorrect' },
  };
  const SCOPES = [
    { value: 'all', label: 'All notes', hint: 'Everything in your archive' },
    { value: 'notes', label: 'Selected notes', hint: 'Pick one or more notes' },
    { value: 'folder', label: 'A folder', hint: 'Includes its subfolders' },
    { value: 'lecture', label: 'A lecture', hint: 'One recording' },
    { value: 'collection', label: 'A clip collection', hint: 'Only the saved clips' },
  ];

  // Settings for this browser tab. A key typed without "save" is kept in memory only and sent with each request.
  const ai = { model: '', base_url: '', api_key: '', hasSavedKey: false, loaded: false };
  const aiPayload = () => ({ provider: 'external', model: ai.model || undefined, base_url: ai.base_url || undefined, api_key: ai.api_key || undefined });
  async function loadAI() {
    if (ai.loaded) return;
    try { const settings = await app.loadAISettings(); ai.model = settings.model || ''; ai.base_url = settings.base_url || ''; ai.hasSavedKey = !!settings.has_api_key; ai.loaded = true; }
    catch (_) { /* The fields stay empty; the server reports what is missing. */ }
  }

  const view = { sessionId: null, session: null, busy: false, retrying: false, setup: { scope: 'all' }, material: null };

  // ===== Routing =====
  app.parseRecallRoute = function (hash) {
    if (hash === '#recall') return { sessionId: null };
    const match = /^#recall\/(\d+)$/.exec(hash || '');
    return match ? { sessionId: Number(match[1]) } : null;
  };

  app.openRecall = function (sessionId = null, { push = true } = {}) {
    return app.attemptNavigation(() => {
      const hash = sessionId ? `#recall/${sessionId}` : '#recall';
      if (push && location.hash !== hash) history.pushState(null, '', hash);
      view.sessionId = sessionId; view.retrying = false;
      app.showView('view-recall');
      document.querySelectorAll('.nav-link').forEach(link => link.classList.toggle('active', link.id === 'nav-recall'));
      renderHistory();
      return sessionId ? loadSession(sessionId) : renderSetup();
    });
  };

  // ===== Past sessions (sidebar) =====
  async function renderHistory() {
    const list = $('recall-history');
    try {
      const { sessions } = await request('/api/recall/sessions');
      list.innerHTML = `<button type="button" class="collection-link ${view.sessionId ? '' : 'active'}" data-session=""><span>+ New session</span></button>` + (sessions.length
        ? sessions.map(item => {
          const done = item.question_count - item.outcomes.pending, score = item.summary?.score ?? null;
          const status = item.status === 'ended' ? (score == null ? 'No answers' : `${score}% · ${plural(done, 'question')}`) : `In progress · ${done}/${item.target_count}`;
          return `<button type="button" class="collection-link ${view.sessionId === item.id ? 'active' : ''}" data-session="${item.id}"><span>${escape(item.title)}</span><small>${escape(app.smoothDate(item.created_at))} · ${escape(status)}</small></button>`;
        }).join('')
        : '<p class="collection-empty">No study sessions yet.</p>');
      list.querySelectorAll('[data-session]').forEach(button => button.onclick = () => app.openRecall(button.dataset.session ? Number(button.dataset.session) : null));
    } catch (error) { list.innerHTML = `<p class="collection-empty">${escape(error.message)}</p>`; }
  }

  // ===== Setting up a session =====
  async function loadMaterial() {
    const [lectures, folders, collections] = await Promise.all([request('/api/lectures?limit=1000'), request('/api/folders'), request('/api/collections')]);
    const byId = new Map(folders.folders.map(folder => [folder.id, folder]));
    const path = folder => { const names = []; for (let current = folder, guard = 0; current && guard < 20; current = byId.get(current.parent_id), guard++) names.unshift(current.name); return names.join(' / '); };
    const notes = lectures.lectures || [];
    view.material = {
      notes,
      recordings: notes.filter(item => !String(item.session_id || '').startsWith('note-')),
      folders: folders.folders.map(folder => ({ id: folder.id, label: path(folder) })).sort((a, b) => a.label.localeCompare(b.label)),
      collections: collections.collections.filter(item => item.clip_count),
    };
  }

  async function renderSetup() {
    $('recall-setup').hidden = false; $('recall-session').hidden = true;
    const form = $('recall-setup-form'), status = text => { $('recall-setup-status').textContent = text; };
    form.classList.add('is-loading');
    try { await Promise.all([view.material ? null : loadMaterial(), loadAI()]); }
    catch (error) { status(`Couldn't load your notes: ${error.message}`); return; }
    finally { form.classList.remove('is-loading'); }
    const counts = { all: view.material.notes.length, notes: view.material.notes.length, folder: view.material.folders.length, lecture: view.material.recordings.length, collection: view.material.collections.length };
    $('recall-scope-options').innerHTML = SCOPES.map(scope => `<label class="recall-option ${counts[scope.value] ? '' : 'is-empty'}"><input type="radio" name="recall-scope" value="${scope.value}" ${view.setup.scope === scope.value ? 'checked' : ''} ${counts[scope.value] ? '' : 'disabled'}><span><strong>${scope.label}</strong><small>${scope.hint}</small></span></label>`).join('');
    $('recall-scope-options').querySelectorAll('input').forEach(input => input.onchange = () => { view.setup.scope = input.value; renderScopeDetail(); });
    $('recall-model').value = ai.model; $('recall-url').value = ai.base_url; $('recall-key').value = ai.api_key;
    $('recall-ai-summary').textContent = ai.model ? `${ai.model}${ai.hasSavedKey || ai.api_key ? '' : ' · API key needed'}` : 'Not set up';
    $('recall-ai').open = !(ai.model && (ai.hasSavedKey || ai.api_key));
    $('recall-key-hint').textContent = ai.hasSavedKey ? 'A key is securely saved in your operating system credential vault. Enter a new key only to replace it.' : 'Without “save”, the key is kept only while this tab is open.';
    renderScopeDetail(); status('');
  }

  function renderScopeDetail() {
    const box = $('recall-scope-detail'), material = view.material, scope = view.setup.scope;
    const select = (items, label, empty) => items.length
      ? `<label class="recall-field">${label}<select id="recall-scope-select">${items.map(item => `<option value="${item.id}">${escape(item.label)}</option>`).join('')}</select></label>`
      : `<p class="recall-empty">${empty}</p>`;
    if (scope === 'all') box.innerHTML = `<p class="recall-scope-note">Questions are drawn from all ${plural(material.notes.length, 'note')} and recording${material.notes.length === 1 ? '' : 's'}, spread across them.</p>`;
    else if (scope === 'folder') box.innerHTML = select(material.folders, 'Folder', 'You have no folders yet.');
    else if (scope === 'lecture') box.innerHTML = select(material.recordings.map(item => ({ id: item.id, label: `${item.title || 'Untitled lecture'} · ${app.smoothDate(item.created_at)}` })), 'Lecture', 'You have no recordings yet.');
    else if (scope === 'collection') box.innerHTML = select(material.collections.map(item => ({ id: item.id, label: `${item.title} · ${plural(item.clip_count, 'clip')}` })), 'Clip collection', 'You have no collections with clips yet.');
    else {
      const chosen = view.setup.notes || (view.setup.notes = new Set());
      box.innerHTML = `<div class="recall-picker"><input id="recall-note-filter" type="search" placeholder="Filter notes…" aria-label="Filter notes" autocomplete="off"><p class="recall-picked" id="recall-picked" aria-live="polite"></p><ul id="recall-note-list"></ul></div>`;
      const list = $('recall-note-list'), picked = () => { $('recall-picked').textContent = chosen.size ? `${plural(chosen.size, 'note')} selected` : 'None selected'; };
      const draw = filter => {
        const needle = filter.trim().toLowerCase();
        list.innerHTML = material.notes.filter(item => !needle || (item.title || '').toLowerCase().includes(needle)).map(item => `<li><label><input type="checkbox" value="${item.id}" ${chosen.has(item.id) ? 'checked' : ''}><span>${escape(item.title || 'Untitled')}</span><small>${String(item.session_id || '').startsWith('note-') ? 'Note' : 'Recording'} · ${escape(app.smoothDate(item.created_at))}</small></label></li>`).join('') || '<li class="recall-empty">No notes match.</li>';
        list.querySelectorAll('input').forEach(input => input.onchange = () => { const id = Number(input.value); if (input.checked) chosen.add(id); else chosen.delete(id); picked(); });
      };
      $('recall-note-filter').oninput = event => draw(event.target.value); draw(''); picked();
    }
  }

  async function startSession(event) {
    event.preventDefault();
    if (view.busy) return;
    const status = text => { $('recall-setup-status').textContent = text; };
    const scope = view.setup.scope, types = [...document.querySelectorAll('#recall-types input:checked')].map(input => input.value);
    let ids = [];
    if (scope === 'notes') { ids = [...(view.setup.notes || [])]; if (!ids.length) return status('Select at least one note.'); }
    else if (scope !== 'all') { const select = $('recall-scope-select'); if (!select) return status('There is nothing to choose for that option yet.'); ids = [Number(select.value)]; }
    if (!types.length) return status('Choose at least one question type.');
    ai.model = $('recall-model').value.trim(); ai.base_url = $('recall-url').value.trim(); ai.api_key = $('recall-key').value.trim();
    if (!ai.model) { $('recall-ai').open = true; return status('Enter the model to use.'); }
    if (!ai.api_key && !ai.hasSavedKey) { $('recall-ai').open = true; return status('An API key is required to write and grade questions.'); }
    view.busy = true; $('recall-start').disabled = true; status('Preparing your session…');
    try {
      if ($('recall-save-settings').checked) { const saved = await app.saveAISettings({ model: ai.model, base_url: ai.base_url, api_key: ai.api_key || null }); ai.hasSavedKey = !!saved.has_api_key; ai.api_key = ''; }
      const count = Number(document.querySelector('#recall-length input:checked').value);
      const { session } = await request('/api/recall/sessions', { method: 'POST', body: { scope_type: scope, scope_ids: ids, question_types: types, question_count: count, model: ai.model } });
      status(''); view.busy = false;
      app.openRecall(session.id);  // a session with no questions yet continues straight to its first question
    } catch (error) { status(error.message); }
    finally { view.busy = false; $('recall-start').disabled = false; }
  }

  // ===== A session =====
  async function loadSession(id) {
    $('recall-setup').hidden = true; $('recall-session').hidden = false;
    if (view.session?.id !== id) { $('recall-thread').innerHTML = '<li class="skeleton-card" aria-hidden="true"></li>'; $('recall-composer').hidden = true; $('recall-results').hidden = true; }
    try {
      const { session } = await request(`/api/recall/sessions/${id}`);
      if (view.sessionId !== id) return;
      render(session);
      // A fresh session (or one reopened after its last question was skipped) continues straight to a question.
      if (session.status === 'active' && !session.progress.complete && !session.questions.some(question => question.outcome === 'pending') && (!session.questions.length || session.questions[session.questions.length - 1].outcome === 'skipped')) nextQuestion();
    } catch (error) {
      if (error.status === 404) { app.showNotice('That study session no longer exists.'); history.replaceState(null, '', '#recall'); view.sessionId = null; renderHistory(); return renderSetup(); }
      $('recall-thread').innerHTML = `<li class="clips-empty"><h2>Couldn't load this session.</h2><p>${escape(error.message)}</p></li>`;
    }
  }

  function render(session) {
    view.session = session;
    const progress = session.progress, ended = session.status === 'ended', current = session.questions[session.questions.length - 1];
    $('recall-eyebrow').textContent = session.title;
    $('recall-heading').innerHTML = ended ? 'Session <em>results.</em>' : current ? `Question ${current.position} <em>of ${session.target_count}.</em>` : 'Getting <em>ready.</em>';
    const tally = session.outcomes;
    $('recall-tally').innerHTML = [['correct', '✓'], ['partially_correct', '◐'], ['incorrect', '✗'], ['skipped', '↷']].map(([name, mark]) => `<span class="recall-tally-${name}" title="${name === 'skipped' ? 'Skipped' : VERDICTS[name].label}">${mark} ${tally[name]}</span>`).join('') + (progress.score == null ? '' : `<strong>${progress.score}%</strong>`);
    $('recall-progress').innerHTML = Array.from({ length: session.target_count }, (_, index) => { const question = session.questions[index]; return `<span class="${question ? `is-${question.outcome}` : ''}${question === current && !ended ? ' is-current' : ''}"></span>`; }).join('');
    $('recall-progress').setAttribute('aria-label', `${progress.answered} of ${session.target_count} questions done`);
    $('recall-end').hidden = ended; $('recall-settings').hidden = ended;
    const thread = $('recall-thread');
    const before = thread.querySelectorAll('.recall-msg').length;
    thread.innerHTML = session.questions.map(question => renderQuestion(question, session)).join('');
    thread.querySelectorAll('.recall-msg').forEach((element, index) => element.classList.toggle('is-new', index >= before && before > 0));
    wireCitations(thread, session);
    renderComposer(session);
    renderResults(session);
    app.refreshIcons();
  }

  function citationChips(citations, label = 'Source') {
    if (!citations.length) return '';
    return `<p class="recall-sources"><span>${label}</span>${citations.map(citation => `<button type="button" class="recall-cite ${citation.missing || citation.source_deleted ? 'is-missing' : ''}" data-cite="${escape(citation.citation_id)}" title="${citation.missing ? 'This passage has changed since the question was written' : 'Open this passage'}">${citation.source_type === 'transcript' || citation.source_type === 'clip' ? '🎧' : '📄'} ${escape(citation.label)}</button>`).join('')}</p>`;
  }

  function renderQuestion(question, session) {
    const type = TYPES[question.question_type] || { label: question.question_type };
    let html = `<li class="recall-msg is-ai"><p class="recall-kicker">Q${question.position} · ${escape(type.label)}${question.topic ? ` · ${escape(question.topic)}` : ''}</p><p class="recall-question">${escape(question.question)}</p>${citationChips(question.citations, 'From')}</li>`;
    const byId = new Map(question.citations.map(citation => [citation.citation_id, citation]));
    question.attempts.forEach((attempt, index) => {
      const verdict = VERDICTS[attempt.verdict];
      html += `<li class="recall-msg is-user"><p class="recall-kicker">${attempt.after_reveal ? 'Practice answer · not scored' : index ? `Retry ${index}` : 'Your answer'}</p><p class="recall-answer">${escape(attempt.answer)}</p></li>`;
      const list = (title, items, kind) => items.length ? `<div class="recall-points is-${kind}"><p>${title}</p><ul>${items.map(item => `<li>${escape(item)}</li>`).join('')}</ul></div>` : '';
      html += `<li class="recall-msg is-feedback verdict-${attempt.verdict}"><p class="recall-verdict"><span>${verdict.mark}</span>${verdict.label}<small>${Math.round(attempt.score * 100)}%</small></p><p class="recall-feedback">${escape(attempt.feedback)}</p>${list('You covered', attempt.correct_points, 'covered')}${list('You missed', attempt.missing_points, 'missed')}${list('Check this', attempt.misconceptions, 'wrong')}${citationChips(attempt.source_refs.map(ref => byId.get(ref)).filter(Boolean), 'See')}</li>`;
    });
    if (question.revealed || session.status === 'ended') {
      if (question.expected_points) html += `<li class="recall-msg is-explanation"><p class="recall-kicker">Explanation${question.revealed ? '' : ' · answer key'}</p><ul>${question.expected_points.map(point => `<li>${escape(point)}</li>`).join('')}</ul>${question.explanation ? `<p>${escape(question.explanation)}</p>` : ''}${citationChips(question.citations)}</li>`;
    }
    if (question.skipped && !question.attempts.length) html += '<li class="recall-msg is-system">Skipped</li>';
    return html;
  }

  function wireCitations(container, session) {
    const all = new Map([...session.questions.flatMap(question => question.citations), ...(session.summary?.review || []).map(item => item.citation).filter(Boolean)].map(citation => [citation.citation_id, citation]));
    container.querySelectorAll('[data-cite]').forEach(button => button.onclick = () => openSource(all.get(button.dataset.cite)));
  }

  function openSource(citation) {
    if (!citation || citation.missing) return app.showNotice('This passage has changed or been deleted since the question was written.');
    if (citation.source_type === 'clip') {
      if (!citation.href) return app.showNotice('The recording this clip came from has been deleted.');
      return app.attemptNavigation(() => { location.hash = citation.href; });
    }
    app.openCitation(citation);
  }

  // The composer only ever answers the current question: this is a study drill, not an open chat.
  function renderComposer(session) {
    const composer = $('recall-composer'), current = session.questions[session.questions.length - 1];
    composer.hidden = session.status === 'ended' || !current;
    if (composer.hidden) return;
    const answered = current.attempts.length > 0, open = current.outcome === 'pending' && !answered, practice = view.retrying || open;
    const finished = session.progress.complete, nextLabel = finished ? 'See results →' : 'Next question →';
    $('recall-answer-field').hidden = !practice;
    const answer = $('recall-answer');
    answer.placeholder = current.revealed ? 'Try answering in your own words (practice, not scored)…' : view.retrying ? 'Try again…' : 'Type your answer in your own words…';
    const buttons = [];
    if (practice) buttons.push(`<button type="button" class="primary" data-act="submit">${view.retrying ? 'Submit retry' : 'Submit answer'}</button>`);
    if (!current.revealed) buttons.push('<button type="button" data-act="reveal">Reveal explanation</button>');
    if (open) buttons.push('<button type="button" data-act="skip">Skip</button>');
    if (!practice && (answered || current.revealed)) buttons.unshift(`<button type="button" data-act="retry">${current.revealed ? 'Practice answer' : 'Retry'}</button>`);
    if (!open) buttons.push(`<button type="button" class="${practice ? '' : 'primary'}" data-act="next">${nextLabel}</button>`);
    $('recall-actions').innerHTML = buttons.join('');
    $('recall-actions').querySelectorAll('[data-act]').forEach(button => button.onclick = () => ACTIONS[button.dataset.act]());
    $('recall-hint').textContent = practice ? 'Ctrl + Enter to submit' : '';
    if (practice && !view.busy) requestAnimationFrame(() => answer.focus({ preventScroll: true }));
    scrollToEnd();
  }

  function scrollToEnd() {
    requestAnimationFrame(() => { const composer = $('recall-composer'); if (!composer.hidden) composer.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'end' }); });
  }

  function setBusy(text) {
    view.busy = !!text;
    $('recall-composer').classList.toggle('is-busy', view.busy);
    $('recall-actions').querySelectorAll('button').forEach(button => { button.disabled = view.busy; });
    $('recall-answer').disabled = view.busy; $('recall-end').disabled = view.busy;
    const thinking = $('recall-thinking');
    thinking.hidden = !text; thinking.querySelector('span').textContent = text || '';
    if (text) scrollToEnd();
  }

  const status = text => { $('recall-status').textContent = text || ''; };

  async function act(label, run) {
    if (view.busy) return;
    status(''); setBusy(label);
    try { const { session } = await run(); view.retrying = false; setBusy(''); render(session); renderHistory(); return session; }
    catch (error) {
      setBusy('');
      if (error.code === 'finished') return endSession();
      if (error.code === 'ended' || error.code === 'exhausted') { status(error.message); return loadSession(view.sessionId); }
      status(/api key/i.test(error.message) ? `${error.message} Open “AI settings” to add it.` : error.message);
      if (view.session) renderComposer(view.session);
    }
  }

  function nextQuestion() {
    if (!view.sessionId) return;
    const id = view.sessionId;
    return act('Writing a question from your notes…', () => request(`/api/recall/sessions/${id}/next`, { method: 'POST', body: aiPayload() }));
  }

  const ACTIONS = {
    submit() {
      const question = view.session.questions[view.session.questions.length - 1], answer = $('recall-answer').value.trim();
      if (!answer) { status('Write an answer first — or skip the question.'); return $('recall-answer').focus(); }
      return act('Checking your answer against the notes…', () => request(`/api/recall/questions/${question.id}/answer`, { method: 'POST', body: { answer, ...aiPayload() } })).then(session => { if (session) $('recall-answer').value = ''; });
    },
    retry() { view.retrying = true; status(''); renderComposer(view.session); },
    reveal() { const question = view.session.questions[view.session.questions.length - 1]; return act('Opening the explanation…', () => request(`/api/recall/questions/${question.id}/reveal`, { method: 'POST' })); },
    async skip() {
      const question = view.session.questions[view.session.questions.length - 1];
      const session = await act('Skipping…', () => request(`/api/recall/questions/${question.id}/skip`, { method: 'POST' }));
      if (session) { $('recall-answer').value = ''; session.progress.complete ? endSession() : nextQuestion(); }
    },
    next() { $('recall-answer').value = ''; return view.session.progress.complete ? endSession() : nextQuestion(); },
  };

  async function endSession() {
    const id = view.sessionId;
    const session = await act('Adding up your results…', () => request(`/api/recall/sessions/${id}/end`, { method: 'POST' }));
    if (session) document.querySelector('.recall-session-head').scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
  }

  // ===== Results =====
  function renderResults(session) {
    const box = $('recall-results'), summary = session.summary;
    box.hidden = session.status !== 'ended' || !summary;
    $('recall-thread').classList.toggle('is-review', !box.hidden);
    if (box.hidden) return;
    if (!summary.questions) {
      box.innerHTML = `<div class="clips-empty"><h2>No questions answered.</h2><p>This session ended before any question was answered.</p></div>${resultActions(session, false)}`;
      return wireResults(box, session);
    }
    const stat = (value, label, kind = '') => `<div class="recall-stat ${kind}"><strong>${value}</strong><span>${label}</span></div>`;
    const weak = summary.weak_topics.map(topic => `<li class="recall-topic"><div class="recall-topic-head"><h3>${escape(topic.topic)}</h3><span>${topic.score}%</span></div><div class="recall-meter" aria-hidden="true"><i style="width:${Math.max(topic.score, 3)}%"></i></div><p class="recall-topic-meta">${topic.questions.map(item => `Q${item.position} ${item.outcome === 'skipped' ? 'skipped' : item.outcome === 'revealed' ? 'revealed' : VERDICTS[item.outcome]?.mark || ''}`).join(' · ')}</p>${topic.missing_points.length ? `<ul>${topic.missing_points.map(point => `<li>${escape(point)}</li>`).join('')}</ul>` : ''}</li>`).join('');
    const review = summary.review.map(item => `<li><button type="button" class="recall-cite" data-cite="${escape(item.citation?.citation_id || item.ref)}">${item.citation?.source_type === 'document' ? '📄' : '🎧'} ${escape(item.label)}</button><small>${escape(item.topics.join(' · '))}</small></li>`).join('');
    box.innerHTML = `<div class="recall-stats">${stat(`${summary.score}%`, 'Score', 'is-score')}${stat(summary.attempted, 'Attempted')}${stat(summary.correct, 'Correct', 'is-correct')}${stat(summary.partially_correct, 'Partial', 'is-partial')}${stat(summary.incorrect, 'Incorrect', 'is-incorrect')}${summary.skipped + summary.revealed ? stat(summary.skipped + summary.revealed, 'Skipped or revealed', 'is-muted') : ''}</div>
      ${summary.weak_topics.length ? `<section class="recall-section"><h2>Weak topics</h2><ol class="recall-topics">${weak}</ol></section>` : '<section class="recall-section"><h2>No weak topics.</h2><p class="recall-scope-note">Every question was answered correctly.</p></section>'}
      ${review ? `<section class="recall-section"><h2>Review these passages</h2><p class="recall-scope-note">The exact parts of your notes behind the questions you missed, most-missed first.</p><ul class="recall-review">${review}</ul></section>` : ''}
      ${summary.strong_topics.length ? `<section class="recall-section"><h2>Solid</h2><p class="recall-strong">${summary.strong_topics.map(topic => `<span>✓ ${escape(topic)}</span>`).join('')}</p></section>` : ''}
      ${resultActions(session, summary.review.some(item => item.citation && !item.citation.missing))}
      <h2 class="recall-thread-title">All questions</h2>`;
    wireResults(box, session);
  }

  const resultActions = (session, canRetryWeak) => `<div class="recall-result-actions"><button type="button" class="paper-button danger" data-result="delete">Delete session</button>${canRetryWeak ? '<button type="button" class="paper-button" data-result="weak">Study weak topics again</button>' : ''}<button type="button" class="capture-stamp" data-result="new">New session</button></div>`;

  function wireResults(box, session) {
    wireCitations(box, session);
    box.querySelectorAll('[data-result]').forEach(button => button.onclick = async () => {
      const action = button.dataset.result;
      if (action === 'new') return app.openRecall(null);
      if (action === 'delete') {
        if (!await confirmDialog('Delete this study session?', 'Its questions, your answers and the results will be removed. Your notes are not affected.', 'Delete session')) return;
        try { await request(`/api/recall/sessions/${session.id}`, { method: 'DELETE' }); app.showNotice('Study session deleted.'); app.openRecall(null); }
        catch (error) { status(error.message); }
        return;
      }
      // Study weak topics again: a new session over just the notes behind the missed questions.
      const ids = [...new Set(session.summary.review.map(item => item.citation).filter(citation => citation && !citation.missing).map(citation => citation.document_id ?? citation.lecture_id).filter(id => id != null))];
      try {
        const { session: created } = await request('/api/recall/sessions', { method: 'POST', body: { scope_type: 'notes', scope_ids: ids, question_types: session.question_types, question_count: Math.min(Math.max(ids.length * 2, 3), 10), model: ai.model || session.model } });
        app.openRecall(created.id);
      } catch (error) { status(error.message); }
    });
  }

  function confirmDialog(title, message, confirmLabel) {
    return new Promise(resolve => {
      const modal = document.createElement('div'); modal.className = 'editor-modal';
      modal.innerHTML = '<div class="editor-dialog" role="alertdialog" aria-modal="true" aria-labelledby="recall-confirm-title"><h2 id="recall-confirm-title"></h2><p></p><div class="dialog-actions"><button class="editor-button" type="button">Cancel</button><button class="editor-button save" type="button"></button></div></div>';
      modal.querySelector('h2').textContent = title; modal.querySelector('p').textContent = message; const [cancel, confirm] = modal.querySelectorAll('button'); confirm.textContent = confirmLabel;
      const close = value => { modal.remove(); resolve(value); };
      cancel.onclick = () => close(false); confirm.onclick = () => close(true);
      modal.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); close(false); } });
      document.body.appendChild(modal); cancel.focus();
    });
  }

  // AI settings for a session in progress (e.g. after a reload when the key was not saved).
  async function openSettings() {
    await loadAI();
    const modal = document.createElement('div'); modal.className = 'ai-modal';
    modal.innerHTML = `<section class="ai-panel" role="dialog" aria-modal="true" aria-labelledby="recall-ai-title"><h2 id="recall-ai-title">AI settings</h2><p>Questions and grading use this OpenAI-compatible model. A local Ollama URL works too.</p><div class="ai-grid"><label>Model<input id="recall-modal-model" placeholder="openai/gpt-oss-120b"></label><label>Base URL<input id="recall-modal-url" placeholder="https://api.groq.com/openai/v1"></label></div><label>API Key<input id="recall-modal-key" type="password" autocomplete="new-password" placeholder="${ai.hasSavedKey ? 'Saved securely on this computer' : 'Required'}"></label><label class="ai-save-key"><input id="recall-modal-save" type="checkbox"> Save model, URL, and API key securely on this computer</label><div class="ai-status" id="recall-modal-status" aria-live="polite"></div><div class="ai-actions"><button type="button" id="recall-modal-cancel">Cancel</button><button type="button" class="primary" id="recall-modal-apply">Use these settings</button></div></section>`;
    document.body.appendChild(modal);
    const field = id => modal.querySelector(`#${id}`);
    field('recall-modal-model').value = ai.model; field('recall-modal-url').value = ai.base_url; field('recall-modal-key').value = ai.api_key;
    field('recall-modal-cancel').onclick = () => modal.remove();
    field('recall-modal-apply').onclick = async () => {
      ai.model = field('recall-modal-model').value.trim(); ai.base_url = field('recall-modal-url').value.trim(); ai.api_key = field('recall-modal-key').value.trim();
      try { if (field('recall-modal-save').checked) { const saved = await app.saveAISettings({ model: ai.model, base_url: ai.base_url, api_key: ai.api_key || null }); ai.hasSavedKey = !!saved.has_api_key; ai.api_key = ''; } modal.remove(); status('Settings updated.'); }
      catch (error) { field('recall-modal-status').textContent = error.message; }
    };
    field('recall-modal-model').focus();
  }

  // ===== Wiring =====
  document.addEventListener('DOMContentLoaded', () => {
    $('recall-types').innerHTML = Object.entries(TYPES).map(([value, type]) => `<label class="recall-option"><input type="checkbox" value="${value}" checked><span><strong>${type.label}</strong><small>${type.hint}</small></span></label>`).join('');
    $('recall-length').innerHTML = [5, 8, 10, 15].map(count => `<label class="recall-chip"><input type="radio" name="recall-length" value="${count}" ${count === 8 ? 'checked' : ''}><span>${count}</span></label>`).join('');
    $('recall-setup-form').addEventListener('submit', startSession);
    $('recall-end').onclick = () => { if (!view.busy) endSession(); };
    $('recall-settings').onclick = openSettings;
    $('recall-answer').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); ACTIONS.submit(); } });
    $('nav-recall').addEventListener('click', () => { if (location.hash !== '#recall') app.openRecall(null); });
  });
})();
