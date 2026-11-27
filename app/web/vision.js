// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Sluka Vision (vision.html): the words of a game's whole window, laid over
 * the game where they sit, as YomiNinja lays them -- each word you are
 * learning underlined in the colour of its level, its card when it is pointed
 * at, its panel (and its grades) when it is clicked.  Nothing is written over
 * the game's own letters.
 *
 * What was read comes from the app (vision.py, from ocrd.py's VisionWatch):
 * each line of text found in the window -- where it is, how it is tilted,
 * whether it is a column of vertical text -- and, where Google Lens said, where
 * each of its words is.  The lines are sent together to Sluka's engine
 * (mpv-engine.js) as one more player, called "vision", which cuts them into
 * Sluka's words, says how well each is known, looks a word up and files it at
 * a level: the questions the script in mpv and the floating subtitles ask,
 * answered by the same code.  Each word is then placed along its line where
 * its letters are.
 *
 * The window (winshell.py) is as large as the game's inside and see-through,
 * and takes the pointer only where this page says something is drawn (report,
 * below): everywhere else the game is clicked as if Sluka were not there.
 */

const shim = globalThis.__slukaShim;
const api = (name, body) => (shim ? shim.api(name, body) : Promise.reject(new Error('Sluka Desktop is not here')));

/** What the script in mpv and the engine say to each other (mpv/sluka.lua PROTOCOL): this page speaks the same. */
const PROTOCOL = 2;
const NEW = 0;
const KNOWN = 5;
const IGNORED = 6;
const LINKED = 7;
/** A first meaning longer than this makes the card wider and its letters smaller (content/ui.js). */
const GLANCE_LONG = 40;
/** How long the card stays after the pointer has left the words (it may be on its way to another). */
const LEAVE_MS = 160;
/** How long after the pointer has left the words the app is told so (it may only be crossing the room between two). */
const POINTING_LEFT_MS = 700;
/** A line this little tilted is taken as level: its words are one part of the window, not one each. */
const LEVEL = 0.02;

const $ = (id) => document.getElementById(id);
const words = $('words');
const badge = $('badge');
/** The game's picture, kept while the game is stopped where it is (its keys), and the pill that says which way. */
const still = $('still');
const frozenPill = $('frozen');
const card = $('card');
const panel = $('panel');
const toast = $('toast');
const root = document.documentElement;

/** How Sluka is set to look, as its engine says (`ready`); until it has, the script in mpv's own defaults (as bar.js). */
const look = {
  fonts: { cc: ['system-ui', 'Segoe UI', 'Roboto', 'sans-serif'], ui: ['system-ui', 'sans-serif'], word: ['Georgia', 'Times New Roman', 'serif'] },
  font_lang: '',
  theme: 'dark',
  words: {
    0: { fill: ['3b82f6', 0.4] }, 1: { fill: ['f7a800', 0.522] }, 2: { fill: ['f7a800', 0.348] },
    3: { fill: ['f7a800', 0.209], line: 'f7a800' }, 4: { line: 'f7a800' },
  },
  panel: { new: 'a7c7fb', levels: ['facb66', 'fcdc99', 'fdeac2', 'fef5e0'], lines: ['a87200', 'a87200'], fade: false, twin: 'ffb7df' },
  hover_delay: 0.12,
  keys: { 0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: 'k', 6: 'x' },
  anki_key: '',
  say_key: '',
  ask_key: '',
  text: { known: 'Known', ignore: 'Ignore', labels: {}, legend: null, also: 'Also' },
};

/** Sluka's engine: whether there is one at all, whether it has answered, and the language it reads in. */
const app = { engine: true, ready: false, lang: '', langName: '' };

/** What was read: { id, size: [w, h] (the window's pixels), lines: [{ i, p, v, rtl, text, box: [cx, cy, w, h, angle], words }] }. */
let layout = null;
/** The lines as one text for the engine, and where each line is in it (as JavaScript counts). */
let line = null;
let starts = [];
let seq = 0;
let hover = null;
let pinned = null;
let entry = null;
let dwell = 0;
let leaveTimer = 0;
let toastTimer = 0;
let front = true;
let reading = false;
let placed = false;
/** Each word's boxes, by its number (1, 2, ... as the engine counts them). */
const pieces = new Map();
/** Lines said to be gone while the word pointed at or clicked is on them: put away once it no longer is (heldBack). */
const held = new Set();
/** What the app was last told of what is being done with the words (syncLooking). */
const looking = { said: '|', read: 0, lines: [] };
let pointingTimer = 0;

// ------------------------------------------------------------ small things

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

const GENERIC = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace',
  'ui-rounded', 'emoji', 'math', 'fangsong', '-apple-system', 'BlinkMacSystemFont']);
const family = (list) => (Array.isArray(list) ? list : [])
  .map((name) => String(name ?? '').trim())
  .filter(Boolean)
  .map((name) => (GENERIC.has(name) ? name : `"${name.replace(/["\\]/g, '\\$&')}"`))
  .join(', ');

function channels(hex, fallback = '255 255 255') {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex ?? ''));
  return m ? [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)).join(' ') : fallback;
}
const colour = (hex, alpha = 1) => `rgb(${channels(hex)} / ${alpha})`;

/** Where each UTF-8 byte offset of `text` falls in it as JavaScript counts (the engine says where words are in bytes). */
function byteIndex(text) {
  const at = new Map();
  let byte = 0;
  for (let i = 0; i < text.length;) {
    at.set(byte, i);
    const cp = text.codePointAt(i);
    byte += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    i += cp > 0xffff ? 2 : 1;
  }
  at.set(byte, text.length);
  return at;
}

const CJK = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f\uac00-\ud7af]/;
const isCjk = (ch) => CJK.test(ch || '');

// ------------------------------------------------------------ talking

async function send(msg) {
  try {
    const answer = await api('vision/say', { msg });
    if (answer && answer.engine === false && app.engine) {
      app.engine = false;
      app.ready = false;
      showToast('Sluka’s engine is not running here: the words cannot be read (the app’s log says why)', 6);
    }
    return answer;
  } catch {
    return null;
  }
}

function hello() {
  send({ t: 'hello', v: PROTOCOL, sub_lang: '' });
}

// ------------------------------------------------------------ the look

function adoptLook(l) {
  if (!l || typeof l !== 'object') return;
  for (const k of ['hover_delay']) if (Number.isFinite(l[k])) look[k] = l[k];
  for (const k of ['font_lang', 'theme']) if (typeof l[k] === 'string') look[k] = l[k];
  if (l.fonts && typeof l.fonts === 'object') {
    for (const k of ['cc', 'ui', 'word']) if (Array.isArray(l.fonts[k]) && l.fonts[k].length) look.fonts[k] = l.fonts[k];
  }
  if (l.words && typeof l.words === 'object') look.words = l.words;
  if (l.panel && Array.isArray(l.panel.levels)) look.panel = l.panel;
  if (l.keys && typeof l.keys === 'object') {
    for (const [st, key] of Object.entries(l.keys)) if (typeof key === 'string' && key.length === 1) look.keys[st] = key;
  }
  if (typeof l.anki_key === 'string' && l.anki_key.length <= 1) look.anki_key = l.anki_key;
  look.say_key = typeof l.say_key === 'string' && l.say_key.length <= 1 ? l.say_key : '';
  look.ask_key = typeof l.ask_key === 'string' && l.ask_key.length <= 1 ? l.ask_key : '';
  if (l.text && typeof l.text === 'object') {
    look.text = {
      known: typeof l.text.known === 'string' ? l.text.known : 'Known',
      ignore: typeof l.text.ignore === 'string' ? l.text.ignore : 'Ignore',
      labels: l.text.labels && typeof l.text.labels === 'object' ? l.text.labels : {},
      legend: null,
      also: typeof l.text.also === 'string' && l.text.also ? l.text.also : 'Also',
    };
  }
}

