// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * What this computer's web engine does with the things Sluka needs, one line
 * each.  Opened with "./sluka selftest"; the result is also written to
 * data/logs/selftest.txt, which is the file to send when something is wrong.
 *
 * Nothing here reads or changes the word list, the books or the settings: the
 * checks use keys and files of their own and take them away again.
 */
const shim = globalThis.__slukaShim;
const boot = globalThis.__SLUKA_BOOT__ || {};
const table = document.getElementById('rows');
const lines = [];
let failed = 0;

function show(state, name, detail) {
  const row = document.createElement('tr');
  row.className = state;
  for (const [cls, text] of [['state', state], ['name', name], ['detail', detail || '']]) {
    const cell = document.createElement('td');
    cell.className = cls;
    cell.textContent = text;
    row.append(cell);
  }
  table.append(row);
  lines.push(`[${state.padEnd(4)}] ${name}${detail ? `: ${detail}` : ''}`);
  if (state === 'FAIL') failed += 1;
}

const within = (promise, ms) => Promise.race([
  promise,
  new Promise((_, reject) => setTimeout(() => reject(new Error(`no answer in ${ms / 1000} s`)), ms)),
]);

/** Run one check: what it returns is shown beside "ok", what it throws beside "FAIL" (or "note", where nothing depends on it). */
async function check(name, run, { optional = false, ms = 15000 } = {}) {
  try {
    show('ok', name, await within(Promise.resolve().then(run), ms));
  } catch (err) {
    show(optional ? 'note' : 'FAIL', name, err?.message || String(err));
  }
}
/** Said by a check that has something to tell but nothing wrong to report. */
class Note extends Error {}
async function tell(name, run, ms = 15000) {
  try {
    show('ok', name, await within(Promise.resolve().then(run), ms));
  } catch (err) {
    show(err instanceof Note ? 'note' : 'FAIL', name, err?.message || String(err));
  }
}

const mb = (bytes) => `${Math.round(bytes / (1024 * 1024))} MB`;
const key = `__selftest:${Date.now().toString(36)}`;

await check('the engine', async () => {
  const ua = navigator.userAgent;
  const webkit = /AppleWebKit\/([\d.]+)/.exec(ua)?.[1];
  let host = '';
  try {
    host = (await shim.api('info', {})).engine || '';
  } catch { /* said by the next checks */ }
  return [host, webkit && `AppleWebKit/${webkit}`, /Chrome\/[\d.]+/.exec(ua)?.[0]].filter(Boolean).join(' · ') || ua;
});

await tell('the page has Sluka\'s own address', () => {
  if (location.origin === `chrome-extension://${boot.id}`) return location.origin;
  throw new Note(`${location.origin} (the test server; in the app this is chrome-extension://${boot.id})`);
});

await check('a secure context', () => {
  if (!globalThis.isSecureContext) throw new Error('no: WebCrypto and some storage are withheld from this address');
  return 'yes';
});

await check('WebCrypto (Sluka checks a licence with it)', async () => {
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
  const data = new TextEncoder().encode('sluka');
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, data);
  const good = await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, pair.publicKey, signature, data);
  if (!good) throw new Error('a signature it made itself did not verify');
  return 'ECDSA P-256 signs and verifies';
});

await check('Sluka\'s own modules load', async () => {
  const constants = await import('/lib/constants.js');
  const names = Object.keys(constants);
  if (!names.length) throw new Error('lib/constants.js loaded but exports nothing');
  return `Sluka ${chrome.runtime.getManifest().version}, lib/constants.js (${names.length} exports)`;
});

await check('WebAssembly', async () => {
  await WebAssembly.instantiate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]));
  return 'compiles under Sluka\'s policy';
});

await check('Sluka\'s content policy is enforced', () => {
  let ran = false;
  try {
    ran = new Function('return true')();
  } catch { /* what the policy is for */ }
  if (ran) throw new Error('text was run as code: the policy is NOT in force (is [security] csp off?)');
  return 'text is not run as code';
});

await check('the app\'s storage file (your words are kept there)', async () => {
  const value = { n: 42, text: 'señal · 信号 · сигнал', list: [1, 2, 3] };
  await chrome.storage.local.set({ [key]: value });
  const got = (await chrome.storage.local.get(key))[key];
  await chrome.storage.local.remove(key);
  const gone = !(key in await chrome.storage.local.get(key));
  if (JSON.stringify(got) !== JSON.stringify(value)) throw new Error(`came back changed: ${JSON.stringify(got)}`);
  if (!gone) throw new Error('could not be removed again');
  return 'written, read back the same, removed';
});

await check('a large value through the same door', async () => {
  const big = 'ñ'.repeat(600 * 1024);
  const t0 = performance.now();
  await chrome.storage.local.set({ [`${key}:big`]: big });
  const got = (await chrome.storage.local.get(`${key}:big`))[`${key}:big`];
  await chrome.storage.local.remove(`${key}:big`);
  if (got !== big) throw new Error(`came back ${got?.length ?? 'missing'} characters long, not ${big.length}`);
  return `1.2 MB there and back in ${Math.round(performance.now() - t0)} ms`;
});

