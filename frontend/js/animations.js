window.AudioNotes = window.AudioNotes || {};
window.AudioNotes.refreshIcons = function () { if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.7 } }); };
// Note routes: #note/<id> and #note/<id>/cite/<C123|T123> (a RAG citation inside that note).
window.AudioNotes.parseNoteRoute = function (hash) {
  // #note/<id>/t/<start>-<end> is a recording range cited by synthesized notes.
  const match = /^#note\/(\d+)(?:\/cite\/([CT]\d+)|\/t\/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?))?$/.exec(hash || '');
  return match ? { id: Number(match[1]), citationId: match[2] || null, range: match[3] ? { start: Number(match[3]), end: Number(match[4]) } : null } : null;
};
// Clip routes: #clips (all clips) and #collection/<id>. Recall routes (#recall, #recall/<id>) are parsed in recall.js.
window.AudioNotes.parseClipsRoute = function (hash) {
  if (hash === '#clips') return { collectionId: null };
  const match = /^#collection\/(\d+)$/.exec(hash || '');
  return match ? { collectionId: Number(match[1]) } : null;
};
window.AudioNotes.sectionHash = section => section === 'favorites' ? '#favorites' : section === 'all' ? '#all-notes' : '#workspace';
window.AudioNotes.showView = function (viewId) {
  const app = window.AudioNotes;
  // Leaving the note viewer or clips must not leave their hash behind, or a refresh would reopen them.
  const hash = window.location.hash, staleNote = viewId !== 'view-detail' && app.parseNoteRoute(hash), staleClips = viewId !== 'view-clips' && viewId !== 'view-detail' && app.parseClipsRoute(hash);
  const staleRecall = viewId !== 'view-recall' && viewId !== 'view-detail' && app.parseRecallRoute?.(hash);
  if (staleNote && viewId !== 'view-clips' && viewId !== 'view-recall' || staleClips || staleRecall) history.pushState(null, '', app.sectionHash(app.state.filters?.section));
  app.state.activeViewId = viewId;
  ['view-welcome', 'view-live', 'view-detail', 'view-clips', 'view-recall'].forEach(id => document.getElementById(id).classList.toggle('active', id === viewId));
  if (viewId === 'view-live') { app.state.activeLectureId = null; document.querySelectorAll('.lecture-folder').forEach(folder => folder.classList.remove('selected')); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

(function () {
  const sections = { workspace: 'recent', library: 'recent', 'all-notes': 'all', favorites: 'favorites' };
  const hashFor = section => window.AudioNotes.sectionHash(section);
  const applyHash = () => {
    const app = window.AudioNotes;
    if (!app?.setActiveFilter) return;
    const route = app.parseNoteRoute(window.location.hash);
    if (route) { app.openNoteRoute(route.id, route.citationId, route.range); return; }
    const clipsRoute = app.parseClipsRoute(window.location.hash);
    if (clipsRoute) { app.openClips?.(clipsRoute.collectionId, { push: false }); return; }
    const recallRoute = app.parseRecallRoute?.(window.location.hash);
    if (recallRoute) { app.openRecall(recallRoute.sessionId, { push: false }); return; }
    const section = sections[window.location.hash.slice(1)] || 'recent';
    if (app.state.activeViewId === 'view-welcome' && app.state.filters.section === section) return;
    app.showView('view-welcome');
    app.setActiveFilter(section);
  };
  window.addEventListener('hashchange', applyHash);
  document.addEventListener('DOMContentLoaded', () => {
    ['recent', 'all', 'favorites'].forEach(section => document.getElementById(`nav-${section}`).addEventListener('click', () => {
      const hash = hashFor(section);
      if (window.location.hash !== hash) window.location.hash = hash;
    }));
    applyHash();
  });
})();

// Escape closes the topmost AI dialog (Ask your notes / AI Summarize). The editor's own Escape handling is left alone.
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || window.AudioNotes.state?.editor?.isEditing) return;
  const dialogs = document.querySelectorAll('.ai-modal');
  if (dialogs.length) { event.preventDefault(); dialogs[dialogs.length - 1].remove(); }
});