/** The colour a level is underlined in: the line it wears on a page, else the colour of its fill, a little stronger. */
function levelColour(st) {
  const w = look.words?.[st];
  if (!w || typeof w !== 'object') return '';
  if (w.line) return colour(w.line, 0.95);
  if (Array.isArray(w.fill)) return colour(w.fill[0], clamp(Number(w.fill[1]) * 1.9 || 0.85, 0.75, 1));
  return '';
}

const wear = new CSSStyleSheet();
document.adoptedStyleSheets = [...document.adoptedStyleSheets, wear];

function dressWords() {
  const rules = [];
  for (const st of Object.keys(look.words || {})) {
    if (!Number.isFinite(Number(st))) continue;
    const under = levelColour(st);
    const w = look.words[st];
    const lit = w?.line || (Array.isArray(w?.fill) ? w.fill[0] : '');
    const said = [];
    if (under) said.push(`--u: ${under}`);
    if (lit) said.push(`--hl: ${channels(lit)}`);
    if (said.length) rules.push(`.vw[data-st="${Number(st)}"]:not([data-g]) { ${said.join('; ')} }`);
  }
  wear.replaceSync(rules.join('\n'));
}

function applyLook() {
  const s = root.style;
  s.setProperty('--ui-font', family(look.fonts.ui) || 'system-ui, sans-serif');
  s.setProperty('--word-font', family(look.fonts.word) || 'serif');
  const theme = look.theme === 'light' ? 'light' : 'dark';
  card.dataset.theme = theme;
  panel.dataset.theme = theme;
  dressWords();
}

// ------------------------------------------------------------ the letters along a line

const measure = document.createElement('canvas').getContext('2d');
const widths = new Map();

/** How wide a letter is beside the others (an em is 1): Chinese and Japanese letters are all one; others as the font has them. */
function advance(text, i) {
  const code = text.charCodeAt(i);
  if (code >= 0xdc00 && code <= 0xdfff) return 0;  // (the second half of a letter beyond the first 65536)
  const ch = String.fromCodePoint(text.codePointAt(i));
  if (isCjk(ch)) return 1;
  if (/\s/.test(ch)) return 0.3;
  let w = widths.get(ch);
  if (w === undefined) {
    measure.font = `100px ${family(look.fonts.cc) || 'sans-serif'}`;
    w = clamp(measure.measureText(ch).width / 100, 0.2, 1.2);
    widths.set(ch, w);
  }
  return w;
}

/** Letters s..e of a text spread over a..b, each as wide as it is (from b to a in a line written right to left). */
function spread(spans, text, s, e, a, b, rtl) {
  const ws = [];
  let total = 0;
  for (let i = s; i < e; i++) {
    const w = advance(text, i);
    ws.push(w);
    total += w;
  }
  let at = 0;
  for (let i = s; i < e; i++) {
    const w = total > 0 ? ((b - a) * ws[i - s]) / total : (b - a) / Math.max(1, e - s);
    spans[i] = rtl ? [b - at - w, b - at] : [a + at, a + at + w];
    at += w;
  }
}

/**
 * Where each letter of a line is along it, from its start (its left end; its
 * top, in a column), in the window's pixels: within each word where Google
 * Lens said the word is, the letters between words in the gaps, and in a line
 * read without words the letters spread over all of it.
 */
function letterSpans(ln) {
  const text = ln.text;
  const n = text.length;
  const length = ln.v ? ln.box[3] : ln.box[2];
  const spans = new Array(n).fill(null);
  const found = (Array.isArray(ln.words) ? ln.words : [])
    .filter((w) => Array.isArray(w) && w[0] >= 0 && w[1] > w[0] && w[1] <= n && w[3] > w[2])
    .sort((x, y) => x[0] - y[0]);
  if (!found.length) {
    spread(spans, text, 0, n, 0, length, ln.rtl);
    return spans;
  }
  for (const [s, e, a, b] of found) spread(spans, text, s, e, a, b, ln.rtl);
  // The letters no word holds: in the room between the words beside them.
  let i = 0;
  while (i < n) {
    if (spans[i]) {
      i += 1;
      continue;
    }
    let j = i;
    while (j < n && !spans[j]) j += 1;
    const before = i > 0 ? spans[i - 1] : null;
    const after = j < n ? spans[j] : null;
    let a;
    let b;
    if (ln.rtl) {
      a = after ? after[1] : 0;
      b = before ? before[0] : length;
    } else {
      a = before ? before[1] : 0;
      b = after ? after[0] : length;
    }
    if (b < a) [a, b] = [b, a];
    spread(spans, text, i, j, a, b, ln.rtl);
    i = j;
  }
  return spans;
}

// ------------------------------------------------------------ the lines, and the words on them

/** The lines read as one text for the engine: a paragraph's lines run on (with a space between letters that are not Chinese or Japanese), paragraphs a line each. */
function joinLines(lines) {
  let text = '';
  const at = [];
  lines.forEach((ln, k) => {
    if (k > 0) {
      const prev = lines[k - 1];
      if (prev.p !== ln.p) text += '\n';
      else if (!(isCjk(text[text.length - 1]) && isCjk(ln.text[0]))) text += ' ';
    }
    at.push(text.length);
    text += ln.text;
  });
  return { text, at };
}

/** The window's pixels as this page's: as wide as the game's inside was when it was read. */
function scale() {
  return layout && layout.size[0] > 0 ? innerWidth / layout.size[0] : 1 / (devicePixelRatio || 1);
}

function render() {
  words.replaceChildren();
  pieces.clear();
  if (!layout || !line) return;
  const k = scale();
  const lines = layout.lines;
  const boxes = lines.map((ln) => {
    const [cx, cy, w, h, angle] = ln.box;
    const node = el('div', ln.v ? 'vl v' : 'vl');
    node.dataset.line = String(ln.i);
    node.style.left = `${(cx - w / 2) * k}px`;
    node.style.top = `${(cy - h / 2) * k}px`;
    node.style.width = `${w * k}px`;
    node.style.height = `${h * k}px`;
    if (angle) node.style.transform = `rotate(${angle}rad)`;
    const thick = (ln.v ? w : h) * k;
    node.style.setProperty('--t', `${clamp(thick * 0.085, 2, 6).toFixed(1)}px`);
    node.style.setProperty('--o', `${clamp(thick * 0.07, 1, 5).toFixed(1)}px`);
    if (ln.gone) node.classList.add('gone');
    words.append(node);
    return { node, spans: null };
  });
  if (!Array.isArray(line.toks)) return;
  const at = byteIndex(line.text);
  line.toks.forEach((tok, t) => {
    const from = at.get(Number(tok.s));
    const to = at.get(Number(tok.e));
    if (from === undefined || to === undefined || to <= from) return;
    const index = t + 1;
    tok.from = from;
    tok.to = to;
    const mine = [];
    lines.forEach((ln, n) => {
      const start = starts[n];
      const lo = Math.max(from, start) - start;
      const hi = Math.min(to, start + ln.text.length) - start;
      if (hi <= lo) return;
      const holder = boxes[n];
      holder.spans ||= letterSpans(ln);
      const first = holder.spans[lo];
      const last = holder.spans[hi - 1];
      if (!first || !last) return;
      const a = Math.min(first[0], last[0]);
      const b = Math.max(first[1], last[1]);
      if (b - a <= 0.5) return;
      const piece = el('div', 'vw');
      piece.dataset.i = String(index);
      piece.dataset.st = String(Number(tok.st) || 0);
      if (tok.g) piece.dataset.g = '';
      if (ln.v) {
        piece.style.top = `${a * k}px`;
        piece.style.height = `${(b - a) * k}px`;
      } else {
        piece.style.left = `${a * k}px`;
        piece.style.width = `${(b - a) * k}px`;
      }
      holder.node.append(piece);
      mine.push(piece);
    });
    if (mine.length) pieces.set(index, mine);
  });
  markWords();
}

