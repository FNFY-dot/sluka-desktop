// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * The app's own buttons in each of its windows (shim.js brings them in where
 * the app has them): a small dock in a corner of the window -- the bottom
 * left unless [bar] button in config.ini says another, or none -- with
 *
 *   the floating subtitles' button, which turns them on and off, and
 *   the game text button, which opens the game text menu: where the lines
 *   the floating subtitles show come from (a game, read by Sluka's own
 *   engine -- LunaHook, from LunaTranslator -- or a box of a game's window
 *   read off the screen, or the clipboard), which game, and which of the
 *   game's text threads -- as LunaTranslator's text selection has it; and
 *   Sluka Vision, a game's whole window read and its words laid over it.
 *   The work is the app's (gametext.py, texthook.py, hookd.py; ocrtext.py,
 *   ocrd.py for the screen; vision.py); this page only shows it and passes
 *   on what is clicked.
 *
 * The dock can be dragged elsewhere, and stays there.  It lives in a shadow
 * root of its own, out of reach of the page's styles and scripts.
 */
(() => {
  'use strict';
  if (globalThis.__slukaDock) return;
  globalThis.__slukaDock = true;

  const shim = globalThis.__slukaShim;
  const BOOT = globalThis.__SLUKA_BOOT__ || {};
  const where = String(BOOT.barButton || 'bottom-left');
  if (!shim || where === 'none') return;
  const [vertical, horizontal] = where.split('-');
  const GAMES = BOOT.games === true;

  const CSS = `
    :host { all: initial; }
    [hidden] { display: none !important; }
    .dock {
      position: fixed;
      ${vertical === 'top' ? 'top' : 'bottom'}: 12px;
      ${horizontal === 'right' ? 'right' : 'left'}: 12px;
      z-index: 2147483000;
      display: flex;
      gap: 6px;
      padding: 3px;
      border-radius: 999px;
      background: rgb(24 24 22 / .5);
      box-shadow: 0 0 0 1px rgb(255 255 255 / .1), 0 4px 14px rgb(0 0 0 / .22);
      opacity: .6;
      transition: opacity .15s;
      font: 13px/1.4 system-ui, 'Segoe UI', sans-serif;
      -webkit-tap-highlight-color: transparent;
    }
    .dock:hover, .dock:focus-within, .dock.open, .dock.moving { opacity: 1; }
    .dock.moving { cursor: grabbing; }
    .b {
      position: relative;
      box-sizing: border-box;
      width: 30px;
      height: 30px;
      margin: 0;
      padding: 0;
      border: 0;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: rgb(24 24 22 / .74);
      color: rgb(255 255 255 / .9);
      cursor: pointer;
      transition: background-color .15s, color .15s;
    }
    .b:hover { background: rgb(44 44 41 / .92); }
    .b:focus-visible { outline: 2px solid rgb(126 168 255); outline-offset: 2px; }
    .b[aria-pressed='true'], .b[aria-expanded='true'] { background: rgb(242 240 235); color: rgb(26 24 21); }
    .b svg { width: 16px; height: 16px; display: block; }
    .dot {
      position: absolute;
      right: 1px;
      top: 1px;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      box-shadow: 0 0 0 1.5px rgb(24 24 22);
      display: none;
    }
    .dot[data-tone] { display: block; }
    .dot[data-tone='live'] { background: rgb(92 201 138); }
    .dot[data-tone='wait'] { background: rgb(224 166 74); }
    .dot[data-tone='other'] { background: rgb(126 168 255); }
    .dot[data-tone='bad'] { background: rgb(230 98 84); }
    @media print { .dock, .panel { display: none !important; } }

    /* ---------------------------------------------------------- the menu, in Sluka's card palettes */

    .theme {
      --bg: 255 255 255; --ring: 33 32 28; --ring-a: .14; --shade: 33 32 28; --shade-a: .16;
      --ink: 33 32 28; --body: 52 51 46; --ink2: 83 82 76; --ink3: 120 118 112;
      --chip: 33 32 28; --chip-a: .06; --chip-hover-a: .1; --hair-a: .1; --field: 255 255 255;
      --on: 33 32 28; --on-ink: 255 255 255; --accent: 36 89 199; --good: 31 154 87; --warn: 176 110 20; --bad: 196 62 50;
      --pick: 36 89 199; --pick-a: .09;
    }
    .theme[data-theme='dark'] {
      --bg: 34 34 33; --ring: 255 255 255; --ring-a: .2; --shade: 0 0 0; --shade-a: .4;
      --ink: 242 240 235; --body: 222 219 212; --ink2: 181 179 173; --ink3: 146 144 137;
      --chip: 255 255 255; --chip-a: .07; --chip-hover-a: .12; --hair-a: .09; --field: 26 26 25;
      --on: 242 240 235; --on-ink: 26 24 21; --accent: 126 168 255; --good: 92 201 138; --warn: 232 178 92; --bad: 240 120 106;
      --pick: 126 168 255; --pick-a: .14;
    }
    .panel {
      position: fixed;
      z-index: 2147483001;
      box-sizing: border-box;
      width: min(400px, calc(100vw - 16px));
      max-height: min(620px, calc(100vh - 72px));
      display: flex;
      flex-direction: column;
      border-radius: 14px;
      background: rgb(var(--bg));
      color: rgb(var(--ink));
      box-shadow: 0 0 0 1px rgb(var(--ring) / var(--ring-a)), 0 14px 36px rgb(var(--shade) / var(--shade-a));
      font: 13px/1.45 system-ui, 'Segoe UI', sans-serif;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }
    .panel * { box-sizing: border-box; }
    header { display: flex; align-items: center; gap: 8px; padding: 12px 12px 8px 16px; }
    h2 { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: -.005em; flex: 1; }
    .pill {
      display: inline-block; margin-left: 6px; padding: 1px 8px; border-radius: 999px; vertical-align: 1px;
      font-size: 11px; font-weight: 600; background: rgb(var(--chip) / var(--chip-a)); color: rgb(var(--ink2));
    }
    .pill[data-tone='live'] { color: rgb(var(--good)); }
    .pill[data-tone='wait'] { color: rgb(var(--warn)); }
    .pill[data-tone='bad'] { color: rgb(var(--bad)); }
    .pill[data-tone='other'] { color: rgb(var(--accent)); }
    .icon {
      width: 28px; height: 28px; border: 0; border-radius: 8px; padding: 0; display: grid; place-items: center;
      background: transparent; color: rgb(var(--ink2)); cursor: pointer; font: inherit;
    }
    .icon:hover { background: rgb(var(--chip) / var(--chip-hover-a)); color: rgb(var(--ink)); }
    .icon svg { width: 14px; height: 14px; }
    .tabs { display: flex; gap: 4px; margin: 0 12px 8px; padding: 3px; border-radius: 999px; background: rgb(var(--chip) / var(--chip-a)); }
    .tabs button {
      flex: 1; border: 0; border-radius: 999px; padding: 5px 6px; background: transparent; color: rgb(var(--ink2));
      font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; white-space: nowrap;
    }
    .tabs button:hover { color: rgb(var(--ink)); }
    .tabs button[aria-selected='true'] { background: rgb(var(--on)); color: rgb(var(--on-ink)); }
    .body { overflow: auto; padding: 2px 16px 12px; flex: 1; min-height: 0; }
    p { margin: 6px 0 10px; color: rgb(var(--body)); }
    .small { font-size: 12px; color: rgb(var(--ink3)); }
    .row { display: flex; gap: 6px; align-items: center; margin: 8px 0; }
    .row > .grow { flex: 1; min-width: 0; }
    select, input[type='text'] {
      height: 30px; border-radius: 8px; border: 0; padding: 0 9px; font: inherit; color: rgb(var(--ink));
      background: rgb(var(--field)); box-shadow: inset 0 0 0 1px rgb(var(--ring) / .2); min-width: 0;
    }
    select:focus-visible, input[type='text']:focus-visible, .btn:focus-visible, .tabs button:focus-visible, .icon:focus-visible,
    summary:focus-visible, .t:focus-visible { outline: 2px solid rgb(var(--accent)); outline-offset: 1px; }
    input.code { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
    .btn {
      height: 30px; padding: 0 12px; border: 0; border-radius: 999px; font: inherit; font-weight: 600; cursor: pointer;
      background: rgb(var(--chip) / var(--chip-a)); color: rgb(var(--ink)); white-space: nowrap;
      box-shadow: inset 0 0 0 1px rgb(var(--ring) / .12);
    }
    .btn:hover { background: rgb(var(--chip) / var(--chip-hover-a)); }
    .btn.primary { background: rgb(var(--on)); color: rgb(var(--on-ink)); box-shadow: none; }
    .btn.primary:hover { filter: brightness(1.08); }
    .btn.quiet { background: transparent; box-shadow: none; color: rgb(var(--accent)); padding: 0 4px; height: 24px; font-weight: 600; }
    .btn[disabled] { opacity: .45; cursor: default; }
    .card { margin: 8px 0; padding: 10px 12px; border-radius: 10px; background: rgb(var(--chip) / var(--chip-a)); }
    .card b { font-weight: 650; }
    .state, .boxstate { display: flex; gap: 8px; align-items: center; }
    .state .what, .boxstate .what { flex: 1; min-width: 0; }
    .state .name, .boxstate .name { font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .state .how, .boxstate .how { font-size: 12px; color: rgb(var(--ink2)); }
    .state .how[data-tone='bad'], .boxstate .how[data-tone='bad'] { color: rgb(var(--bad)); }
    .state .how[data-tone='live'], .boxstate .how[data-tone='live'] { color: rgb(var(--good)); }
    .bar { height: 4px; border-radius: 2px; background: rgb(var(--chip) / .12); overflow: hidden; margin-top: 8px; }
    .bar i { display: block; height: 100%; width: 0; background: rgb(var(--accent)); transition: width .2s; }
    .head { display: flex; align-items: baseline; gap: 8px; margin: 12px 0 4px; }
    .head h3 { margin: 0; font-size: 12px; font-weight: 650; text-transform: uppercase; letter-spacing: .06em; color: rgb(var(--ink2)); flex: 1; }
    ol.threads { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .t {
      display: flex; gap: 8px; align-items: flex-start; padding: 7px 8px 7px 6px; border-radius: 10px; cursor: pointer;
      box-shadow: inset 0 0 0 1px rgb(var(--ring) / .1);
    }
    .t:hover { background: rgb(var(--chip) / var(--chip-a)); }
    .t[aria-selected='true'] { background: rgb(var(--pick) / var(--pick-a)); box-shadow: inset 0 0 0 1.5px rgb(var(--pick) / .7); }
    .t.fresh .line { animation: fresh .6s ease-out; }
    @keyframes fresh { from { background: rgb(var(--pick) / .22); } to { background: transparent; } }
    .t input { margin: 3px 2px 0; accent-color: rgb(var(--pick)); cursor: pointer; flex: none; }
    .t .tx { flex: 1; min-width: 0; }
    .t .line {
      color: rgb(var(--ink)); font-size: 14px; line-height: 1.45; overflow-wrap: anywhere; border-radius: 4px;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 1.45em;
    }
    .t .line.none { color: rgb(var(--ink3)); font-style: italic; font-size: 12.5px; }
    .t .meta { display: flex; gap: 6px; align-items: baseline; margin-top: 2px; font-size: 11px; color: rgb(var(--ink3)); min-width: 0; }
    .t .nm { font-weight: 600; color: rgb(var(--ink2)); white-space: nowrap; }
    .t .cd { font-family: ui-monospace, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .t .ct { white-space: nowrap; }
    .tag { padding: 0 6px; border-radius: 999px; font-size: 10.5px; font-weight: 650; white-space: nowrap; }
    .tag.sug { background: rgb(var(--good) / .14); color: rgb(var(--good)); }
    .tag.got { background: rgb(var(--pick) / .16); color: rgb(var(--pick)); }
    .hint { font-size: 12px; color: rgb(var(--ink3)); margin: 6px 2px; }
    details { margin: 10px 0 0; border-top: 1px solid rgb(var(--ring) / var(--hair-a)); padding-top: 8px; }
    summary { cursor: pointer; font-weight: 600; color: rgb(var(--ink2)); list-style: none; padding: 2px 0; border-radius: 6px; }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: '▸'; display: inline-block; width: 1em; transition: transform .15s; }
    details[open] > summary::before { transform: rotate(90deg); }
    label.opt { display: flex; gap: 8px; align-items: flex-start; margin: 7px 0; cursor: pointer; color: rgb(var(--body)); }
    label.opt input { margin: 2px 0 0; accent-color: rgb(var(--pick)); }
    label.opt small { display: block; color: rgb(var(--ink3)); font-size: 11.5px; }
    .field { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; margin: 7px 0; color: rgb(var(--body)); }
    .field small { display: block; color: rgb(var(--ink3)); font-size: 11.5px; }
    pre.log {
      margin: 6px 0 0; padding: 8px; border-radius: 8px; max-height: 160px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      font: 11px/1.45 ui-monospace, Consolas, monospace; background: rgb(var(--chip) / var(--chip-a)); color: rgb(var(--ink2));
    }
    .err { color: rgb(var(--bad)); font-size: 12px; margin: 6px 0; }
    footer {
      padding: 8px 16px 10px; border-top: 1px solid rgb(var(--ring) / var(--hair-a)); font-size: 12px; color: rgb(var(--ink3));
      display: flex; gap: 6px; min-width: 0;
    }
    footer .txt { color: rgb(var(--ink)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .presets { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
    .field select { max-width: 210px; }
    .field select.wide { max-width: 258px; }
    .read {
      margin: 8px 0 2px; color: rgb(var(--ink)); font-size: 14px; line-height: 1.45; overflow-wrap: anywhere; white-space: pre-line;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
    }
    .read.none { color: rgb(var(--ink3)); font-style: italic; font-size: 12.5px; }
    .note { font-size: 12px; color: rgb(var(--ink3)); margin: -2px 0 8px; }
    .note[data-tone='bad'] { color: rgb(var(--bad)); }
    .card .row { margin: 8px 0 0; }
    .keys { margin: 8px 0 10px; padding: 9px 12px 7px; border-radius: 10px; background: rgb(var(--chip) / var(--chip-a)); }
    .keys .keyshead { font-weight: 650; margin-bottom: 3px; }
    .keys .keyshead small { display: block; font-weight: 400; font-size: 12px; color: rgb(var(--ink3)); }
    .keyrow { display: grid; grid-template-columns: 1fr auto 22px; gap: 6px; align-items: center; padding: 3px 0; }
    .keyrow .key {
      min-width: 132px; padding: 4px 9px; border-radius: 7px; border: 1px solid rgb(var(--ring) / var(--ring-a));
      background: rgb(var(--field)); color: rgb(var(--ink)); font: 600 12.5px/1.35 inherit; cursor: pointer; text-align: center;
    }
    .keyrow .key.none { color: rgb(var(--ink3)); font-weight: 400; }
    .keyrow .key.listening { border-color: rgb(var(--accent)); color: rgb(var(--accent)); font-weight: 600; }
    .keyrow .key:focus-visible { outline: 2px solid rgb(var(--accent)); outline-offset: 1px; }
    .keyrow .x { width: 22px; height: 22px; padding: 0; border: 0; background: none; color: rgb(var(--ink3)); cursor: pointer;
      border-radius: 6px; font-size: 15px; line-height: 22px; }
    .keyrow .x:hover { background: rgb(var(--chip) / var(--chip-hover-a)); color: rgb(var(--ink)); }
    .keys .note { margin: 4px 0 0; }
  `;

  const SUBTITLES = '<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">'
    + '<rect x="1.4" y="4.6" width="13.2" height="8" rx="2.2" stroke-width="1.5"/>'
    + '<path d="M4.2 7.4h4.2M10.2 7.4h1.6M4.2 10h2.2M8.2 10h3.6" stroke-width="1.4"/>'
    + '<path d="M5.6 2.2h4.8" stroke-width="1.4" opacity=".6"/></g></svg>';
  const GAMEPAD = '<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M5.2 4.6h5.6a3.4 3.4 0 0 1 3.3 4.2l-.55 2.3a1.5 1.5 0 0 1-2.6.65L9.8 10.4H6.2l-1.15 1.35a1.5 1.5 0 0 1-2.6-.65L1.9 8.8a3.4 3.4 0 0 1 3.3-4.2z" stroke-width="1.4"/>'
    + '<path d="M4.9 6.8v2.2M3.8 7.9H6" stroke-width="1.3"/></g>'
    + '<circle cx="10.7" cy="7.2" r=".85" fill="currentColor"/><circle cx="12.1" cy="8.7" r=".85" fill="currentColor"/></svg>';
  const CLOSE = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  /** The code pages a game's text that is not Unicode may be in: LunaTranslator's, in its order. */
  const CODEPAGES = [
    [932, 'Japanese (Shift-JIS, 932)'], [65001, 'UTF-8 (65001)'], [936, 'Chinese, simplified (GBK, 936)'],
    [950, 'Chinese, traditional (Big5, 950)'], [949, 'Korean (949)'], [1258, 'Vietnamese (1258)'], [874, 'Thai (874)'],
    [1256, 'Arabic (1256)'], [1255, 'Hebrew (1255)'], [1254, 'Turkish (1254)'], [1253, 'Greek (1253)'], [1257, 'Baltic (1257)'],
    [1250, 'Central European (1250)'], [1251, 'Cyrillic (1251)'], [1252, 'Western (1252)'], [437, 'English (437)'],
    [0, 'As each hook finds it'],
  ];
  const AGAIN = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M11.6 7a4.6 4.6 0 1 1-1.35-3.25M11.6 2.2v2.6H9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  /** The screen's readers (ocrd.py's): what the menu calls each, and "auto"'s order. */
  const READERS = [
    ['auto', 'Auto (the best one here)'], ['builtin', 'Sluka’s own — offline'],
    ['windows', 'Windows’ OCR — offline'], ['lens', 'Google Lens — online'],
  ];
  const READER_NAMES = { builtin: 'Sluka’s own OCR', windows: 'Windows’ OCR', lens: 'Google Lens' };
  /** The Screen tab's keys (hotkeys.py's actions), in the order shown. */
  const KEY_ACTIONS = [['read', 'Read the box now'], ['select', 'Select the text box'], ['once', 'Read a box once'],
    ['toggle', 'Start or stop reading']];
  /** Sluka Vision's readers, Google Lens first (the best at a whole window), and its keys (vision.py's). */
  const VISION_READERS = [
    ['lens', 'Google Lens — online (best)'], ['builtin', 'Sluka’s own — offline'],
    ['windows', 'Windows’ OCR — offline'],
  ];
  const VISION_KEYS = [['read', 'Read the window'], ['auto', 'Read by itself: on or off'], ['clear', 'Put the words away'],
    ['pause', 'Pause the game: on or off'], ['freeze', 'Freeze the picture: on or off']];
  const VISION_STATES = {
    reading: ['Reading the window…', 'live'], waiting: ['Watching the window', 'live'], idle: ['', ''],
    picking: ['Click on the game’s window now…', 'wait'], behind: ['Waiting: another program’s window is in front of the game', 'wait'],
    hidden: ['Waiting: the game’s window is minimized', 'wait'], nopicture: ['No picture of the window could be taken', 'bad'],
    failed: ['Could not be read', 'bad'],
  };
  /** Keys that are only a modifier (or a lock): waited past for the key pressed with them. */
  const MODIFIER_CODES = new Set([16, 17, 18, 20, 91, 92, 93, 144, 229]);
  const AUTO_ORDER = ['builtin', 'windows'];
  /** Said where Google Lens is chosen and has not had its yes yet (lensask.py: asked once, before it first reads). */
  const LENS_ASKS = 'Sluka asks first, before any picture goes to Google; until then an offline reader reads.';

  /* ------------------------------------------------------------------ small helpers */

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value; // only the app's own icons
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat()) if (child !== null && child !== undefined && child !== false) node.append(child);
    return node;
  }

  async function call(name, body = {}) {
    try {
      return await shim.api(name, body);
    } catch (err) {
      return { ok: false, error: String(err?.message || err) };
    }
  }

  function ago(at) {
    if (!at) return '';
    const s = Math.max(0, Math.round(Date.now() / 1000 - at));
    if (s < 5) return 'just now';
    if (s < 60) return `${s} s ago`;
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
  }

  /** Whether the page under the dock is dark: the menu takes Sluka's dark card there, else the light one. */
  function pageIsDark() {
    const seen = (node) => {
      if (!node) return null;
      const color = getComputedStyle(node).backgroundColor || '';
      const m = color.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      if (!(a > 0.5)) return null;
      return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.45;
    };
    const found = seen(document.body) ?? seen(document.documentElement);
    if (found !== null) return found;
    return matchMedia('(prefers-color-scheme: dark)').matches;
  }

  /* ------------------------------------------------------------------ the dock */

  let host = null;
  let root = null;
  let dock = null;
  let subButton = null;
  let gameButton = null;
  let dot = null;
  let barOn = false;
  let barBusy = false;

  const PLACE_KEY = 'sluka-desktop:dock';
  try {
    // 0.6.0 kept its single button's place under another name: the dock starts where it is meant to.
    localStorage.removeItem('sluka-desktop:bar-button');
  } catch {
    /* nothing kept */
  }
  function savedPlace() {
    try {
      const place = JSON.parse(localStorage.getItem(PLACE_KEY) || 'null');
      return place && Number.isFinite(place.x) && Number.isFinite(place.y) ? place : null;
    } catch {
      return null;
    }
  }
  function putAt(x, y) {
    const r = dock.getBoundingClientRect();
    const left = Math.max(4, Math.min(innerWidth - r.width - 4, x));
    const top = Math.max(4, Math.min(innerHeight - r.height - 4, y));
    Object.assign(dock.style, { left: `${Math.round(left)}px`, top: `${Math.round(top)}px`, right: 'auto', bottom: 'auto' });
  }
  function placeAgain() {
    const place = savedPlace();
    if (place && dock) putAt(place.x * innerWidth, place.y * innerHeight);
    if (panelOpen) placePanel();
  }

  function showBar(state) {
    barOn = !!state;
    if (!subButton) return;
    subButton.setAttribute('aria-pressed', String(barOn));
    subButton.title = barOn
      ? 'Floating subtitles are on: click to put them away'
      : 'Floating subtitles: Sluka’s subtitle box over every window, for text from games and other programs';
  }
  async function refreshBar() {
    try {
      const status = await shim.api('bar/status', {});
      showBar(status && status.on);
    } catch {
      /* the app is not answering: left as it is */
    }
  }
  let channel = null;
  try {
    channel = new BroadcastChannel('sluka-desktop-bar');
    channel.onmessage = (e) => {
      if (e.data && typeof e.data.on === 'boolean') showBar(e.data.on);
    };
  } catch {
    /* each window asks for itself */
  }
  async function toggleBar() {
    if (barBusy) return;
    barBusy = true;
    try {
      const answer = await shim.api('bar/toggle', {});
      showBar(answer && answer.on);
      channel?.postMessage({ on: barOn });
    } catch (err) {
      console.error('[sluka-desktop] the floating subtitles could not be turned', barOn ? 'off' : 'on', err);
    } finally {
      barBusy = false;
    }
  }

  /** A press that moves takes the dock elsewhere; one that does not is a click. */
  function draggable(button, onClick) {
    let press = null;
    button.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const r = dock.getBoundingClientRect();
      press = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false };
      try {
        button.setPointerCapture(e.pointerId);
      } catch {
        /* followed while it stays on the button */
      }
    });
    button.addEventListener('pointermove', (e) => {
      if (!press || e.pointerId !== press.id) return;
      if (!press.moved && Math.hypot(e.clientX - press.x, e.clientY - press.y) < 5) return;
      press.moved = true;
      dock.classList.add('moving');
      putAt(e.clientX - press.dx, e.clientY - press.dy);
      if (panelOpen) placePanel();
    });
    const release = (e) => {
      if (!press || e.pointerId !== press.id) return;
      const moved = press.moved;
      press = null;
      dock.classList.remove('moving');
      if (!moved) return;
      const r = dock.getBoundingClientRect();
      try {
        localStorage.setItem(PLACE_KEY, JSON.stringify({ x: r.left / innerWidth, y: r.top / innerHeight }));
      } catch {
        /* kept for this window only */
      }
      button.dataset.moved = String(Date.now());
    };
    button.addEventListener('pointerup', release);
    button.addEventListener('pointercancel', release);
    button.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (Date.now() - Number(button.dataset.moved || 0) < 400) return;
      onClick();
    });
  }

  /* ------------------------------------------------------------------ the menu */

  let panel = null;
  let panelOpen = false;
  let state = null;
  let version = -1;
  let polling = false;
  let processes = null;
  let ui = {};
  const rows = new Map();

  function placePanel() {
    if (!panel || !dock) return;
    const d = dock.getBoundingClientRect();
    const below = d.top + d.height / 2 < innerHeight / 2;
    const onLeft = d.left + d.width / 2 < innerWidth / 2;
    const room = below ? innerHeight - d.bottom - 16 : d.top - 16;
    Object.assign(panel.style, {
      top: below ? `${Math.round(d.bottom + 8)}px` : 'auto',
      bottom: below ? 'auto' : `${Math.round(innerHeight - d.top + 8)}px`,
      left: onLeft ? `${Math.max(8, Math.round(d.left))}px` : 'auto',
      right: onLeft ? 'auto' : `${Math.max(8, Math.round(innerWidth - d.right))}px`,
      maxHeight: `${Math.max(240, Math.min(620, room))}px`,
    });
  }

  function openPanel() {
    if (!panel) buildPanel();
    panel.dataset.theme = pageIsDark() ? 'dark' : 'light';
    panel.hidden = false;
    panelOpen = true;
    gameButton.setAttribute('aria-expanded', 'true');
    dock.classList.add('open');
    placePanel();
    version = -1;
    poll();
    loadProcesses();
    // The engine's files, looked at again where something was wrong with them (put back since, say).
    if (!state || !state.engine || state.engine.error) call('games/rescan', {});
    else if (state.mode === 'screen') call('games/ocr-engines', {});
    setTimeout(() => panel.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true }), 0);
  }
  function closePanel() {
    stopListening(true);
    if (!panel) return;
    panel.hidden = true;
    panelOpen = false;
    gameButton.setAttribute('aria-expanded', 'false');
    dock.classList.remove('open');
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      while (panelOpen) {
        const answer = await call('games/state', { since: version, wait: version >= 0 });
        if (!panelOpen) break;
        if (answer && typeof answer.version === 'number') {
          version = answer.version;
          state = answer;
          render();
          showDot(answer);
        } else {
          await new Promise((done) => setTimeout(done, 1500));
        }
      }
    } finally {
      polling = false;
    }
  }

  /** While the menu is closed, the game button's dot says now and then how the game text is doing. */
  async function glance() {
    if (panelOpen || document.visibilityState !== 'visible') return;
    const brief = await call('games/state', { brief: true });
    if (brief && brief.mode) showDot(brief);
  }

  function tone(s) {
    if (!s || s.mode === 'off') return '';
    if (s.mode === 'game') {
      const game = s.game;
      if (!game) return '';
      if (game.state === 'failed') return 'bad';
      if (game.state === 'attached' && (Array.isArray(s.selected) ? s.selected.length : s.selected)) return 'live';
      if (game.state === 'attaching' || game.state === 'attached') return 'wait';
      return '';
    }
    if (s.mode === 'screen') {
      const sc = s.screen || {};
      const what = sc.target ? sc.target.state : sc.state;
      const status = sc.target ? sc.target.status : sc.status;
      if (what === 'failed') return 'bad';
      if (what === 'watching') return ['behind', 'hidden', 'nopicture', 'loading'].includes(status) ? 'wait' : 'live';
      return what === 'starting' ? 'wait' : '';
    }
    if (s.mode === 'vision') {
      const v = s.vision || {};
      const status = typeof v.status === 'string' ? v.status : v.status?.state;
      if (v.error || status === 'failed' || status === 'nopicture') return 'bad';
      if (!(v.window || v.target)) return '';
      return ['behind', 'hidden', 'picking'].includes(status) ? 'wait' : 'live';
    }
    return 'other';
  }
  function showDot(s) {
    if (!dot) return;
    const t = tone(s);
    if (t) dot.dataset.tone = t;
    else delete dot.dataset.tone;
    const label = { live: { screen: 'reading the screen', vision: 'Sluka Vision' }[s.mode] || 'reading a game', wait: 'waiting',
      bad: 'needs a look', other: 'from the clipboard' }[t];
    gameButton.title = `Game text${label ? `: ${label}` : ''}`;
  }

  async function loadProcesses() {
    if (!ui.procs) return;
    ui.procs.disabled = true;
    const answer = await call('games/processes', {});
    processes = answer && answer.processes ? answer.processes : [];
    const keep = ui.procs.value;
    ui.procs.replaceChildren(el('option', { value: '', text: processes.length ? 'Choose the game…' : 'No program with a window found' }));
    for (const p of processes) {
      const kind = p.bits ? ` · ${p.bits}-bit` : '';
      const mark = p.current ? '● ' : p.known ? '★ ' : '';
      const title = p.title && p.title !== p.exe ? `${p.title} — ${p.exe}` : p.exe;
      ui.procs.append(el('option', { value: String(p.pid), text: `${mark}${title}${kind}` }));
    }
    if (keep && processes.some((p) => String(p.pid) === keep)) ui.procs.value = keep;
    else {
      const first = processes.find((p) => p.current) || processes.find((p) => p.known);
      if (first) ui.procs.value = String(first.pid);
    }
    ui.procs.disabled = false;
    ui.hook.disabled = !ui.procs.value;
  }

  function option(label, note, key) {
    const box = el('input', { type: 'checkbox' });
    box.addEventListener('change', () => call('games/settings', { settings: { [key]: box.checked } }));
    (ui.opts[key] ||= []).push(box);
    return el('label', { class: 'opt' }, box, el('span', {}, label, note ? el('small', { text: note }) : null));
  }
  const NUMBERS = new Set(['flush_ms', 'codepage', 'clip_most', 'ocr_interval_ms']);
  function chooser(label, note, key, choices, select = el('select', {})) {
    for (const [value, text] of choices) select.append(el('option', { value: String(value), text }));
    select.addEventListener('change', () => {
      const value = NUMBERS.has(key) ? Number(select.value) : select.value;
      call('games/settings', { settings: { [key]: value } });
    });
    (ui.opts[key] ||= []).push(select);
    return el('div', { class: 'field' }, el('span', {}, label, note ? el('small', { text: note }) : null), select);
  }

  function buildPanel() {
    ui = { opts: {} };
    const tabs = el('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Where the lines come from' });
    ui.tabs = {};
    for (const [mode, label] of [['game', 'Game'], ['screen', 'Screen'], ['clipboard', 'Clipboard'], ['vision', 'Sluka Vision'], ['off', 'Off']]) {
      const tab = el('button', { type: 'button', role: 'tab', 'aria-selected': 'false', text: label, dataset: { mode } });
      tab.addEventListener('click', async () => {
        if (state) {
          state.mode = mode;
          render();
        }
        await call('games/mode', { mode });
        if (mode === 'screen') call('games/ocr-engines', {});
        if (mode === 'vision') call('games/vision-engines', {});
      });
      ui.tabs[mode] = tab;
      tabs.append(tab);
    }

    // ---- a game
    ui.engineError = el('div', { class: 'err' });
    ui.noEngine = el('div', {},
      el('p', {}, 'Sluka reads a game’s text with its own engine: ', el('b', { text: 'LunaHook' }),
        ', the open-source text hooker inside LunaTranslator (GPL-3.0, by HIllya51), which comes in Sluka Desktop’s engine folder.'),
      ui.engineError,
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'btn', text: 'Look again', onclick: () => call('games/rescan', {}) })),
      el('p', { class: 'small', text: 'A text hooker reaches into games, so antivirus programs sometimes take it for a threat. If Windows '
        + 'Security removed or blocked one of the engine’s files, allow it in its Protection history (or add the engine folder to its '
        + 'exclusions) and unpack Sluka Desktop’s zip again. Meanwhile, the Clipboard tab takes the lines LunaTranslator or '
        + 'Textractor read (set them to copy each line).' }));

    ui.procs = el('select', { class: 'grow', 'aria-label': 'The game' });
    ui.procs.addEventListener('change', () => { ui.hook.disabled = !ui.procs.value; });
    const hook = async (pid, elevate = false) => {
      if (!pid) return;
      const answer = await call('games/attach', elevate ? { pid, elevate: true } : { pid });
      ui.attachError.hidden = !!answer.ok;
      ui.attachError.textContent = answer.ok ? '' : answer.error || 'The game could not be hooked.';
      ui.adminPid = !answer.ok && answer.admin ? pid : 0;
      ui.adminRow.hidden = !ui.adminPid;
    };
    ui.hook = el('button', { type: 'button', class: 'btn primary', text: 'Hook', disabled: true,
      onclick: () => hook(Number(ui.procs.value)) });
    ui.attachError = el('div', { class: 'err', hidden: true });
    ui.adminPid = 0;
    ui.adminRow = el('div', { class: 'row', hidden: true },
      el('button', { type: 'button', class: 'btn primary', text: 'Hook as administrator', title: 'Windows asks you first',
        onclick: () => hook(ui.adminPid || state?.game?.pid || 0, true) }));
    ui.pick = el('button', { type: 'button', class: 'btn quiet', text: 'Or click on the game’s window',
      onclick: () => (state?.picking ? call('games/cancel-pick', {}) : call('games/pick', { seconds: 10 })) });
    ui.chooser = el('div', {},
      el('div', { class: 'row' }, ui.procs,
        el('button', { type: 'button', class: 'icon', title: 'Look for programs again', 'aria-label': 'Look for programs again',
          html: AGAIN, onclick: loadProcesses }),
        ui.hook),
      el('div', { class: 'row' }, ui.pick),
      ui.attachError, ui.adminRow);

    ui.gameName = el('div', { class: 'name' });
    ui.gameHow = el('div', { class: 'how' });
    ui.autoBox = el('input', { type: 'checkbox' });
    ui.autoBox.addEventListener('change', () => call('games/auto', { on: ui.autoBox.checked }));
    ui.pcBox = el('input', { type: 'checkbox' });
    ui.pcBox.addEventListener('change', () => call('games/pchooks', { on: ui.pcBox.checked }));
    ui.gameCard = el('div', { class: 'card' },
      el('div', { class: 'state' },
        el('div', { class: 'what' }, ui.gameName, ui.gameHow),
        el('button', { type: 'button', class: 'btn', text: 'Let go', onclick: () => call('games/detach', {}) })),
      el('label', { class: 'opt' }, ui.autoBox, el('span', { text: 'Hook this game by itself when it starts' })),
      el('label', { class: 'opt' }, ui.pcBox, el('span', {}, 'Read Windows’ text functions too',
        el('small', { text: 'For a game whose engine is not found: more threads to choose from' }))));

    ui.threads = el('ol', { class: 'threads', role: 'listbox', 'aria-label': 'Text threads', 'aria-multiselectable': 'true' });
    ui.threadsHint = el('div', { class: 'hint' });
    ui.code = el('input', { type: 'text', class: 'grow code', placeholder: 'Hook code, e.g. HS-4@1234:game.exe', 'aria-label': 'Hook code',
      spellcheck: 'false', autocomplete: 'off' });
    ui.codeError = el('div', { class: 'err', hidden: true });
    const addCode = async () => {
      const answer = await call('games/hookcode', { code: ui.code.value });
      ui.codeError.hidden = !!answer.ok;
      ui.codeError.textContent = answer.ok ? '' : answer.error || 'The hook code was not taken.';
      if (answer.ok) ui.code.value = '';
    };
    ui.code.addEventListener('keydown', (e) => { if (e.key === 'Enter') addCode(); });
    ui.threadsBlock = el('div', {},
      el('div', { class: 'head' }, el('h3', { text: 'Text threads' }),
        ui.forget = el('button', { type: 'button', class: 'btn quiet', text: 'Forget this game', onclick: () => call('games/forget', {}) })),
      el('p', { class: 'small', text: 'Click the thread that shows the game’s lines: they go to the floating subtitles. Tick more than '
        + 'one to have them together (a name and its line).' }),
      ui.threads, ui.threadsHint,
      el('div', { class: 'row' }, ui.code, el('button', { type: 'button', class: 'btn', text: 'Add', onclick: addCode })),
      ui.codeError);
    // Where it can be seen: the lines read from the game, on the clipboard too, for any other program that reads it.
    ui.copyRow = option('Copy each line to the clipboard too', 'For other programs that read it (a dictionary, Anki…)', 'copy');

    ui.engineInfo = el('div', { class: 'small' });
    const settings = el('details', { class: 'more' }, el('summary', { text: 'Text settings' }),
      chooser('Wait for the rest of a line', 'A line is sent once the game is quiet this long', 'flush_ms',
        [[50, '0.05 s'], [100, '0.1 s'], [200, '0.2 s'], [300, '0.3 s'], [500, '0.5 s'], [800, '0.8 s'], [1200, '1.2 s'], [2000, '2 s']]),
      chooser('The game’s text is in', 'For a game whose text is not Unicode', 'codepage', CODEPAGES),
      chooser('Letters sent more than once', 'Some engines draw each letter 2–4 times', 'repeats',
        [['auto', 'Undo by itself'], ['off', 'Leave them'], ['2', 'Each sent twice'], ['3', 'Each sent 3 times'], ['4', 'Each sent 4 times']]),
      option('Join the lines the game breaks', 'Where the text box ends, as in SiglusEngine', 'join'),
      option('Take out the game’s layout codes', '[r], {w}, <color>, \\C[2] …', 'codes'),
      option('Pick the dialogue by itself', 'Where no thread is picked yet; a click changes it', 'auto_pick'),
      option('Hook games used before when they start', 'The games marked ★ in the list', 'auto_hook'),
      el('div', { class: 'head' }, el('h3', { text: 'Engine' })),
      ui.engineInfo);
    ui.logs = [el('pre', { class: 'log' }), el('pre', { class: 'log' })];
    const logBlock = el('details', { class: 'more' }, el('summary', { text: 'What the engine says' }), ui.logs[0]);

    ui.engineOk = el('div', {}, ui.chooser, ui.gameCard, ui.threadsBlock, ui.copyRow);
    const gamePane = el('div', { dataset: { pane: 'game' } }, ui.noEngine, ui.engineOk, settings, logBlock);

    // ---- the screen: a box of a game's window, read off the screen (OCR)
    ui.readers = el('select', { class: 'wide', 'aria-label': 'Read with' });
    const readerField = chooser('Read with', '', 'ocr_engine', READERS, ui.readers);
    ui.readerNote = el('div', { class: 'note' });
    ui.screenError = el('div', { class: 'err', hidden: true });
    ui.selectBox = el('button', { type: 'button', class: 'btn primary', text: 'Select the text box',
      onclick: async () => {
        if (state?.screen?.selecting) {
          call('games/ocr-cancel', {});
          return;
        }
        const answer = await call('games/ocr-select', {});
        ui.selectError = answer.ok ? '' : answer.error || 'The box could not be dragged.';
        render();
      } });
    ui.selectError = '';
    ui.boxName = el('div', { class: 'name' });
    ui.boxHow = el('div', { class: 'how' });
    ui.boxText = el('div', { class: 'read' });
    ui.boxWhen = el('div', { class: 'small' });
    ui.readNow = el('button', { type: 'button', class: 'btn', text: 'Read now', onclick: () => call('games/ocr-once', {}) });
    ui.stopStart = el('button', { type: 'button', class: 'btn', text: 'Stop',
      onclick: () => call(['starting', 'watching'].includes(state?.screen?.target?.state) ? 'games/ocr-stop' : 'games/ocr-start', {}) });
    ui.forgetBox = el('button', { type: 'button', class: 'btn quiet', text: 'Forget this box', onclick: () => call('games/ocr-forget', {}) });
    ui.boxCard = el('div', { class: 'card' },
      el('div', { class: 'boxstate' }, el('div', { class: 'what' }, ui.boxName, ui.boxHow)),
      ui.boxText, ui.boxWhen,
      el('div', { class: 'row' }, ui.readNow, ui.stopStart, el('span', { class: 'grow' }), ui.forgetBox));
    ui.screenHint = el('p', { class: 'small' });
    ui.intervalField = chooser('How often', 'Read where the text has changed', 'ocr_interval_ms',
      [[500, '0.5 s'], [1000, '1 s'], [1500, '1.5 s'], [2000, '2 s'], [3000, '3 s'], [5000, '5 s']]);
    ui.langs = el('select', {});
    ui.langField = chooser('Windows’ OCR reads', 'A language Windows has the OCR of', 'ocr_lang', [], ui.langs);
    const screenSettings = el('details', { class: 'more' }, el('summary', { text: 'Reading settings' }),
      chooser('When to read', '', 'ocr_mode',
        [['auto', 'As the text changes'], ['interval', 'Every few seconds'], ['trigger', 'After a click or a key']]),
      ui.intervalField,
      chooser('The text is written', 'Vertical text is read in columns, right to left', 'ocr_vertical',
        [['auto', 'Either way'], ['h', 'Across'], ['v', 'Down (vertical)']]),
      option('Leave out furigana', 'The small kana over a word that tell how it is read', 'ocr_furigana'),
      option('Read only while the game is in front', 'Not what another program shows over it', 'ocr_front'),
      chooser('What is read', 'The game’s own window: Sluka’s windows show in screenshots and recordings (not every game gives a '
        + 'picture of its own window)', 'ocr_capture',
        [['screen', 'What the screen shows'], ['window', 'The game’s own window']]),
      ui.langField);
    const screenLog = el('details', { class: 'more' }, el('summary', { text: 'What the screen reader says' }), ui.logs[1]);
    // The keys: pressed in the game, they do what the buttons here do.
    ui.keyButtons = {};
    ui.keyClears = {};
    ui.keysNote = el('div', { class: 'note' });
    ui.keysError = '';
    ui.listeningFor = '';
    const keyRows = KEY_ACTIONS.map(([action, label]) => {
      const button = el('button', { type: 'button', class: 'key none', text: 'Set a key', 'aria-label': `Key: ${label}`,
        onclick: () => (ui.listeningFor === action ? stopListening(true) : startListening(action)) });
      const clear = el('button', { type: 'button', class: 'x', text: '×', title: 'No key', 'aria-label': `No key for ${label}`,
        onclick: async () => {
          stopListening(false);
          const answer = await call('games/ocr-key', { action, clear: true });
          ui.keysError = answer.ok ? '' : answer.error || '';
          render();
          button.focus();  // (this button is hidden now: the keyboard stays in the menu)
        } });
      ui.keyButtons[action] = button;
      ui.keyClears[action] = clear;
      return el('div', { class: 'keyrow' }, el('span', { text: label }), button, clear);
    });
    const keysBlock = el('div', { class: 'keys' },
      el('div', { class: 'keyshead', text: 'Keys' },
        el('small', { text: 'In any program — the game too — while this tab is chosen. Click a key’s box, then press the keys.' })),
      ...keyRows, ui.keysNote);
    const screenPane = el('div', { dataset: { pane: 'screen' } },
      el('p', { text: 'Sluka reads the text in a box of the game’s window off the screen (OCR): for a game whose text no hook '
        + 'reads — an emulator’s, a browser’s, a film’s subtitles.' }),
      readerField, ui.readerNote,
      el('div', { class: 'row' }, ui.selectBox),
      el('p', { class: 'small', text: 'Drag a box over where the game writes its text: the window under it is read, and the box is '
        + 'kept for that game. Right-click, or click without dragging, to stop.' }),
      ui.screenError, ui.boxCard, keysBlock,
      option('Copy each text read to the clipboard too', 'For other programs that read it', 'copy'),
      option('Join the box’s lines into one', '', 'join'),
      screenSettings, ui.screenHint, screenLog);

    // ---- the clipboard
    ui.clipState = el('div', { class: 'how' });
    const clipPane = el('div', { dataset: { pane: 'clipboard' } },
      el('p', { text: 'Every text copied in another program goes to the floating subtitles: set LunaTranslator or Textractor to copy '
        + 'what it reads (or copy a line yourself).' }),
      el('div', { class: 'card' }, ui.clipState),
      option('Not what is copied in Sluka’s own windows', '', 'skip_own'),
      chooser('Longest text taken', 'Longer is a page, not a line', 'clip_most',
        [[300, '300 letters'], [1000, '1000 letters'], [4000, '4000 letters']]));

    // ---- Sluka Vision: the game's whole window read, its words laid over it where they sit (as YomiNinja does)
    ui.visionReaders = el('select', { class: 'wide', 'aria-label': 'Sluka Vision reads with' });
    const visionReaderField = chooser('Read with', '', 'vision_engine', VISION_READERS, ui.visionReaders);
    ui.visionReaderNote = el('div', { class: 'note' });
    ui.visionError = el('div', { class: 'err', hidden: true });
    ui.visionStart = el('p', { class: 'start' });
    ui.visionPick = el('button', { type: 'button', class: 'btn',
      onclick: async () => {
        const answer = await call('games/vision-pick', {});
        ui.visionPickError = answer.ok ? '' : answer.error || 'The window could not be chosen.';
        render();
      } });
    ui.visionPickError = '';
    ui.visionName = el('div', { class: 'name' });
    ui.visionHow = el('div', { class: 'how' });
    ui.visionText = el('div', { class: 'read' });
    ui.visionWhen = el('div', { class: 'small' });
    ui.visionRead = el('button', { type: 'button', class: 'btn primary', text: 'Read again', onclick: () => call('games/vision-read', {}) });
    ui.visionClear = el('button', { type: 'button', class: 'btn', text: 'Put away', title: 'Put the words away (they come back at the next read)',
      onclick: () => call('games/vision-clear', {}) });
    ui.visionForget = el('button', { type: 'button', class: 'btn quiet', text: 'Forget this window', onclick: () => call('games/vision-forget', {}) });
    // The game stopped where it is, to read it at leisure (as its keys do): paused, or only its picture kept.
    ui.visionPause = el('button', { type: 'button', class: 'btn', text: 'Pause the game',
      title: 'The game paused where it is, its picture kept over it; again: it goes on',
      onclick: async () => {
        const answer = await call('games/vision-freeze', { mode: 'pause' });
        if (answer && answer.ok === false) ui.visionPickError = answer.error || '';
        render();
      } });
    ui.visionFreeze = el('button', { type: 'button', class: 'btn', text: 'Freeze the picture',
      title: 'Only the game’s picture kept over it, the game going on behind it; again: let go',
      onclick: async () => {
        const answer = await call('games/vision-freeze', { mode: 'picture' });
        if (answer && answer.ok === false) ui.visionPickError = answer.error || '';
        render();
      } });
    ui.visionCard = el('div', { class: 'card' },
      el('div', { class: 'boxstate' }, el('div', { class: 'what' }, ui.visionName, ui.visionHow)),
      ui.visionText, ui.visionWhen,
      el('div', { class: 'row' }, ui.visionRead, ui.visionClear, el('span', { class: 'grow' }), ui.visionForget),
      el('div', { class: 'row' }, ui.visionPause, ui.visionFreeze));
    const visionKeyRows = VISION_KEYS.map(([action, label]) => {
      const id = `vision:${action}`;
      const button = el('button', { type: 'button', class: 'key none', text: 'Set a key', 'aria-label': `Key: ${label}`,
        onclick: () => (ui.listeningFor === id ? stopListening(true) : startListening(id)) });
      const clear = el('button', { type: 'button', class: 'x', text: '×', title: 'No key', 'aria-label': `No key for ${label}`,
        onclick: async () => {
          stopListening(false);
          const answer = await call('games/vision-key', { action, clear: true });
          ui.visionKeysError = answer.ok ? '' : answer.error || '';
          render();
          button.focus();
        } });
      ui.keyButtons[id] = button;
      ui.keyClears[id] = clear;
      return el('div', { class: 'keyrow' }, el('span', { text: label }), button, clear);
    });
    ui.visionKeysNote = el('div', { class: 'note' });
    ui.visionKeysError = '';
    const visionKeys = el('div', { class: 'keys' },
      el('div', { class: 'keyshead', text: 'Keys' },
        el('small', { text: 'In any program — the game too — while this tab is chosen. Click a key’s box, then press the keys.' })),
      ...visionKeyRows, ui.visionKeysNote);
    const visionSettings = el('details', { class: 'more' }, el('summary', { text: 'Sluka Vision settings' }),
      option('Leave the furigana out', 'The small kana over a word that tell how it is read', 'vision_furigana'),
      chooser('What Sluka Vision reads', 'The game’s own window: its words show in screenshots and recordings (not every game '
        + 'gives a picture of its own window)', 'vision_capture',
        [['screen', 'What the screen shows'], ['window', 'The game’s own window']]));
    ui.visionHint = el('p', { class: 'small' });
    const visionLog = el('details', { class: 'more' }, el('summary', { text: 'What the screen reader says' }), ui.logs[2] = el('pre', { class: 'log' }));
    const visionPane = el('div', { dataset: { pane: 'vision' } },
      el('p', { text: 'Sluka reads the game’s whole window and lays its words over the game where they sit, as YomiNinja does: each '
        + 'word you are learning is underlined in its level’s colour — point at one for its card, click it for its panel. The '
        + 'floating subtitles rest meanwhile.' }),
      visionReaderField, ui.visionReaderNote,
      ui.visionStart,
      el('div', { class: 'row' }, ui.visionPick),
      ui.visionError, ui.visionCard,
      option('Read again by itself as the window changes', 'Once what it shows has changed and settled; its key reads at once too', 'vision_auto'),
      visionKeys, visionSettings, ui.visionHint, visionLog);

    const offPane = el('div', { dataset: { pane: 'off' } },
      el('p', { text: 'Sluka takes no text from games or other programs. The floating subtitles still show what is sent to their '
        + 'address (see the README).' }));

    ui.panes = { game: gamePane, screen: screenPane, clipboard: clipPane, vision: visionPane, off: offPane };
    ui.pill = el('span', { class: 'pill' });
    ui.lastText = el('span', { class: 'txt' });
    ui.lastWhen = el('span', {});
    ui.footer = el('footer', {}, ui.lastWhen, ui.lastText);
    panel = el('section', { class: 'panel theme', role: 'dialog', 'aria-label': 'Game text', hidden: true },
      el('header', {}, el('h2', {}, 'Game text', ui.pill),
        el('button', { type: 'button', class: 'icon', title: 'Close', 'aria-label': 'Close', html: CLOSE, onclick: closePanel })),
      tabs,
      el('div', { class: 'body' }, gamePane, screenPane, clipPane, visionPane, offPane),
      ui.footer);
    panel.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closePanel();
        gameButton.focus();
      }
    });
    // A key for an action: the next keys pressed (before the menu's own Escape).
    window.addEventListener('keydown', (e) => {
      if (!ui.listeningFor) return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (MODIFIER_CODES.has(e.keyCode)) return;
      if (e.keyCode === 27 && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) {
        stopListening(true);
        return;
      }
      const id = ui.listeningFor;
      ui.listeningFor = '';
      const vision = id.startsWith('vision:');
      const action = vision ? id.slice('vision:'.length) : id;
      call(vision ? 'games/vision-key' : 'games/ocr-key', { action, vk: e.keyCode, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, win: e.metaKey })
        .then((answer) => {
          const error = answer.ok ? '' : answer.error || 'That key cannot be one.';
          if (vision) ui.visionKeysError = error;
          else ui.keysError = error;
          render();
        });
      render();
    }, true);
    root.append(panel);
  }

  /** The keys the page waits for: the Screen tab's (an action) or Sluka Vision's ("vision:" and an action). */
  const listenCall = (id) => (String(id).startsWith('vision:') ? 'games/vision-keys-listen' : 'games/ocr-keys-listen');

  function startListening(action) {
    if (ui.listeningFor && listenCall(ui.listeningFor) !== listenCall(action)) call(listenCall(ui.listeningFor), { on: false });
    ui.listeningFor = action;
    ui.keysError = '';
    ui.visionKeysError = '';
    call(listenCall(action), { on: true });  // (the keys held let go of: one of them reaches this page)
    render();
    ui.keyButtons[action].focus();
  }

  function stopListening(tell) {
    if (!ui.listeningFor) return;
    const was = ui.listeningFor;
    ui.listeningFor = '';
    if (tell) call(listenCall(was), { on: false });
    render();
  }

  /* ------------------------------------------------------------------ drawing what the app says */

  const STATES = {
    attaching: ['Hooking…', ''],
    attached: ['Hooked', 'live'],
    ended: ['The game has closed', ''],
    failed: ['Could not be hooked', 'bad'],
  };

  function render() {
    if (!panel || !state) return;
    const s = state;
    for (const [mode, tab] of Object.entries(ui.tabs)) tab.setAttribute('aria-selected', String(s.mode === mode));
    for (const [mode, pane] of Object.entries(ui.panes)) pane.hidden = s.mode !== mode;

    const t = tone(s);
    const box = s.screen?.target;
    const pillText = {
      off: 'off', clipboard: 'clipboard', socket: s.socket?.state === 'connected' ? 'connected' : 'waiting',
      game: s.game ? (STATES[s.game.state]?.[0] || '').toLowerCase() : 'no game',
      screen: s.screen?.selecting ? 'dragging' : box ? (SCREEN_STATES[box.state]?.[0] || '').replace(/…$/, '').toLowerCase() : 'no box',
      vision: s.vision?.picking ? 'choosing' : s.vision?.target ? (s.vision.status?.state === 'reading' ? 'reading' : 'watching') : 'no window',
    }[s.mode];
    ui.pill.textContent = pillText || '';
    if (t) ui.pill.dataset.tone = t;
    else delete ui.pill.dataset.tone;

    // settings
    const set = s.settings || {};
    renderLanguages(s);
    for (const [key, inputs] of Object.entries(ui.opts)) {
      for (const input of inputs) {
        if (document.activeElement === host && root.activeElement === input) continue;
        if (input.type === 'checkbox') input.checked = !!set[key];
        else if (set[key] !== undefined) input.value = String(set[key]);
      }
    }

    // Sluka's engine
    const engine = s.engine;
    const broken = !engine || !!engine.error;
    ui.noEngine.hidden = !broken;
    ui.engineOk.hidden = broken;
    ui.engineError.textContent = engine?.error || 'Sluka’s engine was not found.';
    ui.engineInfo.textContent = engine
      ? `${engine.name}, from ${engine.version}, in ${engine.folder} — for ${engine.kinds.map((k) => `${k}-bit`).join(' and ')} games`
        + `${engine.running ? '; running' : ''}.`
      : '';

    // the game
    const game = s.game;
    ui.gameCard.hidden = !game;
    ui.threadsBlock.hidden = !game || game.state === 'ended' || game.state === 'failed';
    ui.pick.textContent = s.picking ? `Click on the game’s window now… (${Math.ceil(s.picking)} s, click here to stop)` : 'Or click on the game’s window';
    if (game) {
      ui.gameName.textContent = game.title && game.title !== game.exe ? `${game.title} — ${game.exe}` : game.exe || `program ${game.pid}`;
      const [label, gameTone] = STATES[game.state] || [game.state, ''];
      let how = `${label} · ${game.bits}-bit`;
      if (game.engine) how += ` · ${game.engine}`;
      if (game.elevated) how += ' · as administrator';
      if (game.state === 'attached' && !s.threads.length) how += ' · advance the game’s text once';
      if (game.error) how += ` · ${game.error}`;
      ui.gameHow.textContent = how;
      if (gameTone) ui.gameHow.dataset.tone = gameTone;
      else delete ui.gameHow.dataset.tone;
      if (root.activeElement !== ui.autoBox) ui.autoBox.checked = !!game.auto;
      if (root.activeElement !== ui.pcBox) ui.pcBox.checked = !!game.pchooks;
      ui.pcBox.disabled = game.state !== 'attached';
      ui.forget.hidden = !game.remembered && !(game.codes || []).length && !game.pchooks;
    }
    // Why the game could not be hooked; where it runs as administrator, the hook goes in as administrator
    // (Windows asks first).
    const failed = s.attach && !s.attach.ok ? s.attach : null;
    ui.attachError.hidden = !failed;
    ui.attachError.textContent = failed ? failed.error || 'The game could not be hooked.' : '';
    let adminPid = failed && failed.admin ? failed.pid : 0;
    if (game && game.state === 'failed' && game.admin && !game.elevated) adminPid = game.pid;
    ui.adminPid = adminPid;
    ui.adminRow.hidden = !adminPid;
    renderThreads(s);
    renderScreen(s);
    renderVision(s);

    // the clipboard
    const clip = s.clipboard || {};
    ui.clipState.textContent = clip.error ? `The clipboard cannot be watched: ${clip.error}` : clip.watching ? 'Watching the clipboard.' : 'Starting…';

    // what was said
    const lines = (s.log || []).map(([at, level, text]) => `${new Date(at * 1000).toLocaleTimeString()}  ${level === 'info' || level === 'engine' ? '' : `${level}: `}${text}`);
    for (const log of ui.logs) {
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
      log.textContent = lines.join('\n') || 'Nothing yet.';
      if (atEnd) log.scrollTop = log.scrollHeight;
    }
    const last = s.last || {};
    ui.footer.hidden = !last.text;
    ui.lastWhen.textContent = last.at ? `Last line, ${ago(last.at)}:` : '';
    ui.lastText.textContent = last.text || '';
    ui.lastText.title = last.text || '';
  }

  const SCREEN_STATES = {
    starting: ['Starting…', 'wait'], watching: ['Reading', 'live'], stopped: ['Stopped', ''],
    ended: ['The window has closed', ''], failed: ['Could not be read', 'bad'],
  };
  const WAITING = {
    loading: 'Loading the reader…', behind: 'Waiting: another program’s window is in front of the game',
    hidden: 'Waiting: the game’s window is minimized', nopicture: 'No picture of the box could be taken',
  };

  /** The languages Windows' OCR has here, for its chooser (the one chosen kept among them). */
  function renderLanguages(s) {
    const found = s.screen?.engines?.windows?.languages || [];
    const chosen = s.settings?.ocr_lang || 'ja';
    const choices = found.map(([tag, name]) => [tag, name ? `${name} (${tag})` : tag]);
    if (!choices.some(([tag]) => tag === chosen)) choices.unshift([chosen, chosen]);
    const key = JSON.stringify(choices);
    if (ui.langs.dataset.key === key) return;
    ui.langs.dataset.key = key;
    ui.langs.replaceChildren(...choices.map(([value, text]) => el('option', { value, text })));
  }

  function renderScreen(s) {
    const sc = s.screen || {};
    const engines = sc.engines || {};
    const set = s.settings || {};
    const looked = Object.keys(engines).length > 0;
    for (const item of ui.readers.options) {
      const base = (READERS.find(([value]) => value === item.value) || [])[1] || item.value;
      const info = engines[item.value];
      item.textContent = item.value !== 'auto' && info && !info.ok ? `${base} (not here)` : base;
    }
    const chosen = set.ocr_engine || 'auto';
    let note = '';
    let bad = false;
    if (!looked) note = sc.error || 'Looking at what can read the screen here…';
    else if (chosen === 'auto') {
      if (sc.auto) note = `Here: ${READER_NAMES[sc.auto]}, ${engines[sc.auto]?.why || ''}.`;
      else {
        note = `None of the offline readers works here — ${AUTO_ORDER.map((name) => `${READER_NAMES[name]}: ${engines[name]?.why || '?'}`).join('; ')}.`;
        bad = true;
      }
    } else {
      const info = engines[chosen] || {};
      note = info.why ? `${info.why.charAt(0).toUpperCase()}${info.why.slice(1)}.` : '';
      bad = !info.ok;
      if (chosen === 'lens' && info.ok && !set.lens_ok) note = `${note} ${LENS_ASKS}`.trim();
    }
    ui.readerNote.textContent = note;
    if (bad || (sc.error && !looked)) ui.readerNote.dataset.tone = 'bad';
    else delete ui.readerNote.dataset.tone;
    const reader = chosen === 'auto' ? sc.auto : chosen;
    ui.langField.hidden = reader !== 'windows';
    ui.intervalField.hidden = set.ocr_mode !== 'interval';

    const box = sc.target;
    ui.selectBox.textContent = sc.selecting ? 'Dragging the box… (click here to stop)' : box ? 'Select another box' : 'Select the text box';
    if (box || sc.selecting) ui.selectError = '';
    const error = ui.selectError || (!box && sc.error) || '';
    ui.screenError.hidden = !error;
    ui.screenError.textContent = error;
    ui.boxCard.hidden = !box;
    if (box) {
      ui.boxName.textContent = !box.hwnd ? 'A box on the screen'
        : box.exe && box.title && box.title !== box.exe ? `${box.title} — ${box.exe}` : box.title || box.exe || 'the game';
      let [label, boxTone] = SCREEN_STATES[box.state] || [box.state, ''];
      if (box.state === 'watching' && WAITING[box.status]) {
        label = WAITING[box.status];
        boxTone = 'wait';
      }
      const parts = [label];
      if (box.engine) parts.push(READER_NAMES[box.engine] || box.engine);
      if (box.box) parts.push(`${box.box[2]}×${box.box[3]} px`);
      if (box.how === 'window') parts.push('the game’s own window');
      if (box.error) {
        parts.push(box.error);
        boxTone = 'bad';
      }
      ui.boxHow.textContent = parts.join(' · ');
      if (boxTone === 'live' || boxTone === 'bad') ui.boxHow.dataset.tone = boxTone;
      else delete ui.boxHow.dataset.tone;
      const last = sc.last || {};
      const reading = box.state === 'watching' || box.state === 'starting';
      ui.boxText.textContent = last.text || (reading ? 'Nothing read yet: advance the game’s text.' : '');
      ui.boxText.classList.toggle('none', !last.text);
      ui.boxText.hidden = !ui.boxText.textContent;
      ui.boxWhen.textContent = last.text && last.at
        ? `Read ${ago(last.at)}${last.ms ? ` in ${(last.ms / 1000).toFixed(1)} s` : ''}${last.engine ? ` by ${READER_NAMES[last.engine] || last.engine}` : ''}.`
        : '';
      ui.boxWhen.hidden = !ui.boxWhen.textContent;
      ui.readNow.disabled = !reading;
      ui.stopStart.textContent = reading ? 'Stop' : 'Read';
      ui.forgetBox.hidden = !box.kept;
    }
    const keys = sc.keys || {};
    const notes = [];
    for (const [action, label] of KEY_ACTIONS) {
      const found = keys[action] || {};
      const button = ui.keyButtons[action];
      const listening = ui.listeningFor === action;
      button.textContent = listening ? 'Press the keys… (Esc: none)' : found.key || 'Set a key';
      button.classList.toggle('none', !listening && !found.key);
      button.classList.toggle('listening', listening);
      ui.keyClears[action].hidden = !found.key || listening;
      if (found.error && found.key) notes.push([`${found.key} (${label}): ${found.error}.`, 'bad']);
      else if (found.note) notes.push([`${found.note}.`, '']);
    }
    if (ui.keysError) notes.unshift([ui.keysError.charAt(0).toUpperCase() + ui.keysError.slice(1) + (/[.!]$/.test(ui.keysError) ? '' : '.'), 'bad']);
    ui.keysNote.textContent = notes.map(([text]) => text).join(' ');
    ui.keysNote.hidden = !notes.length;
    if (notes.some(([, tone]) => tone === 'bad')) ui.keysNote.dataset.tone = 'bad';
    else delete ui.keysNote.dataset.tone;
    const ownWindow = (set.ocr_capture || 'screen') === 'window' && sc.target?.how !== 'screen';
    ui.screenHint.textContent = sc.excluded === false
      ? 'Windows here cannot leave Sluka’s windows out of the pictures of the screen (Windows 10 2004 or later can): keep them off '
        + 'the box, or read the game’s own window (Reading settings).'
      : ownWindow
        ? 'The game’s own window is read: Sluka’s windows, the floating subtitles too, show in screenshots and recordings.'
        : 'While a box is read off the screen, Sluka’s own windows are left out of screenshots and recordings, so that the floating '
          + 'subtitles are never read back. To have them in your recordings, read the game’s own window (Reading settings).';
  }

  /** The Sluka Vision tab: the reader, the window read and what was read, the keys. */
  function renderVision(s) {
    const v = s.vision || {};
    const engines = v.engines || {};
    const set = s.settings || {};
    const looked = Object.keys(engines).length > 0;
    for (const item of ui.visionReaders.options) {
      const base = (VISION_READERS.find(([value]) => value === item.value) || [])[1] || item.value;
      const info = engines[item.value];
      item.textContent = info && !info.ok ? `${base} (not here)` : base;
    }
    const chosen = set.vision_engine || 'lens';
    const info = engines[chosen] || {};
    let note = '';
    if (chosen === 'lens') {
      note = info.ok === false ? `${info.why ? `${info.why.charAt(0).toUpperCase()}${info.why.slice(1)}` : 'Google Lens cannot be used here'}.`
        : set.lens_ok ? 'Online: each read sends a picture of the game’s window to Google, whose terms apply.'
          : 'Online: Sluka asks first, before any picture of the game’s window goes to Google; until then Sluka’s own OCR reads.';
    } else if (!looked) note = v.error || 'Looking at what can read the screen here…';
    else note = info.why ? `${info.why.charAt(0).toUpperCase()}${info.why.slice(1)}.` : '';
    ui.visionReaderNote.textContent = note;
    if (info.ok === false) ui.visionReaderNote.dataset.tone = 'bad';
    else delete ui.visionReaderNote.dataset.tone;

    const keys = v.keys || {};
    const readKey = keys.read?.key || '';
    const target = v.target;
    const status = v.status || {};
    ui.visionStart.textContent = target ? ''
      : readKey ? `Press ${readKey} in the game: the window in front is read, and its words are laid over it. Or choose its window:`
        : 'Choose the game’s window (or give “Read the window” a key below, and press it in the game):';
    ui.visionStart.hidden = !!target;
    ui.visionPick.textContent = v.picking ? `Click on the game’s window now… (${Math.ceil(v.picking)} s, click here to stop)`
      : target ? 'Choose another window' : 'Choose the window';
    const error = ui.visionPickError || (!target && v.error) || '';
    ui.visionError.hidden = !error;
    ui.visionError.textContent = error;
    ui.visionCard.hidden = !target;
    if (target) {
      ui.visionName.textContent = target.exe && target.title && target.title !== target.exe ? `${target.title} — ${target.exe}`
        : target.title || target.exe || 'the game';
      let [label, how] = VISION_STATES[status.state] || ['', ''];
      const parts = [];
      if (label) parts.push(label);
      if (v.frozen === 'pause') parts.push('the game is paused');
      else if (v.frozen === 'picture') parts.push('its picture is frozen');
      else if (set.vision_auto) parts.push('reads by itself as it changes');
      else if (readKey) parts.push(`reads at ${readKey}`);
      if (v.error) {
        parts.push(v.error);
        how = 'bad';
      } else if (status.state === 'failed' && status.text) parts.push(status.text);
      ui.visionHow.textContent = parts.join(' · ');
      if (how === 'live' || how === 'bad') ui.visionHow.dataset.tone = how;
      else delete ui.visionHow.dataset.tone;
      const last = v.last || {};
      ui.visionText.textContent = last.at ? last.text || 'No text was found in the window.' : 'Nothing read yet.';
      ui.visionText.classList.toggle('none', !last.text);
      ui.visionWhen.textContent = last.at
        ? `${last.lines} line${last.lines === 1 ? '' : 's'} read ${ago(last.at)}${last.ms ? ` in ${(last.ms / 1000).toFixed(1)} s` : ''}`
          + `${last.engine ? ` by ${READER_NAMES[last.engine] || last.engine}` : ''}${last.why === 'auto' ? ', by itself' : ''}`
          + `${v.shown ? '' : ' — its words are put away'}.`
        : '';
      ui.visionWhen.hidden = !ui.visionWhen.textContent;
      ui.visionClear.disabled = !v.shown;
      const pauseKey = keys.pause?.key ? ` (${keys.pause.key})` : '';
      const freezeKey = keys.freeze?.key ? ` (${keys.freeze.key})` : '';
      ui.visionPause.textContent = v.frozen === 'pause' ? `Go on${pauseKey}` : `Pause the game${pauseKey}`;
      ui.visionFreeze.textContent = v.frozen === 'picture' ? `Let the picture go${freezeKey}` : `Freeze the picture${freezeKey}`;
      ui.visionPause.classList.toggle('primary', v.frozen === 'pause');
      ui.visionFreeze.classList.toggle('primary', v.frozen === 'picture');
    }
    const notes = [];
    for (const [action, label] of VISION_KEYS) {
      const id = `vision:${action}`;
      const found = keys[action] || {};
      const button = ui.keyButtons[id];
      const listening = ui.listeningFor === id;
      button.textContent = listening ? 'Press the keys… (Esc: none)' : found.key || 'Set a key';
      button.classList.toggle('none', !listening && !found.key);
      button.classList.toggle('listening', listening);
      ui.keyClears[id].hidden = !found.key || listening;
      if (found.error && found.key) notes.push([`${found.key} (${label}): ${found.error}.`, 'bad']);
      else if (found.note) notes.push([`${found.note}.`, '']);
    }
    if (ui.visionKeysError) {
      const e = ui.visionKeysError;
      notes.unshift([e.charAt(0).toUpperCase() + e.slice(1) + (/[.!]$/.test(e) ? '' : '.'), 'bad']);
    }
    ui.visionKeysNote.textContent = notes.map(([text]) => text).join(' ');
    ui.visionKeysNote.hidden = !notes.length;
    if (notes.some(([, tone]) => tone === 'bad')) ui.visionKeysNote.dataset.tone = 'bad';
    else delete ui.visionKeysNote.dataset.tone;
    const visionOwn = v.capture ? v.capture === 'window' : (set.vision_capture || 'screen') === 'window';
    ui.visionHint.textContent = 'Play in a window or a borderless window: nothing can be laid over a game in exclusive full screen. '
      + (v.excluded === false
        ? 'Windows here cannot leave Sluka’s windows out of the pictures of the screen (Windows 10 2004 or later can): read the '
          + 'game’s own window (Sluka Vision settings).'
        : visionOwn
          ? 'The game’s own window is read: Sluka Vision’s words show in screenshots and recordings.'
          : 'While the screen is read, Sluka’s words and windows are left out of screenshots and recordings, so that it never reads '
            + 'itself back. To have them in your recordings, read the game’s own window (Sluka Vision settings).');
  }

  function renderThreads(s) {
    const threads = s.threads || [];
    const selected = new Set(s.selected || []);
    const seen = new Set();
    for (const t of threads) {
      seen.add(t.id);
      let row = rows.get(t.id);
      if (!row) {
        row = makeRow(t.id);
        rows.set(t.id, row);
      }
      const on = selected.has(t.id);
      row.node.setAttribute('aria-selected', String(on));
      row.box.checked = on;
      if (row.count !== t.count) {
        if (row.count !== undefined) {
          row.node.classList.remove('fresh');
          void row.node.offsetWidth; // the flash starts again
          row.node.classList.add('fresh');
        }
        row.count = t.count;
      }
      row.line.textContent = t.text || '(nothing readable yet)';
      row.line.classList.toggle('none', !t.text);
      row.line.title = (t.lines || []).join('\n');
      row.nm.textContent = t.name || '?';
      row.cd.textContent = t.code || '';
      row.cd.title = t.code || '';
      row.ct.textContent = `×${t.count}`;
      const suggested = s.suggested === t.id && !on;
      row.tag.hidden = !(suggested || (on && s.picked && s.picked !== 'you'));
      row.tag.className = `tag ${on ? 'got' : 'sug'}`;
      row.tag.textContent = on ? (s.picked === 'auto' ? 'picked by itself' : 'as last time') : 'looks like dialogue';
      if (row.node.parentNode !== ui.threads) ui.threads.append(row.node);
    }
    for (const [id, row] of rows) {
      if (!seen.has(id)) {
        row.node.remove();
        rows.delete(id);
      }
    }
    const game = s.game;
    let hint = '';
    if (game && game.state === 'attached' && !threads.length) {
      const waited = Date.now() / 1000 - (game.since || 0);
      hint = waited > 25
        ? 'Still nothing: tick “Read Windows’ text functions too” above, or give the game’s hook code (search for its name with “hook code” or “H-code”).'
        : 'Waiting for the game’s text: click in the game so that a new line shows.';
    } else if (game && game.state === 'attaching') {
      hint = 'Putting the hook into the game…';
    } else if (threads.length && !selected.size) {
      hint = 'No thread is picked yet: click the one with the game’s lines.';
    }
    ui.threadsHint.textContent = hint;
    ui.threadsHint.hidden = !hint;
  }

  function makeRow(id) {
    const box = el('input', { type: 'checkbox', 'aria-label': 'Show this thread too' });
    const line = el('div', { class: 'line' });
    const nm = el('span', { class: 'nm' });
    const cd = el('span', { class: 'cd' });
    const ct = el('span', { class: 'ct' });
    const tag = el('span', { class: 'tag', hidden: true });
    const node = el('li', { class: 't', role: 'option', tabindex: '0', dataset: { id: String(id) } },
      box, el('div', { class: 'tx' }, line, el('div', { class: 'meta' }, nm, tag, cd, ct)));
    box.addEventListener('click', (e) => {
      e.stopPropagation();
      call('games/select', { id, on: box.checked });
    });
    const pick = () => {
      const on = node.getAttribute('aria-selected') !== 'true' || (state?.selected || []).length > 1;
      call('games/select', { id, on, only: true });
    };
    node.addEventListener('click', pick);
    node.addEventListener('dblclick', () => call('games/send', { id }));
    node.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pick();
      }
    });
    return { node, box, line, nm, cd, ct, tag, count: undefined };
  }

  /* ------------------------------------------------------------------ in the page */

  function place() {
    if (host) return;
    host = document.createElement('sluka-desktop-dock');
    // Closed to the page; the tests ask for it open (the app never does).
    root = host.attachShadow({ mode: BOOT.openShadow === true ? 'open' : 'closed' });
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(CSS);
      root.adoptedStyleSheets = [sheet];
    } catch {
      const style = document.createElement('style');
      style.textContent = CSS;
      root.append(style);
    }
    subButton = el('button', { type: 'button', class: 'b sub', 'aria-label': 'Floating subtitles', html: SUBTITLES });
    draggable(subButton, toggleBar);
    dock = el('div', { class: 'dock', role: 'toolbar', 'aria-label': 'Sluka Desktop' }, subButton);
    if (GAMES) {
      gameButton = el('button', { type: 'button', class: 'b game', 'aria-label': 'Game text', 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
        html: GAMEPAD });
      dot = el('i', { class: 'dot' });
      gameButton.append(dot);
      gameButton.title = 'Game text';
      draggable(gameButton, () => (panelOpen ? closePanel() : openPanel()));
      dock.append(gameButton);
    }
    root.append(dock);
    document.documentElement.append(host);
    placeAgain();
    showBar(barOn);
    refreshBar();
    if (GAMES) {
      glance();
      setInterval(glance, 4000);
    }
  }

  addEventListener('resize', placeAgain);
  addEventListener('storage', (e) => {
    if (e.key === PLACE_KEY) placeAgain();
  });
  // A click elsewhere in the page closes the menu.
  addEventListener('pointerdown', (e) => {
    if (panelOpen && host && !e.composedPath().includes(host)) closePanel();
  }, true);
  // Out of the way of a film shown on the whole screen.
  document.addEventListener('fullscreenchange', () => {
    if (!host) return;
    host.hidden = !!document.fullscreenElement;
    if (document.fullscreenElement) closePanel();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      refreshBar();
      glance();
    }
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', place, { once: true });
  else place();
})();
