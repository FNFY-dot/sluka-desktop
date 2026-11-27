// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * The floating subtitles (bar.html): Sluka's subtitle box in a window that
 * stays over every other, for text that comes from another program.
 *
 * To Sluka's engine (mpv-engine.js) this page is one more player, called
 * "bar": it says hello, sends the line it was given, asks what a word means
 * and files a word at a level -- the questions the script in mpv asks,
 * answered by the same code, so a word graded here is graded in your books and
 * films too.  It draws what it is told as Sluka's pages draw it: the box
 * (content.css), the card for the word pointed at and the panel for the word
 * clicked (content/ui.js), by the numbers the script in mpv draws by
 * (mpv/sluka.lua) -- here with the web engine's own layout and fonts, which
 * are the ones Sluka's own pages have.
 *
 * The app (bar.py) carries what is said both ways, and keeps where the bar is
 * and how it is set between starts.  The window (winshell.py) is as large as
 * the screen and see-through, and takes the pointer only where this page says
 * something is drawn (report, below): the rest of the screen stays clickable.
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
/** A line a little too wide for one row is set up to a tenth smaller instead of on two. */
const SQUEEZE_MIN = 0.9;
/** How far a press on the subtitle moves before it is a drag and not a click. */
const DRAG_FROM = 5;
const SCALE_MIN = 0.5;
const SCALE_MAX = 3;
const SCALE_STEP = 1.1;
/** How long the bar's buttons stay after the pointer has left it. */
const LEAVE_MS = 260;

const $ = (id) => document.getElementById(id);
const bar = $('bar');
const area = $('area');
const tools = $('tools');
const box = $('box');
const cc = $('cc');
const badge = $('badge');
const card = $('card');
const panel = $('panel');
const toast = $('toast');
const root = document.documentElement;

/** The app's windows each have a button for the bar: they are told when it comes and goes. */
let channel = null;
try {
  channel = new BroadcastChannel('sluka-desktop-bar');
} catch {
  /* the buttons ask for themselves */
}

/** Where the bar is (its middle and its foot, as shares of the screen), how wide and how large, and how it behaves. */
const state = { x: 0.5, y: 0.9, width: 0, scale: 1, lock: false, through: false };

/** How Sluka is set to look, as its engine says (`ready`); until it has, the script in mpv's own defaults. */
const look = {
  cjk: false,
  size: 1,
  bg: 0.84,
  light: false,
  line_height: 1.34,
  spacing: 0.01,
  fonts: { cc: ['system-ui', 'Segoe UI', 'Roboto', 'sans-serif'], ui: ['system-ui', 'sans-serif'], word: ['Georgia', 'Times New Roman', 'serif'] },
  font_lang: '',
  theme: 'light',
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

/** The line shown: its text, and its words once the engine has cut it ({ s, e, key, st, g } each, s and e in UTF-8 bytes). */
let line = null;
let seq = 0;
let subLang = '';
let hover = null;
let pinned = null;
let entry = null;
let dwell = 0;
let drag = null;
let leaveTimer = 0;
let toastTimer = 0;

// ------------------------------------------------------------ small things

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** The families of a list, as a stylesheet writes them: the generic ones bare, every other in quotes. */
const GENERIC = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace',
  'ui-rounded', 'emoji', 'math', 'fangsong', '-apple-system', 'BlinkMacSystemFont']);
const family = (list) => (Array.isArray(list) ? list : [])
  .map((name) => String(name ?? '').trim())
  .filter(Boolean)
  .map((name) => (GENERIC.has(name) ? name : `"${name.replace(/["\\]/g, '\\$&')}"`))
  .join(', ');

/** "rrggbb" (how the engine says every colour) as "r g b", for rgb() with an alpha of its own. */
function channels(hex, fallback = '255 255 255') {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex ?? ''));
  return m ? [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)).join(' ') : fallback;
}
const colour = (hex, alpha = 1) => `rgb(${channels(hex)} / ${alpha})`;

/** Where each UTF-8 byte offset of `text` falls in it as JavaScript counts (the engine says where words are in bytes, for mpv's Lua). */
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