function markWords() {
  for (const node of words.querySelectorAll('.vw.hov, .vw.pin')) node.classList.remove('hov', 'pin');
  for (const node of pieces.get(hover) || []) node.classList.add('hov');
  for (const node of pieces.get(pinned) || []) node.classList.add('pin');
  heldBack();
  syncLooking();
}

/** The lines word `i` is on. */
function linesOf(i) {
  const out = new Set();
  for (const node of pieces.get(i) || []) out.add(Number(node.parentElement?.dataset.line));
  return out;
}

/** Lines held back from going (goneLines) that the word pointed at, or clicked, has left: put away now. */
function heldBack() {
  if (!held.size) return;
  const kept = new Set([...linesOf(hover), ...linesOf(pinned)]);
  const going = [...held].filter((i) => !kept.has(i));
  if (!going.length) return;
  for (const i of going) held.delete(i);
  goneLines(going);
}

/**
 * What the app is told of what is being done with the words.  A panel open:
 * Sluka's grading keys -- 1 to 4, K, X, 0 back to New (as Sluka is set), Esc
 * to close -- are the panel's, for this window never has the keyboard (the
 * game keeps it), and the app holds them for it, giving them back to the game
 * the moment the panel closes.  And the lines of the word pointed at, or of
 * the one whose panel is open: what changes under them alone does not have
 * the window read again by itself, which would take the card away from under
 * the pointer -- a game's button lights up as the pointer comes over it.
 */
function syncLooking() {
  const panel = pinned != null && front && app.ready && app.engine;
  const lines = front && layout
    ? [...new Set([...linesOf(hover), ...linesOf(pinned)])].filter((i) => Number.isInteger(i)).sort((a, b) => a - b)
    : [];
  clearTimeout(pointingTimer);
  pointingTimer = 0;
  if (lines.length || !looking.lines.length) {
    tellLooking(panel, layout ? layout.id : 0, lines);
    return;
  }
  // Off the words: the panel's keys given back at once, its lines let go of a moment later (the pointer may only
  // be crossing the room between two words).
  tellLooking(false, looking.read, looking.lines);
  pointingTimer = setTimeout(() => {
    pointingTimer = 0;
    tellLooking(false, 0, []);
  }, POINTING_LEFT_MS);
}

function tellLooking(panel, read, lines) {
  const said = `${panel ? 'panel' : ''}|${lines.length ? `${read}:${lines.join(',')}` : ''}`;
  if (said === looking.said) return;
  Object.assign(looking, { said, read, lines });
  const body = { panel, read, lines };
  if (panel) body.keys = look.keys;
  // The panel's Anki key, held with its grading keys while the game is in front (vision.py).
  if (panel && look.anki_key) body.anki = look.anki_key;
  // And its key that says the word (Settings → Keyboard, V), held the same way.
  if (panel && look.say_key) body.say = look.say_key;
  // And the AI check's (Settings → Keyboard, F), for the panel open.
  if (panel && look.ask_key) body.ask = look.ask_key;
  api('vision/looking', body).catch(() => {
    // Not heard (the app may be starting over): said again at the next change, whatever it is.
    Object.assign(looking, { said: '?', read: 0, lines: [] });
  });
}

function onKey(m) {
  if (pinned == null) return;
  if (m.anki) pickAnki();
  else if (m.say) speakWord();
  else if (m.ask) askAi();
  else if (m.close) unpin();
  else if (Number.isInteger(m.st)) grade(m.st);
}

function newLayout(m) {
  clearTimeout(dwell);
  hover = null;
  pinned = null;
  entry = null;
  held.clear();
  hideCard();
  const lines = (Array.isArray(m.lines) ? m.lines : []).filter((ln) => ln && typeof ln.text === 'string'
    && Array.isArray(ln.box) && ln.box.length >= 5 && ln.box.every(Number.isFinite) && ln.box[2] > 0 && ln.box[3] > 0);
  const size = Array.isArray(m.size) ? m.size.map(Number) : [];
  if (!lines.length || size.length < 2 || !(size[0] > 0)) {
    layout = null;
    line = null;
    starts = [];
    render();
    report();
    tellShown();
    return;
  }
  layout = { id: m.id, size, lines };
  const joined = joinLines(lines);
  starts = joined.at;
  line = { id: ++seq, text: joined.text, toks: null };
  render();
  report();
  if (app.ready) send({ t: 'line', id: line.id, text: line.text });
  tellShown();
}

/*
 * Whether the words are on screen to be read: the game in front, and a read's
 * words laid over it.  Told to the engine as it changes, which counts what is
 * read on Sluka's Home page only while they are (progress.js).
 */
let toldShown = null;
function tellShown() {
  const on = !!(front && layout && line);
  if (!app.ready || on === toldShown) return;
  toldShown = on;
  send({ t: 'shown', on });
}

function clearAll() {
  layout = null;
  line = null;
  starts = [];
  clearTimeout(dwell);
  hover = null;
  pinned = null;
  entry = null;
  held.clear();
  hideCard();
  render();
  report();
  tellShown();
}

/**
 * Lines whose text has gone from under them (the game moved on): put away at
 * once -- unless the word pointed at or clicked is on one, whose card stays up
 * until the pointer leaves the word or the panel closes (heldBack).  A game's
 * button that lights up, or moves, as the pointer comes over it changes what
 * is under its word without its text having gone.
 */
function goneLines(ids) {
  if (!layout) return;
  const kept = new Set([...linesOf(hover), ...linesOf(pinned)]);
  const gone = new Set();
  for (const i of ids.map(Number)) {
    if (kept.has(i)) held.add(i);
    else gone.add(i);
  }
  if (!gone.size) return;
  for (const ln of layout.lines) if (gone.has(ln.i)) ln.gone = true;
  for (const node of words.querySelectorAll('.vl')) if (gone.has(Number(node.dataset.line))) node.classList.add('gone');
  const shown = (i) => (pieces.get(i) || []).some((node) => !node.parentElement.classList.contains('gone'));
  if (hover != null && !shown(hover)) hover = null;
  if (pinned != null && !shown(pinned)) pinned = null;
  if (hover == null && pinned == null) {
    entry = null;
    hideCard();
  } else {
    markWords();
    showCard();
  }
  report();
}

/** Lines said to be gone whose text is back as it was read (the button the pointer lit is dark again): shown again. */
function backLines(ids) {
  if (!layout) return;
  const back = new Set(ids.map(Number));
  for (const i of back) held.delete(i);
  let changed = false;
  for (const ln of layout.lines) {
    if (back.has(ln.i) && ln.gone) {
      ln.gone = false;
      changed = true;
    }
  }
  if (!changed) return;
  for (const node of words.querySelectorAll('.vl.gone')) if (back.has(Number(node.dataset.line))) node.classList.remove('gone');
  report();
}

// ------------------------------------------------------------ a word pointed at, clicked, graded

function setHover(i) {
  if (i === hover) return;
  hover = i;
  clearTimeout(dwell);
  if (pinned == null) {
    entry = null;
    hideCard();
    if (i != null) dwell = setTimeout(() => ask(false), Math.max(20, (Number(look.hover_delay) || 0.12) * 1000));
  }
  markWords();
}

function tokAt(i) {
  return i == null || !line || !Array.isArray(line.toks) ? null : line.toks[i - 1] || null;
}

function ask(pin) {
  const idx = pinned ?? hover;
  const tok = tokAt(idx);
  if (!tok || !app.ready || tok.from === undefined) return;
  if (!pin && entry && entry.id === line.id && entry.tok === idx) return;
  send({ t: 'lookup', id: line.id, tok: idx, key: tok.key, text: line.text.slice(tok.from, tok.to), pin: pin || undefined });
}

function clickWord(i) {
  if (i == null || pinned === i) {
    unpin();
    return;
  }
  pinned = i;
  hover = i;
  clearTimeout(dwell);
  if (entry && (entry.tok !== i || entry.id !== line?.id)) entry = null;
  markWords();
  ask(true);
  showCard();
}

