window.BOOK_CONFIG = {
  title: '__NAME__の どうぶつパーティー',
  scenes: {
    inu: {
      sfxs: ['わん　わん', 'わん！', 'わうわう', 'くんくん', 'ワン　ワン'],
      talks: [
        '__NAME__、\nいぬさん だよ！',
        'わんわん ないてるね',
        'しっぽ ふりふり',
        '__NAME__、\nなでなで しよ！',
      ],
      colors: ['yellow', 'pink', 'white'],
      notes:  [392, 494, 587, 740],
      // わんわん: 立ち下がる短い吠えを 2 連。
      cry: [
        { type: 'sawtooth', f0: 520, f1: 300, dur: 0.10, gain: 0.20, at: 0 },
        { type: 'sawtooth', f0: 520, f1: 300, dur: 0.10, gain: 0.20, at: 0.17 },
      ],
    },
    neko: {
      sfxs: ['にゃー', 'にゃーお', 'にゃん', 'ごろごろ', 'みゃー'],
      talks: [
        '__NAME__、\nねこさん きたよ',
        'にゃー って ないた！',
        'ふわふわ きもちー',
        'ごろごろ してるね',
      ],
      colors: ['pink', 'yellow', 'white'],
      notes:  [440, 523, 659, 784],
      // にゃー: 上がってから下がるグライド（鳴き上げ→収め）。
      // at=0.11 は chirp1（dur=0.12）終端と 0.01s 重ねて滑らかに繋ぐ意図（独立 GainNode なので安全）。
      cry: [
        { type: 'sawtooth', f0: 620, f1: 880, dur: 0.12, gain: 0.16, at: 0 },
        { type: 'sawtooth', f0: 880, f1: 520, dur: 0.22, gain: 0.16, at: 0.11 },
      ],
    },
    buta: {
      sfxs: ['ぶー　ぶー', 'ぶひっ', 'ぶぅ', 'ふがふが', 'ぶーっ'],
      talks: [
        '__NAME__、\nぶたさん だよ！',
        'ぶーぶー かわいい',
        'おはな ぷにぷに',
        '__NAME__、\nいっしょに あそぼ',
      ],
      colors: ['pink', 'white', 'yellow'],
      notes:  [330, 392, 466, 587],
      // ぶーぶー: 低い鼻音の唸りを 2 連（square で鼻にかかった響き）。
      cry: [
        { type: 'square', f0: 200, f1: 150, dur: 0.12, gain: 0.16, at: 0 },
        { type: 'square', f0: 190, f1: 140, dur: 0.12, gain: 0.16, at: 0.18 },
      ],
    },
    zou: {
      sfxs: ['ぱおーん', 'ぱおっ', 'ぷしゅー', 'ぱおぱお', 'どすん'],
      talks: [
        '__NAME__、\nぞうさん おおきいね',
        'ぱおーん って ないた！',
        'おはな なが〜い',
        'みみ ぱたぱた',
      ],
      colors: ['white', 'pink', 'yellow'],
      notes:  [262, 311, 392, 523],
      // ぱおーん: 低音から一気に立ち上げ（ぱ）→ 高音を伸ばす（おーん）ラッパ。
      // 2 つ目は dur=0.50 と長め（伸ばす表現）。連打で重なりうるが単発は gain 0.18 で安全範囲内。
      cry: [
        { type: 'sawtooth', f0: 230, f1: 680, dur: 0.14, gain: 0.18, at: 0 },
        { type: 'sawtooth', f0: 700, f1: 620, dur: 0.50, gain: 0.18, at: 0.13 },
      ],
    },
    party: {
      sfxs: ['わいわい', 'いえーい！', 'ぱちぱち', 'やったー', 'だいすき'],
      talks: [
        '__NAME__、\nみんな あつまった！',
        'パーティー たのしー！',
        'いっしょに おどろ！',
        '__NAME__、\nだいすきだよ！',
      ],
      colors: ['pink', 'yellow', 'white'],
      notes:  [523, 659, 784, 988],
      // パーティー: 上がっていくお祝いのファンファーレ（ド・ミ・ソ・高いド）。
      cry: [
        { type: 'triangle', f0: 523,  f1: 523,  dur: 0.12, gain: 0.16, at: 0 },
        { type: 'triangle', f0: 659,  f1: 659,  dur: 0.12, gain: 0.16, at: 0.12 },
        { type: 'triangle', f0: 784,  f1: 784,  dur: 0.12, gain: 0.16, at: 0.24 },
        { type: 'triangle', f0: 1047, f1: 1047, dur: 0.20, gain: 0.16, at: 0.36 },
      ],
    },
  },
};
