// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Settings → Dictionary → Your own dictionaries, in the app (shim.js brings this into the dashboard): a dictionary of
 * yours in a kind of file Sluka does not read itself -- StarDict, ABBYY Lingvo (.dsl), JMdict, CC-CEDICT, CC-Canto,
 * Folkets lexikon, kaikki.org's Wiktionary -- picked with Sluka's own "Add a dictionary…", is made into a Yomitan
 * dictionary on this computer (dictfiles.py) and handed back to Sluka as if that had been picked: Sluka then reads
 * it, asks what it asks, and keeps it as it keeps any dictionary of yours.  A Yomitan dictionary or a table goes to
 * Sluka just as it is, as it always has.
 *
 * Only the card's file box is touched: it takes several files at once now (a StarDict dictionary is three or four),
 * and what is picked in it passes through here first.
 */
(() => {
  'use strict';
  if (globalThis.__slukaOwnDicts) return;
  globalThis.__slukaOwnDicts = true;
  const shim = globalThis.__slukaShim;
  if (!shim) return;
  const API = `${location.origin}/__sluka__/api/`;

  const KINDS_LINE =
    'In Sluka Desktop it also reads StarDict, ABBYY Lingvo (.dsl), JMdict, CC-CEDICT, CC-Canto, Folkets lexikon and ' +
    "kaikki.org's Wiktionary files, plain or in an archive, made into a Yomitan dictionary on this computer first. " +
    "Pick a StarDict dictionary's .ifo, .idx and .dict files together.";

  /** A file's first bytes. */
  const headOf = async (file, n = 65536) => new Uint8Array(await file.slice(0, n).arrayBuffer());

  /** The names in a zip, from its central directory (a Yomitan dictionary has an index.json), or null. */
  async function zipNames(file) {
    const tailSize = Math.min(file.size, 65557);
    const tail = new Uint8Array(await file.slice(file.size - tailSize).arrayBuffer());
    let end = -1;
    for (let i = tail.length - 22; i >= 0; i--) {
      if (tail[i] === 0x50 && tail[i + 1] === 0x4b && tail[i + 2] === 0x05 && tail[i + 3] === 0x06) {
        end = i;
        break;
      }
    }
    if (end < 0) return null;
    const ev = new DataView(tail.buffer, tail.byteOffset + end);
    let size = ev.getUint32(12, true);
    let at = ev.getUint32(16, true);
    if (size === 0xffffffff || at === 0xffffffff) {
      // Zip64: the record its locator, just before, points at.
      if (end < 20) return null;
      const lv = new DataView(tail.buffer, tail.byteOffset + end - 20);
      if (lv.getUint32(0, true) !== 0x07064b50) return null;
      const where = Number(lv.getBigUint64(8, true));
      const z64 = new DataView(await file.slice(where, where + 56).arrayBuffer());
      if (z64.byteLength < 56 || z64.getUint32(0, true) !== 0x06064b50) return null;
      size = Number(z64.getBigUint64(40, true));
      at = Number(z64.getBigUint64(48, true));
    }
    if (size > 64 * 1024 * 1024 || at + size > file.size) return null;
    const cd = new Uint8Array(await file.slice(at, at + size).arrayBuffer());
    const names = [];
    const text = new TextDecoder();
    let p = 0;
    while (p + 46 <= cd.length && cd[p] === 0x50 && cd[p + 1] === 0x4b && cd[p + 2] === 0x01 && cd[p + 3] === 0x02) {
      const v = new DataView(cd.buffer, cd.byteOffset + p);
      const n = v.getUint16(28, true);
      const x = v.getUint16(30, true);
      const c = v.getUint16(32, true);
      names.push(text.decode(cd.subarray(p + 46, p + 46 + n)));
      p += 46 + n + x + c;
    }
    return names;
  }

  /** The start of a text file, as it says it is written (a byte order mark), or UTF-8. */
  function textOf(head) {
    if (head[0] === 0xff && head[1] === 0xfe) return new TextDecoder('utf-16le').decode(head.subarray(2));
    if (head[0] === 0xfe && head[1] === 0xff) return new TextDecoder('utf-16be').decode(head.subarray(2));
    let zeros = 0;
    for (let i = 1; i < Math.min(head.length, 200); i += 2) if (head[i] === 0) zeros++;
    if (zeros > 40) return new TextDecoder('utf-16le').decode(head);
    return new TextDecoder('utf-8').decode(head);
  }

  const CEDICT_LINE = /^\S+ \S+ \[[^\]]*\](?: \{[^}]*\})? \/.*\/\s*$/;
  const STARDICT = /\.(ifo|idx|dict|syn)(\.(gz|dz))?$/i;

  /**
   * Whether Sluka reads a file itself ('sluka': a Yomitan dictionary, a table) or the app makes it into one first
   * ('app'), as dictfiles.py detect tells the kinds apart.
   */
  async function whose(file) {
    const name = file.name.toLowerCase();
    if (STARDICT.test(name) || /\.(dsl|dz|gz|tgz|bz2|tbz2?|xz|txz|tar)$/.test(name)) return 'app';
    const head = await headOf(file);
    if (head[0] === 0x50 && head[1] === 0x4b) {
      const names = await zipNames(file).catch(() => null);
      // A zip that cannot be listed is Sluka's to say so of.
      if (!names) return 'sluka';
      return names.some((n) => n === 'index.json' || /^[^/]+\/index\.json$/.test(n)) ? 'sluka' : 'app';
    }
    if (head[0] === 0x1f && head[1] === 0x8b) return 'app';
    if (head[0] === 0x42 && head[1] === 0x5a && head[2] === 0x68) return 'app';
    if (head[0] === 0xfd && head[1] === 0x37 && head[2] === 0x7a && head[3] === 0x58) return 'app';
    if (head.length > 262 && String.fromCharCode(...head.subarray(257, 262)) === 'ustar') return 'app';
    const text = textOf(head).replace(/^﻿/, '');
    const start = text.trimStart();
    if (/^#(NAME|INDEX_LANGUAGE|CONTENTS_LANGUAGE)\b/.test(start) || start.startsWith("StarDict's dict ifo file")) return 'app';
    if (start.startsWith('<')) return 'app';
    const first = text.split(/\r?\n/).slice(0, 200).find((line) => line.trim() && !line.startsWith('#')) || '';
    if (CEDICT_LINE.test(first)) return 'app';
    if (first.trimStart().startsWith('{') && /"word"\s*:/.test(text) && /"senses"\s*:/.test(text)) return 'app';
    if (text.includes('\u0000')) return 'app';
    return 'sluka';
  }

  /** The files picked, in sets: Sluka's each alone; a StarDict dictionary's pieces as one; any other file alone. */
  async function setsOf(files) {
    const sluka = [];
    const app = new Map();
    for (const file of files) {
      if ((await whose(file)) === 'sluka') {
        sluka.push(file);
        continue;
      }
      const stem = STARDICT.test(file.name) ? `stardict:${file.name.replace(STARDICT, '').toLowerCase()}` : `file:${app.size}:${file.name}`;
      if (!app.has(stem)) app.set(stem, []);
      app.get(stem).push(file);
    }
    return { sluka, app: [...app.values()] };
  }

  let started = false;

  function start() {
    if (started) return true;
    const input = document.getElementById('ownDictFile');
    const add = document.getElementById('ownDictAdd');
    const card = document.getElementById('ownDictCard');
    if (!input || !add || !card) return false;
    started = true;
    input.multiple = true;
    if (!card.querySelector('.sluka-desktop-kinds')) {
      const line = document.createElement('p');
      line.className = 'muted sluka-desktop-kinds';
      line.textContent = KINDS_LINE;
      (card.querySelector('p.muted') || add).after(line);
    }
    const status = document.createElement('p');
    status.className = 'note sluka-desktop-making';
    status.setAttribute('role', 'status');
    status.hidden = true;
    (add.closest('.row') || add).after(status);
    const say = (text) => {
      status.textContent = text || '';
      status.hidden = !text;
    };

    let passing = false;
    let busy = false;

    /** Sluka's own Add, done with what it was given: its button on again (dashboard/own-dicts.js). */
    const settled = () => new Promise((resolve) => {
      if (!add.disabled) {
        resolve();
        return;
      }
      const watch = new MutationObserver(() => {
        if (!add.disabled) {
          watch.disconnect();
          resolve();
        }
      });
      watch.observe(add, { attributes: true, attributeFilter: ['disabled'] });
    });

    /** One file handed to Sluka's own Add, as if it alone had been picked; done once Sluka is. */
    async function toSluka(file) {
      const picked = new DataTransfer();
      picked.items.add(file);
      input.files = picked.files;
      add.disabled = false;
      passing = true;
      try {
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } finally {
        passing = false;
      }
      await settled();
    }

    async function call(name, body) {
      return shim.api(name, body);
    }

    /** A set of files made into a Yomitan dictionary by the app, then handed to Sluka. */
    async function made(files) {
      const what = files.length === 1 ? files[0].name : `${files[0].name.replace(STARDICT, '')} (${files.length} files)`;
      say(`Reading ${what}…`);
      let job = '';
      try {
        for (const file of files) {
          const q = new URLSearchParams({ name: file.name, ...(job ? { job } : {}) });
          const res = await fetch(`${API}dict/file?${q}`, { method: 'POST', body: file });
          const got = await res.json().catch(() => ({}));
          if (!res.ok || !got.ok) throw new Error(got.error || `${file.name} could not be read (${res.status}).`);
          job = got.job;
        }
        await call('dict/convert', { job });
        let state;
        for (;;) {
          await new Promise((resolve) => setTimeout(resolve, 400));
          state = await call('dict/converting', { job });
          if (!state.ok) throw new Error(state.error || 'It could not be read.');
          if (state.state === 'failed') throw new Error(state.error || 'It could not be read.');
          if (state.state === 'ready') break;
          const kind = state.name ? ` (${state.name})` : '';
          const count = Number(state.entries) > 0 ? `: ${Number(state.entries).toLocaleString()} entries` : '';
          say(`Making ${what}${kind} into a Yomitan dictionary${count}…`);
        }
        const res = await fetch(`${API}dict/made?job=${encodeURIComponent(job)}`);
        if (!res.ok) throw new Error(`The dictionary made could not be had (${res.status}).`);
        const blob = await res.blob();
        const base = (files.find((f) => /\.(ifo|dsl)$/i.test(f.name)) || files[0]).name.replace(/(\.(ifo|idx|dict|syn|dz|gz|bz2|xz|tar|tgz|zip|dsl|xml|txt|u8|jsonl?))+$/i, '');
        say('');
        await toSluka(new File([blob], `${base || 'dictionary'}.zip`, { type: 'application/zip' }));
      } finally {
        if (job) call('dict/forget', { job }).catch(() => {});
      }
    }

    async function handle(files) {
      busy = true;
      add.disabled = true;
      try {
        const { sluka, app } = await setsOf(files);
        for (const file of sluka) await toSluka(file);
        for (const set of app) {
          try {
            await made(set);
          } catch (err) {
            say(`${set[0].name}: ${err?.message || err}`);
            return;
          }
        }
      } finally {
        busy = false;
        add.disabled = false;
      }
    }

    // Before Sluka's own listener: what Sluka reads goes on to it, the rest is made into what it reads.
    document.addEventListener('change', (e) => {
      if (e.target !== input || passing) return;
      e.stopImmediatePropagation();
      const files = [...(input.files || [])];
      input.value = '';
      if (!files.length || busy) return;
      say('');
      handle(files).catch((err) => say(String(err?.message || err)));
    }, true);
    return true;
  }

  if (!start()) {
    const watch = new MutationObserver(() => {
      if (start()) watch.disconnect();
    });
    watch.observe(document.documentElement, { childList: true, subtree: true });
    addEventListener('DOMContentLoaded', () => {
      if (start()) watch.disconnect();
    }, { once: true });
  }
})();
