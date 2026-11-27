// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Between a page in Anki and the app's own pages.
 *
 * The app's pages -- Sluka's worker among them -- are of one origin and talk
 * to each other over one channel in the web engine (shim.js).  Sluka's page
 * script in Anki's review screen is in another program altogether, and reaches
 * the app only through the desktop app's host (ankibridge.py).  This page
 * stands in the channel for it: what the page in Anki says is said here, and
 * what is said here that concerns it is sent to it.
 *
 * Only what concerns it, because the channel carries everything the app's
 * pages say to each other -- a whole dictionary's worth while a book is read --
 * and none of that is the page's business: who is there, what is sent to its
 * tab or in answer to it, the ports it has a hand in, and what changed in the
 * store, which every copy of Sluka's code listens for.
 */
const { api } = globalThis.__slukaShim;

const channel = new BroadcastChannel('__sluka_bus__');

/** Every page in Anki with Sluka in it, by the name it goes by on the way here. */
const pages = new Map();
/** What a page is waiting to hear of at most: older questions are let go. */
const KEPT = 400;

function pageOf(client) {
  let page = pages.get(client);
  if (!page) {
    page = { client, from: null, calls: new Set(), ports: new Set() };
    pages.set(client, page);
  }
  return page;
}

function keep(set, id) {
  set.add(id);
  if (set.size > KEPT) set.delete(set.values().next().value);
}

/** Whether something said on the channel is for `page` to hear. */
function concerns(page, m) {
  const me = page.from?.id;
  if (!me) return false;
  switch (m.k) {
    case 'hello':
    case 'info':
    case 'bye':
      return m.from?.id !== me;
    case 'here':
    case 'clash':
    case 'ping':
    case 'pong':
      return m.to === me;
    case 'msg':
      return !!m.to && m.to.tabId === page.from.tabId && m.from?.id !== me;
    case 'ack':
    case 'drop':
      return page.calls.has(m.id);
    case 'resp':
    case 'fail': {
      const mine = page.calls.has(m.id);
      page.calls.delete(m.id);
      return mine;
    }
    case 'conn':
      if (!Array.isArray(m.ends) || !m.ends.includes(me)) return false;
      keep(page.ports, m.portId);
      return true;
    case 'conn-ok':
    case 'conn-no':
    case 'port':
    case 'disc':
      return page.ports.has(m.portId);
    case 'storage':
      return true;
    default:
      return false;
  }
}

// ------------------------------------------------------------ from the app's pages to Anki

let outbox = [];
let flushing = false;
async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    while (outbox.length) {
      const msgs = outbox;
      outbox = [];
      await api('anki/push', { msgs }).catch((err) => console.error('[sluka-desktop] Anki gateway:', err));
    }
  } finally {
    flushing = false;
  }
}

channel.onmessage = (event) => {
  const m = event.data;
  if (!m || typeof m !== 'object' || !pages.size) return;
  for (const page of pages.values()) {
    if (concerns(page, m)) outbox.push({ to: page.client, m });
  }
  if (outbox.length) flush();
};

// ------------------------------------------------------------ from Anki to the app's pages

function said({ client, m, gone }) {
  if (!client) return;
  if (gone) {
    // Its page was closed, or Anki was: said for it, since it no longer can.
    const page = pages.get(client);
    pages.delete(client);
    if (page?.from) channel.postMessage({ k: 'bye', from: page.from });
    return;
  }
  if (!m || typeof m !== 'object') return;
  const page = pageOf(client);
  if (m.from && typeof m.from === 'object' && m.from.id) page.from = m.from;
  if (m.k === 'msg' && m.id) keep(page.calls, m.id);
  if (m.k === 'conn' && m.portId) keep(page.ports, m.portId);
  channel.postMessage(m);
  if (m.k === 'bye') pages.delete(client);
}

let fresh = true;
let failures = 0;
for (;;) {
  try {
    const got = await api('anki/poll', { fresh });
    fresh = false;
    failures = 0;
    // Another copy of this page has taken over.
    if (got.superseded) break;
    for (const item of got.msgs || []) {
      try {
        said(item);
      } catch (err) {
        console.error('[sluka-desktop] Anki gateway:', err);
      }
    }
  } catch (err) {
    // The app's host went away, or is not there yet: asked again, ever more slowly.
    failures++;
    if (failures === 1) console.error('[sluka-desktop] Anki gateway:', err);
    await new Promise((resolve) => setTimeout(resolve, Math.min(15000, 500 * failures)));
  }
}