function unpin() {
  if (pinned == null) return;
  pinned = null;
  if (hover == null || (entry && entry.tok !== hover)) entry = null;
  markWords();
  showCard();
}

/** The pinned word into Anki (the panel's Anki key, or its key, held for the panel while the game is in front). */
function pickAnki() {
  const tok = tokAt(pinned);
  if (pinned == null || !tok || !line || !app.ready || tok.from === undefined || tok.g) return;
  send({ t: 'anki', id: line.id, tok: pinned, key: tok.key, text: line.text.slice(tok.from, tok.to), read: layout ? layout.id : undefined });
}

function grade(status) {
  const idx = pinned ?? hover;
  const tok = tokAt(idx);
  if (!tok || tok.from === undefined) return;
  if (tok.g) {
    showToast('A piece of grammar, not a word to grade', 3);
    return;
  }
  send({ t: 'grade', id: line.id, tok: idx, key: tok.key, text: line.text.slice(tok.from, tok.to), status });
}

// ------------------------------------------------------------ the card and the panel (as bar.js draws them)

function headEl(head) {
  const node = el('span', 'head');
  for (const seg of Array.isArray(head) ? head : []) {
    const t = String(seg?.t ?? '');
    if (typeof seg?.r === 'string' && seg.r) {
      const ruby = el('ruby');
      ruby.append(t, el('rt', '', seg.r));
      node.append(ruby);
    } else {
      node.append(t);
    }
  }
  return node;
}

function readingEl(reading) {
  if (!Array.isArray(reading) || !reading.length) return null;
  const node = el('span', 'reading');
  reading.forEach((r, i) => {
    if (i > 0) node.append(el('span', 'dot', '·'));
    if (typeof r?.pos === 'string' && r.pos) node.append(el('span', 'pos', r.pos));
    let started = false;
    if (typeof r?.text === 'string' && r.text) {
      node.append(el('span', 't', r.text));
      started = true;
    }
    for (const drawing of Array.isArray(r?.pitch) ? r.pitch : []) {
      if (started) node.append(el('span', 'gap'));
      started = true;
      const pitch = el('span', 'pitch');
      for (const beat of Array.isArray(drawing.beats) ? drawing.beats : []) {
        const b = el('span', 'beat', beat.t ?? '');
        if (beat.hi) b.classList.add('hi');
        if (beat.rise) b.classList.add('rise');
        if (beat.drop) b.classList.add('drop');
        if (beat.tail) b.classList.add('tail');
        pitch.append(b);
      }
      pitch.append(el('span', 'n', `[${Number(drawing.n) || 0}]`));
      node.append(pitch);
    }
  });
  return node;
}

function chipEl(e) {
  const st = Number(e.st ?? NEW);
  const pal = look.panel || {};
  const levels = Array.isArray(pal.levels) ? pal.levels : [];
  const lines = Array.isArray(pal.lines) ? pal.lines : [];
  const dot = el('i');
  if (st === 3 || st === 4) {
    dot.className = st === 3 ? 'square' : 'flat';
    const fill = st === 3 || pal.fade ? levels[st - 1] : '';
    dot.style.setProperty('--dot', fill ? `#${fill}` : 'transparent');
    const under = lines[st - 3];
    if (under) dot.style.boxShadow = `inset 0 -2px 0 #${under}`;
  } else {
    let paint = '';
    if (st === NEW) paint = pal.new ? `#${pal.new}` : '';
    else if (st === 1 || st === 2) paint = levels[st - 1] ? `#${levels[st - 1]}` : '';
    else if (st === KNOWN) paint = 'rgb(var(--known-dot))';
    else if (st === LINKED) paint = `#${pal.twin || pal.new || 'ffb7df'}`;
    if (paint) dot.style.setProperty('--dot', paint);
  }
  const label = e.label || look.text.labels?.[st] || '';
  const chip = el('span', 'chip');
  chip.append(dot, String(label));
  return chip;
}

function buildGlance(e) {
  card.replaceChildren();
  const lead = String(e.lead ?? '');
  const more = (Array.isArray(e.more) ? e.more : []).map((s) => String(s ?? '')).filter(Boolean);
  const long = [...lead].length > GLANCE_LONG || more.some((s) => [...s].length > GLANCE_LONG);
  card.classList.toggle('long', long);
  const top = el('div', 'top');
  top.append(headEl(e.head));
  const reading = readingEl(e.reading);
  if (reading) top.append(reading);
  card.append(top);
  if (lead) card.append(el('div', [...lead].length > GLANCE_LONG ? 'lead long' : 'lead', lead));
  else if (e.none) card.append(el('div', 'none', e.none));
  if (more.length) card.append(el('div', 'more', more.join(' · ')));
  const foot = el('div', 'foot');
  foot.append(chipEl(e));
  if (e.rank) foot.append(el('span', 'rank', e.rank));
  card.append(foot);
}

const CLOSE_SVG = '<svg viewBox="0 0 11 11" aria-hidden="true"><path d="M1.2 1.2l8.6 8.6M9.8 1.2l-8.6 8.6" stroke="currentColor" stroke-width="1.55" stroke-linecap="round"/></svg>';

function senseEl(marker, text, cls) {
  const node = el('div', cls ? `sense ${cls}` : 'sense');
  node.append(el('span', 'n', marker), el('span', 't', text));
  return node;
}

function levelsEl(e) {
  const row = el('div', 'levels');
  const pal = look.panel || {};
  const levels = Array.isArray(pal.levels) ? pal.levels : [];
  const lines = Array.isArray(pal.lines) ? pal.lines : [];
  const buttons = [[1, '1'], [2, '2'], [3, '3'], [4, '4'], [KNOWN, look.text.known || 'Known'], [IGNORED, look.text.ignore || 'Ignore']];
  const cap = (key) => (key ? ` (${String(key).toUpperCase()})` : '');
  for (const [st, label] of buttons) {
    const button = el('button', st >= KNOWN ? 'wide' : '');
    button.type = 'button';
    button.dataset.act = 'grade';
    button.dataset.st = String(st);
    button.title = (look.text.labels?.[st] || label) + cap(look.keys?.[st]);
    if (Number(e.st) === st) {
      button.classList.add('lit');
      // The word's own level, pressed again, puts it back to New, as 0 does (content/ui.js lvlBtn): its title says so.
      button.dataset.lit = '';
      button.setAttribute('aria-pressed', 'true');
      button.title = (look.text.back || 'Back to new') + cap(look.keys?.[NEW]);
      if (st >= 1 && st <= 3 && levels[st - 1]) {
        button.style.setProperty('--fill', `#${levels[st - 1]}`);
        button.style.setProperty('--fill-ink', '#1a1815');
      } else if (st === KNOWN) {
        button.style.setProperty('--fill', '#1a7d44');
        button.style.setProperty('--fill-ink', '#ffffff');
      } else if (st === IGNORED) {
        button.style.setProperty('--fill', '#5f5d57');
        button.style.setProperty('--fill-ink', '#ffffff');
      }
      button.append(label);
    } else if (st <= 4) {
      const swatch = el('span', 'sw');
      swatch.style.setProperty('--sw', (st < 4 || pal.fade) && levels[st - 1] ? `#${levels[st - 1]}` : '#ffffff');
      const under = st >= 3 ? lines[st - 3] : '';
      if (under) swatch.style.setProperty('--sw-line', `#${under}`);
      button.append(swatch, label);
    } else {
      button.append(label);
    }
    row.append(button);
  }
  return row;
}

