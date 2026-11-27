// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Answers the mpv script with Sluka's own code.
 *
 * The script in mpv (mpv/sluka.lua) draws subtitles and asks three things:
 * which words are in this line and how well each is known, what a word means,
 * and to file a word at a level.  Every answer here is Sluka's: its tokenizer
 * for the language, its word list, its dictionary, its rules for what a grade
 * does -- the free allowance included, which is asked of Sluka's own store and
 * never worked around.  So a word graded in mpv is graded in the book you read
 * tomorrow, and the other way round.
 *
 * What mpv draws is to look as Sluka looks in a browser, so the script is also
 * told how: the subtitle settings (size, place, background, font), the colours
 * a word wears at each level, and for a word what Sluka's card and panel print
 * -- the headword with its furigana, the reading with its pitch drawn, the
 * short meanings, the dictionary's own, how common the word is.  All of it is
 * worked out by Sluka's modules; the script only lays it out.
 *
 * The questions arrive through the desktop app (mpvbridge.py), which holds a
 * request of this page's open until there is one.
 *
 * This file is the one part of Sluka Desktop that leans on Sluka's insides:
 * the modules imported below are not an interface anyone promised.  They are
 * imported by name and checked, so a later Sluka that has moved one says so
 * in the app's log instead of drawing wrong subtitles.  What only the look
 * needs (WANTS) is done without where it is missing: the words are still
 * read, cut and graded, and the log says what could not be shown.
 */

const shim = globalThis.__slukaShim;
const { api } = shim;

const NEEDS = {
  '/lib/constants.js': ['STATUS', 'STATUS_LABEL', 'KEY'],
  '/lib/languages.js': ['getLanguage', 'SUPPORTED', 'languageName'],
  '/lib/vocab.js': ['Vocab'],
  '/lib/counting.js': ['COUNTING', 'settleLevels', 'surfaceKey', 'wordKey'],
  '/lib/dictionary.js': ['lookupBatch'],
  '/lib/word-gloss.js': ['glossSenses'],
  '/lib/glosses.js': ['pronunciationOf'],
  '/lib/settings.js': ['loadSettings', 'onSettingsChanged'],
  '/lib/store.js': ['loadUserWords', 'loadMeanings'],
  '/lib/word-picks.js': ['applyWordPicks', 'loadWordPicks'],
  '/lib/word-splits.js': ['loadWordSplits', 'standingSplits'],
  '/lib/i18n.js': ['T', 'startI18n'],
};

/** For the look alone: each is used where it is there. */
const WANTS = {
  '/lib/colours.js': ['pageScheme', 'ccScheme', 'levelColour', 'levelLine', 'ccLevelColour'],
  '/lib/theme.js': ['themeChoice', 'resolveTheme'],
  '/lib/settings.js': ['readingMode', 'ccFontFor'],
  '/lib/languages.js': ['FREQUENCY_ORDERED'],
  '/lib/glosses.js': ['glossSource', 'glossParts'],
  '/lib/word-gloss.js': ['meaningSenses', 'nativeSenses', 'wholeSenses'],
  '/lib/ja-pitch.js': ['morae', 'pitchShape', 'pitchFinder'],
  '/lib/anki-pitch.js': ['pitchRowsOf'],
  '/lib/ruby.js': ['furiganaSegments'],
  '/lib/ja-kana.js': ['toKatakana'],
  '/lib/freq-list.js': ['freqTable', 'readOwnList'],
  '/lib/media.js': ['listRanks'],
  '/lib/counting.js': ['tailFile', 'parseFreq'],
  '/lib/gz.js': ['fetchGzipText'],
  '/lib/i18n.js': ['Tord', 'Tx', 'uiLocale', 'Tn'],
  // How many times a word was looked up, the 👀 of Sluka's panel (counted on a click, as a page counts one).
  '/lib/lookups.js': ['LookupCounter'],
};

const S = {};
for (const [path, names] of Object.entries(NEEDS)) {
  const mod = await import(path);
  for (const name of names) {
    if (!(name in mod)) throw new Error(`This version of Sluka has no ${name} in ${path}: the mpv engine needs updating for it.`);
    S[name] = mod[name];
  }
}
const { STATUS, STATUS_LABEL, KEY, COUNTING } = S;

const O = {};
const missing = [];
for (const [path, names] of Object.entries(WANTS)) {
  const mod = await import(path).catch(() => null);
  for (const name of names) {
    if (mod && name in mod) O[name] = mod[name];
    else missing.push(`${name} (${path})`);
  }
}
if (missing.length) {
  api('log', { level: 'warning', text: `mpv: this version of Sluka lacks ${missing.join(', ')}: its card in mpv will show less` }).catch(() => {});
}

await S.startI18n({ root: null, local: false }).catch(() => {});

/** The codes a subtitle track is labelled with, as Sluka names the language. */
const TRACK_CODES = {
  zh: 'zh', zho: 'zh', chi: 'zh', cmn: 'zh', yue: 'yue', ja: 'ja', jpn: 'ja', ko: 'ko', kor: 'ko', th: 'th', tha: 'th',
  it: 'it', ita: 'it', fr: 'fr', fra: 'fr', fre: 'fr', es: 'es', spa: 'es', pt: 'pt', por: 'pt', de: 'de', deu: 'de', ger: 'de',
  nl: 'nl', nld: 'nl', dut: 'nl', sv: 'sv', swe: 'sv', da: 'da', dan: 'da', nb: 'nb', nob: 'nb', no: 'nb', nor: 'nb',
  pl: 'pl', pol: 'pl', tr: 'tr', tur: 'tr', id: 'id', ind: 'id', fi: 'fi', fin: 'fi', el: 'el', ell: 'el', gre: 'el',
  ru: 'ru', rus: 'ru', uk: 'uk', ukr: 'uk', en: 'en', eng: 'en', vi: 'vi', vie: 'vi', ar: 'ar', ara: 'ar',
};

/** How many of the dictionary's own meanings the panel in mpv lists, which cannot be scrolled. */
/** What the script and this page say to each other, counted up when it changes shape (mpv/sluka.lua PROTOCOL). */
const PROTOCOL = 2;
const SENSES_SHOWN = 6;
/** And how many of a word's other readings, a line each. */
const ALSO_SHOWN = 2;

const encoder = new TextEncoder();
const bytes = (text) => encoder.encode(text).length;

let settings = await S.loadSettings();
S.onSettingsChanged((next) => {
  settings = next;
  // Colours or the language may be other ones now: every player is told again.
  for (const player of players.values()) ready(player, { quiet: true }).catch(report);
});
// What the app knows of the desktop it runs on: the font the desktop itself is set in, which is what system-ui means.
const desktop = await api('info').catch(() => ({}));
// The palette follows the desktop where Sluka is set to (lib/theme.js): told again when the desktop turns dark or light.
globalThis.matchMedia?.('(prefers-color-scheme: dark)')?.addEventListener?.('change', () => {
  for (const player of players.values()) ready(player, { quiet: true }).catch(report);
});

function report(err) {
  console.error('[sluka-desktop] mpv engine:', err);
}

// ------------------------------------------------------------ languages

/** A language made ready as the reader makes it ready (content/reader.js thumbLanguage), by its id. */
const languages = new Map();

function language(id) {
  if (!languages.has(id)) {
    const opened = (async () => {
      const lang = await S.getLanguage(id);
      await lang.loadIndex(chrome.runtime.getURL(''));
      // The words you made by hand, the spellings you said are other words, the words you split.
      const userWords = await S.loadUserWords(id);
      if (userWords.length) lang.addWords(userWords);
      S.applyWordPicks(lang, await S.loadWordPicks(id));
      lang.setWordSplits?.(S.standingSplits(await S.loadWordSplits(id)));
      const vocab = await new S.Vocab(id).load();
      const { mode } = await S.settleLevels(id, vocab);
      const L = { id, lang, vocab, mode, bases: new Map(), places: null };
      // A word graded in a book or on the dashboard changes its colour in mpv too.
      vocab.onExternalChange(() => repaint(L));
      // How common each word is: fetched now, so the first card does not wait for it.
      places(L);
      return L;
    })();
    opened.catch(() => languages.delete(id));
    languages.set(id, opened);
  }
  return languages.get(id);
}

// The way a language counts its words was changed: it is made ready again, counting that way.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  for (const id of [...languages.keys()]) {
    if (changes[KEY.counting(id)]) {
      languages.delete(id);
      for (const player of players.values()) if (player.lang === id) ready(player, { quiet: true }).catch(report);
    }
  }
});

/** The key a word is filed under, as the reader's engine files it (content/engine.js keyOf). */
function keyOf(L, tok) {
  const key = S.wordKey(L.lang, tok, L.mode);
  const linked = L.mode === COUNTING.LEMMA
    ? key !== tok.base
    : !!L.lang.linkedSpelling?.(S.surfaceKey(L.lang, tok.split ?? tok.text));
  if (tok.base && !linked && !(tok.byCase && L.mode === COUNTING.FORM)) L.bases.set(key, tok.base);
  return key;
}

/** The other half a grade is filed with (content/engine.js pairOf). */
function pairOf(L, key, text) {
  if (L.mode === COUNTING.FORM) return { lemma: S.wordKey(L.lang, { text: key, base: L.bases.get(key) }, COUNTING.LEMMA) };
  return text ? { form: S.surfaceKey(L.lang, text) } : {};
}

/** What the dictionary is asked for (content/engine.js lookupKey). */
function lookupKey(L, key) {
  if (L.mode === COUNTING.FORM) {
    const linked = L.lang.linkedWord?.(key, key);
    if (linked) return linked;
  }
  return L.bases.get(key) || L.lang.lookupForm(key);
}

const label = (status) => S.T(STATUS_LABEL[status] ?? STATUS_LABEL[STATUS.NEW]);

/*
 * How many times each word was looked up (lib/lookups.js): the 👀 Sluka's
 * panel shows from the third, and the Words tab's "Most looked up".  A click
 * on a word in mpv, the floating subtitles or Sluka Vision is a lookup as a
 * click on a page is one -- not a word only pointed at -- and is counted by
 * Sluka's own counter, into the same counts the app's pages and Anki keep.
 * Written at once rather than a few seconds later: this page is never on
 * screen (as a grade is, below).
 */
const lookupCounters = new Map();
/** The panel shows the count from this lookup on (content/ui.js LOOKS_SHOWN_FROM): once or twice is just reading. */
const LOOKS_SHOWN_FROM = 3;

function lookupCounter(id) {
  if (!O.LookupCounter) return null;
  if (!lookupCounters.has(id)) {
    let counter = null;
    try {
      counter = new O.LookupCounter(id);
    } catch (err) {
      report(err);
    }
    lookupCounters.set(id, counter);
  }
  return lookupCounters.get(id);
}

/** The word's count, with this lookup in it where `counted` (a click): 0 where Sluka keeps none. */
async function looksOf(L, key, counted) {
  const counter = lookupCounter(L.id);
  if (!counter || !key) return 0;
  try {
    // The stored counts are read before the first is added to them, or this lookup would show as the only one.
    await counter.ready;
    const n = Number(counted ? counter.looked(key) : counter.count(key)) || 0;
    if (counted) counter.flush().catch(report);
    return n;
  } catch (err) {
    report(err);
    return 0;
  }
}

/** The 👀 note for the panel, as Sluka's says it (content/ui.js _lookNote); none before the third lookup. */
function looksNote(n) {
  if (!(n >= LOOKS_SHOWN_FROM)) return {};
  const shown = n.toLocaleString();
  let title = `Looked up ${shown} times`;
  try {
    if (O.Tn) title = O.Tn(n, 'Looked up {n} time', 'Looked up {n} times', { n: shown });
  } catch {
    /* the English is enough */
  }
  return { looks: n, looks_title: String(title) };
}

// ------------------------------------------------------------ players

/** Every mpv that has said hello, by the key the app knows it under. */
const players = new Map();

function send(player, msg) {
  return api('mpv/reply', { player: player.key, msg }).catch(report);
}

