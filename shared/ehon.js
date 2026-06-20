/* baby-ehon 共通エンジン
 *
 * 各ブックの index.html で window.BOOK_CONFIG を定義してから読み込む:
 *   window.BOOK_CONFIG = {
 *     scenes: {
 *       <scene-key>: {
 *         sfxs:   ['ぶーん', ...],   // タップで出るオノマトペ
 *         talks:  ['__NAME__、〜'],  // 語りかけ吹き出し
 *         colors: ['pink','yellow','white'],
 *         notes:  [330, 415, 494, 660],
 *       },
 *       ...
 *     }
 *   };
 */
(() => {
  const CONFIG = window.BOOK_CONFIG || { scenes: {} };
  const SCENES = CONFIG.scenes || {};

  // ─── 個人名展開（shared/baby.js / window.BABY を参照） ──
  const BABY = window.BABY || { name: 'あかちゃん', honorific: '' };
  const NAME_FULL = `${BABY.name || 'あかちゃん'}${BABY.honorific || ''}`;
  const expandName = (s) => (typeof s === 'string' ? s.split('__NAME__').join(NAME_FULL) : s);

  if (document.title) document.title = expandName(document.title);

  const textWalker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let textNode;
  while ((textNode = textWalker.nextNode())) {
    if (textNode.nodeValue && textNode.nodeValue.includes('__NAME__')) {
      textNode.nodeValue = expandName(textNode.nodeValue);
    }
  }
  document.querySelectorAll('[aria-label*="__NAME__"]').forEach((el) => {
    el.setAttribute('aria-label', expandName(el.getAttribute('aria-label')));
  });

  const pages = Array.from(document.querySelectorAll('.page'));
  const fxLayer = document.getElementById('fx-layer');
  const dotsEl = document.getElementById('dots');
  const prevBtn = document.querySelector('.nav-btn--prev');
  const nextBtn = document.querySelector('.nav-btn--next');

  const AUTO_ADVANCE_MS = 12000;
  const AUTO_SFX_MS = 3500;
  const AUTO_TALK_MS = 5200;

  const KEY_WORDS = [
    'わぁ！', 'やった！', 'すごい！', 'もう いっかい！', 'たのしー！',
    'いえーい！', 'ぱちぱち！', '__NAME__ー！', 'にこにこ', 'おー！',
    'ぱーん！', 'どきどき', 'うふふ', 'きゃー！', 'ぴょん！',
    'はーい！', 'ぽーん', 'ふふっ', 'よーし！', 'えへへ',
  ];
  const KEY_EMOJIS = ['🎉', '⭐', '✨', '🌈', '💖', '🎈', '🎀', '🍭', '🐶', '🐱', '🐰', '🦊', '🐻', '🌸', '🍀'];

  let current = 0;
  let autoTimer = null;
  let sfxTimer = null;
  let talkTimer = null;
  const lastSfxIndex = {};
  const lastTalkIndex = {};

  // ─── Dots ──────────────────────────────────────────────
  pages.forEach((_, i) => {
    const dot = document.createElement('span');
    dot.className = 'dot';
    if (i === 0) dot.classList.add('is-active');
    dotsEl.appendChild(dot);
  });
  const dots = Array.from(dotsEl.children);

  function sceneOf(index) {
    return pages[index].dataset.scene;
  }
  function cfg(scene) {
    return SCENES[scene] || {};
  }

  // ─── Page transitions ─────────────────────────────────
  function goTo(index) {
    const next = (index + pages.length) % pages.length;
    pages[current].classList.remove('is-active');
    dots[current].classList.remove('is-active');
    current = next;
    pages[current].classList.add('is-active');
    dots[current].classList.add('is-active');
    restartTimers();
    setTimeout(() => emitSfxAt(window.innerWidth / 2, window.innerHeight / 2.4), 300);
    setTimeout(() => emitTalk(), 700);
    popCam();
    resetDraggables();
  }

  function restartTimers() {
    clearInterval(autoTimer);
    clearInterval(sfxTimer);
    clearInterval(talkTimer);
    autoTimer = setInterval(() => goTo(current + 1), AUTO_ADVANCE_MS);
    sfxTimer  = setInterval(() => {
      const x = (0.2 + Math.random() * 0.6) * window.innerWidth;
      const y = (0.25 + Math.random() * 0.4) * window.innerHeight;
      emitSfxAt(x, y, { quiet: true });
    }, AUTO_SFX_MS);
    talkTimer = setInterval(() => emitTalk(), AUTO_TALK_MS);
  }

  function pickVarying(arr, scene, store) {
    if (!arr || arr.length === 0) return null;
    if (arr.length === 1) return arr[0];
    let idx;
    let guard = 0;
    do {
      idx = Math.floor(Math.random() * arr.length);
      guard++;
    } while (idx === store[scene] && guard < 6);
    store[scene] = idx;
    return arr[idx];
  }

  // ─── Audio ────────────────────────────────────────────
  let audioCtx;
  function ensureAudio() {
    if (audioCtx) return audioCtx;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    audioCtx = new Ctx();
    return audioCtx;
  }
  function playTone(freq = 440, duration = 0.18, type = 'sine') {
    const ctx = ensureAudio();
    if (!ctx) return;
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(freq * 1.6, ctx.currentTime + duration);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration + 0.05);
  }

  // 録音ファイルを持たない方針のため、動物の鳴き声はオシレーター＋ゲインで合成する。
  // cry は chirp（1 つの音源）の配列で、各 chirp を時間差で並べて「わんわん」「ぱおーん」等を作る。
  //   { type, f0, f1, dur, gain, at } — f0→f1 はピッチのグライド、at は開始オフセット秒。
  const CRY_MAX_GAIN = 0.25; // 0-2 歳の安全上限（突発的に大きくしない）。
  function playCry(cry) {
    const ctx = ensureAudio();
    if (!ctx || !Array.isArray(cry) || cry.length === 0) return;
    if (ctx.state === 'suspended') ctx.resume();
    const base = ctx.currentTime;
    cry.forEach((c) => {
      const start = base + (c.at || 0);
      const dur = c.dur || 0.18;
      const f0 = Math.max(1, c.f0 || 440);
      const f1 = Math.max(1, c.f1 || f0);
      const peak = Math.min(c.gain || 0.18, CRY_MAX_GAIN);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = c.type || 'sawtooth';
      osc.frequency.setValueAtTime(f0, start);
      osc.frequency.exponentialRampToValueAtTime(f1, start + dur);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(peak, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + dur + 0.05);
    });
  }

  // ─── SFX text + sparks ────────────────────────────────
  function emitSfxAt(x, y, opts = {}) {
    const page = pages[current];
    const scene = page.dataset.scene;
    const sceneCfg = cfg(scene);
    const sfxList = sceneCfg.sfxs || [page.dataset.sfx || 'ぱ　ち'];
    const text = pickVarying(sfxList, scene, lastSfxIndex) || 'ぱ　ち';

    const notes = sceneCfg.notes || [440, 550, 660];
    const note = notes[Math.floor(Math.random() * notes.length)];
    // 通常タップは動物の鳴き声（cry があれば）を主たる音にする。鳴き声と音階ビープが
    // 重なって騒がしくならないよう、cry のある場面では beep を出さない。静かな自動 SFX
    // （quiet）は従来どおり柔らかい音階のみ（鳴き声を連発しない）。
    if (opts.quiet) {
      playTone(note, 0.14, 'sine');
    } else if (Array.isArray(sceneCfg.cry) && sceneCfg.cry.length) {
      playCry(sceneCfg.cry);
    } else {
      playTone(note, 0.22, 'triangle');
    }

    const colors = sceneCfg.colors || ['pink', 'yellow', 'white'];
    const bubble = document.createElement('div');
    bubble.className = 'sfx-bubble ' + colors[Math.floor(Math.random() * colors.length)];
    bubble.textContent = text;
    bubble.style.left = x + 'px';
    bubble.style.top  = y + 'px';
    fxLayer.appendChild(bubble);
    setTimeout(() => bubble.remove(), 1200);

    const count = opts.quiet ? 4 : 10;
    for (let i = 0; i < count; i++) {
      const spark = document.createElement('div');
      spark.className = 'spark ' + colors[i % colors.length];
      spark.style.left = x + 'px';
      spark.style.top  = y + 'px';
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.4;
      const dist  = 80 + Math.random() * 120;
      spark.style.setProperty('--dx', Math.cos(angle) * dist + 'px');
      spark.style.setProperty('--dy', Math.sin(angle) * dist + 'px');
      fxLayer.appendChild(spark);
      setTimeout(() => spark.remove(), 900);
    }
  }

  // ─── 語りかけ吹き出し ─────────────────────────────────
  function emitTalk() {
    const scene = sceneOf(current);
    const sceneCfg = cfg(scene);
    const list = sceneCfg.talks;
    const text = pickVarying(list, scene, lastTalkIndex);
    if (!text) return;

    const camEl = document.getElementById('cam-window');
    let originX, originY;
    if (camEl && !camEl.classList.contains('cam-window--off')) {
      const rect = camEl.getBoundingClientRect();
      originX = rect.left - 12;
      originY = rect.top + rect.height / 2;
    } else {
      originX = window.innerWidth * 0.7;
      originY = window.innerHeight * 0.55;
    }

    const talk = document.createElement('div');
    talk.className = 'talk-bubble';
    talk.textContent = expandName(text);
    talk.style.left = originX + 'px';
    talk.style.top  = originY + 'px';
    fxLayer.appendChild(talk);
    setTimeout(() => talk.remove(), 2600);

    const notes = sceneCfg.notes || [440];
    playTone(notes[0] * 1.5, 0.08, 'sine');
    setTimeout(() => playTone(notes[0] * 2, 0.08, 'sine'), 110);
  }

  // ─── Pointer ──────────────────────────────────────────
  function onTap(e) {
    if (e.target.closest('.parent-nav')) return;
    if (e.target.closest('.cam-window')) return;
    // .draggable は別ハンドラで処理（タップだけ SFX、ドラッグは無音）
    if (e.target.closest('.draggable')) return;
    const touch = e.changedTouches ? e.changedTouches[0] : e;
    emitSfxAt(touch.clientX, touch.clientY);
  }
  document.addEventListener('pointerdown', onTap);

  // ─── ドラッグ可能な乗り物 (.draggable) ────────────────
  function setupDraggable(el) {
    let pointerId = null;
    let startX = 0;
    let startY = 0;
    let movedYet = false;

    el.addEventListener('pointerdown', (e) => {
      if (pointerId !== null) return;
      pointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      movedYet = false;
      try { el.setPointerCapture(pointerId); } catch (_) {}
    });

    el.addEventListener('pointermove', (e) => {
      if (e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      if (!movedYet) {
        if (Math.abs(dx) < 4) return;
        movedYet = true;
        // 今アニメで描画されている位置で固定する
        const rect = el.getBoundingClientRect();
        const parent = el.offsetParent || el.parentElement;
        const parentRect = parent.getBoundingClientRect();
        const liveLeft = rect.left - parentRect.left;
        el.style.animation = 'none';
        el.style.left = liveLeft + 'px';
        el.style.transform = 'translateX(0px)';
        el.classList.add('is-dragging');
      }
      el.style.transform = `translateX(${dx}px)`;
    });

    function end(e) {
      if (e.pointerId !== pointerId) return;
      try { el.releasePointerCapture(pointerId); } catch (_) {}
      pointerId = null;
      el.classList.remove('is-dragging');
      if (movedYet) {
        // 移動した分を left に畳む
        const baseLeft = parseFloat(el.style.left) || 0;
        const m = /translateX\((-?[\d.]+)px\)/.exec(el.style.transform || '');
        const dx = m ? parseFloat(m[1]) : 0;
        const finalLeft = baseLeft + dx;
        el.style.left = finalLeft + 'px';
        el.style.transform = 'translateX(0px)';

        // 離した位置から右へ流れて画面外へ → CSSアニメ復帰
        const rect = el.getBoundingClientRect();
        const screenWidth = window.innerWidth;
        const distance = Math.max(screenWidth + 200 - rect.left, 200);
        // 1画面分を10秒で渡る速度（ゆっくりめ、CSSアニメ近似）
        const duration = Math.max(1500, (distance / (screenWidth / 10)) * 1000);

        const anim = el.animate(
          [
            { transform: 'translateX(0px)' },
            { transform: `translateX(${distance}px)` },
          ],
          { duration, easing: 'linear', fill: 'none' }
        );
        anim.onfinish = () => {
          // インライン解除 → CSS アニメ再開（左から再登場）
          el.style.animation = '';
          el.style.left = '';
          el.style.transform = '';
        };
      }
      // タップだけ（動かさず離した）は何もしない
    }
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
  }

  document.querySelectorAll('.draggable').forEach(setupDraggable);

  // ページ切替時に、ドラッグで動かされた乗り物を元のCSSアニメに戻す
  function resetDraggables() {
    document.querySelectorAll('.draggable').forEach((el) => {
      el.style.animation = '';
      el.style.left = '';
      el.style.transform = '';
    });
  }

  // ─── Nav + keyboard ───────────────────────────────────
  prevBtn.addEventListener('click', (e) => { e.stopPropagation(); goTo(current - 1); });
  nextBtn.addEventListener('click', (e) => { e.stopPropagation(); goTo(current + 1); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') return goTo(current + 1);
    if (e.key === 'ArrowLeft')  return goTo(current - 1);
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    emitKeyReaction(e.key);
  });

  function emitKeyReaction(key) {
    const scene = sceneOf(current);
    const sceneCfg = cfg(scene);
    const colors = sceneCfg.colors || ['pink', 'yellow', 'white'];

    const x = (0.15 + Math.random() * 0.7) * window.innerWidth;
    const y = (0.2  + Math.random() * 0.55) * window.innerHeight;

    const useEmoji = Math.random() < 0.3;
    const text = useEmoji
      ? KEY_EMOJIS[Math.floor(Math.random() * KEY_EMOJIS.length)]
      : KEY_WORDS[Math.floor(Math.random() * KEY_WORDS.length)];

    const bubble = document.createElement('div');
    bubble.className = 'key-bubble ' + colors[Math.floor(Math.random() * colors.length)];
    bubble.textContent = expandName(text);
    bubble.style.left = x + 'px';
    bubble.style.top  = y + 'px';
    const tilt = (Math.random() * 30 - 15).toFixed(1);
    bubble.style.setProperty('--tilt', tilt + 'deg');
    fxLayer.appendChild(bubble);
    setTimeout(() => bubble.remove(), 1400);

    const count = 14;
    for (let i = 0; i < count; i++) {
      const spark = document.createElement('div');
      spark.className = 'spark ' + colors[i % colors.length];
      spark.style.left = x + 'px';
      spark.style.top  = y + 'px';
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.5;
      const dist  = 100 + Math.random() * 180;
      spark.style.setProperty('--dx', Math.cos(angle) * dist + 'px');
      spark.style.setProperty('--dy', Math.sin(angle) * dist + 'px');
      fxLayer.appendChild(spark);
      setTimeout(() => spark.remove(), 900);
    }

    const notes = sceneCfg.notes || [440, 550, 660];
    const code = (key || '').charCodeAt(0) || Math.floor(Math.random() * 100);
    const note = notes[code % notes.length] * (0.8 + ((code * 13) % 9) / 10);
    playTone(note, 0.18, ['triangle', 'sine', 'square'][code % 3]);

    popCam();

    document.body.classList.remove('flash');
    void document.body.offsetWidth;
    document.body.classList.add('flash');
  }

  // ─── Swipe ────────────────────────────────────────────
  let touchStartX = null;
  document.addEventListener('touchstart', (e) => {
    touchStartX = e.changedTouches[0].clientX;
  }, { passive: true });
  document.addEventListener('touchend', (e) => {
    if (touchStartX == null) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(dx) > 80) {
      goTo(current + (dx < 0 ? 1 : -1));
    }
    touchStartX = null;
  });

  // ─── Camera mirror ────────────────────────────────────
  const camWindow = document.getElementById('cam-window');
  const camVideo  = document.getElementById('cam-video');
  const camToggle = document.getElementById('cam-toggle');
  let camStream = null;

  async function startCam() {
    if (camStream) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('このブラウザは カメラに たいおうしてないみたい');
      return;
    }
    try {
      camStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 640 } },
        audio: false,
      });
      camVideo.srcObject = camStream;
      camWindow.classList.remove('cam-window--off');
      popCam();
    } catch (err) {
      console.warn('camera error', err);
      alert('カメラの きょかが いるみたい！');
    }
  }
  function stopCam() {
    if (!camStream) return;
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
    camVideo.srcObject = null;
    camWindow.classList.add('cam-window--off');
  }
  function popCam() {
    if (!camWindow) return;
    camWindow.classList.remove('cam-pop');
    void camWindow.offsetWidth;
    camWindow.classList.add('cam-pop');
  }
  if (camToggle) {
    camToggle.addEventListener('click', (e) => { e.stopPropagation(); startCam(); });
  }
  if (camWindow) {
    camWindow.addEventListener('dblclick', (e) => { e.stopPropagation(); stopCam(); });
  }

  // ─── ロック（チャイルドロック）─────────────────────
  const lockBtn = document.querySelector('.lock-btn');
  const parentNav = document.querySelector('.parent-nav');
  let isLocked = false;
  let lockPressTimer = null;
  const LOCK_UNLOCK_MS = 1500;

  function beforeUnloadGuard(e) {
    e.preventDefault();
    e.returnValue = '';
  }

  function setLocked(v) {
    isLocked = v;
    if (parentNav) parentNav.classList.toggle('is-locked', v);
    if (lockBtn) lockBtn.textContent = v ? '🔓' : '🔒';
    if (v) {
      const el = document.documentElement;
      const req = el.requestFullscreen || el.webkitRequestFullscreen;
      if (req) {
        try { req.call(el).catch(() => {}); } catch (_) {}
      }
      window.addEventListener('beforeunload', beforeUnloadGuard);
    } else {
      if (document.exitFullscreen) {
        try { document.exitFullscreen().catch(() => {}); } catch (_) {}
      }
      window.removeEventListener('beforeunload', beforeUnloadGuard);
    }
  }

  function startLockPress() {
    if (!lockBtn) return;
    lockBtn.classList.add('is-pressing');
    clearTimeout(lockPressTimer);
    lockPressTimer = setTimeout(() => {
      setLocked(false);
      lockBtn.classList.remove('is-pressing');
    }, LOCK_UNLOCK_MS);
  }
  function cancelLockPress() {
    if (!lockBtn) return;
    clearTimeout(lockPressTimer);
    lockBtn.classList.remove('is-pressing');
  }

  if (lockBtn) {
    lockBtn.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      if (!isLocked) {
        setLocked(true);
      } else {
        startLockPress();
      }
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => {
      lockBtn.addEventListener(ev, (e) => { e.stopPropagation(); cancelLockPress(); });
    });
    lockBtn.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  // ─── Kickoff ──────────────────────────────────────────
  restartTimers();
  document.addEventListener('pointerdown', () => ensureAudio(), { once: true });
})();
