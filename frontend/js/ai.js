(function () {
  const app = window.AudioNotes = window.AudioNotes || {};
  const DEFAULT_PROMPT = `Create clear, structured lecture notes from the transcript.

Include:
- Overview
- Key concepts
- Important details
- Definitions
- Formulas when present
- Examples when present
- Exam-relevant points when appropriate

Use Markdown.

Do not invent information that is not supported by the transcript.

Preserve important technical terminology, numbers, definitions and relationships between concepts.`;
  const PRESETS = {
    'Lecture Notes': DEFAULT_PROMPT,
    'Exam Revision': 'Create exam-oriented notes. Prioritize definitions, formulas, important concepts, comparisons, common mistakes and likely exam-relevant points.',
    Short: 'Create a concise Markdown summary with only the most important concepts and facts.',
    Detailed: 'Create detailed, structured Markdown lecture notes. Include all supported concepts, definitions, examples, formulas and relationships.'
  };
  let running = false, generated = null;
  const style = document.createElement('style');
  style.textContent = `.ai-modal{position:fixed;inset:0;z-index:40;background:rgba(37,34,29,.42);display:grid;place-items:center;padding:18px}.ai-panel{width:min(670px,100%);max-height:90vh;overflow:auto;background:var(--paper-light);border:1px solid var(--line);box-shadow:7px 8px 0 rgba(37,34,29,.22);padding:25px}.ai-panel h2{font:600 28px var(--serif);margin:0 0 5px}.ai-panel p{color:var(--muted);line-height:1.5}.ai-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.ai-panel label{display:block;font:10px var(--mono);text-transform:uppercase;letter-spacing:.08em;margin-top:16px}.ai-panel input,.ai-panel select,.ai-panel textarea{box-sizing:border-box;width:100%;margin-top:6px;padding:9px;background:#fffaf0;border:1px solid var(--line);font:13px var(--mono)}.ai-panel textarea{min-height:175px;resize:vertical}.ai-presets{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.ai-presets button,.ai-actions button{border:1px solid var(--line);background:var(--paper);padding:8px 10px;cursor:pointer;font:10px var(--mono);text-transform:uppercase;letter-spacing:.05em}.ai-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}.ai-actions .primary{background:var(--orange);color:#fff7ea;border-color:var(--orange-dark)}.ai-status{min-height:20px;margin-top:14px;font:11px var(--mono);color:var(--orange-dark)}.ai-preview{margin-top:18px;border-top:2px solid var(--ink);padding-top:16px}.ai-preview[hidden]{display:none}.ai-warning{border-left:3px solid var(--mustard);padding-left:10px}`;
  document.head.appendChild(style);

  function openModal() {
    const lecture = app.state.activeLecture;
    if (!lecture || running) return;
    if (lecture.is_manually_edited && !window.confirm('This lecture contains manual edits. Generating new AI notes will not replace them until you explicitly accept the new version. Continue?')) return;
    const modal = document.createElement('div'); modal.className = 'ai-modal';
    const panel = document.createElement('section'); panel.className = 'ai-panel'; panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.innerHTML = `<h2>✦ AI Summarize</h2><p>Generated notes stay a preview until you accept them.</p><label>Provider<select id="ai-provider"><option value="external">External LLM</option><option value="local">Local LLM</option></select></label><div id="ai-external"><div class="ai-grid"><label>Model<input id="ai-model" placeholder="gpt-4o-mini"></label><label>Base URL <small>(optional)</small><input id="ai-url" placeholder="https://api.openai.com/v1"></label></div><label>API Key<input id="ai-key" type="password" autocomplete="off" placeholder="Provided for this request only"></label></div><label>Prompt<textarea id="ai-prompt"></textarea></label><div class="ai-presets" id="ai-presets"></div><label><input id="ai-fallback" type="checkbox" checked> Automatically fall back to local AI</label><div class="ai-status" id="ai-status" aria-live="polite"></div><div class="ai-actions"><button id="ai-cancel">Cancel</button><button id="ai-test">Test Connection</button><button class="primary" id="ai-generate">Generate Notes ✦</button></div><div class="ai-preview" id="ai-preview" hidden><h2>✦ Generated Notes</h2><div class="markdown-body" id="ai-result"></div><p id="ai-source"></p><div class="ai-actions"><button id="ai-regenerate">Regenerate</button><button id="ai-edit">Edit</button><button class="primary" id="ai-accept">Accept</button></div></div>`;
    modal.appendChild(panel); document.body.appendChild(modal);
    const prompt = panel.querySelector('#ai-prompt'); prompt.value = localStorage.getItem('audio-notes-last-prompt') || DEFAULT_PROMPT;
    Object.entries(PRESETS).forEach(([name, value]) => { const button = document.createElement('button'); button.type = 'button'; button.textContent = name; button.onclick = () => { prompt.value = value; }; panel.querySelector('#ai-presets').appendChild(button); });
    const provider = panel.querySelector('#ai-provider'), external = panel.querySelector('#ai-external');
    provider.onchange = () => { external.hidden = provider.value === 'local'; panel.querySelector('#ai-test').hidden = provider.value === 'local'; };
    const status = text => panel.querySelector('#ai-status').textContent = text;
    const request = async (testOnly) => {
      if (running) return; const isExternal = provider.value === 'external';
      if (isExternal && !panel.querySelector('#ai-key').value.trim()) { status('An API key is required for external AI.'); return; }
      running = true; panel.querySelectorAll('button').forEach(b => b.disabled = true); status(testOnly ? 'Testing external AI connection…' : (isExternal ? 'Generating with external AI…' : 'Generating with local AI…'));
      const payload = { lecture_id: lecture.id, provider: provider.value, api_key: panel.querySelector('#ai-key').value, model: panel.querySelector('#ai-model').value, base_url: panel.querySelector('#ai-url').value, prompt: prompt.value, fallback_to_local: panel.querySelector('#ai-fallback').checked };
      try { const response = await fetch(testOnly ? '/api/ai/test' : '/api/ai/summarize', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.message || 'AI request failed.');
        if (testOnly) status('External AI connection verified.'); else { generated = data; localStorage.setItem('audio-notes-last-prompt', prompt.value); panel.querySelector('#ai-result').innerHTML = app.safeMarkdownToHTML(data.summary_markdown); panel.querySelector('#ai-source').textContent = data.source === 'local_fallback' ? `External AI unavailable. Using local AI instead: ${data.fallback_reason}` : `Generated with ${data.source === 'external' ? 'external AI' : 'local AI'}.`; panel.querySelector('#ai-preview').hidden = false; status('Preview ready — accept to replace the saved notes.'); }
      } catch (error) { status(error.message); } finally { running = false; panel.querySelectorAll('button').forEach(b => b.disabled = false); }
    };
    panel.querySelector('#ai-cancel').onclick = () => modal.remove(); panel.querySelector('#ai-test').onclick = () => request(true); panel.querySelector('#ai-generate').onclick = () => request(false); panel.querySelector('#ai-regenerate').onclick = () => request(false);
    panel.querySelector('#ai-accept').onclick = async () => { if (!generated || running) return; running = true; status('Saving accepted notes…'); try { const res = await fetch(`/api/lectures/${lecture.id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({summary_markdown:generated.summary_markdown,is_manually_edited:false})}); if (!res.ok) throw Error('Could not save generated notes.'); const saved = await res.json(); app.renderLecture(saved); app.fetchLectures({preserveSearch:true}); modal.remove(); } catch (error) { status(error.message); } finally { running = false; } };
    panel.querySelector('#ai-edit').onclick = () => { if (!generated) return; modal.remove(); app.enterEditMode(); app.state.editor.draft.summary_markdown = generated.summary_markdown; app.renderEditor(); };
    panel.querySelector('#ai-cancel').focus();
  }
  document.addEventListener('DOMContentLoaded', () => { const actions = document.querySelector('.document-actions > div'); if (!actions) return; const button = document.createElement('button'); button.className = 'edit-button'; button.type = 'button'; button.textContent = '✦ AI Summarize'; button.addEventListener('click', openModal); actions.insertBefore(button, document.getElementById('btn-edit-document')); });
})();