// ------------------------------------------------------------ talking

/** Something said to Sluka's engine, as a player says it. */
async function send(msg) {
  try {
    const answer = await api('bar/say', { msg });
    if (answer && answer.engine === false && app.engine) {
      // Sluka's engine is not running in this app (Sluka Desktop's log says why): lines are shown as they come.
      app.engine = false;
      app.ready = false;
      renderLine();
      layout();
    }
    return answer;
  } catch {
    return null;
  }
}

function hello() {
  send({ t: 'hello', v: PROTOCOL, sub_lang: subLang });
}

// ------------------------------------------------------------ the look

function adoptLook(l) {
  if (!l || typeof l !== 'object') return;
  for (const k of ['cjk', 'light', 'spaced']) if (typeof l[k] === 'boolean') look[k] = l[k];
  for (const k of ['size', 'pos', 'bg', 'line_height', 'spacing', 'hover_delay']) if (Number.isFinite(l[k])) look[k] = l[k];
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
      legend: l.text.legend && typeof l.text.legend === 'object' ? l.text.legend : null,
      also: typeof l.text.also === 'string' && l.text.also ? l.text.also : 'Also',
    };
  }
}

/** What a word wears at each level: a fill behind it a pixel short at its start, a line under it, the letters' own colour. */
const wear = new CSSStyleSheet();
document.adoptedStyleSheets = [...document.adoptedStyleSheets, wear];

function dressWords() {
  const rules = [];
  for (const [st, w] of Object.entries(look.words || {})) {
    if (!w || typeof w !== 'object' || !Number.isFinite(Number(st))) continue;
    const layers = [];
    if (w.line) {
      // Under levels 3 and 4: a line that curves up at the word's corners.
      layers.push(`linear-gradient(to right, transparent 1px, ${colour(w.line)} 1px) left bottom / 100% .1em no-repeat`);
      if (!Array.isArray(w.fill)) {
        // Without a fill the word's box is said by its sides: a hairline of the level's colour.
        const side = colour(w.line, 0.2);
        layers.push(`linear-gradient(to right, transparent 1px, ${side} 1px 2px, transparent 2px calc(100% - 1px), ${side} calc(100% - 1px))`);
      }
    }
    if (Array.isArray(w.fill)) layers.push(`linear-gradient(to right, transparent 1px, ${colour(w.fill[0], clamp(Number(w.fill[1]) || 0, 0, 1))} 1px)`);
    const said = [];
    if (layers.length) said.push(`background: ${layers.join(', ')}`);
    if (w.ink) said.push(`color: ${colour(w.ink)}`);
    if (said.length) rules.push(`.cc .w[data-st="${Number(st)}"]:not([data-g]) { ${said.join('; ')} }`);
  }
  wear.replaceSync(rules.join('\n'));
}

/** The language the box is in, for the web engine's choice of letters (Japanese and Chinese kanji differ). */
function langTag() {
  const told = look.font_lang;
  if (told === 'zh-tw') return 'zh-Hant';
  if (told === 'zh-cn') return 'zh-Hans';
  if (told === 'zh-hk') return 'zh-HK';
  return app.lang || told || '';
}

function applyLook() {
  const s = root.style;
  s.setProperty('--cc-font', family(look.fonts.cc) || 'system-ui, sans-serif');
  s.setProperty('--ui-font', family(look.fonts.ui) || 'system-ui, sans-serif');
  s.setProperty('--word-font', family(look.fonts.word) || 'serif');
  s.setProperty('--lh', String(look.line_height));
  s.setProperty('--sp', `${look.spacing}em`);
  const bg = clamp(Number(look.bg), 0, 1);
  s.setProperty('--cc-bg', String(bg));
  s.setProperty('--cc-hair', String(!look.light && bg > 0.05 ? 0.07 * bg : 0));
  // A box thinned out gets a dark edge round its letters (content.css --llr-cc-edges).
  const edge = clamp(1 - bg / 0.6, 0, 1);
  const ink = look.light ? '255 255 255' : '0 0 0';
  const a = (edge * 0.85).toFixed(3);
  s.setProperty('--cc-edges', edge > 0 ? `0 0 .045em rgb(${ink} / ${a}), 0 0 .07em rgb(${ink} / ${a}), 0 0 .14em rgb(${ink} / ${a})` : 'none');
  cc.classList.toggle('light', !!look.light);
  const theme = look.theme === 'dark' ? 'dark' : 'light';
  card.dataset.theme = theme;
  panel.dataset.theme = theme;
  cc.lang = langTag();
  dressWords();
}

