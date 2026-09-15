window.AudioNotes = window.AudioNotes || {};
window.AudioNotes.refreshIcons = function () { if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.7 } }); };
window.AudioNotes.showView = function (viewId) {
  const app = window.AudioNotes;
  app.state.activeViewId = viewId;
  ['view-welcome', 'view-live', 'view-detail'].forEach(id => document.getElementById(id).classList.toggle('active', id === viewId));
  if (viewId === 'view-live') { app.state.activeLectureId = null; document.querySelectorAll('.lecture-folder').forEach(folder => folder.classList.remove('selected')); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
};