function buildPanel(e) {
  panel.replaceChildren();
  const ph = el('div', 'ph');
  ph.append(headEl(e.head));
  const say = sayEl(e);
  if (say) {
    ph.prepend(say);
    ph.classList.add('has-say');
  }
  const close = el('button', 'close');
  close.type = 'button';
  close.title = 'Close';
  close.dataset.act = 'unpin';
  close.innerHTML = CLOSE_SVG;
  const keys = keysEl(e);
  if (keys) {
    ph.append(keys);
    ph.style.setProperty('--keys', String(keys.childElementCount));
  }
  ph.append(close);
  const menu = lookMenuEl(e);
  if (menu) ph.append(menu);

  const sub = el('div', 'sub');
  const reading = readingEl(e.reading);
  if (reading) sub.append(reading);
  sub.append(chipEl(e));
  if (e.rank) sub.append(el('span', 'rank', e.rank));
  // How many times the word was looked up, from the third (the engine says so only then), as Sluka's panel says it.
  if (Number(e.looks) > 0) {
    const looks = el('span', 'looks', `👀 ${Number(e.looks).toLocaleString()}`);
    looks.title = String(e.looks_title || '');
    sub.append(looks);
  }

  const body = el('div', 'body');
  const tr = translationEl(e);
  if (tr) body.append(tr);
  if (e.inflection && e.inflection.why) body.append(el('div', 'form', `${e.inflection.form ?? ''} — ${e.inflection.why}`));
  // Your own dictionaries, where Settings puts them: instead of Sluka's meanings, above them or under them.
  const own = ownEl(e);
  const place = own ? e.own.place : '';
  if (typeof e.mine === 'string' && e.mine) body.append(senseEl('✎', e.mine, 'mine'));
  if (own && place !== 'below') body.append(own);
  if (place !== 'replace') {
    const senses = (Array.isArray(e.senses) ? e.senses : []).map((s) => String(s ?? '')).filter(Boolean);
    senses.forEach((s, i) => body.append(senseEl(`${i + 1}.`, s)));
    if (!senses.length && !own && !(typeof e.mine === 'string' && e.mine)) {
      const none = e.none || e.lead;
      if (none) body.append(el('div', 'none', none));
    }
    (Array.isArray(e.also) ? e.also : []).forEach((a, i) => {
      const row = el('div', 'also');
      row.append(el('span', i === 0 ? 'label' : 'label blank', look.text.also || 'Also'), el('span', 'ah', a?.head ?? ''), String(a?.gloss ?? ''));
      body.append(row);
    });
    const left = Number(e.senses_more) || 0;
    if (left > 0 && senses.length) body.append(el('div', 'left', `+${left}`));
  }
  if (own && place === 'below') body.append(own);
  // The AI check's answer under the meanings; or, where nothing answered, its button.
  const band = askBandEl(e);
  if (band) body.append(band);

  // (no row of keys under the levels: each button names its key, which works while the panel is open -- syncLooking)
  panel.append(ph, sub, body, levelsEl(e), el('div', 'foot'));
}

/**
 * The pinned panel's keys in its head, as a page's panel has them (content/ui.js headKeys): Translate, Look up and
 * Anki, with the extension's own marks, as the engine tells them (mpv-engine.js headTools, ankiNote).  Translate puts
 * the word into Google Translate, its translation shown under the head; Look up opens the menu of the dictionary
 * sites -- each in a small window of Sluka's own -- and, beside a site whose dictionary can be had, the same
 * dictionary offline (installed on its first click).
 */
let lookOpen = false;

function keysEl(e) {
  const keys = el('div', 'keys');
  const tools = (e && e.tools) || {};
  if (tools.translate) {
    const b = el('button', 'head-key tr-key');
    b.type = 'button';
    b.dataset.act = 'translate';
    b.title = tools.translate.title || 'Translate with Google Translate';
    b.setAttribute('aria-label', b.title);
    b.innerHTML = String(tools.translate.icon || '').startsWith('<svg') ? tools.translate.icon : 'T';
    keys.append(b);
  }
  if (tools.look && Array.isArray(tools.look.links) && tools.look.links.length) {
    const b = el('button', 'head-key look-key');
    b.type = 'button';
    b.dataset.act = 'look';
    b.title = tools.look.title || 'Look up';
    b.setAttribute('aria-label', b.title);
    b.setAttribute('aria-haspopup', 'menu');
    b.setAttribute('aria-expanded', lookOpen ? 'true' : 'false');
    b.innerHTML = `${String(tools.look.icon || '').startsWith('<svg') ? tools.look.icon : ''}<span class="caret" aria-hidden="true">▾</span>`;
    keys.append(b);
  }
  const ankiKey = ankiEl(e);
  if (ankiKey) {
    ankiKey.classList.add('head-key');
    keys.append(ankiKey);
  }
  // The AI check's ✦ (content/ui.js _askKey, 'head'): a second opinion where the dictionaries answered; gone once asked.
  if (tools.ask && !tools.ask.wanted && !askSettled(e)) {
    const b = el('button', 'head-key ai-key');
    b.type = 'button';
    b.dataset.act = 'ask';
    b.title = tools.ask.title || 'Ask AI to double-check.';
    b.setAttribute('aria-label', tools.ask.aria || 'Ask AI to double-check this word');
    const glyph = el('span', 'glyph', '✦');
    glyph.setAttribute('aria-hidden', 'true');
    b.append(glyph);
    keys.append(b);
  }
  return keys.childElementCount ? keys : null;
}

/** The Look up menu: the sites, and each one's dictionary offline where it can be had. */
function lookMenuEl(e) {
  const look = e && e.tools && e.tools.look;
  if (!lookOpen || !look || !Array.isArray(look.links)) return null;
  const menu = el('div', 'look-menu');
  menu.setAttribute('role', 'menu');
  for (const link of look.links) {
    const row = el('button', 'site', String(link.name || link.id));
    row.type = 'button';
    row.dataset.act = 'site';
    row.dataset.site = String(link.id);
    row.setAttribute('role', 'menuitem');
    menu.append(row);
    if (link.offline) {
      const off = el('button', 'site offline');
      off.type = 'button';
      off.dataset.act = 'site';
      off.dataset.site = String(link.id);
      off.dataset.offline = '1';
      off.setAttribute('role', 'menuitem');
      off.append(`${link.name} · ${look.offline || 'offline'}`, el('span', link.installed ? 'state in' : 'state', link.installed ? '✓' : 'Install'));
      menu.append(off);
    }
  }
  return menu;
}

/** Google's translation of the word, once asked for (the head's Translate key), under the head. */
function translationEl(e) {
  const tr = e && e.tr;
  if (!tr) return null;
  const box = el('div', 'gtr');
  box.append(el('span', 'gtr-by', 'Google Translate'));
  if (tr.status === 'loading') box.append(el('span', 'gtr-text wait', '…'));
  else if (tr.status === 'error') box.append(el('span', 'gtr-text none', tr.error || 'No translation.'));
  else {
    box.append(el('span', 'gtr-text', tr.text || ''));
    for (const a of Array.isArray(tr.alternatives) ? tr.alternatives : []) {
      const alt = el('div', 'gtr-alt');
      if (a.pos) alt.append(el('span', 'gtr-pos', a.pos));
      alt.append((Array.isArray(a.terms) ? a.terms : []).join(', '));
      box.append(alt);
    }
  }
  return box;
}

function onTranslation(m) {
  if (!entry || m.id !== entry.id || m.tok !== entry.tok) return;
  entry = { ...entry, tr: m.ok ? { status: 'done', text: m.text, alternatives: m.alternatives } : { status: 'error', error: m.error } };
  if (pinned === entry.tok) showCard();
}

/** The word's text in its line, for the engine. */
function wordAt(idx) {
  const tok = tokAt(idx);
  return tok && line ? { tok, text: line.text.slice(tok.from, tok.to) } : null;
}

/*
 * The panel's speaker, in the head's top left corner with the word beside it (content/ui.js .head > .say), with the
 * extension's mark: the word said as a page's speaker says it (mpv-engine.js speakWord), lit while it is.  Its key
 * (Settings → Keyboard, V) says the word open, pinned or only pointed at, as a page's does.
 */
let speaking = null;

function sayEl(e) {
  const say = e?.tools?.say;
  if (!say || typeof say.icon !== 'string') return null;
  const button = el('button', 'say');
  button.type = 'button';
  button.dataset.act = 'speak';
  button.title = String(say.title || 'Hear it');
  button.setAttribute('aria-label', 'Hear it');
  button.innerHTML = say.icon;
  if (speaking && speaking.id === e.id && speaking.tok === e.tok) button.dataset.active = '';
  return button;
}

