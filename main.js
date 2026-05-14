(() => {
  const pages = Array.from(document.querySelectorAll('.page'));
  const fxLayer = document.getElementById('fx-layer');
  const dotsEl = document.getElementById('dots');
  const prevBtn = document.querySelector('.nav-btn--prev');
  const nextBtn = document.querySelector('.nav-btn--next');

  const AUTO_ADVANCE_MS = 12000;
  const AUTO_SFX_MS = 3500;
  const AUTO_TALK_MS = 5200;
  const SCENE_COLORS = {
    takeoff: ['pink', 'yellow', 'white'],
    clouds:  ['white', 'pink', 'yellow'],
    sea:     ['white', 'yellow', 'pink'],
    night:   ['yellow', 'white', 'white'],
    landing: ['pink', 'yellow', 'white'],
  };

  // シーン別 オノマトペ（ランダムに選ぶ）
  const SCENE_SFXS = {
    takeoff: ['ぶ　ー　ん', 'ごー', 'しゅっ', 'ぐぃーん', 'びゅーん', 'ばたばた'],
    clouds:  ['ひゅ　ー　ん', 'もこもこ', 'ふわー', 'すぅーっ', 'もくもく', 'ふんわり'],
    sea:     ['ぴょ　ー　ん', 'ばしゃん', 'ざぶーん', 'きらん', 'ちゃぷん', 'すいすい'],
    night:   ['きら　きら', 'ぴかーん', 'きらん', 'しーん', 'ぽつん', 'ちかちか'],
    landing: ['ガタ　ガタ', 'がしゃん', 'きゅっ', 'すとん', 'ピタッ', 'ことん'],
  };

  // キーボードを叩いたとき出るやつ（1歳の適当タイピング用）
  const KEY_WORDS = [
    'わぁ！', 'やった！', 'すごい！', 'もう いっかい！', 'たのしー！',
    'いえーい！', 'ぱちぱち！', '__NAME__ー！', 'にこにこ', 'おー！',
    'ぱーん！', 'どきどき', 'うふふ', 'きゃー！', 'ぴょん！',
    'はーい！', 'ぽーん', 'ふふっ', 'よーし！', 'えへへ',
  ];
  const KEY_EMOJIS = ['🎉', '⭐', '✨', '🌈', '💖', '🎈', '🎀', '🍭', '🐶', '🐱', '🐰', '🦊', '🐻', '🌸', '🍀'];

  // シーン別 __NAME__くんへの語りかけ
  const SCENE_TALKS = {
    takeoff: [
      '__NAME__くん、\nしゅっぱつ だよ！',
      '__NAME__くん、\nしっかり つかまって！',
      'べると しめてー',
      'たかい たかーい！',
    ],
    clouds: [
      '__NAME__くん、\nくも やわらかい？',
      'もこもこ きれいだね',
      'そら たかいねー',
      '__NAME__くん、\nふわふわ！',
    ],
    sea: [
      '__NAME__くん、\nいるか いるよ！',
      'うみ ひかってる！',
      'おさかな みえる？',
      '__NAME__くん、\nきらきら だね',
    ],
    night: [
      '__NAME__くん、\nおほしさま みえる？',
      'おつきさま\nこんばんは',
      'よぞら きれいだね',
      '__NAME__くん、\nねむくない？',
    ],
    landing: [
      '__NAME__くん、\nついたよー！',
      'おかえりー',
      'よく がんばったね！',
      '__NAME__くん、\nまた のろうね',
    ],
  };

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

  // ─── Page transitions ─────────────────────────────────
  function goTo(index) {
    const next = (index + pages.length) % pages.length;
    pages[current].classList.remove('is-active');
    dots[current].classList.remove('is-active');
    current = next;
    pages[current].classList.add('is-active');
    dots[current].classList.add('is-active');
    restartTimers();
    // ページ切り替え時に1発オノマトペ + カメラ窓のリアクション
    setTimeout(() => emitSfxAt(window.innerWidth / 2, window.innerHeight / 2.4), 300);
    setTimeout(() => emitTalk(), 700);
    popCam();
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

  // 同じ要素が連続で選ばれないようにする
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

  // ─── Audio (gentle tone) ──────────────────────────────
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

  const SCENE_NOTES = {
    takeoff: [330, 415, 494, 660],
    clouds:  [523, 587, 659, 784],
    sea:     [392, 466, 587, 698],
    night:   [294, 370, 440, 587],
    landing: [262, 311, 392, 523],
  };

  // ─── SFX text + sparks ────────────────────────────────
  function emitSfxAt(x, y, opts = {}) {
    const page = pages[current];
    const scene = page.dataset.scene;
    const sfxList = SCENE_SFXS[scene];
    const text = pickVarying(sfxList, scene, lastSfxIndex) || page.dataset.sfx || 'ぱ　ち';

    // sound
    const notes = SCENE_NOTES[scene] || [440, 550, 660];
    const note = notes[Math.floor(Math.random() * notes.length)];
    if (!opts.quiet) playTone(note, 0.22, 'triangle');
    else playTone(note, 0.14, 'sine');

    // text bubble
    const bubble = document.createElement('div');
    bubble.className = 'sfx-bubble ' + (SCENE_COLORS[scene] || ['pink'])[Math.floor(Math.random() * 3)];
    bubble.textContent = text;
    bubble.style.left = x + 'px';
    bubble.style.top  = y + 'px';
    fxLayer.appendChild(bubble);
    setTimeout(() => bubble.remove(), 1200);

    // sparks
    const count = opts.quiet ? 4 : 10;
    const colors = SCENE_COLORS[scene] || ['yellow', 'pink', 'white'];
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

  // ─── __NAME__くんへの語りかけバブル ─────────────────────
  function emitTalk() {
    const page = pages[current];
    const scene = page.dataset.scene;
    const list = SCENE_TALKS[scene];
    const text = pickVarying(list, scene, lastTalkIndex);
    if (!text) return;

    // カメラ窓の左上に寄せて吹き出しを出す（顔から喋ってる風）
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
    talk.textContent = text;
    talk.style.left = originX + 'px';
    talk.style.top  = originY + 'px';
    fxLayer.appendChild(talk);
    setTimeout(() => talk.remove(), 2600);

    // やさしい音
    const notes = SCENE_NOTES[scene] || [440];
    playTone(notes[0] * 1.5, 0.08, 'sine');
    setTimeout(() => playTone(notes[0] * 2, 0.08, 'sine'), 110);
  }

  // ─── Pointer handling ─────────────────────────────────
  function onTap(e) {
    // 大人のナビを押した場合はスキップ
    if (e.target.closest('.parent-nav')) return;
    const touch = e.changedTouches ? e.changedTouches[0] : e;
    emitSfxAt(touch.clientX, touch.clientY);
  }
  document.addEventListener('pointerdown', onTap);

  // ─── Nav buttons + keyboard ───────────────────────────
  prevBtn.addEventListener('click', (e) => { e.stopPropagation(); goTo(current - 1); });
  nextBtn.addEventListener('click', (e) => { e.stopPropagation(); goTo(current + 1); });
  document.addEventListener('keydown', (e) => {
    // ナビ用キー（大人が操作）
    if (e.key === 'ArrowRight') return goTo(current + 1);
    if (e.key === 'ArrowLeft')  return goTo(current - 1);
    // ブラウザのショートカット（⌘/Ctrl/Alt等）はスルー
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // それ以外（1歳がてきとうに叩いたぶん）→ ランダムリアクション
    emitKeyReaction(e.key);
  });

  // ─── キーボード乱打リアクション ───────────────────────
  function emitKeyReaction(key) {
    const page = pages[current];
    const scene = page.dataset.scene;
    const colors = SCENE_COLORS[scene] || ['pink', 'yellow', 'white'];

    // 表示位置：画面の中央寄りでランダム
    const x = (0.15 + Math.random() * 0.7) * window.innerWidth;
    const y = (0.2  + Math.random() * 0.55) * window.innerHeight;

    // 70% は ことば、30% は えもじ
    const useEmoji = Math.random() < 0.3;
    const text = useEmoji
      ? KEY_EMOJIS[Math.floor(Math.random() * KEY_EMOJIS.length)]
      : KEY_WORDS[Math.floor(Math.random() * KEY_WORDS.length)];

    const bubble = document.createElement('div');
    bubble.className = 'key-bubble ' + colors[Math.floor(Math.random() * colors.length)];
    bubble.textContent = text;
    bubble.style.left = x + 'px';
    bubble.style.top  = y + 'px';
    // 回転をランダムに
    const tilt = (Math.random() * 30 - 15).toFixed(1);
    bubble.style.setProperty('--tilt', tilt + 'deg');
    fxLayer.appendChild(bubble);
    setTimeout(() => bubble.remove(), 1400);

    // たくさんのきらきら
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

    // 音：キーごとに音程を変えて、乱打しても飽きないように
    const notes = SCENE_NOTES[scene] || [440, 550, 660];
    const code = (key || '').charCodeAt(0) || Math.floor(Math.random() * 100);
    const note = notes[code % notes.length] * (0.8 + ((code * 13) % 9) / 10);
    playTone(note, 0.18, ['triangle', 'sine', 'square'][code % 3]);

    // カメラ窓もリアクション
    popCam();

    // 画面全体に「フラッシュ」っぽい雰囲気
    document.body.classList.remove('flash');
    void document.body.offsetWidth;
    document.body.classList.add('flash');
  }

  // ─── Swipe (horizontal) ───────────────────────────────
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

  // ─── カメラ（ミラー）───────────────────────────────────
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
    // reflow で再生
    void camWindow.offsetWidth;
    camWindow.classList.add('cam-pop');
  }
  camToggle.addEventListener('click', (e) => {
    e.stopPropagation();
    startCam();
  });
  // ダブルクリックでオフ（大人用の隠しスイッチ）
  camWindow.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    stopCam();
  });

  // ─── Kickoff ──────────────────────────────────────────
  restartTimers();
  // 初回タップで AudioContext を起こす
  document.addEventListener('pointerdown', () => ensureAudio(), { once: true });
})();