function pickLanguage(player) {
  const studied = settings.activeLanguages?.length ? settings.activeLanguages : [settings.activeLang].filter(Boolean);
  const code = String(player.subLang || '').toLowerCase().split(/[-_]/)[0];
  const named = TRACK_CODES[code];
  // The track's own language where it is one you are learning; otherwise the one Sluka is set to.
  if (named && studied.includes(named)) return named;
  return settings.activeLang || studied[0] || 'en';
}

// ------------------------------------------------------------ the look

/** A colour as Sluka's settings and modules write one -- #rgb, #rrggbb, rgb(r, g, b) -- as [r, g, b], or null. */
function rgbOf(colour) {
  const text = String(colour ?? '').trim();
  let m = /^#?([0-9a-f]{6})$/i.exec(text);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  m = /^#?([0-9a-f]{3})$/i.exec(text);
  if (m) return [...m[1]].map((c) => parseInt(c + c, 16));
  m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(text);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  return null;
}
const hexOf = (rgb) => rgb.map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, '0')).join('');
/** `colour` as rrggbb, which is how the script in mpv is told every colour. */
const hex = (colour, fallback) => {
  const rgb = rgbOf(colour);
  return rgb ? hexOf(rgb) : fallback;
};
/** `colour` at `alpha` on white, as the panel shows a level (content/ui.js _levelVars). */
const onWhite = (colour, alpha, fallback) => {
  const rgb = rgbOf(colour);
  return rgb ? hexOf(rgb.map((c) => c * alpha + 255 * (1 - alpha))) : fallback;
};
/** `share` of `colour` and the rest white, mixed in Oklab, as content.css mixes SlukaCC's own level colours. */
function towardWhite(colour, share) {
  const rgb = rgbOf(colour);
  if (!rgb) return 'ffffff';
  const lin = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = rgb.map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const q = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const lab = [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * q, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * q, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * q];
  const [L, A, B] = lab.map((v, i) => v * share + (i === 0 ? 1 : 0) * (1 - share));
  const l3 = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m3 = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const q3 = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const out = [4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * q3, -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * q3, -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * q3];
  return hexOf(out.map((v) => (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.max(v, 0) ** (1 / 2.4) - 0.055) * 255));
}