function speakWord() {
  const idx = pinned ?? hover;
  const tok = tokAt(idx);
  if (idx == null || !tok || !line || !app.ready || tok.from === undefined || tok.g) return;
  send({ t: 'speak', id: line.id, tok: idx, key: tok.key, text: line.text.slice(tok.from, tok.to) });
}

function onSpeaking(m) {
  speaking = m.on ? { id: m.id, tok: m.tok } : (speaking && speaking.id === m.id && speaking.tok === m.tok ? null : speaking);
  const button = panel.querySelector('.ph > .say');
  if (button && entry) button.toggleAttribute('data-active', !!speaking && speaking.id === entry.id && speaking.tok === entry.tok);
}

/*
 * Your own dictionaries' meanings (Settings → Dictionary → Your own dictionaries), as the engine drew them with the
 * extension's own renderer (mpv-engine.js withOwnDicts; lib/own-dicts/render.js: escaped, its tags and styles only,
 * links only to the web) -- each under its name, instead of Sluka's, under them or above them as Settings says -- with
 * their own stylesheets, held inside them.  A link in them opens in a small window of Sluka's, as a site of Look up.
 */
let ownSheet = null;

function ownEl(e) {
  const own = e && e.own;
  if (!own || !Array.isArray(own.dicts) || !own.dicts.length) return null;
  const box = el('div', 'own-dicts');
  if (typeof own.html === 'string' && own.html) {
    box.innerHTML = own.html;
  } else {
    for (const d of own.dicts) {
      const group = el('div', 'reading-group rg-dict');
      group.append(el('span', 'rg-tag', String(d.title || '')));
      for (const h of d.hits || []) {
        const entryBox = el('div', 'od-entry');
        if (h.head && h.head !== e.key) {
          const head = el('div', 'od-head');
          head.append(el('span', 'od-hw', h.head));
          if (h.reading) head.append(el('span', 'od-reading', h.reading));
          entryBox.append(head);
        }
        const list = el('ol', 'od-defs');
        for (const sense of h.senses || []) list.append(el('li', '', String(sense)));
        entryBox.append(list);
        group.append(entryBox);
      }
      box.append(group);
    }
  }
  if (!ownSheet) {
    ownSheet = document.createElement('style');
    document.head.append(ownSheet);
  }
  const css = typeof own.css === 'string' ? own.css : '';
  if (ownSheet.textContent !== css) ownSheet.textContent = css;
  return box;
}

/*
 * The AI check (Settings → AI check), as a page's panel has it (content/ui.js _askState, _askBlock, _askKey,
 * _renderVerdict).  Where the dictionaries answered, a quiet ✦ in the head; where they have nothing, asking is the
 * main thing left to do, and a button says so in the meanings, with what pressing it sends.  The answer goes under
 * the meanings -- the dictionary is the answer, this a note about it: what the check says of the word (a real word,
 * a narrow one, not a word, or not known) and how sure, its meaning, an example of its own, where it is used, why;
 * and the answer to your own request (its Advanced) under "Your question".  Once answered, it is not asked again.
 */
let verdict = null;

function verdictFor(e) {
  return verdict && e && verdict.id === e.id && verdict.tok === e.tok ? verdict : null;
}

/** Asked already, and answered or on its way: the key is gone (content/ui.js _askState, settled). */
function askSettled(e) {
  const v = verdictFor(e);
  return !!v && v.status !== 'error';
}

/** The example with the word in it marked (content/ui.js markedIn). */
function markedEl(cls, text, word) {
  const box = el('div', cls);
  const at = word ? text.indexOf(word) : -1;
  if (at < 0) {
    box.textContent = text;
    return box;
  }
  box.append(text.slice(0, at), el('b', '', word), text.slice(at + word.length));
  return box;
}

function askBandEl(e) {
  const ask = e && e.tools && e.tools.ask;
  const v = verdictFor(e);
  if (!v && !(ask && ask.wanted)) return null;
  const band = el('div', ask && ask.wanted ? 'ask' : 'ask secondary');
  if (v) band.append(verdictEl(v));
  if (ask && ask.wanted && !askSettled(e)) {
    const b = el('button', 'ask-go', ask.label || 'Ask AI if this is a real word');
    b.type = 'button';
    b.dataset.act = 'ask';
    band.append(b);
    if (ask.why) band.append(el('div', 'why', ask.why));
  }
  return band;
}

function verdictEl(v) {
  if (v.status === 'loading') return el('div', 'spinner', v.label || 'Checking…');
  if (v.status === 'error') return el('div', 'err', v.error || 'The check failed.');
  const box = el('div', 'verdict');
  const r = v.result || {};
  const labels = v.labels || {};
  const head = el('div', 'vd-head');
  head.append(el('span', `vd-tag vd-${String(r.verdict || '').replace(/[^a-z_]/g, '')}`, labels.tag || r.verdict || ''));
  if (labels.confidence) head.append(el('span', 'vd-conf', labels.confidence));
  box.append(head);
  if (r.meaning) box.append(el('div', 'vd-meaning', r.meaning));
  if (r.example) {
    const ex = el('div', 'vd-example');
    ex.append(markedEl('vd-ex', r.example, String(v.word || '')));
    if (r.exampleTranslation) ex.append(el('div', 'vd-ex-tr', r.exampleTranslation));
    box.append(ex);
  }
  for (const [field, label] of [['reading', labels.reading], ['register', labels.register], ['breakdown', labels.breakdown], ['explanation', labels.explanation]]) {
    if (!r[field]) continue;
    const row = el('div', 'vd-line');
    row.append(el('b', '', `${label || field}:`), ` ${r[field]}`);
    box.append(row);
  }
  if (r.ownAnswer) {
    const own = el('div', 'vd-own');
    own.append(el('b', '', labels.own || 'Your question'), el('div', 'vd-own-text', r.ownAnswer));
    box.append(own);
  }
  return box;
}