/** Sluka's subtitle size, as it sets it over a film as wide as the screen (content.css): then the bar's own size. */
function fontSize() {
  const wide = Math.max(320, innerWidth);
  return (13 + wide * 0.0165) * (Number(look.size) || 1) * (look.cjk ? 1 : 0.88) * state.scale;
}

// ------------------------------------------------------------ the bar's place and size

function barWidth() {
  const vw = innerWidth;
  const wanted = state.width > 0 ? state.width : Math.min(vw * 0.6, 1100);
  return Math.round(clamp(wanted, 160, Math.max(160, vw - 16)));
}

function layout() {
  const E = fontSize();
  root.style.setProperty('--E', `${E}px`);
  const width = barWidth();
  bar.style.setProperty('--width', `${width}px`);
  squeeze(width, E);
  place();
}

/** A line a little too wide for one row is set smaller rather than broken; a longer one is broken into rows of even length. */
function squeeze(width, E) {
  cc.style.removeProperty('font-size');
  if (!line || cc.classList.contains('idle')) return;
  const room = width - 1.1 * E;
  cc.style.whiteSpace = 'nowrap';
  cc.style.maxWidth = 'none';
  const natural = cc.getBoundingClientRect().width - 1.1 * E;
  cc.style.whiteSpace = '';
  cc.style.maxWidth = '';
  if (natural > room + 0.5 && room / natural >= SQUEEZE_MIN) {
    cc.style.fontSize = `${(Math.floor((room / natural) * 1000) / 1000) * E}px`;
  }
}

/** The bar where it was put, kept on the screen: the room for its buttons over it included. */
function place() {
  const vw = innerWidth;
  const vh = innerHeight;
  const width = barWidth();
  const height = bar.offsetHeight || 0;
  let x = state.x * vw;
  let y = state.y * vh;
  if (!(drag && drag.started)) {
    x = clamp(x, width / 2 + 4, vw - width / 2 - 4);
    y = clamp(y, Math.min(vh - 4, height + 44), vh - 4);
  }
  bar.style.setProperty('--x', `${Math.round(x)}px`);
  bar.style.setProperty('--y', `${Math.round(y)}px`);
}

function dress() {
  bar.classList.toggle('locked', !!state.lock);
  bar.classList.toggle('through', !!state.through);
  for (const button of tools.querySelectorAll('[data-act="lock"]')) button.setAttribute('aria-pressed', String(!!state.lock));
  for (const button of tools.querySelectorAll('[data-act="through"]')) button.setAttribute('aria-pressed', String(!!state.through));
}

let saveTimer = 0;
function save(now = false) {
  clearTimeout(saveTimer);
  const go = () => {
    const kept = { x: state.x, y: state.y, width: state.width, scale: state.scale, lock: state.lock, through: state.through };
    api('bar/state', { state: kept }).catch(() => {});
  };
  if (now) go();
  else saveTimer = setTimeout(go, 200);
}

// ------------------------------------------------------------ the line

function renderLine() {
  cc.replaceChildren();
  delete cc.dataset.rtl;
  const text = line ? line.text : '';
  if (!text.trim()) {
    cc.classList.add('idle');
    cc.append('Sluka');
    cc.append(el('span', 'hint', app.engine
      ? 'Floating subtitles: lines sent here are read with Sluka'
      : 'Floating subtitles: Sluka’s engine is off, so lines are shown plain'));
    return;
  }
  cc.classList.remove('idle');
  if (line.rtl) cc.dataset.rtl = '';
  if (!Array.isArray(line.toks)) {
    // Shown as it is until the engine has cut it into words.
    cc.append(text);
    return;
  }
  const at = byteIndex(text);
  let done = 0;
  line.toks.forEach((tok, k) => {
    const from = at.get(Number(tok.s));
    const to = at.get(Number(tok.e));
    if (from === undefined || to === undefined || from < done || to <= from) return;
    if (from > done) cc.append(text.slice(done, from));
    const word = el('span', 'w', text.slice(from, to));
    word.dataset.i = String(k + 1);
    word.dataset.st = String(Number(tok.st) || 0);
    if (tok.g) word.dataset.g = '';
    tok.from = from;
    tok.to = to;
    cc.append(word);
    done = to;
  });
  if (done < text.length) cc.append(text.slice(done));
  markWords();
}