/** SlukaCC's sizes (content/content.css, .llr-cc[data-size]). */
const CC_SIZE = { s: 0.82, m: 1, l: 1.2, xl: 1.42 };
/** The languages whose subtitle is set at the full size, and on taller rows (content/cc-overlay.js, content.css). */
const CJK_LANGS = new Set(['zh', 'yue', 'ja', 'ko']);
/** The subtitle's faces by script, first choice first (content/content.css, .llr-cc-line[data-cc='target']). */
const CC_SANS = {
  '': ['system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
  hant: ['Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', 'system-ui', 'sans-serif'],
  hans: ['Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
  ja: ['Noto Sans JP', 'Hiragino Sans', 'Yu Gothic UI', 'Meiryo', 'system-ui', 'sans-serif'],
  ko: ['Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', 'system-ui', 'sans-serif'],
};
/** The faces that go in front of those under Serif and Monospace (cc.font; content.css --llr-cc-lead). */
const CC_SERIF = ['Iowan Old Style', 'Palatino Linotype', 'Palatino', 'Book Antiqua', 'Georgia', 'serif'];
const CC_SERIF_BY = {
  hant: ['Noto Serif TC', 'Source Han Serif TC', 'Songti TC', 'PMingLiU', 'MingLiU'],
  hans: ['Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'SimSun'],
  ja: ['Noto Serif JP', 'Source Han Serif', 'Hiragino Mincho ProN', 'Yu Mincho', 'YuMincho', 'MS Mincho'],
  ko: ['Noto Serif KR', 'Source Han Serif K', 'Nanum Myeongjo', 'AppleMyungjo', 'Batang'],
};
const CC_MONO = ['Consolas', 'Cascadia Mono', 'SF Mono', 'Menlo', 'Roboto Mono'];
/** The panel's own face, and its headword's by script (content/ui.js: .panel, WORD_FONTS, HAN_FONTS). */
const UI_FONT = ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'];
const WORD_FONTS = {
  hant: ['Noto Serif TC', 'Source Han Serif TC', 'Songti TC', 'PMingLiU', 'MingLiU', 'serif'],
  hans: ['Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'SimSun', 'serif'],
  ja: ['Noto Serif JP', 'Source Han Serif', 'Hiragino Mincho ProN', 'Yu Mincho', 'YuMincho', 'MS Mincho', 'serif'],
  hangul: ['Noto Serif KR', 'Nanum Myeongjo', 'Apple SD Gothic Neo', 'Malgun Gothic', 'serif'],
  thai: ['Noto Serif Thai', 'Noto Sans Thai Looped', 'Tahoma', 'Thonburi', 'Leelawadee UI', 'serif'],
  arabic: ['Noto Naskh Arabic', 'Amiri', 'Scheherazade New', 'Sakkal Majalla', 'Geeza Pro', 'Segoe UI', 'Tahoma', 'serif'],
  latin: ['Georgia', 'Times New Roman', 'serif'],
};
/** What fontconfig calls a language whose writing a Latin face does not hold; the rest are asked for no language. */
const FONT_LANG = { ja: 'ja', ko: 'ko', yue: 'zh-hk', th: 'th', ar: 'ar', ru: 'ru', uk: 'uk', el: 'el' };

/** Which of the scripts a language's faces are picked by: a Chinese track marked simplified is that. */
function scriptOf(id, player) {
  if (id === 'ja' || id === 'ko') return id;
  if (id === 'yue') return 'hant';
  if (id === 'zh') return /hans|[-_]cn|[-_]sg|chs/i.test(String(player.subLang || '')) ? 'hans' : 'hant';
  return '';
}

/** The keys that grade in Sluka, by the level each gives, where mpv can be told them as they are: one plain character. */
function gradeKeys() {
  const keys = settings.keys || {};
  const want = { 1: keys.level1 ?? '1', 2: keys.level2 ?? '2', 3: keys.level3 ?? '3', 4: keys.level4 ?? '4', 5: keys.known ?? 'k', 6: keys.ignore ?? 'x', 0: keys.forget ?? '0' };
  const fallback = { 1: '1', 2: '2', 3: '3', 4: '4', 5: 'k', 6: 'x', 0: '0' };
  const out = {};
  const taken = new Set();
  for (const [status, key] of Object.entries(want)) {
    const plain = typeof key === 'string' && /^[a-z0-9]$/i.test(key) && !taken.has(key.toLowerCase()) ? key.toLowerCase() : fallback[status];
    taken.add(plain);
    out[status] = plain;
  }
  return out;
}

/** The key legend under the panel's buttons, cut where its keys stand (content/ui.js, the hint). */
function legend(keys) {
  const cap = (k) => `\u0001${String(k).toUpperCase()}\u0002`;
  const parts = [
    S.T('{from}–{to} level', { from: cap(keys[1]), to: cap(keys[4]) }),
    S.T('{key} known', { key: cap(keys[5]) }),
    S.T('{key} ignore', { key: cap(keys[6]) }),
  ];
  const forget = S.T('{key} back to new', { key: cap(keys[0]) });
  const cut = (text) => String(text).split(/(\u0001[^\u0002]*\u0002)/).filter(Boolean).map((piece) => (piece[0] === '\u0001' ? { k: piece.slice(1, -1) } : piece));
  return { parts: parts.map(cut), forget: cut(forget) };
}

/**
 * How the script is to draw: SlukaCC's settings for its subtitles, the colours
 * a word of the line wears at each level (content/reader.js applyColors, and
 * content.css for SlukaCC's own colours), and the panel's palette
 * (content/ui.js _levelVars).
 */
function look(player) {
  const id = player.lang;
  const script = scriptOf(id, player);
  const cjk = CJK_LANGS.has(id);
  const drawn = O.pageScheme ? O.pageScheme(settings) : settings;
  const cc = (O.ccScheme ? O.ccScheme(settings) : settings.cc) || {};
  const colors = drawn.colors || {};
  const seenAlpha = Array.isArray(drawn.seenAlpha) ? drawn.seenAlpha : [];
  const newAlpha = Number.isFinite(drawn.newAlpha) ? drawn.newAlpha : 0.2;
  const fade = drawn.levelStyle === 'fade';
  const level = (i) => (O.levelColour ? O.levelColour(drawn, i) : colors.seen) || '#f7a800';
  const line = (i) => (O.levelLine ? O.levelLine(drawn, i) : level(i));

  // What each level wears in the subtitle: a fill behind the word, a line under it, or the letters' own colour.
  const words = {};
  const own = !!cc.colours?.own;
  if (settings.highlights === false) {
    /* highlights off: plain words */
  } else if (own) {
    const c = cc.colours;
    const learning = (i) => (O.ccLevelColour?.(cc, i) || (i === 0 ? c.learning : `#${towardWhite(c.learning, 1 - i * 0.2)}`));
    const inks = { 0: c.new, 1: learning(0), 2: learning(1), 3: learning(2), 4: learning(3), 5: c.known, 6: c.ignored || c.known, 7: c.known };
    if (cc.colourStyle === 'fill') {
      const a = Array.isArray(cc.levelAlpha) ? cc.levelAlpha : [0.6, 0.45, 0.3, 0.18];
      const strength = { 0: cc.newAlpha ?? 0.45, 1: a[0], 2: a[1], 3: a[2], 4: a[3], 5: cc.knownAlpha ?? 0.18, 6: cc.knownAlpha ?? 0.18, 7: cc.knownAlpha ?? 0.18 };
      for (const [st, ink] of Object.entries(inks)) words[st] = { fill: [hex(ink, 'ffffff'), Math.max(0, Math.min(1, Number(strength[st]) || 0))] };
    } else {
      for (const [st, ink] of Object.entries(inks)) words[st] = { ink: hex(ink, 'ffffff') };
    }
  } else {
    words[0] = { fill: [hex(colors.new, '3b82f6'), Math.min(0.5, newAlpha * 2)] };
    for (let i = 0; i < 4; i++) {
      const filled = i < 3 || fade;
      words[i + 1] = {
        ...(filled ? { fill: [hex(level(i), 'f7a800'), Math.min(0.55, (seenAlpha[i] ?? 0.2) * 0.87)] } : {}),
        // On the dark box the line is the level's colour as picked: darkened, as a page needs it, it vanishes.
        ...(i >= 2 && !fade ? { line: hex(level(i), 'f7a800') } : {}),
      };
    }
  }

  const face = O.ccFontFor ? O.ccFontFor(cc, id) : { font: cc.font, fontName: cc.fontName };
  const sans = CC_SANS[script] || CC_SANS[''];
  let stack = sans;
  if (face?.font === 'serif') stack = [...(CC_SERIF_BY[script] || []), ...CC_SERIF, ...sans];
  else if (face?.font === 'mono') stack = [...CC_MONO, ...(cjk ? [] : ['monospace']), ...sans];
  else if (face?.font === 'own' && face.fontName) stack = [String(face.fontName), ...sans];

  let theme = 'light';
  try {
    theme = O.resolveTheme && O.themeChoice ? O.resolveTheme(O.themeChoice(settings)) : 'light';
  } catch {
    /* the light one */
  }
  const keys = gradeKeys();
  const wordScript = (script === 'hant' || script === 'hans' || script === 'ja') ? script : ({ ko: 'hangul', th: 'thai', ar: 'arabic' }[id] || 'latin');
  return {
    cjk,
    size: CC_SIZE[cc.size] || 1,
    pos: Number.isFinite(cc.position) ? cc.position : 8,
    bg: Math.max(0, Math.min(1, (cc.background ?? 84) / 100)),
    light: cc.theme === 'light',
    line_height: cjk ? 1.42 : 1.34,
    spacing: id === 'zh' || id === 'yue' ? 0.03 : 0.01,
    // Each text breaks where its writing allows: between any two words where none are spaced apart.
    spaced: !(cjk || id === 'th'),
    fonts: { cc: stack, ui: UI_FONT, word: WORD_FONTS[wordScript] || WORD_FONTS.latin },
    font_lang: script === 'hant' ? (id === 'yue' ? 'zh-hk' : 'zh-tw') : script === 'hans' ? 'zh-cn' : FONT_LANG[id] || '',
    ui_font: String(desktop?.ui_font || ''),
    // The app's own setting for a larger or smaller Sluka in mpv ([mpv] scale).
    scale: Number(desktop?.mpv_scale) > 0 ? Number(desktop.mpv_scale) : 1,
    words,
    theme: theme === 'dark' ? 'dark' : 'light',
    // Which engine draws Sluka's pages here: a few things (where furigana sit) are set a little differently by each.
    engine: /\bChrom(?:e|ium)\//.test(navigator.userAgent) ? 'chromium' : 'webkit',
    panel: {
      new: onWhite(colors.new || '#3b82f6', Math.max(newAlpha, 0.45), 'a7c7fb'),
      levels: [0, 1, 2, 3].map((i) => onWhite(level(i), seenAlpha[i] ?? 0.3, 'facb66')),
      lines: fade ? ['', ''] : [hex(line(2), 'a87200'), hex(line(3), 'a87200')],
      fade,
      twin: onWhite(colors.twin || '#ff79c6', Math.max(newAlpha, 0.45), 'ffb7df'),
    },
    hover_delay: Number.isFinite(settings.hoverDelayMs) ? settings.hoverDelayMs / 1000 : 0.12,
    keys,
    // The panel's Anki key, while Settings → Anki has the panel's button on for the language ('' otherwise).
    anki_key: ankiLookKey(id),
    // The key that says the open word (Settings → Keyboard, V), where there is a voice to say it ('' otherwise).
    say_key: sayLookKey(),
    // The AI check's key (Settings → Keyboard, F), for a panel open, where the check is on ('' otherwise).
    ask_key: askLookKey(),
    text: {
      known: S.T('Known'),
      ignore: S.T('Ignore'),
      // The title of the level a word is at, which puts it back to New when pressed again (content/ui.js lvlBtn).
      back: S.T('Back to new'),
      legend: legend(keys),
      labels: Object.fromEntries(Object.entries(STATUS_LABEL).map(([st, name]) => [st, S.T(name)])),
      also: O.Tx ? O.Tx('other entries', 'Also') : 'Also',
    },
  };
}

/**
 * The faces those lists come to on this computer, where the app looks them up
 * for the script (Windows, which has no fontconfig for the script to ask);
 * null where the script does it itself.  Asked once for each set of lists.
 */
const facesAsked = new Map();
async function facesFor(how) {
  if (!how?.fonts) return null;
  const asked = { stacks: how.fonts, lang: how.font_lang || '' };
  const key = JSON.stringify(asked);
  if (!facesAsked.has(key)) {
    facesAsked.set(key, api('fonts', asked).then((answer) => answer?.faces || null, () => null));
  }
  return facesAsked.get(key);
}

async function ready(player, { quiet = false } = {}) {
  const id = pickLanguage(player);
  player.lang = id;
  let name = id;
  try {
    name = S.languageName(id) || id;
  } catch {
    /* a language Sluka no longer names */
  }
  let how = {};
  try {
    how = look(player);
    how.faces = await facesFor(how);
  } catch (err) {
    // The words are worth more than their dress: without the look the script draws with Sluka's defaults.
    report(err);
  }
  await send(player, { t: 'ready', v: PROTOCOL, lang: id, lang_name: name, quiet, look: how });
  // Its words loaded now, not on the first line of the film.
  language(id).catch(report);
}

// ------------------------------------------------------------ a line

/** A line's tokens as the reader's engine has them for a page (content/engine.js): by the language's analyser where it has one. */
async function tokensOf(L, text) {
  if (L.lang.tokenizeAll) return (await L.lang.tokenizeAll([text]))[0];
  if (L.lang.prime) await L.lang.prime([text]);
  // A line of a film opens a sentence, which is what German's capitals are read by.
  return L.lang.tokenizeInContext ? L.lang.tokenizeInContext(text, () => true) : L.lang.tokenize(text);
}

async function cut(L, text) {
  const tokens = await tokensOf(L, text);
  const toks = [];
  const extra = [];   // what the analyser said of each word, for its panel: kept here, not sent
  const words = [];   // the words, each with where it is in the text: what reading is counted in (progress.js)
  let at = 0;      // in UTF-16 units, as JavaScript counts
  let byte = 0;    // in UTF-8 bytes, as mpv's Lua counts
  for (const tok of tokens || []) {
    const piece = String(tok.text ?? '');
    if (!piece) continue;
    // Where the tokenizer's piece really is: it is trusted to be in order, not to be gapless.
    const found = text.indexOf(piece, at);
    if (found < 0) continue;
    byte += bytes(text.slice(at, found));
    const start = byte;
    byte += bytes(piece);
    at = found + piece.length;
    if (tok.word) words.push({ text: piece, at: found });
    if (!tok.word && !tok.grammar) continue;
    const key = keyOf(L, tok);
    const grammar = !!tok.grammar && !tok.word;
    toks.push({ s: start, e: byte, key, st: grammar ? STATUS.IGNORED : L.vocab.get(key), g: grammar || undefined });
    // `a`, `b`: where the word is in the line, as JavaScript counts -- for its Anki card's sentence (cardSentenceOf).
    extra.push({ rd: tok.reading || '', bound: !!tok.bound, a: found, b: at });
  }
  return { toks, extra, words };
}

async function line(player, m) {
  const text = String(m.text ?? '');
  const L = await language(player.lang || pickLanguage(player));
  const { toks, extra, words } = await cut(L, text);
  player.line = { id: m.id, text, toks, extra, lang: L.id };
  // A film's lines, with their times in it (the script in mpv says them): for a card's clip (mpvMedia).
  if (Number.isFinite(Number(m.start)) && Number(m.end) > Number(m.start)) {
    player.history = [...(player.history || []).filter((l) => l.id !== m.id).slice(-7), { id: m.id, text, start: Number(m.start), end: Number(m.end) }];
  }
  await send(player, { t: 'tokens', id: m.id, toks, rtl: L.id === 'ar' || undefined });
  // Answered first: what is read is counted after (progress.js), and nothing there can hold a line up.
  await tracked(() => progress?.line(player, kindOf(player), L, text, words, m));
}

/** A grade made elsewhere: the words of the line each player is showing are looked at again. */
function repaint(L) {
  for (const player of players.values()) {
    if (player.line?.lang !== L.id) continue;
    for (const tok of player.line.toks) {
      if (tok.g) continue;
      const now = L.vocab.get(tok.key);
      if (now === tok.st) continue;
      tok.st = now;
      send(player, { t: 'status', key: tok.key, st: now, label: label(now) });
    }
  }
}

// ------------------------------------------------------------ a word's card

/** A form pointing at its dictionary form, as Sluka's own glosses read one (lib/word-gloss.js FORM_OF). */
const FORM_OF = /\bof\s+([^\s,;()[\]“”"]+)\s*\.?\s*$/;
/** A part of speech in front of a reading, which the panel sets apart (content/ui.js POS, readingHtml). */
const POS = /^((?:proper |auxiliary )?(?:noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|determiner|article|numeral|number|particle|prefix|suffix|phrase|proverb|contraction|abbreviation|letter|symbol|classifier|postposition|participle))(?:\s+(.*))?$/i;
/** The languages whose reading can itself be a plain lowercase word, and is never taken for a label. */
const READING_LANGS = new Set(['zh', 'yue', 'ja', 'ko']);

/**
 * A kana reading with its pitch, once for each of its numbers, as Sluka's
 * panel draws it (content/ui.js pitchHtml): which beats are high, where the
 * line starts, the beat the pitch falls after, and the tail of a flat word.
 */
function pitchDrawings(kana, accents) {
  if (!O.morae || !O.pitchShape) return [];
  const beats = O.morae(kana);
  const last = beats.length - 1;
  const out = [];
  for (const n of accents) {
    const shape = O.pitchShape(beats.length, n);
    if (!shape) continue;
    out.push({
      n,
      beats: beats.map((b, i) => ({
        t: b,
        hi: shape.high[i] ? true : undefined,
        rise: shape.high[i] && !shape.high[i - 1] ? true : undefined,
        drop: shape.drop === i ? true : undefined,
        tail: i === last && n === 0 ? true : undefined,
      })),
    });
  }
  return out;
}

/** The language's frequency list with each word's place in it, and the places past its end (content/reader.js loadList, loadTail). */
function places(L) {
  if (!O.FREQUENCY_ORDERED?.has(L.id) || !O.freqTable || !O.listRanks) return Promise.resolve(null);
  if (!L.places) {
    L.places = (async () => {
      const [{ words, ranks }, own] = await Promise.all([O.freqTable(L.id, L.mode), O.readOwnList ? O.readOwnList(L.id).catch(() => null) : null]);
      const list = O.listRanks(words, null, ranks);
      let tail = null;
      // A list of your own ranks nothing past its end.
      if (!own && O.tailFile && O.parseFreq && O.fetchGzipText) {
        try {
          tail = O.listRanks(O.parseFreq(await O.fetchGzipText(chrome.runtime.getURL(`data/${L.id}/${O.tailFile(L.mode)}`))).words);
        } catch {
          /* a language built before the tail: its rarer words show no place */
        }
      }
      return { list, tail };
    })().catch(() => null);
  }
  return L.places;
}

/** "1,234th most common", or '' for a word with no place to give (content/reader.js rankNote). */
async function rankNote(L, key) {
  const known = await places(L);
  if (!known) return '';
  const past = known.tail?.rank?.get(key);
  const place = known.list.rank?.get(key) || (past ? known.list.size + past : 0);
  if (!place) return '';
  const n = place.toLocaleString(O.uiLocale ? O.uiLocale() : undefined);
  return S.T('{nth} most common', { nth: O.Tord ? O.Tord(place, { n }) : n });
}

/**
 * What Sluka's card and panel say about a word of the line, in pieces the
 * script lays out: the headword with its furigana, the reading with its pitch,
 * the short meanings of the card, the dictionary's own for the panel, the form
 * the line has it in, and how common it is.
 *
 * @param {object} L the language, made ready
 * @param {string} key what the word is filed under
 * @param {string} text the word as the line writes it
 * @param {{rd?: string, bound?: boolean}} at what the analyser said of it there
 */
async function describe(L, key, text, at = {}) {
  const word = lookupKey(L, key);
  const found = await S.lookupBatch([word], L.id);
  const filed = found[word] || null;
  // The reading the word has in this line leads, where the language's analyser reads one (lib/languages.js entryInContext).
  let entry = filed;
  try {
    if (filed && L.lang.entryInContext) entry = L.lang.entryInContext(filed, at.rd || null, { word: text, bound: !!at.bound }) || filed;
  } catch {
    entry = filed;
  }
  const status = L.vocab.get(key);
  const out = { key, st: status, label: label(status) };

  // The headword: the word as filed, or as written where that is the same word, so a name keeps its capital.
  const folded = S.surfaceKey(L.lang, text || '');
  out.head = [{ t: text && folded === key ? text : key }];
  const mode = O.readingMode ? O.readingMode(settings, L.id) : 'none';
  const fmt = (reading, how = mode) => {
    try {
      return L.lang.formatReading?.(reading, how) || '';
    } catch {
      return '';
    }
  };
  const spoken = entry ? entry.readingsHere?.[0] ?? S.pronunciationOf(entry) : '';

  // Japanese: kana over each run of kanji (content/ui.js _headFurigana). The analyser's reading of the word as
  // it stands first, which alone knows that form's sound; then the dictionary's, which fits the dictionary form.
  let furigana = '';
  if (L.id === 'ja' && O.furiganaSegments && mode !== 'none') {
    for (const reading of [text === key ? at.rd || '' : '', entry ? S.pronunciationOf(entry) : '']) {
      const segs = reading ? O.furiganaSegments(key, reading) : null;
      if (!segs) continue;
      furigana = reading;
      out.head = segs.map(({ text: t, r }) => (r ? { t, r: mode === 'katakana' && O.toKatakana ? O.toKatakana(r) : r } : { t }));
      break;
    }
  }

  // The reading under it, a Japanese one with its pitch drawn (content/ui.js _definition).
  out.reading = [];
  if (entry && spoken) {
    const said = entry.readingsHere?.length ? entry.readingsHere : [spoken];
    let accentsOf = () => null;
    if (L.id === 'ja' && O.pitchRowsOf && O.pitchFinder && settings.pitchAccent !== false && mode !== 'none') {
      accentsOf = O.pitchFinder(await O.pitchRowsOf(key, entry).catch(() => []));
    }
    const inKana = mode === 'hiragana' || mode === 'katakana';
    for (const r of said) {
      const accents = accentsOf(r);
      const pitch = accents ? pitchDrawings(fmt(r, mode === 'katakana' ? 'katakana' : 'hiragana'), accents) : [];
      // In kana the drawing is the reading; beside romaji it is the kana, since the beats are the kana's.
      const piece = { text: pitch.length && inKana ? '' : fmt(r) || (READING_LANGS.has(L.id) ? '' : String(r)) };
      if (pitch.length) piece.pitch = pitch;
      if (!READING_LANGS.has(L.id)) {
        const m = POS.exec(piece.text);
        if (m) Object.assign(piece, { pos: m[1], text: m[2] || '' });
      }
      if (piece.text || piece.pos || piece.pitch) out.reading.push(piece);
    }
    // The same kana once is enough: not again as a plain line under a headword that carries them (_lineUnderFurigana).
    if (furigana && inKana && out.reading.length === 1 && !out.reading[0].pitch && out.reading[0].text === fmt(furigana)) out.reading = [];
  }

  // What you wrote down yourself says it first, as it does in Sluka (content/reader.js glanceSenses).
  const own = (await S.loadMeanings(L.id))[key];
  const mine = typeof own === 'string' ? own : own?.text;
  let short = [];
  if (mine) {
    short = O.meaningSenses ? O.meaningSenses(mine) : [mine];
    out.mine = String(mine).slice(0, 300);
  } else if (entry) {
    // "second-person singular of ir" is answered with what ir means: that word is fetched too.
    const lemmas = new Set();
    for (const [, glosses] of entry.r || []) {
      for (const gloss of (glosses || []).slice(0, 4)) {
        const named = String(gloss ?? '').match(FORM_OF)?.[1];
        if (named && named !== word) lemmas.add(named);
      }
    }
    const more = lemmas.size ? await S.lookupBatch([...lemmas].slice(0, 6), L.id) : {};
    const follow = (form) => more[form] || found[form] || null;
    short = S.glossSenses(entry, { follow, english: L.id !== 'en' });
    if (!short.length && O.nativeSenses) short = O.nativeSenses(entry);
    if (!short.length && L.id !== 'en') short = S.glossSenses(entry, { follow });
    // No short sense to be had: the dictionary's meanings whole, its last resort.
    if (!short.length) short = O.wholeSenses ? [...O.wholeSenses(entry)] : (entry.r?.[0]?.[1] || []).map((g) => String(g ?? '').trim()).filter(Boolean);
  }
  short = short.map((sense) => String(sense ?? '').trim()).filter(Boolean);
  out.lead = (short[0] || '').slice(0, 300);
  out.more = short.slice(1, 4).map((sense) => sense.slice(0, 120));

  // The dictionary's own meanings, for the panel a click opens: those of the reading that leads, and the
  // word's other readings a line each.
  out.senses = [];
  out.also = [];
  if (entry?.r?.length) {
    // CC-CEDICT writes its cross-references for the file: set as words, in the spelling the line was written in.
    const traditional = !(entry.s && entry.s !== entry.t && key === entry.s);
    const plain = (gloss) => {
      const text = String(gloss ?? '').trim();
      if (L.id !== 'zh' || !O.glossParts) return text;
      try {
        return O.glossParts(text, { traditional }).map((part) => (part.text !== undefined ? part.text : [part.word, part.reading && fmt(part.reading)].filter(Boolean).join(' '))).join('');
      } catch {
        return text;
      }
    };
    const headOf = (reading) => {
      const text = O.glossSource ? O.glossSource(reading).text : String(reading ?? '');
      return fmt(text) || text;
    };
    const [first, ...rest] = entry.r;
    const all = (first[1] || []).map(plain).filter(Boolean);
    out.senses = all.slice(0, SENSES_SHOWN).map((sense) => sense.slice(0, 260));
    if (all.length > out.senses.length) out.senses_more = all.length - out.senses.length;
    out.also = rest.slice(0, ALSO_SHOWN).map(([reading, glosses]) => ({
      head: String(headOf(reading)).slice(0, 40),
      gloss: (glosses || []).slice(0, 3).map(plain).filter(Boolean).join('; ').slice(0, 160),
    })).filter((row) => row.head || row.gloss);
  }

  // The form the line has it in, named (content/reader.js extraFor, content/ui.js _inflectionLine).
  if (text && !(text === key && L.mode !== COUNTING.FORM)) {
    try {
      const told = L.lang.inflection?.(text, word) ?? null;
      const why = Array.isArray(told) ? told : told?.why;
      if (why?.length) out.inflection = { form: String(told.spelled || text), why: why.map((w) => S.T(w)).join(' · ') };
    } catch {
      /* a form the language cannot name is left unnamed */
    }
  }

  out.rank = await rankNote(L, key).catch(() => '');
  out.none = entry || mine ? '' : S.T('No entry in the dictionary.');
  return out;
}

async function lookup(player, m) {
  await tracked(() => progress?.active(player));
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  const i = Number(m.tok) - 1;
  const mine = player.line?.id === m.id && player.line.toks[i]?.key === key;
  // A click on a new word files it at level 1, as a click does in Sluka's pages (its own setting says whether).
  if (m.pin && mine && !player.line.toks[i].g && settings.autoLingqOnClick !== false && L.vocab.get(key) === STATUS.NEW) {
    await grade(player, { key, text: m.text, status: STATUS.L1 });
  }
  const entry = await describe(L, key, String(m.text ?? ''), (mine && player.line.extra?.[i]) || {});
  // (drawn as the extension draws them for the pages' open panel; as text for mpv and the small card)
  await withOwnDicts(entry, L, key, String(m.text ?? ''), !!m.pin && kindOf(player) !== 'mpv').catch(report);
  const looks = looksNote(await looksOf(L, key, !!m.pin && mine));
  // A pinned panel's Anki key, as a page's panel has it (content/ui.js _ankiKey): only while Settings → Anki has it on.
  let anki = null;
  let tools = null;
  if (m.pin && mine && !player.line.toks[i].g) {
    player.ankiAt = { id: m.id, tok: m.tok, key, text: String(m.text ?? ''), lang: L.id };
    anki = await ankiNote(L, key, String(m.text ?? '')).catch((err) => (report(err), null));
    tools = await headTools(L).catch((err) => (report(err), null));
    if (tools && speakerThere()) tools.say = { title: sayTitle(), icon: SPEAKER_ICON };
    if (tools && aiThere()) tools.ask = await askTool(L, key, entry).catch((err) => (report(err), undefined));
  }
  await send(player, { t: 'entry', id: m.id, tok: m.tok, ...entry, ...looks, ...(anki ? { anki } : {}), ...(tools ? { tools } : {}) });
  // Settings → Voice → "Say a word when you open it", as a click on a page says it (content/reader.js sayOnClick):
  // a word of mpv's subtitles once the video is paused, as a page's video words wait for theirs.
  if (tools?.say && settings.tts?.sayOnClick && (GAME_PLAYERS.has(player.key) || m.paused === true)) {
    speakWord(player, m).catch(report);
  }
}

// ------------------------------------------------------------ a grade

async function grade(player, m) {
  await tracked(() => progress?.active(player));
  const status = Number(m.status);
  if (![STATUS.NEW, STATUS.L1, STATUS.L2, STATUS.L3, STATUS.L4, STATUS.KNOWN, STATUS.IGNORED].includes(status)) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  if (!key) return;
  const tok = player.line?.toks?.find((t) => t.key === key);
  if (tok?.g) return;
  // Sluka's own store decides, the free allowance included: a grade it turns down stays turned down.
  const before = L.vocab.get(key);
  const taken = status === before ? true : L.vocab.set(key, status, pairOf(L, key, String(m.text ?? '')));
  if (!taken) {
    await send(player, {
      t: 'say',
      text: S.T('The free allowance of words for this language is used up. A licence lifts it: Settings → Licence.'),
      seconds: 6,
    });
  }
  // Written now rather than when a timer comes round: this page is never on screen.
  await L.vocab.flush().catch(report);
  const now = L.vocab.get(key);
  if (taken && now !== before) toAnki(player, L, key, String(m.text ?? ''), now);
  for (const other of players.values()) {
    if (other.line?.lang !== L.id) continue;
    for (const t of other.line.toks) if (t.key === key) t.st = now;
    send(other, { t: 'status', key, st: now, label: label(now), graded: other === player });
  }
}

// ------------------------------------------------------------ Anki

/*
 * Anki: the panel's Anki button, or its key, in the floating subtitles, in
 * Sluka Vision and in mpv -- this word into the deck for picked words, with
 * the sentence it stands in, as a page's panel does it (content/reader.js
 * pickForAnki): the extension's own round makes the card, with the note type,
 * the deck and what goes on it as Settings → Anki says.  A game's line brings
 * its sound and a picture of the game (the app keeps them: ankicards.py),
 * cut and made into the files the extension puts on its cards -- the clip an
 * .m4a by the extension's own encoder (offscreen/m4a.js), the picture a JPEG
 * 640 across (content/cc-clip.js) -- and sent as a page sends a clip
 * (MSG.ANKI_MEDIA).  Where the video is chosen, the picture goes instead, as
 * the extension puts one where a video cannot be made.  And a grade tells
 * Anki of the word as a page's grade does (content/reader.js toAnki).
 *
 * Every part of the extension used here is looked for, and none is needed:
 * without one, the panel has no Anki key, and nothing else changes.
 */
const A = {};
for (const [path, names] of Object.entries({
  '/lib/constants.js': ['MSG'],
  '/lib/settings.js': ['ankiFor', 'pictureOnCard', 'videoOnCard', 'translateFor', 'ownDictPlaceFor'],
  '/lib/dict-links.js': ['shownLinks', 'linkFor'],
  '/lib/anki-note-types.js': ['pickChoice'],
  '/lib/anki-icon.js': ['ankiIcon'],
  '/lib/languages.js': ['LANGUAGE_LABELS', 'languageInText'],
  '/lib/speech.js': ['createSpeaker', 'noVoiceLine'],
  // Your own dictionaries (Settings → Dictionary → Your own dictionaries), as a page's panel shows them.
  '/lib/own-dicts/render.js': ['ownDictsHtml', 'ownDictsCss', 'glanceSenses'],
  '/lib/own-dicts/lead.js': ['leadWithSluka'],
  // The AI check (Settings → AI check), the panel's ✦.
  '/lib/ai-providers.js': ['aiCompanyOf'],
  '/lib/cloud-voice.js': ['cloudProvider', 'ownVoiceFor', 'ownWordVoiceFor', 'voiceNow', 'volumeOf'],
  '/content/anki-sentence.js': ['cardSentence'],
  '/offscreen/m4a.js': ['encodeClip'],
  '/offscreen/file-clip.js': ['openFileClip'],
  '/offscreen/video-clip.js': ['cutVideo'],
  '/lib/clip-range.js': ['clipAround'],
})) {
  const mod = await import(path).catch(() => null);
  for (const name of names) if (mod && name in mod) A[name] = mod[name];
}
/** Whether this version of Sluka has what a card is made with. */
const ankiThere = () => !!(A.MSG?.ANKI_PICK && A.ankiFor && globalThis.chrome?.runtime?.sendMessage && globalThis.chrome?.storage?.local);
/** The picture on a card, at most this wide, and its JPEG quality (content/cc-clip.js). */
const PICTURE_MAX_W = 640;
const PICTURE_QUALITY = 0.82;
/** The players a game's line comes to, whose sound and picture the app keeps. */
const GAME_PLAYERS = new Set(['bar', 'vision']);
/** Words picked here whose pick the list does not show yet (content/reader.js state.anki.pending). */
const ankiPending = new Set();

async function ankiAsk(msg) {
  try {
    return (await chrome.runtime.sendMessage(msg)) ?? null;
  } catch {
    return null;
  }
}

/** The word a card is filed under: counting every form, the dictionary form (content/reader.js ankiKey). */
function ankiWord(L, key, text) {
  return L.mode === COUNTING.FORM ? pairOf(L, key, text).lemma || key : key;
}

/** The key that adds to Anki, where it is one plain character that grades nothing (Settings → Keys). */
function ankiKeyChar() {
  const k = settings.keys?.ankiPick ?? 'p';
  const plain = typeof k === 'string' && /^[a-z0-9]$/i.test(k) ? k.toLowerCase() : '';
  return plain && !Object.values(gradeKeys()).includes(plain) ? plain : '';
}

/** The Anki key a player is told with its look: only while the panel's button is on for its language. */
function ankiLookKey(lang) {
  try {
    return ankiThere() && A.ankiFor(settings, lang).pick ? ankiKeyChar() : '';
  } catch {
    return '';
  }
}

/** How a word stands with Anki, as a page's panel tells it (content/reader.js ankiStateOf): null while the button is off. */
async function ankiStateOf(lang, word) {
  if (!ankiThere()) return null;
  const anki = A.ankiFor(settings, lang);
  if (!anki.pick) return null;
  const own = anki.decks?.[lang] || `Sluka::${A.LANGUAGE_LABELS?.[lang] || lang}`;
  const chosen = anki.pickDecks?.[lang] && anki.pickDecks[lang] !== own ? anki.pickDecks[lang] : null;
  const deck = chosen || own;
  const sentKey = KEY.ankiSent(lang);
  const pickedKey = KEY.ankiPicked(lang);
  const got = await chrome.storage.local.get([sentKey, pickedKey]);
  const rec = got[sentKey]?.[word];
  const picked = got[pickedKey]?.[word];
  const active = !!rec?.n && !rec.s;
  if (ankiPending.has(`${lang}|${word}`) || picked?.c || picked?.nw) return { state: 'queued', deck };
  if (active && (!chosen || !!rec.p)) return { state: 'in', deck: rec.p || deck };
  if (picked) return { state: 'queued', deck };
  return { state: active ? 'move' : 'add', deck };
}

/** The panel's Anki key, for a page to draw: its state, what it says, its mark (lib/anki-icon.js) and its key. */
async function ankiNote(L, key, text) {
  const at = await ankiStateOf(L.id, ankiWord(L, key, text));
  if (!at) return null;
  const k = ankiKeyChar();
  const deck = at.deck;
  const says = {
    add: S.T('Add to Anki, into {deck}', { deck }),
    move: S.T('Move its Anki card into {deck}', { deck }),
    queued: S.T('Waiting for Anki…'),
    in: S.T('In Anki, in {deck}. Opens its card in Anki', { deck }),
  }[at.state] || S.T('Add to Anki, into {deck}', { deck });
  return { state: at.state, title: k ? `${says} (${k.toUpperCase()})` : says, icon: A.ankiIcon ? A.ankiIcon(at.state) : '', key: k };
}

/** The open panel's Anki key told again, as the list of picks or of cards changes. */
async function ankiRefresh(player) {
  const at = player.ankiAt;
  if (!at || !players.has(player.key)) return;
  const L = await language(at.lang);
  const note = await ankiNote(L, at.key, at.text);
  await send(player, { t: 'anki', id: at.id, tok: at.tok, ...(note || { state: '' }) });
}

if (ankiThere()) {
  chrome.storage.onChanged?.addListener?.((changes, area) => {
    if (area && area !== 'local') return;
    if (!Object.keys(changes || {}).some((k) => k.startsWith('ankiSent:') || k.startsWith('ankiPicked:'))) return;
    for (const player of players.values()) ankiRefresh(player).catch(report);
  });
}

/**
 * The sentence the word stands in, for its card (content/anki-sentence.js cardSentence, as a page reads it): the
 * line's text laid out as SlukaCC's subtitle is, its paragraphs as blocks no sentence crosses, and read around the
 * word.  `{ t, a, l }`, or null.
 */
function cardSentenceOf(L, text, a, b) {
  if (!(b > a) || a < 0 || b > text.length) return null;
  if (A.cardSentence && globalThis.document?.body) {
    const host = document.createElement('div');
    host.className = 'llr-cc-txt';
    host.hidden = true;
    let pos = 0;
    let word = null;
    for (const part of text.split('\n')) {
      const block = document.createElement('div');
      const from = pos;
      const to = pos + part.length;
      if (a >= from && b <= to) {
        word = document.createElement('span');
        word.textContent = part.slice(a - from, b - from);
        block.append(part.slice(0, a - from), word, part.slice(b - from));
      } else {
        block.append(part);
      }
      host.append(block);
      pos = to + 1;
    }
    document.body.append(host);
    try {
      const got = word ? A.cardSentence(word, word, { lang: L.id, locale: L.id }) : null;
      if (got?.t) return got;
    } catch (err) {
      report(err);
    } finally {
      host.remove();
    }
  }
  const line = text.split('\n').find((_, i, all) => {
    const from = all.slice(0, i).reduce((n, p) => n + p.length + 1, 0);
    return a >= from && b <= from + all[i].length;
  }) ?? text;
  const from = text.indexOf(line);
  return { t: line, a: a - from, l: b - a };
}

const UNSPACED = /[　-ヿ㐀-鿿豈-﫿＀-￯฀-๿]/;

/** Lines either side taken into a card's sentence (Settings → Anki, "With the sentence before and after"). */
function withLines(sentence, before = [], after = []) {
  if (!sentence) return sentence;
  const joint = (x, y) => (UNSPACED.test(x.at(-1) || '') && UNSPACED.test(y[0] || '') ? '' : ' ');
  let t = sentence.t;
  let a = sentence.a;
  for (const prev of before.map((x) => String(x || '').replace(/\s+/g, ' ').trim()).filter(Boolean).reverse()) {
    const glue = joint(prev, t);
    t = `${prev}${glue}${t}`;
    a += prev.length + glue.length;
  }
  for (const next of after.map((x) => String(x || '').replace(/\s+/g, ' ').trim()).filter(Boolean)) t = `${t}${joint(t, next)}${next}`;
  return { ...sentence, t, a };
}

/** The word's sentence in the player's line, where the word is in it. */
function lineSentence(player, L, key, m = {}) {
  const line = player.line;
  if (!line) return null;
  const i = Number(m.tok) - 1;
  let at = line.id === m.id && line.toks[i]?.key === key ? i : line.toks.findIndex((t) => t.key === key);
  const extra = at >= 0 ? line.extra?.[at] : null;
  if (!extra || !Number.isInteger(extra.a)) return null;
  return cardSentenceOf(L, line.text, extra.a, extra.b);
}

/** A grade, for Anki, while Settings → Anki is in use (content/reader.js toAnki): with its sentence while words go by themselves. */
function toAnki(player, L, key, text, status) {
  if (!ankiThere()) return;
  const anki = A.ankiFor(settings, L.id);
  if (!anki.send && !anki.pick) return;
  const sentence = anki.send && status >= STATUS.L1 && status <= STATUS.L4 ? lineSentence(player, L, key) : null;
  ankiAsk({ type: A.MSG.ANKI_GRADED, lang: L.id, word: ankiWord(L, key, text), sentence });
}

const fromB64 = (b64) => Uint8Array.from(atob(String(b64 || '')), (c) => c.charCodeAt(0));
function toB64(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
}

/** A 16-bit one-channel WAV's samples, -1 to 1 (as the app makes it: gamesound.py wav). */
function wavSamples(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let at = 12;
  while (at + 8 <= bytes.length) {
    const id = String.fromCharCode(...bytes.subarray(at, at + 4));
    const size = view.getUint32(at + 4, true);
    if (id === 'data') {
      const n = Math.floor(Math.min(size, bytes.length - at - 8) / 2);
      const out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = view.getInt16(at + 8 + i * 2, true) / 32768;
      return out;
    }
    at += 8 + size + (size & 1);
  }
  return new Float32Array(0);
}

/** A picture (a BMP from the app, a JPEG from mpv) as the card's JPEG, at most PICTURE_MAX_W across: base64. */
async function cardPicture(bytes, type = 'image/bmp') {
  const image = await createImageBitmap(new Blob([bytes], { type }));
  const w = Math.min(PICTURE_MAX_W, image.width);
  const h = Math.max(1, Math.round((image.height * w) / image.width));
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(image, 0, 0, w, h);
  image.close?.();
  const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: PICTURE_QUALITY });
  return toB64(new Uint8Array(await blob.arrayBuffer()));
}

/** The clip and the picture of a game's line, onto its card once there is one (lib/anki-media.js keeps them till then). */
async function gameMedia(player, lang, word, where, media) {
  const audio = media?.audio !== false && where.sound;
  const picture = where.picture && (A.pictureOnCard?.(media) || A.videoOnCard?.(media));
  if (!audio && !picture) return;
  const got = await api('cards/media', { ticket: where.ticket, audio, picture, context: media?.context === true }).catch(() => null);
  if (!got?.ok) return;
  const msg = { type: A.MSG.ANKI_MEDIA, lang, word };
  if (got.audio?.wav && A.encodeClip) {
    const file = await A.encodeClip(wavSamples(fromB64(got.audio.wav)), Number(got.audio.rate) || 24000).catch((err) => (report(err), null));
    if (file?.bytes?.length) msg.audio = { b64: toB64(file.bytes), ext: file.ext };
  }
  if (got.picture?.bmp) {
    const jpeg = await cardPicture(fromB64(got.picture.bmp)).catch((err) => (report(err), null));
    if (jpeg) msg.picture = { b64: jpeg, ext: 'jpg' };
  }
  if (!msg.audio && !msg.picture) return;
  const res = await ankiAsk(msg);
  if (!res?.ok && res?.error && res.error !== 'off') api('log', { level: 'warning', text: `anki: a game's clip and picture were turned away: ${res.error}` }).catch(() => {});
}

/** The rate a clip is cut at, as the extension keeps a video's sound for clips (offscreen/clip-host.js CLIP_RATE). */
const CLIP_RATE = 24000;
/** s the clip fades in and out over, as the extension's video clip's sound does (offscreen/clip-host.js fade). */
const FADE = 0.01;

function fade(x, rate) {
  const n = Math.min(Math.round(FADE * rate), Math.floor(x.length / 2));
  for (let i = 0; i < n; i++) {
    const g = 0.5 - 0.5 * Math.cos((Math.PI * i) / n);
    x[i] *= g;
    x[x.length - 1 - i] *= g;
  }
  return x;
}

/**
 * The clip, the picture and the video of a word picked in mpv, as SlukaCC makes them of a video file of yours (the
 * videos page): its line's sound and pictures read out of the file itself, a range at a time (offscreen/file-clip.js,
 * through the app: mpv/file), padded as a subtitle's are, with the lines either side where Settings → Anki asks
 * (lib/clip-range.js clipAround); the picture the frame on screen, which the script in mpv took as the word was picked
 * (mpv/shot); the video, where it is chosen, cut by the extension's own (offscreen/video-clip.js).
 */
async function mpvMedia(player, lang, word, m, media) {
  const audio = media?.audio !== false;
  const video = !!A.videoOnCard?.(media);
  const picture = !!(A.pictureOnCard?.(media) || video);
  const start = Number(m.start);
  const end = Number(m.end);
  const lines = player.history || [];
  const i = lines.findIndex((l) => l.id === m.id);
  let r = Number.isFinite(start) && end > start ? { from: Math.max(0, start - 0.25), to: end + 0.45 } : null;
  if (r && i >= 0 && A.clipAround) r = A.clipAround(lines, i, Infinity, { context: media?.context === true }) || r;
  const msg = { type: A.MSG.ANKI_MEDIA, lang, word };
  let file = null;
  let pcm = null;
  if (r && (audio || video) && A.openFileClip) {
    file = await A.openFileClip(`/__sluka__/api/mpv/file?player=${encodeURIComponent(player.key)}`, { sound: Number.isInteger(m.aid) ? m.aid : null })
      .catch((err) => (api('log', { level: 'info', text: `anki: the file in mpv cannot be read for a clip (${err?.message || err})` }).catch(() => {}), null));
    if (file?.hasSound) pcm = await file.pcm(r.from, r.to, CLIP_RATE).catch((err) => (report(err), null));
    if (audio && pcm?.length && A.encodeClip) {
      const made = await A.encodeClip(pcm, CLIP_RATE).catch((err) => (report(err), null));
      if (made?.bytes?.length) msg.audio = { b64: toB64(made.bytes), ext: made.ext };
    }
  }
  if (picture && typeof m.shot === 'string' && m.shot) {
    const got = await api('mpv/shot', { name: m.shot }).catch(() => null);
    const jpeg = got?.ok ? await cardPicture(fromB64(got.b64), 'image/jpeg').catch((err) => (report(err), null)) : null;
    if (jpeg) msg.picture = { b64: jpeg, ext: 'jpg' };
  }
  if (msg.audio || msg.picture) await ankiAsk(msg);
  // The video comes after its clip, as a message of its own (lib/anki-media.js keepMedia).
  if (video && msg.audio && file?.hasVideo && A.cutVideo) {
    const pictures = await file.video(r.from, r.to).catch(() => null);
    const made = pictures ? await A.cutVideo({ ...pictures, from: r.from, to: r.to, pcm: fade(pcm.slice(), CLIP_RATE), rate: CLIP_RATE }).catch((err) => (report(err), null)) : null;
    if (made?.webm) {
      await ankiAsk({ type: A.MSG.ANKI_MEDIA, lang, word, video: { webm: { b64: toB64(made.webm) }, ...(made.mp4 ? { mp4: { b64: toB64(made.mp4) } } : {}) } });
    }
  }
}

/** The panel's Anki button or key (content/reader.js pickForAnki). */
async function anki(player, m) {
  await tracked(() => progress?.active(player));
  if (!ankiThere()) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  const text = String(m.text ?? '');
  if (!key) return;
  const tok = player.line?.toks?.find((t) => t.key === key);
  if (tok?.g) return;
  const settingsNow = A.ankiFor(settings, L.id);
  if (!settingsNow.pick) {
    await send(player, { t: 'say', text: S.T("Couldn't send it to Anki. Is the button still on in Settings → Anki?"), seconds: 5 });
    return;
  }
  const word = ankiWord(L, key, text);
  const at = await ankiStateOf(L.id, word);
  // A blue word is filed at level 1 on the way, as a click opening it would: you are learning it now.
  if (L.vocab.get(key) === STATUS.NEW) await grade(player, { key, text, status: STATUS.L1 });
  // A game's line: which it was, the lines either side, its sound and the picture of the game now (ankicards.py).
  const game = GAME_PLAYERS.has(player.key);
  const pictured = !!(A.pictureOnCard?.(settingsNow.media) || A.videoOnCard?.(settingsNow.media));
  const where = game
    ? await api('cards/lines', { player: player.key, text: player.line?.text ?? '', ...(Number.isInteger(m.read) ? { read: m.read } : {}), picture: pictured }).catch(() => null)
    : null;
  let sentence = lineSentence(player, L, key, m);
  const context = settingsNow.media?.context === true;
  if (sentence && context && where?.found && player.key === 'bar') sentence = withLines(sentence, where.before, where.after);
  // A film's line (mpv): its times in the file; the line before it with it, where asked (SlukaCC's -1).
  const timed = !game && Number.isFinite(Number(m.start)) && Number(m.end) > Number(m.start);
  if (sentence && context && timed) {
    const lines = player.history || [];
    const i = lines.findIndex((l) => l.id === m.id);
    if (i > 0 && Number(m.start) - lines[i - 1].end < 10) sentence = withLines(sentence, [lines[i - 1].text], []);
  }
  // The form it stood in, for a card that shows it (content/reader.js formMet); and where it was met (anki-source.js).
  const form = L.mode === COUNTING.FORM ? (word !== key ? key : '') : S.surfaceKey(L.lang, text);
  if (sentence && form && form !== word && !/\s/.test(word)) sentence = { ...sentence, f: form };
  if (sentence && settingsNow.back?.source === true && where?.title) sentence = { ...sentence, src: { n: where.title } };
  if (sentence && settingsNow.back?.source === true && timed && typeof m.title === 'string' && m.title) {
    sentence = { ...sentence, src: { n: m.title, s: Math.max(0, Math.floor(Number(m.start))) } };
  }
  const clip = settingsNow.media?.audio !== false && (game ? !!(where?.found && where.sound) : timed && !!A.openFileClip);
  const { noteType, deck } = A.pickChoice ? A.pickChoice(settings, L.id) : {};
  const again = at?.state === 'in' || at?.state === 'move' ? settingsNow.again : 'update';
  const fresh = again === 'new';
  const pendingKey = `${L.id}|${word}`;
  if (at?.state === 'in' && !fresh) {
    const shown = await ankiAsk({ type: A.MSG.ANKI_BROWSE, lang: L.id, word });
    const said = shown?.ok && shown.found ? S.T('Opened in Anki, in {deck}', { deck: at.deck })
      : shown?.ok ? S.T('Its card had been deleted in Anki. Adding it again.') : S.T('Already in Anki, in {deck}. Open Anki to see its card.', { deck: at.deck });
    await send(player, { t: 'say', text: said, seconds: 4 });
  } else {
    ankiPending.add(pendingKey);
    await send(player, { t: 'say', text: fresh ? S.T('Adding one more card for {word}', { word: text }) : S.T('Adding {word} to Anki…', { word: text }), seconds: 3 });
  }
  const res = await ankiAsk({ type: A.MSG.ANKI_PICK, lang: L.id, word, sentence, clip, ...(noteType !== undefined ? { noteType } : {}), ...(deck !== undefined ? { deck } : {}), ...(fresh ? { fresh: true } : {}) });
  if (!res?.ok) {
    ankiPending.delete(pendingKey);
    await send(player, { t: 'say', text: S.T("Couldn't send it to Anki. Is the button still on in Settings → Anki?"), seconds: 5 });
  }
  await ankiRefresh(player).catch(report);
  // The list shows the pick by now, or will at once: the mark is the list's from here on.
  setTimeout(() => ankiPending.delete(pendingKey), 4000);
  if (res?.ok && game && where?.found) {
    if (where.sound_error) api('log', { level: 'info', text: `anki: the game's sound cannot be had here (${where.sound_error}): its card goes without it` }).catch(() => {});
    gameMedia(player, L.id, word, where, settingsNow.media).catch(report);
  } else if (res?.ok && !game) {
    mpvMedia(player, L.id, word, m, settingsNow.media).catch(report);
  }
}

// ------------------------------------------------------------ the panel's Translate and Look up keys

/*
 * The head's other keys, as a page's panel has them (content/ui.js
 * _translateKey, _lookKey), with the extension's own marks: Translate -- the
 * word put into Google Translate (MSG.TRANSLATE, as a page asks it:
 * content/reader.js translateText), its translation shown in the panel -- and
 * Look up, the menu of Settings' dictionary sites for the language
 * (lib/dict-links.js), each opened in a small window of Sluka's own; and,
 * beside a site whose dictionary its makers publish for anyone, the same
 * dictionary offline (dictionaries.py), installed on its first click.
 */
const TRANSLATE_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0 0 14.07 6H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>';
const BOOK_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5zM20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';
/** The menu's sites whose dictionary can be had offline: site -> dictionary (dictionaries.py CATALOG), and its languages. */
const OFFLINE = { wiktionary: ['wiktionary', null], jisho: ['jmdict', ['ja']], mdbg: ['cedict', ['zh']], cccanto: ['cccanto', ['yue']], folkets: ['folkets', ['sv']] };

/** The language's name at Wiktionary, from its link (…/wiki/{word}#Japanese): kaikki.org files it so. */
function wikiName(url) {
  try {
    return decodeURIComponent(new URL(String(url).replace('{word}', 'x')).hash.slice(1)).replace(/_/g, ' ');
  } catch {
    return '';
  }
}

function offlineOf(link, lang) {
  const [id, langs] = OFFLINE[link.id] || [];
  if (!id || (langs && !langs.includes(lang))) return null;
  if (id === 'wiktionary' && !wikiName(link.url)) return null;
  return id;
}

/** The head's Translate and Look up keys, for a pinned panel to draw (as content/ui.js has them). */
async function headTools(L) {
  const out = {};
  if (A.MSG?.TRANSLATE && globalThis.chrome?.runtime?.sendMessage) out.translate = { title: S.T('Translate with Google Translate'), icon: TRANSLATE_ICON };
  const links = A.shownLinks ? A.shownLinks(settings, L.id) : [];
  if (links.length) {
    const installed = new Set((await api('dict/installed', {}).catch(() => null))?.installed || []);
    out.look = {
      title: S.T('Look up'),
      icon: BOOK_ICON,
      offline: S.T('offline'),
      links: links.map((link) => {
        const off = offlineOf(link, L.id);
        return { id: link.id, name: link.name, ...(off ? { offline: off, installed: installed.has(`${off}-${L.id}`) } : {}) };
      }),
    };
  }
  return out;
}

/** The word into Google Translate, as a page's Translate key puts it (content/reader.js translateText; ui.js _bestTranslation). */
async function translateWord(player, m) {
  if (!A.MSG?.TRANSLATE) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const text = String(m.text ?? '').trim();
  if (!text) return;
  const to = A.translateFor ? A.translateFor(settings, L.id) : 'en';
  const res = await ankiAsk({ type: A.MSG.TRANSLATE, text, from: L.id, to });
  let best = String(res?.text || '').trim();
  if ((!best || best.toLowerCase() === text.toLowerCase()) && res?.alternatives?.[0]?.terms?.[0]) best = res.alternatives[0].terms[0];
  if (text === text.toLowerCase() && text !== text.toUpperCase() && /^\p{Lu}\p{Ll}/u.test(best)) best = best[0].toLowerCase() + best.slice(1);
  const alternatives = (Array.isArray(res?.alternatives) ? res.alternatives : []).slice(0, 3).map((a) => ({
    pos: typeof a?.pos === 'string' ? a.pos : '',
    terms: (Array.isArray(a?.terms) ? a.terms : []).filter((t) => typeof t === 'string' && t !== best).slice(0, 6),
  })).filter((a) => a.terms.length);
  const ok = !!res?.ok && !!best;
  await send(player, {
    t: 'translation', id: m.id, tok: m.tok, ok, text: ok ? best : '', alternatives: ok ? alternatives : [],
    error: ok ? '' : String(res?.error || S.T('Google Translate had no translation.')),
  });
}

/** A site of the Look up menu, or its dictionary offline, in Sluka's own small window (dictionaries.py open). */
async function lookUp(player, m) {
  if (!A.shownLinks || !A.linkFor) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  const text = String(m.text ?? '');
  const link = A.shownLinks(settings, L.id).find((l) => l.id === m.site);
  if (!link || !text) return;
  const word = (key && ankiWord(L, key, text)) || text;
  if (m.offline) {
    const id = offlineOf(link, L.id);
    if (!id) return;
    const name = id === 'wiktionary' ? wikiName(link.url) : '';
    const q = new URLSearchParams({ d: id, lang: L.id, q: text, ...(word !== text ? { k: word } : {}), ...(name ? { w: name } : {}) });
    await api('dict/open', { url: `/__sluka__/dict.html?${q}`, offline: true });
  } else {
    await api('dict/open', { url: A.linkFor(link.url, word) });
  }
}

// ------------------------------------------------------------ the panel's speaker

/*
 * The word said, as a page's speaker says it (lib/speech.js createSpeaker, asked as content/reader.js and
 * dashboard/word-speaker.js ask it): the voices in the order Settings → Voice puts them -- the cloud voice, your own
 * Piper voice, the recordings where they are installed -- and the device's voice last.  Where no cloud voice is set
 * up, Google Translate's voice stands in for one (MSG.TRANSLATE_SAY, the extension's own, which its translation box
 * says its texts with), so every language Sluka has can be heard, online, with nothing to download: no recordings are
 * offered here.  Where a cloud voice is set up and fails, Google's answers before the device's.  The sound plays in
 * this page (the app's own, never the game's, so it is not on a card's recording).
 */
const SPEAKER_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M3 9v6h4l5 4V5L7 9H3z" fill="currentColor"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.3 5.7a9 9 0 0 1 0 12.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

/** Whether this version of Sluka has a speaker to say words with. */
const speakerThere = () => !!(A.createSpeaker && (A.MSG?.TRANSLATE_SAY || A.MSG?.TTS_SPEAK) && globalThis.chrome?.runtime?.sendMessage);

/** The key that says the open word, where it is one plain character that grades nothing (Settings → Keyboard). */
function sayKeyChar() {
  const k = settings.keys?.say ?? 'v';
  const plain = typeof k === 'string' && /^[a-z0-9]$/i.test(k) ? k.toLowerCase() : '';
  return plain && !Object.values(gradeKeys()).includes(plain) && plain !== ankiKeyChar() ? plain : '';
}

function sayLookKey() {
  try {
    return speakerThere() ? sayKeyChar() : '';
  } catch {
    return '';
  }
}

function sayTitle() {
  const k = sayKeyChar();
  return k ? `${S.T('Hear it')} (${k.toUpperCase()})` : S.T('Hear it');
}

const realCloud = () => {
  try {
    return !!(A.cloudProvider && A.cloudProvider(settings));
  } catch {
    return false;
  }
};

/** Google Translate's voice saying `text` (lib/translate.js speakWithGoogle, through the worker): its MP3, whole. */
async function googleSays(text, langId) {
  const res = await ankiAsk({ type: A.MSG.TRANSLATE_SAY, text, lang: langId });
  if (!res?.ok || !Array.isArray(res.audio) || !res.audio.length) {
    throw Object.assign(new Error(res?.error || S.T("Google Translate's voice did not answer.")), { code: res?.busy ? 'busy' : 'other' });
  }
  const parts = res.audio.map(fromB64);
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out.buffer;
}

/** What the speaker last played, for the player whose word it is: `say|player|id|tok` -> { player, id, tok }. */
const sayingFor = new Map();
let sayingLit = null;
/** language -> Promise of its speaker */
const speakers = new Map();

function speakerFor(L) {
  const langId = L.id;
  if (!speakers.has(langId)) {
    const made = Promise.resolve(A.createSpeaker({
      lang: L.lang,
      baseUrl: globalThis.chrome?.runtime?.getURL?.('') || '',
      // The recordings, where they are installed (Settings → Voice): read from the worker's store, never downloaded here.
      store: A.MSG?.SPEECH_STATUS && A.MSG?.SPEECH_SHARD ? {
        status: async () => (await ankiAsk({ type: A.MSG.SPEECH_STATUS, lang: langId, installedOnly: true }))?.installed || null,
        shard: async (shard) => {
          const res = await ankiAsk({ type: A.MSG.SPEECH_SHARD, lang: langId, shard });
          if (!res?.ok) throw new Error(res?.error || 'no shard');
          return fromB64(res.base64).buffer;
        },
      } : null,
      cloud: {
        on: () => realCloud() || !!A.MSG?.TRANSLATE_SAY,
        prefer: () => settings.tts?.prefer,
        which: () => (realCloud() && A.voiceNow ? A.voiceNow(settings, langId) : 'google'),
        say: async ({ text, tag }) => {
          if (!realCloud()) return googleSays(text, langId);
          const res = await ankiAsk({ type: A.MSG.TTS_SPEAK, text, lang: langId, tag, noOwn: true });
          if (res?.ok) return fromB64(res.base64).buffer;
          const err = Object.assign(new Error(res?.error || S.T('The cloud voice did not answer.')), { code: res?.code || 'other' });
          if (!A.MSG?.TRANSLATE_SAY) throw err;
          // The cloud voice out (its quota, a key refused): Google's, before the device's robot.
          return googleSays(text, langId).catch(() => {
            throw err;
          });
        },
      },
      own: {
        on: () => !!(A.ownWordVoiceFor && A.ownWordVoiceFor(settings, langId)),
        which: () => (A.voiceNow ? A.voiceNow(settings, langId, { own: true }) : 'own'),
        say: async ({ text, tag }) => {
          const ownVoice = (A.ownVoiceFor && A.ownVoiceFor(settings, langId, text)) || A.ownWordVoiceFor(settings, langId);
          const res = await ankiAsk({ type: A.MSG.TTS_SPEAK, text, lang: langId, tag, ownVoice });
          if (!res?.ok) throw Object.assign(new Error(res?.error || S.T('Your own voice could not speak.')), { code: res?.code || 'other' });
          return fromB64(res.base64).buffer;
        },
      },
      onCloudError: (err) => sayNote(String(err?.message || err || '')),
      onNoVoice: (why) => sayNote(A.noVoiceLine ? A.noVoiceLine(A.languageInText ? A.languageInText(langId) : langId, why) : S.T('Nothing here can say this word.')),
      onState: (id) => lightSpeaker(id),
      volume: () => (A.volumeOf ? A.volumeOf(settings) : 1),
    }));
    made.catch(() => speakers.delete(langId));
    speakers.set(langId, made);
  }
  return speakers.get(langId);
}

/** A line about the voice, to the player whose word was asked for last (its toast, as a page's flash). */
function sayNote(text) {
  const at = sayingLit || lastAsked;
  const player = at && players.get(at.player);
  if (player && text) send(player, { t: 'say', text, seconds: 4 }).catch(report);
}

let lastAsked = null;

/** The speaker of the word being said lit in its panel, and put out when it stops (or another starts). */
function lightSpeaker(id) {
  const now = id ? sayingFor.get(id) || null : null;
  if (sayingLit && sayingLit !== now) {
    const was = players.get(sayingLit.player);
    if (was) send(was, { t: 'speaking', id: sayingLit.id, tok: sayingLit.tok, on: false }).catch(report);
  }
  sayingLit = now;
  const player = now && players.get(now.player);
  if (player) send(player, { t: 'speaking', id: now.id, tok: now.tok, on: true }).catch(report);
}

/** The word and the reading the speaker is given (content/ui.js _sayRequest, reader.js spokenForm). */
async function spokenOf(L, key, text, at = {}) {
  const word = lookupKey(L, key);
  const found = await S.lookupBatch([word], L.id);
  let entry = found[word] || null;
  try {
    if (entry && L.lang.entryInContext) entry = L.lang.entryInContext(entry, at.rd || null, { word: text, bound: !!at.bound }) || entry;
  } catch {
    /* as filed */
  }
  const reading = entry ? entry.readingsHere?.[0] ?? S.pronunciationOf(entry) : '';
  // The word as it was clicked where it is another form than the headword: said as written, with the analyser's
  // reading of it where there is one (tengo as tengo, not tener).
  const page = String(text || '').trim();
  const another = L.mode === COUNTING.FORM && lookupKey(L, key) !== key;
  if (!page || (!another && S.surfaceKey(L.lang, page) === key)) return { text: key, reading: reading || '', entry };
  return { text: page, reading: at.rd || '', entry: null };
}

/** The open (or hovered) word said: pressed again while it is, it stops. */
async function speakWord(player, m) {
  if (!speakerThere()) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  const text = String(m.text ?? '');
  if (!key && !text) return;
  const i = Number(m.tok) - 1;
  const mine = player.line?.id === m.id && player.line.toks[i]?.key === key;
  const said = await spokenOf(L, key || text, text, (mine && player.line.extra?.[i]) || {});
  const speaker = await speakerFor(L);
  // One voice at a time: another language's word stops for this one.
  for (const [other, made] of speakers) if (other !== L.id) (await made.catch(() => null))?.stop?.();
  const id = `say|${player.key}|${m.id}|${m.tok}`;
  sayingFor.set(id, { player: player.key, id: m.id, tok: m.tok });
  if (sayingFor.size > 64) sayingFor.delete(sayingFor.keys().next().value);
  lastAsked = { player: player.key, id: m.id, tok: m.tok };
  await speaker.speak({ ...said, id, missing: 'voice' });
}

// ------------------------------------------------------------ your own dictionaries

/*
 * The meanings of your own dictionaries (Settings → Dictionary → Your own dictionaries: Yomitan dictionaries and
 * tables, kept by Sluka's worker), as a page's panel has them (content/reader.js ownDefsFor, content/ui.js
 * _definition): asked of the worker (MSG.OWN_LOOKUP) under the word, its spelling here and, in Chinese, its other
 * script; each dictionary's homonyms with Sluka's own first (lead.js).  They go where Settings puts them -- instead
 * of Sluka's meanings, under them or above them (ownDictPlace) -- and only where one of yours has the word.
 *
 * For the pages (the floating subtitles, Sluka Vision) as the extension draws them (render.js ownDictsHtml: escaped,
 * the tags and styles it allows, links only to the web) with their own stylesheets (ownDictsCss); for mpv, and the
 * small card, as text (glanceSenses).
 */
async function withOwnDicts(entry, L, key, text, html) {
  if (!A.MSG?.OWN_LOOKUP || !S.KEY?.ownDicts || !globalThis.chrome?.storage?.local) return;
  const stamp = S.KEY.ownDicts(L.id);
  const got = await chrome.storage.local.get(stamp).catch(() => ({}));
  if (!got?.[stamp]?.on) return;
  const word = lookupKey(L, key);
  const found = await S.lookupBatch([word], L.id).catch(() => ({}));
  const filed = found?.[word] || null;
  const twins = L.id === 'zh' || L.id === 'yue' ? [filed?.t, filed?.s] : [];
  const words = [...new Set([word, key, text, ...twins].filter((w) => typeof w === 'string' && w))];
  const res = await ankiAsk({ type: A.MSG.OWN_LOOKUP, lang: L.id, words });
  let dicts = res?.ok && Array.isArray(res.dicts) ? res.dicts.filter((d) => Array.isArray(d?.hits) && d.hits.length) : [];
  if (!dicts.length) return;
  if (A.leadWithSluka) dicts = A.leadWithSluka(dicts, filed);
  const place = A.ownDictPlaceFor ? A.ownDictPlaceFor(settings, L.id) : 'replace';
  const glance = (e) => (A.glanceSenses ? A.glanceSenses(e, 4) : (e?.d || []).filter((d) => typeof d === 'string').slice(0, 4));
  const own = {
    place: place === 'above' || place === 'below' ? place : 'replace',
    dicts: dicts.slice(0, 6).map((d) => ({
      title: String(d.title || '').slice(0, 80),
      hits: d.hits.slice(0, 6).map((e) => ({ head: String(e?.h || '').slice(0, 60), reading: String(e?.r || '').slice(0, 60),
        senses: glance(e).map((t) => String(t).slice(0, 200)) })).filter((h) => h.senses.length),
    })).filter((d) => d.hits.length),
  };
  if (!own.dicts.length) return;
  if (html && A.ownDictsHtml) {
    own.html = A.ownDictsHtml(dicts, { word: key, lang: L.id, readings: true });
    own.css = A.ownDictsCss ? A.ownDictsCss(dicts) : '';
  }
  entry.own = own;
  // The small card's meaning, where yours go instead of Sluka's (content/reader.js ownDictGloss).
  if (own.place === 'replace') {
    const first = own.dicts[0].hits[0].senses;
    entry.lead = first[0] || entry.lead;
    entry.more = first.slice(1, 4);
  }
  entry.none = '';
}

/** A link of your own dictionaries' entries (render.js: the web only), in a small window of Sluka's, as a site of Look up. */
async function openLink(player, m) {
  const url = String(m.url || '');
  if (!/^https?:\/\//i.test(url)) return;
  await api('dict/open', { url });
}

// ------------------------------------------------------------ the AI check

/*
 * The panel's ✦, as a page's (content/ui.js _askKey, content/reader.js askAI): the word, and its sentence where
 * Settings → AI check says so, sent to the provider picked there, with your own request (its Advanced: what is asked
 * of every check -- what it means here, how its sentence changes it) answered in a part of its own.  The key stays in
 * the worker (MSG.VERIFY_WORD).  Nothing is sent until the ✦ (or its key, F) is pressed; the answer, in the language
 * words are translated into, is drawn in the panel.
 */
const aiThere = () => !!(settings.ai?.enabled && A.MSG?.VERIFY_WORD && globalThis.chrome?.runtime?.sendMessage);

function askKeyChar() {
  const k = settings.keys?.askWord ?? 'f';
  const plain = typeof k === 'string' && /^[a-z0-9]$/i.test(k) ? k.toLowerCase() : '';
  return plain && !Object.values(gradeKeys()).includes(plain) && plain !== ankiKeyChar() && plain !== sayKeyChar() ? plain : '';
}

function askLookKey() {
  try {
    return aiThere() ? askKeyChar() : '';
  } catch {
    return '';
  }
}

function aiCompany() {
  try {
    return (A.aiCompanyOf ? A.aiCompanyOf(settings) : '') || '';
  } catch {
    return '';
  }
}

/*
 * The check as the panel offers it (content/ui.js _askState): `wanted` where neither Sluka's dictionary nor one of
 * yours has the word -- then asking is the main thing to do, a button in the meanings -- else a quiet key in the head.
 */
async function askTool(L, key, entry) {
  const company = aiCompany();
  const why = company ? S.T('Sends this word and its sentence to {company}.', { company }) : '';
  const k = askKeyChar();
  let wanted = false;
  if (!entry.own) {
    const word = lookupKey(L, key);
    const found = await S.lookupBatch([word], L.id).catch(() => ({}));
    wanted = !found?.[word];
  }
  return {
    title: `${S.T('Ask AI to double-check.')}${k ? ` (${k.toUpperCase()})` : ''}${why ? ` ${why}` : ''}`,
    aria: S.T('Ask AI to double-check this word'),
    label: `${S.T('Ask AI if this is a real word')}${k ? ` (${k.toUpperCase()})` : ''}`,
    why,
    wait: S.T('Checking…'),
    wanted,
  };
}

/** What the check said, as the panel draws it (content/ui.js _renderVerdict): its fields, each a string. */
const VERDICT_FIELDS = ['verdict', 'confidence', 'reading', 'meaning', 'example', 'exampleTranslation', 'register', 'breakdown',
  'explanation', 'ownAnswer'];
const VERDICT_LABELS = () => ({
  established: S.T('Real word'), narrow: S.T('Real, but narrow'), not_a_word: S.T('Not a word'), uncertain: S.T('Uncertain'),
});
const CONFIDENCE_LABELS = () => ({ high: S.T('high confidence'), medium: S.T('medium confidence'), low: S.T('low confidence') });

async function askAi(player, m) {
  if (!aiThere()) return;
  const L = await language(player.line?.lang || player.lang || pickLanguage(player));
  const key = String(m.key ?? '');
  if (!key) return;
  const told = { t: 'verdict', id: m.id, tok: m.tok };
  await send(player, { ...told, status: 'loading', label: S.T('Checking…') });
  const sentence = lineSentence(player, L, key, m)?.t || String(player.line?.text || '').replace(/\s+/g, ' ').trim().slice(0, 600);
  const res = await ankiAsk({ type: A.MSG.VERIFY_WORD, word: key, sentence, language: L.id }).catch((err) => ({ ok: false, error: String(err?.message || err) }));
  if (!res?.ok || !res.result) {
    await send(player, { ...told, status: 'error', error: String(res?.error || S.T('The check failed.')).slice(0, 400) });
    return;
  }
  const result = {};
  for (const field of VERDICT_FIELDS) result[field] = typeof res.result[field] === 'string' ? res.result[field].trim().slice(0, 1600) : '';
  await send(player, {
    ...told,
    status: 'done',
    result,
    labels: {
      tag: VERDICT_LABELS()[result.verdict] || result.verdict,
      confidence: CONFIDENCE_LABELS()[result.confidence] || '',
      reading: S.T('Reading'), register: S.T('Used in'), breakdown: S.T('Actually'), explanation: S.T('Why'),
      own: S.T('Your question'),
    },
  });
}

// ------------------------------------------------------------ the questions, as they come

/** Players whose script is of another version than this page: told once, and not served. */
const turnedAway = new Set();

async function handle({ player: key, msg }) {
  if (!msg || typeof msg.t !== 'string') return;
  if (msg.t === 'bye') {
    players.delete(key);
    turnedAway.delete(key);
    // What it owes, written alongside: a player saying hello again under the same name is not kept waiting for it.
    tracked(() => progress?.gone(key));
    return;
  }
  if (turnedAway.has(key) && msg.t !== 'hello') return;
  let player = players.get(key);
  if (msg.t === 'hello') {
    if (Number(msg.v) !== PROTOCOL) {
      // A player still open from before the app was brought up to date (or the other way round): the two
      // would misread each other, so it is told so and left to mpv's own subtitles.
      players.delete(key);
      // Said once to each such player, however often it greets.
      if (turnedAway.has(key)) return;
      turnedAway.add(key);
      const older = Number(msg.v) < PROTOCOL || !Number(msg.v);
      api('log', {
        level: 'warning',
        text: `mpv: the script in a player speaks version ${Number(msg.v) || '?'} and the app version ${PROTOCOL}: ` +
          (older ? 'that player was opened before the app was brought up to date. Open the video again' : 'the app is the older of the two'),
      }).catch(() => {});
      await api('mpv/reply', {
        player: key,
        msg: { t: 'say', text: older ? 'this player has the older script. Open the video again.' : 'the app is older than this script.', seconds: 6 },
      }).catch(() => {});
      return;
    }
    player = { key, subLang: msg.sub_lang || '', lang: null, line: null };
    players.set(key, player);
    await ready(player);
    return;
  }
  if (!player) {
    // A question from a player this engine never met (it was started again): it is asked to say hello.
    await api('mpv/reply', { player: key, msg: { t: 'hello' } }).catch(() => {});
    return;
  }
  if (msg.t === 'track') {
    player.subLang = msg.sub_lang || '';
    await tracked(() => progress?.track(player));
    if (pickLanguage(player) !== player.lang) await ready(player, { quiet: false });
  } else if (msg.t === 'line') await line(player, msg);
  else if (msg.t === 'lookup') await lookup(player, msg);
  else if (msg.t === 'grade') await grade(player, msg);
  else if (msg.t === 'anki') await anki(player, msg);
  else if (msg.t === 'translate') await translateWord(player, msg);
  else if (msg.t === 'look') await lookUp(player, msg);
  // Not waited for: the next question is not kept back while a voice is fetched, or the AI answers.
  else if (msg.t === 'speak') speakWord(player, msg).catch(report);
  else if (msg.t === 'ask') askAi(player, msg).catch(report);
  else if (msg.t === 'open') openLink(player, msg).catch(report);
  // What is counted on Sluka's Home page (progress.js): an mpv player's look at itself, the floating subtitles' or
  // Sluka Vision's text put away or shown again, and how long a game was played (the app's play clock).
  else if (msg.t === 'clock') await tracked(() => progress?.clock(player, msg));
  else if (msg.t === 'shown') await tracked(() => progress?.shown(player, msg.on !== false));
  else if (msg.t === 'played') await tracked(() => progress?.played(player, msg));
}

/** One player's questions are answered in the order they were asked; players do not wait on each other. */
const queues = new Map();
function enqueue(item) {
  const before = queues.get(item.player) || Promise.resolve();
  const next = before.then(() => handle(item)).catch(report);
  queues.set(item.player, next);
  next.then(() => {
    if (queues.get(item.player) === next) queues.delete(item.player);
  });
}

// ------------------------------------------------------------ what is counted on Sluka's Home page

/*
 * Words read, minutes heard and subtitle words, from mpv, the floating
 * subtitles and Sluka Vision (progress.js), written by Sluka's own modules and
 * its worker.  Those are imported by name and checked here, as the ones above
 * are: without one of them nothing is counted, and the log says so -- the
 * subtitles are not touched either way.
 */
const TRACKS = {
  '/lib/constants.js': ['MSG', 'KEY'],
  '/lib/reading.js': ['paceUnit', 'paceFrom', 'withSamples', 'hashText', 'PACE_LIMITS', 'PACE_SAMPLES_NEEDED',
    'SAMPLE_MIN_MS', 'SAMPLE_MIN_UNITS', 'CUE_SHARE', 'CUE_MAX_STEP_S'],
  '/lib/stats.js': ['recordReading', 'recordDayDeltas', 'readingMemory'],
  '/lib/listening.js': ['textLanguage', 'sameLanguage', 'creditLocalVideo', 'retire', 'archive', 'startOfDay'],
};

/** The kind of player: the floating subtitles, Sluka Vision, or an mpv (mpvbridge.py, bar.py, vision.py). */
function kindOf(player) {
  return player.key === 'bar' || player.key === 'vision' ? player.key : 'mpv';
}

async function tracked(fn) {
  try {
    await fn();
  } catch (err) {
    report(err);
  }
}

async function startTracking() {
  const T = {};
  const lacking = [];
  for (const [path, names] of Object.entries(TRACKS)) {
    const mod = await import(path).catch(() => null);
    for (const name of names) {
      if (mod && name in mod) T[name] = mod[name];
      else lacking.push(`${name} (${path})`);
    }
  }
  for (const name of ['READ_WORDS', 'LISTEN_LOCAL_VIDEO', 'LISTEN_NARRATED']) if (T.MSG && !T.MSG[name]) lacking.push(`MSG.${name} (/lib/constants.js)`);
  for (const name of ['listenRecent', 'listenHistory']) if (T.KEY && !T.KEY[name]) lacking.push(`KEY.${name} (/lib/constants.js)`);
  if (lacking.length) {
    api('log', {
      level: 'warn',
      text: `this version of Sluka lacks ${lacking.join(', ')}: what is read and heard in mpv, the floating subtitles and Sluka Vision is not counted on its Home page`,
    }).catch(() => {});
    return null;
  }
  // Which of your languages a film's subtitles are in, where their track does not say: Sluka's own test, where it has one.
  const langs = await import('/lib/languages.js').catch(() => null);
  if (typeof langs?.strongestLanguage === 'function') T.strongestLanguage = langs.strongestLanguage;
  const { startProgress, TICK_MS } = await import('./progress.js');
  const tracking = startProgress({
    S: T,
    settings: () => settings,
    studied: () => (settings.activeLanguages?.length ? settings.activeLanguages : [settings.activeLang].filter(Boolean)),
    trackLanguage: (code) => TRACK_CODES[String(code || '').toLowerCase().split(/[-_]/)[0]] || null,
    ask: (message) => chrome.runtime.sendMessage(message),
    storage: chrome.storage.local,
    report,
    log: (text) => api('log', { level: 'info', text }).catch(() => {}),
    nameOf: (id) => {
      try {
        return S.languageName(id);
      } catch {
        return id;
      }
    },
  });
  setInterval(() => {
    try {
      tracking.tick();
    } catch (err) {
      report(err);
    }
  }, TICK_MS);
  // The app closing: what is owed, sent on the way out.
  addEventListener('pagehide', () => tracking.out());
  return tracking;
}

const progress = await startTracking().catch((err) => {
  report(err);
  return null;
});

let fresh = true;
let failures = 0;
for (;;) {
  try {
    const got = await api('mpv/poll', { fresh });
    fresh = false;
    failures = 0;
    // Another copy of this page has taken over the asking.
    if (got.superseded) break;
    for (const item of got.msgs || []) enqueue(item);
  } catch (err) {
    // The app's host went away, or is not there yet: asked again, ever more slowly.
    failures++;
    if (failures === 1) report(err);
    await new Promise((resolve) => setTimeout(resolve, Math.min(15000, 500 * failures)));
  }
}