await check('the engine\'s own database (dictionaries are built into it)', async () => {
  const name = `sluka-selftest-${Date.now()}`;
  const open = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(name, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('s');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error('blocked'));
  });
  const db = await open();
  const done = (tx) => new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onerror = tx.onabort = () => reject(tx.error || new Error('aborted'));
  });
  const write = db.transaction('s', 'readwrite');
  write.objectStore('s').put(new Uint8Array(256 * 1024), 'k');
  await done(write);
  const got = await new Promise((resolve, reject) => {
    const req = db.transaction('s').objectStore('s').get('k');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  db.close();
  await new Promise((resolve) => {
    const req = indexedDB.deleteDatabase(name);
    req.onsuccess = req.onerror = req.onblocked = resolve;
  });
  if (got?.byteLength !== 256 * 1024) throw new Error('what was stored did not come back');
  return 'IndexedDB stores and returns';
});

await tell('room in it', async () => {
  const { quota, usage } = await navigator.storage.estimate();
  const text = `${mb(usage || 0)} used of ${mb(quota || 0)} this engine allows`;
  if (quota && quota < 2 * 1024 ** 3) throw new Note(`${text}. Enough for dictionaries and books; films are better kept as files and played in mpv.`);
  return text;
});

await check('Sluka\'s background page', async () => {
  const t0 = performance.now();
  const there = () => [...shim.peers.values()].find((p) => p.role === 'background' && p.ready);
  while (!there() && performance.now() - t0 < 40000) await new Promise((r) => setTimeout(r, 200));
  if (!there()) throw new Error('never said hello: pages in different windows cannot hear each other (BroadcastChannel), or the worker did not start. See sluka-desktop.log');
  // A question it has no answer to: what matters is that it is heard and let go, not left hanging.
  await chrome.runtime.sendMessage({ type: '__sluka_desktop_selftest__' });
  return `heard after ${Math.round(performance.now() - t0)} ms, and answers`;
}, { ms: 60000 });

await tell('timers in the background page', async () => {
  const found = await shim.probe('background');
  if (!found) throw new Error('it did not answer');
  if (found.ms > 400) {
    throw new Note(`a 100 ms timer took ${found.ms} ms: this engine slows a page that is not on screen. Sluka does not lean on timers there, so this is slower in places, not broken.`);
  }
  return `a 100 ms timer took ${found.ms} ms`;
});

await check('files Sluka saves (backups, exports)', async () => {
  const url = URL.createObjectURL(new Blob(['Sluka Desktop self-test\n'], { type: 'text/plain' }));
  let id;
  try {
    id = await chrome.downloads.download({ url, filename: 'Sluka/selftest.txt', conflictAction: 'overwrite', saveAs: false });
  } finally {
    URL.revokeObjectURL(url);
  }
  const [item] = await chrome.downloads.search({ id });
  if (!item || item.state !== 'complete') throw new Error(`not written (${item?.state || 'no record'})`);
  await chrome.downloads.removeFile(id);
  await chrome.downloads.erase({ id });
  return `written to ${item.filename}, and taken away again`;
});

await tell('video and audio in the app\'s own player', () => {
  const video = document.createElement('video');
  const kinds = {
    'H.264/AAC (mp4)': 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"',
    'VP9/Opus (webm)': 'video/webm; codecs="vp9, opus"',
    'mkv files': 'video/x-matroska',
    'AV1': 'video/mp4; codecs="av01.0.05M.08"',
    'AV1 in mkv/webm': 'video/webm; codecs="av01.0.05M.08"',
    'HEVC': 'video/mp4; codecs="hvc1.1.6.L93.B0"',
    'MP3': 'audio/mpeg',
    'Ogg Vorbis': 'audio/ogg; codecs="vorbis"',
    'FLAC': 'audio/flac',
  };
  const yes = [], no = [];
  for (const [name, type] of Object.entries(kinds)) (video.canPlayType(type) ? yes : no).push(name);
  const text = `plays ${yes.join(', ') || 'nothing'}${no.length ? `; not ${no.join(', ')}` : ''}`;
  if (!yes.includes('H.264/AAC (mp4)') || !yes.includes('mkv files')) {
    throw new Note(`${text}. What is missing is played by mpv, with Sluka in it; the app offers that when a film will not play here.`);
  }
  return text;
});

await tell('the network', async () => {
  const mode = boot.network || 'offline';
  let reached = false;
  try {
    await within(fetch('https://example.org/', { mode: 'no-cors', cache: 'no-store' }), 20000);
    reached = true;
  } catch { /* refused, blocked or timed out */ }
  if (mode === 'offline') {
    if (reached) throw new Error('mode is offline, yet a website answered');
    return 'offline, as set: a website could not be reached from Sluka\'s pages';
  }
  if (!reached) throw new Note(`mode is ${mode}, but a website could not be reached${mode === 'tor' ? ' (is Tor connected?)' : ''}`);
  return `${mode}: a website answered`;
}, 30000);

await tell('mpv', async () => {
  const info = await shim.api('info', {});
  if (!info.mpv) throw new Note('the bridge to mpv is off ([mpv] enabled = no)');
  return `${info.mpv.players} player(s) connected now; the script is ${info.mpv.script}`;
});

const end = document.getElementById('end');
let saved = '';
try {
  saved = (await shim.api('selftest', { lines, agent: navigator.userAgent })).path || '';
} catch (err) {
  saved = '';
  lines.push(`(could not be written to a file: ${err?.message || err})`);
}
end.textContent = `${failed ? `${failed} thing(s) did not work.` : 'Everything Sluka needs is here.'}${saved ? ` Written to ${saved}` : ''}`;
document.title = failed ? `Self-test: ${failed} failed` : 'Self-test: all passed';
globalThis.__selftest = { failed, lines, saved };