// A link in your own dictionaries' meanings: never this page's to follow -- the engine opens it in a window of Sluka's.
for (const kind of ['click', 'auxclick']) {
  panel.addEventListener(kind, (e) => {
    const a = e.target.closest?.('a[data-link], .own-dicts a');
    if (!a) return;
    e.preventDefault();
    e.stopPropagation();
    const url = a.getAttribute('href') || '';
    if (/^https?:\/\//i.test(url) && app.ready) send({ t: 'open', url });
  }, true);
}

function onVerdict(m) {
  if (!entry || m.id !== entry.id || m.tok !== entry.tok) return;
  verdict = { ...m, word: verdictFor(m)?.word || '' };
  if (pinned === entry.tok) {
    showCard();
    // (brought into view, as a page's answer is)
    panel.querySelector('.ask .verdict, .ask .err')?.scrollIntoView?.({ block: 'nearest' });
  }
}

/** The ✦ pressed, its button, or its key: the open word asked of the AI check -- once, as a page asks it. */
function askAi() {
  const got = wordAt(pinned);
  if (!got || !entry || !app.ready || !(entry.tools && entry.tools.ask)) return;
  if (askSettled(entry)) return;
  verdict = { id: entry.id, tok: entry.tok, status: 'loading', label: entry.tools.ask.wait || 'Checking…', word: got.text };
  showCard();
  send({ t: 'ask', id: line.id, tok: pinned, key: got.tok.key, text: got.text });
}

function translateWord() {
  const got = wordAt(pinned);
  if (!got || !entry || !app.ready) return;
  entry = { ...entry, tr: { status: 'loading' } };
  showCard();
  send({ t: 'translate', id: line.id, tok: pinned, key: got.tok.key, text: got.text });
}

function lookSite(site, offline) {
  const got = wordAt(pinned);
  lookOpen = false;
  if (!got || !app.ready) return;
  send({ t: 'look', id: line.id, tok: pinned, key: got.tok.key, text: got.text, site, ...(offline ? { offline: true } : {}) });
  showCard();
}

/**
 * The pinned panel's Anki key (content/ui.js _ankiKey), as the engine tells it while Settings → Anki has the panel's
 * button on: the word into the deck for picked words, with its sentence -- and from a game, its sound and a picture
 * of the game -- or, once it is there, its card opened in Anki.  Its mark is the extension's own (lib/anki-icon.js).
 */
function ankiEl(e) {
  const a = e && e.anki;
  if (!a || typeof a.state !== 'string' || !a.state) return null;
  const button = el('button', 'anki-key');
  button.type = 'button';
  button.dataset.act = 'anki';
  button.dataset.state = a.state;
  const title = typeof a.title === 'string' ? a.title : 'Add to Anki';
  button.title = title;
  button.setAttribute('aria-label', title);
  if (typeof a.icon === 'string' && a.icon.startsWith('<svg')) button.innerHTML = a.icon;
  else button.textContent = '+';
  return button;
}

/** The Anki key's state told again (the pick taken, the card made): the open panel shows it. */
function onAnki(m) {
  if (!entry || !line || m.id !== entry.id || m.tok !== entry.tok) return;
  entry = { ...entry, anki: m.state ? { state: m.state, title: m.title, icon: m.icon, key: m.key } : undefined };
  if (pinned === entry.tok) showCard();
}

/** Beside the word, as near as the game's window lets it be: over it, else under it; beside a column of vertical text. */
function placeBy(node, word, isPanel) {
  const vw = innerWidth;
  const vh = innerHeight;
  const w = word.getBoundingClientRect();
  if (isPanel) {
    const room = Math.max(w.top - 16, vh - w.bottom - 16);
    node.style.setProperty('--panel-max', `${Math.max(180, Math.floor(Math.min(room, vh - 16)))}px`);
  }
  const r = node.getBoundingClientRect();
  const vertical = !!word.parentElement?.classList.contains('v');
  let x;
  let y;
  if (vertical && (w.left - 10 - r.width >= 8 || w.right + 10 + r.width <= vw - 8)) {
    x = w.left - 10 - r.width >= 8 ? w.left - 10 - r.width : w.right + 10;
    y = clamp(w.top, 8, Math.max(8, vh - r.height - 8));
  } else {
    x = clamp((w.left + w.right) / 2 - r.width / 2, 8, Math.max(8, vw - r.width - 8));
    y = w.top - 10 - r.height;
    if (y < 8) {
      const under = w.bottom + 10;
      y = under + r.height <= vh - 8 ? under : Math.max(8, vh - r.height - 8);
    }
  }
  node.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
}

function showCard() {
  const idx = pinned ?? hover;
  const word = (pieces.get(idx) || [])[0];
  if (!line || idx == null || !entry || entry.tok !== idx || entry.id !== line.id || !word || !front) {
    hideCard();
    return;
  }
  if (pinned === idx) {
    card.hidden = true;
    buildPanel(entry);
    panel.hidden = false;
    placeBy(panel, word, true);
  } else {
    panel.hidden = true;
    buildGlance(entry);
    card.hidden = false;
    placeBy(card, word, false);
  }
  report();
}

function hideCard() {
  syncLooking();
  if (card.hidden && panel.hidden) return;
  card.hidden = true;
  panel.hidden = true;
  report();
}

function showToast(text, seconds = 3) {
  toast.textContent = String(text);
  toast.hidden = false;
  const r = toast.getBoundingClientRect();
  toast.style.transform = `translate(${Math.round(clamp(innerWidth / 2 - r.width / 2, 8, Math.max(8, innerWidth - r.width - 8)))}px, 12px)`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
    report();
  }, clamp(Number(seconds) || 3, 1, 30) * 1000);
  report();
}

function showBadge() {
  badge.hidden = !(reading && front);
  badge.querySelector('span').textContent = 'Sluka Vision · reading…';
  report();
}

// ------------------------------------------------------------ what the engine says

function onReady(m) {
  const was = app.ready;
  app.ready = true;
  app.engine = true;
  app.lang = String(m.lang || '');
  app.langName = String(m.lang_name || app.lang);
  adoptLook(m.look);
  applyLook();
  clearTimeout(dwell);
  hover = null;
  pinned = null;
  entry = null;
  hideCard();
  if (line) {
    line = { id: ++seq, text: line.text, toks: null };
    render();
    report();
    send({ t: 'line', id: line.id, text: line.text });
  }
  // (an engine answering again may be one started since, which has been told nothing)
  toldShown = null;
  tellShown();
  if (!was && !m.quiet) showToast(`Sluka Vision: ${app.langName || 'connected'}`, 2);
}

function onTokens(m) {
  if (!line || m.id !== line.id || !Array.isArray(m.toks)) return;
  line.toks = m.toks;
  render();
  report();
}

function onEntry(m) {
  if (!line || m.id !== line.id || m.tok !== (pinned ?? hover)) return;
  const same = entry && entry.id === m.id && entry.tok === m.tok;
  // The same word told again (graded): its translation and menu as they were; another word: closed.
  if (same && entry.tr && !m.tr) m = { ...m, tr: entry.tr };
  if (!same) lookOpen = false;
  if (!same && verdict && (verdict.id !== m.id || verdict.tok !== m.tok)) verdict = null;
  if (!same && speaking && (speaking.id !== m.id || speaking.tok !== m.tok)) speaking = null;
  entry = m;
  showCard();
}

function onStatus(m) {
  if (!line || !Array.isArray(line.toks)) return;
  let changed = false;
  line.toks.forEach((tok, t) => {
    if (tok.key !== m.key || Number(tok.st) === Number(m.st)) return;
    tok.st = m.st;
    changed = true;
    for (const node of pieces.get(t + 1) || []) node.dataset.st = String(Number(m.st) || 0);
  });
  if (entry && entry.key === m.key) {
    entry.st = m.st;
    entry.label = m.label || entry.label;
  }
  if (m.graded && (Number(m.st) === KNOWN || Number(m.st) === IGNORED) && pinned != null && tokAt(pinned)?.key === m.key) {
    pinned = null;
    if (hover == null) entry = null;
    markWords();
  }
  if (changed || m.graded) showCard();
}

function fromEngine(m) {
  if (!m || typeof m.t !== 'string') return;
  if (m.t === 'hello') hello();
  else if (m.t === 'ready') onReady(m);
  else if (m.t === 'tokens') onTokens(m);
  else if (m.t === 'entry') onEntry(m);
  else if (m.t === 'status') onStatus(m);
  else if (m.t === 'anki') onAnki(m);
  else if (m.t === 'translation') onTranslation(m);
  else if (m.t === 'speaking') onSpeaking(m);
  else if (m.t === 'verdict') onVerdict(m);
  else if (m.t === 'say' && m.text) showToast(m.text, m.seconds || 3);
  else if (m.t === 'bye') app.ready = false;
}

// ------------------------------------------------------------ what the app says

function setFront(on) {
  front = !!on;
  document.body.hidden = !front;
  if (!front) {
    clearTimeout(dwell);
    hover = null;
    pinned = null;
    entry = null;
    hideCard();
    markWords();
  }
  showBadge();
  report(true);
  tellShown();
}

function fromApp(m) {
  if (!m || typeof m.t !== 'string') return;
  if (m.t === 'state') {
    if (m.engine === false) app.engine = false;
    applyLook();
    placed = true;
    setFront(m.front !== false);
    if (app.engine) hello();
  } else if (m.t === 'layout') {
    newLayout(m);
  } else if (m.t === 'stale') {
    if (m.all) clearAll();
    else goneLines(Array.isArray(m.lines) ? m.lines : []);
  } else if (m.t === 'back') {
    backLines(Array.isArray(m.lines) ? m.lines : []);
  } else if (m.t === 'key') {
    onKey(m);
  } else if (m.t === 'clear') {
    clearAll();
  } else if (m.t === 'front') {
    setFront(m.on);
  } else if (m.t === 'status') {
    reading = m.state === 'reading';
    showBadge();
  } else if (m.t === 'note') {
    if (m.text) showToast(m.text, m.seconds || 4);
  } else if (m.t === 'engine') {
    fromEngine(m.msg);
  } else if (m.t === 'freeze') {
    onFreeze(m);
  }
}

