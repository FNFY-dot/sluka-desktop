// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * Starts Sluka's background worker in this page and tells the app once it is up.
 *
 * Imported rather than written as a second <script>: an import is only done
 * when the worker's whole module graph has been evaluated, awaits at the top
 * of a module included, and that is the moment its listeners are all in place.
 */
const shim = globalThis.__slukaShim;
const boot = globalThis.__SLUKA_BOOT__ || {};

const background = boot.manifest?.background?.service_worker
  || boot.manifest?.background?.scripts?.[0]
  || 'background/service-worker.js';

if (boot.shell === 'browser' && window.top === window && navigator.locks?.request) {
  /*
   * Where the app's windows are a browser's, the worker runs wherever a lock
   * says (the end of shim.js): this page, which the app made where nobody sees
   * it, asks for it before anything else and never gives it back.
   */
  await new Promise((mine) => {
    navigator.locks.request('sluka-desktop:background', () => {
      mine();
      return new Promise(() => {});
    });
  });
}

try {
  await import(`/${String(background).replace(/^\/+/, '')}`);
} catch (err) {
  // Said in the app's log, where someone can find it: nothing shows this page.
  console.error('[sluka-desktop] Sluka\'s background worker did not start:', err);
}

if (!chrome.runtime.onMessage.hasListeners()) {
  console.error('[sluka-desktop] the background worker is not listening; lookups and settings will not answer');
}

await shim.backgroundStarted();

if (boot.anki) {
  // The same for the pages of Anki's that have Sluka in them: what they say is passed on from here.
  const frame = document.createElement('iframe');
  frame.src = '/__sluka__/anki-gateway.html';
  frame.hidden = true;
  frame.title = 'Anki gateway';
  document.body.append(frame);
}

if (boot.mpv) {
  // In a frame, so it is a context of its own and can ask this page's worker for things.
  const frame = document.createElement('iframe');
  frame.src = '/__sluka__/mpv-engine.html';
  frame.hidden = true;
  frame.title = 'mpv engine';
  document.body.append(frame);
}
