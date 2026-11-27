// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Sluka in Anki's review screen.
 *
 * Anki's own add-on for this app (anki/sluka_desktop) puts this one script
 * into the page the cards are shown in.  When Sluka Desktop is running, it
 * brings in what the extension brings into a web page -- Sluka's page script
 * and its stylesheets, exactly as they are in the extension -- so the words of
 * a card are coloured, pointed at and graded as they are on any page, with
 * Sluka's own card and panel.
 *
 * Two things a browser would give that script are given here instead:
 *
 *   its files      come from Anki's own little server, which hands out a
 *                  folder of the add-on's (web/ and ext/, the second being
 *                  Sluka's own files);
 *   its `chrome`   is the same stand-in the app's pages use (shim.js), told
 *                  to speak through Anki: what it says goes to the add-on by
 *                  the page's bridge to Python (pycmd), from there to the app
 *                  over a socket only you can open, and answers come back the
 *                  same way (deliver, below).  No network is involved.
 *
 * Without the app running, this script does nothing at all, and Anki is as
 * it always is.
 */
(() => {
  'use strict';
  if (window.__slukaAnki) return;

  const PROTOCOL = 1;
  /** How long the app may take over one question before it is given up. */
  const ANSWER_MS = 20000;

  const here = (document.currentScript && document.currentScript.src) || '';
  // .../_addons/<the add-on's folder>/web/anki-page.js -> .../_addons/<folder>/
  const root = here.replace(/web\/[^/]*$/, '');
  const client = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

  let started = false;      // Sluka's script has been brought in
  let up = false;           // the app is answering
  let seq = 0;
  const pending = new Map();
  let hear = null;          // the stand-in's ear for what the app's pages say
  let greet = null;         // and what it does when the app is there again
  const early = [];         // said before the stand-in was listening

  /** One thing said to the app; false where there is no way to say it. */
  function out(message) {
    try {
      if (typeof window.pycmd !== 'function') return false;
      window.pycmd(`sluka:${JSON.stringify(message)}`);
      return true;
    } catch {
      return false;
    }
  }

  function fail(why) {
    for (const [id, call] of [...pending]) {
      clearTimeout(call.timer);
      pending.delete(id);
      call.reject(new Error(why));
    }
  }

  const remote = {
    kind: 'anki',
    base: `${root}ext/`,
    send(message) {
      out({ t: 'bus', client, m: message });
    },
    listen(onMessage, onUp) {
      hear = onMessage;
      greet = onUp;
      for (const message of early.splice(0)) onMessage(message);
    },
    call(name, body) {
      return new Promise((resolve, reject) => {
        if (!up) {
          reject(new Error('Sluka Desktop is not running'));
          return;
        }
        const id = ++seq;
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`Sluka Desktop did not answer (${name})`));
        }, ANSWER_MS);
        pending.set(id, { resolve, reject, timer });
        if (!out({ t: 'api', id, client, name, body })) {
          clearTimeout(timer);
          pending.delete(id);
          reject(new Error('Anki did not pass the question on'));
        }
      });
    },
  };

  /** How long Sluka's script may take to fetch itself (some sixty files, from this computer). */
  const STARTS_WITHIN_MS = 20000;
  const COPY_HINT = ". If this Anki does not follow the link to Sluka's files, they can be copied instead:  ./sluka install-anki --copy";

  /** Sluka's page script needs an engine of about 2023 or later; an older Anki's is said, not tried. */
  function lacks() {
    const missing = [];
    try {
      if (typeof Array.prototype.at !== 'function') missing.push('Array.prototype.at');
      if (typeof globalThis.structuredClone !== 'function') missing.push('structuredClone');
      if (typeof globalThis.Highlight !== 'function') missing.push('the Highlight API');
      if (!(globalThis.CSS && CSS.supports && CSS.supports('selector(:has(*))'))) missing.push('the :has() selector');
      if (typeof globalThis.DecompressionStream !== 'function') missing.push('DecompressionStream');
    } catch {
      missing.push('a check that failed');
    }
    return missing;
  }

  function script(src, isModule) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      if (isModule) el.type = 'module';
      el.src = src;
      el.async = false;
      el.onload = () => resolve();
      el.onerror = () => reject(new Error(`could not load ${src}`));
      (document.head || document.documentElement).appendChild(el);
    });
  }

  async function start(boot) {
    if (started) return;
    started = true;
    const missing = lacks();
    if (missing.length) {
      out({ t: 'log', level: 'warning', client, text: `Anki's web engine is too old for Sluka's page script (it lacks ${missing.join(', ')}): ${navigator.userAgent}` });
      return;
    }
    try {
      window.__SLUKA_BOOT__ = { id: boot.id, manifest: boot.manifest, app: boot.app, remote };
      await script(`${root}web/shim.js`);
      // What the extension's manifest puts into every page: its stylesheets, then its script.
      for (const sheet of boot.css || []) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = remote.base + sheet;
        link.setAttribute('data-sluka', '');
        (document.head || document.documentElement).appendChild(link);
      }
      // Sluka's script says what stops it on the console alone, which nobody sees in Anki: listened to while it starts.
      const said = [];
      let listening = true;
      const consoleError = console.error;
      console.error = function slukaHears(...args) {
        try {
          if (listening && String(args[0]).startsWith('[sluka]')) {
            said.push(args.map((a) => (a && a.message ? `${a.name || 'Error'}: ${a.message}` : String(a))).join(' ').slice(0, 300));
          }
        } catch {
          /* nothing to note */
        }
        return consoleError.apply(this, args);
      };
      for (const file of boot.js || []) await script(remote.base + file);
      const engine = navigator.userAgent.match(/Chrom\w*\/[\d.]+/)?.[0] || 'engine unknown';
      // Its first file only fetches the rest: it is there once that has come.
      let reader = null;
      for (let waited = 0; waited < STARTS_WITHIN_MS && !reader && !said.length; waited += 100) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        reader = window.__slukaBoot && window.__slukaBoot.mod;
      }
      if (reader) {
        out({ t: 'log', level: 'info', client, text: `Sluka's page script is in Anki's review screen (${engine})` });
        readEveryCard();
        learnKeys();
        // What stops it later in its start is still worth a line.
        setTimeout(() => {
          listening = false;
          if (said.length) out({ t: 'log', level: 'error', client, text: `Sluka's page script met trouble starting in Anki (${engine}): ${said[0]}` });
        }, 8000);
        return;
      }
      listening = false;
      out({ t: 'log', level: 'error', client, text: `Sluka's page script did not start in Anki (${engine}): ${await whyNot(said[0] || '')}` });
    } catch (err) {
      const what = err && err.message ? err.message : String(err);
      const file = (what.match(/could not load (\S+)/) || [])[1] || '';
      const why = file.includes('/ext/') ? await whyNot('', file) : '';
      out({ t: 'log', level: 'error', client, text: `Sluka's page script could not be brought into Anki: ${what}${why ? ` (${why})` : ''}` });
    }
  }

  /** Why Sluka's own files did not come: whether Anki hands them out at all is the first thing to know. */
  async function whyNot(said, file = `${remote.base}content/reader.js`) {
    try {
      const answer = await fetch(file, { cache: 'no-store' });
      if (!answer.ok) return `Anki answered ${answer.status} for Sluka's own file ${file}${COPY_HINT}`;
    } catch (err) {
      return `Sluka's own file ${file} could not be fetched from Anki: ${err && err.message ? err.message : err}${COPY_HINT}`;
    }
    return said || 'its files are there, and it gave no reason';
  }

  /**
   * The single keys Sluka acts on, as its own settings have them (Settings →
   * Keys): until that is known, the four levels.  Somebody who moved the levels
   * to other keys in Sluka has 1 to 4 for Anki alone.
   */
  let slukaKeys = new Set(['1', '2', '3', '4']);
  async function learnKeys() {
    try {
      const { loadSettings, onSettingsChanged } = await import(`${remote.base}lib/settings.js`);
      const take = (settings) => {
        const found = new Set();
        for (const value of Object.values((settings && settings.keys) || {})) {
          if (typeof value === 'string' && value.length === 1) found.add(value.toLowerCase());
        }
        if (found.size) slukaKeys = found;
      };
      take(await loadSettings());
      if (typeof onSettingsChanged === 'function') onSettingsChanged(take);
    } catch {
      /* the four levels it is */
    }
  }

  /**
   * Sluka reads a page when the page is in the language being learned, which
   * it tells from the page's text -- and a card is often a word or two, far
   * too little to tell by.  In a browser the toolbar's menu has "Turn Sluka on
   * here" for such a page.  Anki has no toolbar, and this was put here to read
   * cards: so, once a card is on screen and Sluka has not started by itself,
   * that same choice is made for it (the add-on's setting "read_every_card").
   * Text in other languages is left alone either way, as on any page.
   */
  async function readEveryCard() {
    const wanted = await new Promise((resolve) => {
      try {
        window.pycmd('sluka-config', (config) => resolve(!config || config.read_every_card !== false));
      } catch {
        resolve(true);
      }
      setTimeout(() => resolve(true), 1500);
    });
    if (!wanted) return;
    let turnOn = 'forceOn';
    try {
      turnOn = (await import(`${remote.base}lib/constants.js`)).MSG?.FORCE_ON || turnOn;
    } catch {
      /* the name it has had so far */
    }
    for (let tries = 0; tries < 240; tries++) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const reader = window.__slukaBoot && window.__slukaBoot.mod;
      if (!reader || !up) continue;
      if (typeof reader.activeLanguage === 'function' && reader.activeLanguage()) return;
      const card = document.getElementById('qa') || document.body;
      if (!card || !String(card.textContent || '').trim()) continue;
      const answer = await new Promise((resolve) => {
        try {
          chrome.runtime.onMessage.dispatch({ type: turnOn, action: 'on' }, { id: chrome.runtime.id }, resolve);
        } catch {
          resolve(null);
        }
        setTimeout(() => resolve(null), 1500);
      });
      if (answer && answer.can) return;
    }
  }

  /** The page says it is here, so that the app can tell it how to start; said again whenever the app turns up. */
  function open() {
    out({ t: 'page', state: 'open', v: PROTOCOL, client, ua: navigator.userAgent, url: location.origin + location.pathname });
  }

  /**
   * A key Anki would act on (1 to 4 answer a card): whether Sluka takes it
   * instead.  It does while a word's panel is open -- somebody clicked a word,
   * and the panel shows the levels these keys set -- and Sluka is set to act on
   * that key.  With `hover` (the add-on's setting "grade_keys_on_hover") also
   * while the pointer rests on a word, as on a web page; that is not the rule
   * from the start, because a pointer left lying on a card would take the key
   * meant to answer it.
   *
   * Handed over the way Sluka hands itself a game controller's press, since a
   * key Anki has already taken never reaches the page as a real one.
   */
  function key(name, hover) {
    if (!started || !/^[0-9a-z]$/i.test(String(name))) return false;
    // A key Sluka is not set to act on stays Anki's, wherever the pointer is.
    if (!slukaKeys.has(String(name).toLowerCase())) return false;
    // The word whose panel is open, as long as it is still on the card.
    let wanted = !!document.querySelector('llr-w[data-llr-sel]');
    if (!wanted && hover === true) wanted = !!document.querySelector('llr-w:hover, llr-w[data-llr-hov]');
    if (!wanted) return false;
    const event = new KeyboardEvent('keydown', { key: String(name), bubbles: true, cancelable: true });
    Object.defineProperty(event, 'pad', { value: true });
    window.dispatchEvent(event);
    return true;
  }

  window.__slukaAnki = {
    client,
    key,
    /** One line from the app, passed on by the add-on. */
    deliver(line) {
      let m;
      try {
        m = typeof line === 'string' ? JSON.parse(line) : line;
      } catch {
        return;
      }
      if (!m || typeof m !== 'object' || (m.to && m.to !== client)) return;
      switch (m.t) {
        case 'up':
          // The app has turned up (or come back): it is told of this page.
          open();
          break;
        case 'down':
          up = false;
          fail('Sluka Desktop is not running');
          break;
        case 'boot': {
          const was = up;
          up = true;
          if (!started) start(m.boot || {});
          else if (!was) greet?.();
          break;
        }
        case 'reply': {
          const call = pending.get(m.id);
          if (!call) break;
          clearTimeout(call.timer);
          pending.delete(m.id);
          if (m.ok) call.resolve(m.data);
          else call.reject(new Error(m.error || 'Sluka Desktop refused'));
          break;
        }
        case 'bus':
          if (hear) hear(m.m);
          else if (early.length < 200) early.push(m.m);
          break;
        default:
      }
    },
  };

  // Anki's bridge to Python comes up a moment after the page does.
  let tries = 0;
  (function wait() {
    if (typeof window.pycmd === 'function') open();
    else if (++tries < 200) setTimeout(wait, 50);
  })();
})();