const wordEl = (i) => (i == null ? null : cc.querySelector(`.w[data-i="${i}"]`));

function markWords() {
  for (const word of cc.querySelectorAll('.w.hov, .w.pin')) word.classList.remove('hov', 'pin');
  wordEl(hover)?.classList.add('hov');
  wordEl(pinned)?.classList.add('pin');
}

function newLine(text, lang) {
  text = String(text ?? '').replace(/\r\n?/g, '\n');
  if (typeof lang === 'string' && lang !== subLang) {
    // Text in another of the languages you learn: the engine is told, as mpv tells it of another subtitle track.
    subLang = lang;
    if (app.ready) send({ t: 'track', sub_lang: subLang });
  }
  if (line && line.text === text) return;
  clearTimeout(dwell);
  hover = null;
  pinned = null;
  entry = null;
  hideCard();
  line = text.trim() ? { id: ++seq, text, toks: null, rtl: false } : null;
  renderLine();
  layout();
  report();
  if (line && app.ready) send({ t: 'line', id: line.id, text });
  // Nothing on the bar now: no more of the last line is being read (counted on Sluka's Home page by the engine).
  else if (!line && app.ready) send({ t: 'shown', on: false });
}

// ------------------------------------------------------------ a word pointed at, clicked, graded

function setHover(i) {
  if (i === hover) return;
  hover = i;
  clearTimeout(dwell);
  if (!pinned) {
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
  // A card already up says what would be asked for; a click asks all the same, for it files the word.
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

/** The pinned word into Anki (the panel's Anki key, or its key on the keyboard). */
function pickAnki() {
  const tok = tokAt(pinned);
  if (pinned == null || !tok || !line || !app.ready || tok.g) return;
  send({ t: 'anki', id: line.id, tok: pinned, key: tok.key, text: line.text.slice(tok.from, tok.to) });
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

// ------------------------------------------------------------ the card and the panel

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

/** The reading, a part of speech set apart, and a Japanese reading's pitch drawn over its kana. */
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

/** The pill that names a word's level, with a dot in the colour the level has on a page. */
function chipEl(e) {
  const st = Number(e.st ?? NEW);
  const pal = look.panel || {};
  const levels = Array.isArray(pal.levels) ? pal.levels : [];
  const lines = Array.isArray(pal.lines) ? pal.lines : [];
  const dot = el('i');
  if (st === 3 || st === 4) {
    // Levels 3 and 4 wear a line on a page, so their swatch does too.
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
  for (const [st, label] of buttons) {
    const button = el('button', st >= KNOWN ? 'wide' : '');
    button.type = 'button';
    button.dataset.act = 'grade';
    button.dataset.st = String(st);
    const name = look.text.labels?.[st];
    const key = look.keys?.[st];
    button.title = [name || label, key ? `(${String(key).toUpperCase()})` : ''].filter(Boolean).join(' ');
    if (Number(e.st) === st) {
      button.classList.add('lit');
      // The word's own level, pressed again, puts it back to New, as 0 does (content/ui.js lvlBtn): its title says so.
      button.dataset.lit = '';
      button.setAttribute('aria-pressed', 'true');
      const forget = look.keys?.[NEW];
      button.title = [look.text.back || 'Back to new', forget ? `(${String(forget).toUpperCase()})` : ''].filter(Boolean).join(' ');
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
      // Beside the number, a patch of page with that level on it.
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

/** The keys that do the same, each in its little cap. */
function legendEl(e) {
  const row = el('div', 'legend');
  const legend = look.text.legend;
  if (!legend || !Array.isArray(legend.parts)) return row;
  const parts = [...legend.parts];
  if (Number(e.st) !== NEW && Array.isArray(legend.forget)) parts.push(legend.forget);
  parts.forEach((part, i) => {
    if (i > 0) row.append(el('span', 'sp'), '·', el('span', 'sp'));
    for (const seg of Array.isArray(part) ? part : []) {
      if (seg && typeof seg === 'object' && seg.k != null) {
        row.append(el('span', 'k', seg.k));
      } else if (typeof seg === 'string' && seg) {
        const core = seg.trim();
        if (/^\s/.test(seg)) row.append(el('span', 'sp'));
        if (core) row.append(core);
        if (/\s$/.test(seg) && core) row.append(el('span', 'sp'));
      }
    }
  });
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
  close.title = 'Close (Esc)';
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

  panel.append(ph, sub, body, levelsEl(e), legendEl(e), el('div', 'foot'));
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

/** Over the line and centred on its word, as far as the screen lets it be; under the line where there is no room over it. */
function placeOver(node, word, isPanel) {
  const vw = innerWidth;
  const vh = innerHeight;
  const w = word.getClientRects()[0] || word.getBoundingClientRect();
  const b = cc.getBoundingClientRect();
  if (isPanel) {
    const room = Math.max(b.top - 16, vh - b.bottom - 16);
    node.style.setProperty('--panel-max', `${Math.max(180, Math.floor(room))}px`);
  }
  const r = node.getBoundingClientRect();
  const x = clamp((w.left + w.right) / 2 - r.width / 2, 8, Math.max(8, vw - r.width - 8));
  let y = b.top - 8 - r.height;
  if (y < 8) {
    const under = b.bottom + 8;
    y = under + r.height <= vh - 8 ? under : 8;
  }
  node.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
}

function showCard() {
  const idx = pinned ?? hover;
  const word = wordEl(idx);
  if (!line || idx == null || !entry || entry.tok !== idx || entry.id !== line.id || !word) {
    hideCard();
    return;
  }
  if (pinned === idx) {
    card.hidden = true;
    buildPanel(entry);
    panel.hidden = false;
    const legend = panel.querySelector('.legend');
    if (legend && legend.scrollWidth > legend.clientWidth + 1) legend.style.visibility = 'hidden';
    placeOver(panel, word, true);
  } else {
    panel.hidden = true;
    buildGlance(entry);
    card.hidden = false;
    placeOver(card, word, false);
  }
  bar.classList.add('covered');
  report();
}

function hideCard() {
  if (card.hidden && panel.hidden) return;
  card.hidden = true;
  panel.hidden = true;
  bar.classList.remove('covered');
  report();
}

// ------------------------------------------------------------ a word of Sluka's

function showToast(text, seconds = 3) {
  toast.textContent = String(text);
  toast.hidden = false;
  const b = box.getBoundingClientRect();
  const r = toast.getBoundingClientRect();
  const x = clamp((b.left + b.right) / 2 - r.width / 2, 8, Math.max(8, innerWidth - r.width - 8));
  let y = b.top - 10 - r.height;
  if (y < 8) y = b.bottom + 10;
  toast.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
    report();
  }, clamp(Number(seconds) || 3, 1, 30) * 1000);
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
  // The line on screen asked for again, under the new language or colours.
  if (line) line = { id: ++seq, text: line.text, toks: null, rtl: false };
  renderLine();
  layout();
  report();
  if (line) send({ t: 'line', id: line.id, text: line.text });
  if (!was && !m.quiet) showToast(`Sluka: ${app.langName || 'connected'}`, 2);
}

function onTokens(m) {
  if (!line || m.id !== line.id || !Array.isArray(m.toks)) return;
  line.toks = m.toks;
  line.rtl = !!m.rtl;
  renderLine();
  layout();
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
  line.toks.forEach((tok, k) => {
    if (tok.key !== m.key || Number(tok.st) === Number(m.st)) return;
    tok.st = m.st;
    changed = true;
    const word = wordEl(k + 1);
    if (word) word.dataset.st = String(Number(m.st) || 0);
  });
  if (entry && entry.key === m.key) {
    entry.st = m.st;
    entry.label = m.label || entry.label;
  }
  // Known and ignored are done with: the panel is put away, as Sluka puts its own away.
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

let placed = false;

function fromApp(m) {
  if (!m || typeof m.t !== 'string') return;
  if (m.t === 'state') {
    const s = m.state || {};
    for (const k of ['x', 'y', 'width', 'scale']) if (Number.isFinite(s[k])) state[k] = s[k];
    for (const k of ['lock', 'through']) if (typeof s[k] === 'boolean') state[k] = s[k];
    state.scale = clamp(state.scale || 1, SCALE_MIN, SCALE_MAX);
    if (m.engine === false) app.engine = false;
    dress();
    renderLine();
    bar.hidden = false;
    layout();
    placed = true;
    report(true);
    if (app.engine) hello();
  } else if (m.t === 'set') {
    // Set from the app's side (its window menu): taken as it is.
    const s = m.state || {};
    for (const k of ['lock', 'through']) if (typeof s[k] === 'boolean') state[k] = s[k];
    dress();
    layout();
    report(true);
  } else if (m.t === 'text') {
    newLine(m.text, m.lang);
  } else if (m.t === 'engine') {
    fromEngine(m.msg);
  }
}

// ------------------------------------------------------------ which parts of the window are drawn on

let reportFrame = 0;
let reportTimer = 0;
let reportForced = false;
let lastShape = '';

function union(rects, margin) {
  const real = rects.filter((r) => r && r.width > 0 && r.height > 0);
  if (!real.length) return null;
  const left = Math.min(...real.map((r) => r.left)) - margin;
  const top = Math.min(...real.map((r) => r.top)) - margin;
  const right = Math.max(...real.map((r) => r.right)) + margin;
  const bottom = Math.max(...real.map((r) => r.bottom)) + margin;
  return [left, top, right - left, bottom - top];
}

/**
 * Tells the app which parts of the window are drawn on, in this page's pixels
 * (and how many of the screen's each is): the window is shaped to them, so the
 * pointer goes through everywhere else.  `live` are the parts that still take
 * it when clicks are let through (the button that takes them back, an open
 * panel); `all` is the whole window, while the bar is being moved.
 */
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
  // At the next frame; and in any case soon, for a page the engine draws no frames for until it is seen --
  // which it is not, until the window is told what to show.
  reportFrame = requestAnimationFrame(go);
  reportTimer = setTimeout(go, 100);
}

function tellShape(force) {
  const rects = [];
  const live = [];
  const take = (node, [l, t, r, b], into = rects) => {
    if (!node || node.hidden) return;
    const q = node.getBoundingClientRect();
    if (q.width <= 0 || q.height <= 0) return;
    into.push([q.left - l, q.top - t, q.width + l + r, q.height + t + b]);
  };
  if (!bar.hidden) {
    if (bar.classList.contains('on') || (drag && drag.started)) {
      // While the pointer is on it, the bar whole: its width, its buttons, and the room between them.
      const parts = [area.getBoundingClientRect()];
      if (!bar.classList.contains('covered')) parts.push(tools.getBoundingClientRect());
      if (state.through) parts.push(badge.getBoundingClientRect());
      const whole = union(parts, 6);
      if (whole) rects.push(whole);
    } else {
      take(box, [3, 3, 3, 3]);
      if (state.through) take(badge, [3, 3, 3, 3]);
    }
    if (state.through) take(badge, [2, 2, 2, 2], live);
  }
  // Room for the shadows round them, which reaches the line: the pointer can go from one to the other.
  take(card, [22, 12, 22, 32]);
  take(panel, [26, 14, 26, 38]);
  if (state.through) take(panel, [0, 0, 0, 0], live);
  take(toast, [4, 4, 4, 4]);
  const round = (list) => list.map((r) => r.map((v) => Math.round(v * 10) / 10));
  const shape = { rects: round(rects), live: round(live), all: !!(drag && drag.started), dpr: window.devicePixelRatio || 1 };
  const said = JSON.stringify(shape);
  if (!force && said === lastShape) return;
  lastShape = said;
  api('bar/shape', shape).catch(() => {
    lastShape = '';
  });
}

// ------------------------------------------------------------ the pointer

box.addEventListener('pointermove', (e) => {
  if (drag && drag.started) return;
  const word = e.target.closest?.('.w');
  setHover(word && cc.contains(word) ? Number(word.dataset.i) : null);
});
box.addEventListener('pointerleave', () => {
  if (!drag) setHover(null);
});

bar.addEventListener('pointerenter', () => {
  clearTimeout(leaveTimer);
  if (!bar.classList.contains('on')) {
    bar.classList.add('on');
    report();
  }
});
bar.addEventListener('pointerleave', () => {
  clearTimeout(leaveTimer);
  leaveTimer = setTimeout(() => {
    if (drag) return;
    bar.classList.remove('on');
    report();
  }, LEAVE_MS);
});

function startDrag(e, mode, pending, word = null) {
  const r = bar.getBoundingClientRect();
  drag = {
    id: e.pointerId, mode, pending, started: false, word,
    x0: e.clientX, y0: e.clientY, cx: (r.left + r.right) / 2, by: r.bottom,
  };
  try {
    bar.setPointerCapture(e.pointerId);
  } catch {
    /* the press is followed all the same while it stays on the bar */
  }
}

bar.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || drag) return;
  const target = e.target;
  const act = target.closest?.('[data-act]')?.dataset.act;
  if (act === 'grip') {
    if (!state.lock) startDrag(e, 'move', false);
    e.preventDefault();
  } else if (act === 'size') {
    if (!state.lock) startDrag(e, 'size', false);
    e.preventDefault();
  } else if (!act && box.contains(target)) {
    // On the subtitle: a click on a word, or (where the bar is not kept in place) a drag of the whole.
    const word = target.closest?.('.w');
    startDrag(e, state.lock ? 'click' : 'move', true, word && cc.contains(word) ? Number(word.dataset.i) : null);
  }
});

addEventListener('pointermove', (e) => {
  if (!drag || e.pointerId !== drag.id) return;
  const dx = e.clientX - drag.x0;
  const dy = e.clientY - drag.y0;
  if (drag.pending) {
    if (drag.mode !== 'move' || Math.hypot(dx, dy) < DRAG_FROM) return;
    drag.pending = false;
  }
  if (!drag.started) {
    drag.started = true;
    bar.classList.add('dragging');
    clearTimeout(dwell);
    hover = null;
    pinned = null;
    entry = null;
    markWords();
    hideCard();
  }
  if (drag.mode === 'move') {
    state.x = (drag.cx + dx) / innerWidth;
    state.y = (drag.by + dy) / innerHeight;
    place();
  } else if (drag.mode === 'size') {
    state.width = Math.round(clamp(2 * Math.abs(e.clientX - drag.cx), 160, Math.max(160, innerWidth - 16)));
    layout();
  }
  report();
});

async function endDrag(e) {
  if (!drag || e.pointerId !== drag.id) return;
  const d = drag;
  drag = null;
  try {
    bar.releasePointerCapture(e.pointerId);
  } catch {
    /* already let go */
  }
  bar.classList.remove('dragging');
  if (!d.started) {
    if (e.type === 'pointerup' && (d.mode === 'move' || d.mode === 'click') && d.pending) clickWord(d.word);
    report();
    return;
  }
  if (d.mode === 'move') {
    const cx = state.x * innerWidth;
    const by = state.y * innerHeight;
    const mid = by - bar.offsetHeight / 2;
    if (cx < 0 || cx > innerWidth || mid < 0 || mid > innerHeight) {
      // Taken off this screen: the window goes to the one it was taken to, and the bar with it.
      try {
        const moved = await api('bar/monitor', { x: cx, y: by, dpr: window.devicePixelRatio || 1 });
        if (moved && moved.ok && Number.isFinite(moved.fx) && Number.isFinite(moved.fy)) {
          state.x = moved.fx;
          state.y = moved.fy;
        }
      } catch {
        /* it stays on this one */
      }
    }
  }
  layout();
  save(true);
  report(true);
}
addEventListener('pointerup', endDrag);
addEventListener('pointercancel', endDrag);

document.addEventListener('click', (e) => {
  const button = e.target.closest?.('[data-act]');
  if (!button) return;
  const act = button.dataset.act;
  if (act === 'smaller' || act === 'larger') {
    const next = act === 'larger' ? state.scale * SCALE_STEP : state.scale / SCALE_STEP;
    state.scale = clamp(Math.round(next * 1000) / 1000, SCALE_MIN, SCALE_MAX);
    layout();
    save();
    report();
  } else if (act === 'lock') {
    state.lock = !state.lock;
    dress();
    save(true);
    report();
  } else if (act === 'through') {
    state.through = !state.through;
    dress();
    save(true);
    report(true);
  } else if (act === 'close') {
    channel?.postMessage({ on: false });
    api('bar/hide', {}).catch(() => {});
  } else if (act === 'unpin') {
    unpin();
  } else if (act === 'anki') {
    pickAnki();
  } else if (act === 'translate') {
    translateWord();
  } else if (act === 'speak') {
    speakWord();
  } else if (act === 'ask') {
    askAi();
  } else if (act === 'look') {
    lookOpen = !lookOpen;
    showCard();
  } else if (act === 'site') {
    lookSite(button.dataset.site, button.dataset.offline === '1');
  } else if (act === 'grade') {
    // The lit level puts the word back to New -- but not as the second click of a double-click, which the first
    // click's lit button would take back at once (content/ui.js).
    const lit = button.dataset.lit !== undefined;
    if (lit && e.detail > 1) return;
    grade(lit ? NEW : Number(button.dataset.st));
  }
});

// Where this window has the keyboard (it does not take it from the program under it): Sluka's own keys.
addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    unpin();
    return;
  }
  if (e.ctrlKey || e.altKey || e.metaKey || e.repeat) return;
  if ((pinned ?? hover) == null) return;
  const pressed = String(e.key).toLowerCase();
  if (pinned != null && look.anki_key && pressed === look.anki_key.toLowerCase()) {
    e.preventDefault();
    pickAnki();
    return;
  }
  if (look.say_key && pressed === look.say_key.toLowerCase()) {
    e.preventDefault();
    speakWord();
    return;
  }
  // The AI check's key: only for a panel open (each press is a request on your key).
  if (pinned != null && look.ask_key && pressed === look.ask_key.toLowerCase()) {
    e.preventDefault();
    askAi();
    return;
  }
  for (const [st, key] of Object.entries(look.keys || {})) {
    if (String(key).toLowerCase() === pressed) {
      e.preventDefault();
      grade(Number(st));
      return;
    }
  }
});