// ------------------------------------------------------------ the game stopped where it is

/*
 * Sluka Vision's two keys that stop the game where it is (vision.py): the game paused, or only its picture kept, the
 * game going on behind it.  Either way the picture the app keeps (vision/still) is laid over the whole window, under
 * the words -- shown once it has come, so that nothing blinks -- and the window takes the pointer all over meanwhile:
 * a click on the picture is not the game's.  Let go of, it is taken away (the app waits a moment for the game to draw
 * itself again); a word that it is taken away for later than another picture came is not this one's.
 */
let frozen = null;

function onFreeze(m) {
  if (!m.on) {
    if (!frozen || (m.n != null && m.n !== frozen.n)) return;
    frozen = null;
    still.hidden = true;
    still.removeAttribute('src');
    frozenPill.hidden = true;
    report(true);
    return;
  }
  const fresh = !frozen || frozen.n !== m.n;
  frozen = { n: m.n, mode: m.mode === 'pause' ? 'pause' : 'picture', key: String(m.key || '') };
  frozenPill.dataset.mode = frozen.mode;
  frozenPill.querySelector('span').textContent = frozen.mode === 'pause'
    ? `Game paused${frozen.key ? ` · ${frozen.key} to go on` : ''}`
    : `Picture frozen${frozen.key ? ` · ${frozen.key} to let go` : ''}`;
  if (fresh) {
    const n = m.n;
    still.onload = () => {
      if (!frozen || frozen.n !== n) return;
      still.hidden = false;
      frozenPill.hidden = false;
      report(true);
    };
    still.onerror = () => {
      if (frozen && frozen.n === n) frozenPill.hidden = false;
      report(true);
    };
    still.src = `/__sluka__/api/vision/still?n=${encodeURIComponent(n)}`;
  } else {
    frozenPill.hidden = still.hidden;
    report(true);
  }
}

// ------------------------------------------------------------ which parts of the window are drawn on

let reportFrame = 0;
let reportTimer = 0;
let reportForced = false;
let lastShape = '';

function report(force = false) {
  if (!placed) return;
  reportForced = reportForced || force;
  if (reportFrame) cancelAnimationFrame(reportFrame);
  clearTimeout(reportTimer);
  let done = false;
  const go = () => {
    if (done) return;
    done = true;
    cancelAnimationFrame(reportFrame);
    clearTimeout(reportTimer);
    reportFrame = 0;
    const forced = reportForced;
    reportForced = false;
    tellShape(forced);
  };
  reportFrame = requestAnimationFrame(go);
  reportTimer = setTimeout(go, 100);
}

/** The parts of the window drawn on, in this page's pixels: each line's words (each word of a tilted line), with room for its underline; the card, the panel, the badge, a message. */
function tellShape(force) {
  const rects = [];
  const take = (node, [l, t, r, b]) => {
    if (!node || node.hidden) return;
    const q = node.getBoundingClientRect();
    if (q.width <= 0 || q.height <= 0) return;
    rects.push([q.left - l, q.top - t, q.width + l + r, q.height + t + b]);
  };
  if (front) {
    for (const node of words.querySelectorAll('.vl:not(.gone)')) {
      const parts = [...node.querySelectorAll('.vw')];
      if (!parts.length) continue;
      const pad = parseFloat(node.style.getPropertyValue('--t')) + parseFloat(node.style.getPropertyValue('--o')) + 3 || 8;
      const ln = layout?.lines.find((x) => String(x.i) === node.dataset.line);
      if (ln && Math.abs(ln.box[4] || 0) < LEVEL) {
        // A level line: its words as one part of the window (the room between them is little).
        const qs = parts.map((p) => p.getBoundingClientRect());
        const left = Math.min(...qs.map((q) => q.left));
        const top = Math.min(...qs.map((q) => q.top));
        const right = Math.max(...qs.map((q) => q.right));
        const bottom = Math.max(...qs.map((q) => q.bottom));
        rects.push(ln.v ? [left - pad, top - 2, right - left + pad + 2, bottom - top + 4]
          : [left - 2, top - 2, right - left + 4, bottom - top + pad + 2]);
      } else {
        for (const p of parts) take(p, [pad, pad, pad, pad]);
      }
    }
    take(card, [22, 12, 22, 32]);
    take(panel, [26, 14, 26, 38]);
    take(badge, [2, 2, 2, 2]);
    take(toast, [4, 4, 4, 4]);
    take(frozenPill, [2, 2, 2, 2]);
    // The picture kept, over the whole window: all of it is seen, and takes the pointer.
    if (!still.hidden) rects.unshift([0, 0, innerWidth, innerHeight]);
  }
  const round = (list) => list.map((r) => r.map((v) => Math.round(v * 10) / 10));
  const shape = { rects: round(rects), dpr: window.devicePixelRatio || 1 };
  const said = JSON.stringify(shape);
  if (!force && said === lastShape) return;
  lastShape = said;
  api('vision/shape', shape).catch(() => {
    lastShape = '';
  });
}

// ------------------------------------------------------------ the pointer

words.addEventListener('pointermove', (e) => {
  clearTimeout(leaveTimer);
  const word = e.target.closest?.('.vw');
  setHover(word ? Number(word.dataset.i) : null);
});
words.addEventListener('pointerleave', () => {
  clearTimeout(leaveTimer);
  leaveTimer = setTimeout(() => setHover(null), LEAVE_MS);
});
words.addEventListener('click', (e) => {
  const word = e.target.closest?.('.vw');
  if (word) clickWord(Number(word.dataset.i));
  // On the picture kept, off the words (the game gets no click meanwhile): the panel put away, as a click elsewhere does.
  else if (frozen && pinned != null) unpin();
});

document.addEventListener('click', (e) => {
  const button = e.target.closest?.('[data-act]');
  if (!button) return;
  if (button.dataset.act === 'unpin') unpin();
  else if (button.dataset.act === 'anki') pickAnki();
  else if (button.dataset.act === 'translate') translateWord();
  else if (button.dataset.act === 'speak') speakWord();
  else if (button.dataset.act === 'ask') askAi();
  else if (button.dataset.act === 'look') {
    lookOpen = !lookOpen;
    showCard();
  } else if (button.dataset.act === 'site') lookSite(button.dataset.site, button.dataset.offline === '1');
  else if (button.dataset.act === 'grade') {
    // The lit level puts the word back to New -- but not as the second click of a double-click, which the first
    // click's lit button would take back at once (content/ui.js).
    const lit = button.dataset.lit !== undefined;
    if (lit && e.detail > 1) return;
    grade(lit ? NEW : Number(button.dataset.st));
  }
});

addEventListener('contextmenu', (e) => e.preventDefault());
addEventListener('dragstart', (e) => e.preventDefault());

addEventListener('resize', () => {
  render();
  if (!card.hidden || !panel.hidden) showCard();
  report(true);
});
document.fonts?.ready?.then(() => {
  widths.clear();
  render();
  report();
});

// ------------------------------------------------------------ asking the app for news

async function listen() {
  applyLook();
  let fresh = true;
  let failures = 0;
  for (;;) {
    try {
      const got = await api('vision/poll', { fresh });
      fresh = false;
      failures = 0;
      if (got && got.superseded) break;
      for (const m of (got && got.msgs) || []) {
        try {
          fromApp(m);
        } catch (err) {
          console.error('[sluka-desktop] Sluka Vision could not show what came:', err);
        }
      }
    } catch {
      failures += 1;
      await new Promise((resolve) => setTimeout(resolve, Math.min(15000, 500 * failures)));
    }
  }
}

listen();
