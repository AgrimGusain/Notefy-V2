window.AudioNotes = window.AudioNotes || {};
window.AudioNotes.refreshIcons = function () { if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.7 } }); };
window.AudioNotes.showView = function (viewId) {
  const app = window.AudioNotes;
  app.state.activeViewId = viewId;
  ['view-welcome', 'view-live', 'view-detail'].forEach(id => document.getElementById(id).classList.toggle('active', id === viewId));
  if (viewId === 'view-live') { app.state.activeLectureId = null; document.querySelectorAll('.lecture-folder').forEach(folder => folder.classList.remove('selected')); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

(function () {
  const sections = { workspace: 'recent', library: 'recent', 'all-notes': 'all', favorites: 'favorites' };
  const hashFor = section => section === 'favorites' ? '#favorites' : section === 'all' ? '#all-notes' : '#workspace';
  const applyHash = () => {
    const app = window.AudioNotes;
    if (!app?.setActiveFilter) return;
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