// Not a web page: no menu of the web view's own on a right click, nothing to drag out of it.
addEventListener('contextmenu', (e) => e.preventDefault());
addEventListener('dragstart', (e) => e.preventDefault());

addEventListener('resize', () => {
  layout();
  if (!card.hidden || !panel.hidden) showCard();
  report(true);
});

try {
  new ResizeObserver(() => {
    if (!placed) return;
    place();
    report();
  }).observe(bar);
} catch {
  /* sizes are told as they change otherwise */
}
document.fonts?.ready?.then(() => {
  if (!placed) return;
  layout();
  report();
});

// ------------------------------------------------------------ asking the app for news

async function listen() {
  applyLook();
  channel?.postMessage({ on: true });
  let fresh = true;
  let failures = 0;
  for (;;) {
    try {
      const got = await api('bar/poll', { fresh });
      fresh = false;
      failures = 0;
      // Another copy of this page has taken over.
      if (got && got.superseded) break;
      for (const m of (got && got.msgs) || []) {
        try {
          fromApp(m);
        } catch (err) {
          console.error('[sluka-desktop] the floating subtitles could not show what came:', err);
        }
      }
    } catch {
      // The app's host went away, or is not there yet: asked again, ever more slowly.
      failures += 1;
      await new Promise((resolve) => setTimeout(resolve, Math.min(15000, 500 * failures)));
    }
  }
}

listen();
