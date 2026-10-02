(function () {
  // Recording playback for the note viewer, on the native HTML5 <audio> element (GET /api/lectures/:id/audio supports
  // Range requests, so seeking works without loading the whole file). Each player instance owns its own speed state and
  // only touches elements inside its root, so several players on one page never share or overwrite each other's speed.
  const app = window.AudioNotes = window.AudioNotes || {};
  const SPEEDS = [0.5, 1, 1.25, 1.5, 2, 2.5, 3];
  const DEFAULT_SPEED = 1;
  let instances = 0;

  const label = speed => `${speed}x`;
  const clock = seconds => {
    const total = Math.max(0, Math.floor(seconds || 0)), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = total % 60;
    return `${h ? `${h}:` : ''}${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  app.createAudioPlayer = function (root) {
    const id = `audio-speed-${++instances}`;
    const audio = root.querySelector('audio'), toggle = root.querySelector('.audio-play-toggle'), seek = root.querySelector('.audio-seek');
    const [current, duration] = root.querySelectorAll('time'), speedBox = root.querySelector('.audio-speed');
    const state = { speed: DEFAULT_SPEED, lectureId: null, pendingCue: null, scrubbing: false };

    // --- Speed: one compact menu button ("1x ▾") listing every speed ---
    speedBox.innerHTML = `<button type="button" class="speed-toggle" aria-haspopup="menu" aria-expanded="false" aria-controls="${id}" aria-label="Playback speed"></button>`
      + `<ul class="speed-menu" id="${id}" role="menu" aria-label="Playback speed" hidden>${SPEEDS.map(speed => `<li role="none"><button type="button" role="menuitemradio" class="speed-option" data-speed="${speed}" tabindex="-1">${label(speed)}</button></li>`).join('')}</ul>`;
    const speedToggle = speedBox.querySelector('.speed-toggle'), menu = speedBox.querySelector('.speed-menu'), options = [...menu.querySelectorAll('.speed-option')];

    // Takes effect immediately, and survives a new src: loading resets playbackRate to defaultPlaybackRate, so set both.
    function applySpeed() {
      audio.defaultPlaybackRate = state.speed;
      audio.playbackRate = state.speed;
      if ('preservesPitch' in audio) audio.preservesPitch = true;
    }
    function setSpeed(speed) {
      if (!SPEEDS.includes(speed)) return;
      state.speed = speed; applySpeed(); syncSpeedUI();
    }
    function syncSpeedUI() {
      speedToggle.innerHTML = `${label(state.speed)}<span aria-hidden="true">▾</span>`;
      speedToggle.setAttribute('aria-label', `Playback speed ${label(state.speed)}`);
      options.forEach(option => { const on = Number(option.dataset.speed) === state.speed; option.setAttribute('aria-checked', String(on)); option.classList.toggle('active', on); });
    }
    function openMenu(focusCurrent = true) {
      menu.hidden = false; speedToggle.setAttribute('aria-expanded', 'true'); speedBox.classList.add('is-open');
      if (focusCurrent) (options.find(option => option.classList.contains('active')) || options[0]).focus();
    }
    function closeMenu(returnFocus = false) {
      if (menu.hidden) return;
      menu.hidden = true; speedToggle.setAttribute('aria-expanded', 'false'); speedBox.classList.remove('is-open');
      if (returnFocus) speedToggle.focus();
    }
    speedToggle.addEventListener('click', () => (menu.hidden ? openMenu() : closeMenu()));
    speedToggle.addEventListener('keydown', event => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); openMenu(); } });
    menu.addEventListener('click', event => { const option = event.target.closest('.speed-option'); if (option) { setSpeed(Number(option.dataset.speed)); closeMenu(true); } });
    menu.addEventListener('keydown', event => {
      const index = options.indexOf(document.activeElement);
      const move = { ArrowDown: 1, ArrowUp: -1 }[event.key];
      if (move) { event.preventDefault(); options[(index + move + options.length) % options.length].focus(); }
      else if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); options[event.key === 'Home' ? 0 : options.length - 1].focus(); }
      else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(true); }
      else if (event.key === 'Tab') closeMenu();
    });
    document.addEventListener('click', event => { if (!speedBox.contains(event.target)) closeMenu(); });

    // --- Transport ---
    const setIcon = playing => {
      toggle.innerHTML = `<i data-lucide="${playing ? 'pause' : 'play'}"></i>`;
      toggle.setAttribute('aria-label', playing ? 'Pause audio' : 'Play audio');
      app.refreshIcons?.();
    };
    const syncTime = () => {
      current.textContent = clock(audio.currentTime);
      if (!state.scrubbing) seek.value = String(audio.currentTime || 0);
      seek.style.setProperty('--played', `${audio.duration ? (audio.currentTime / audio.duration) * 100 : 0}%`);
    };
    toggle.addEventListener('click', () => { if (audio.paused) audio.play().catch(() => app.showNotice?.("Couldn't play this recording.")); else audio.pause(); });
    seek.addEventListener('input', () => { state.scrubbing = true; current.textContent = clock(Number(seek.value)); });
    seek.addEventListener('change', () => { audio.currentTime = Number(seek.value); state.scrubbing = false; });
    audio.addEventListener('play', () => { applySpeed(); setIcon(true); root.classList.add('is-playing'); });
    audio.addEventListener('pause', () => { setIcon(false); root.classList.remove('is-playing'); });
    audio.addEventListener('ended', () => { setIcon(false); root.classList.remove('is-playing'); });
    audio.addEventListener('timeupdate', syncTime);
    audio.addEventListener('loadedmetadata', () => {
      applySpeed();
      seek.max = String(audio.duration || 0); duration.textContent = clock(audio.duration);
      if (state.pendingCue != null) { audio.currentTime = Math.min(state.pendingCue, audio.duration || state.pendingCue); state.pendingCue = null; }
      root.hidden = false; syncTime();
    });
    // Recordings made before audio was kept have no file: the player simply stays hidden.
    audio.addEventListener('error', () => { if (state.lectureId != null) { root.hidden = true; } });
    // Anything else changing the rate (devtools, media keys) is reflected rather than silently fought.
    audio.addEventListener('ratechange', () => { if (SPEEDS.includes(audio.playbackRate) && audio.playbackRate !== state.speed) { state.speed = audio.playbackRate; syncSpeedUI(); } });

    function unload() {
      audio.pause(); state.lectureId = null; state.pendingCue = null; root.hidden = true;
      if (audio.getAttribute('src')) { audio.removeAttribute('src'); audio.load(); }
    }

    const player = {
      root, audio,
      get speed() { return state.speed; },
      setSpeed,
      // Show a recording's audio. Reloading the same recording keeps position and play state; cueAt seeks (in seconds).
      load(lecture, { cueAt = null } = {}) {
        const playable = lecture && lecture.segments?.length && !String(lecture.session_id || '').startsWith('note-') && !['recording', 'transcribing'].includes(lecture.status);
        if (!playable) return unload();
        if (state.lectureId === lecture.id) { if (cueAt != null) player.cue(cueAt); return; }
        audio.pause(); state.lectureId = lecture.id; state.pendingCue = cueAt; root.hidden = true;
        seek.value = '0'; seek.max = '0'; current.textContent = clock(0); duration.textContent = clock(0); setIcon(false);
        audio.preload = 'metadata'; audio.src = `/api/lectures/${lecture.id}/audio`; applySpeed();
      },
      // Jump to a time without changing play state or speed.
      cue(seconds) {
        if (audio.readyState >= 1) { audio.currentTime = Math.max(0, seconds); syncTime(); } else state.pendingCue = seconds;
      },
      pause: () => audio.pause(),
      unload,
    };
    syncSpeedUI(); applySpeed();
    return player;
  };

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('audio-player');
    if (!root) return;
    const player = app.audioPlayer = app.createAudioPlayer(root);

    // Hook the note viewer: load the recording's audio, and cue it to a cited transcript range or clip.
    const renderLecture = app.renderLecture;
    app.renderLecture = function (data) {
      const pending = app.state.pendingCitation;
      const cueAt = pending && pending.source_type === 'transcript' && (pending.lecture_id ?? pending.document_id) === data.id && typeof pending.timestamp_start === 'number' ? pending.timestamp_start : null;
      renderLecture.call(this, data);
      player.load(data, { cueAt });
    };
    // Leaving the note viewer stops playback.
    const showView = app.showView;
    app.showView = function (viewId) { if (viewId !== 'view-detail') player.pause(); return showView.apply(this, arguments); };
  });
})();
