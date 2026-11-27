// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * The browser's extension API, for Sluka's own pages running outside a browser.
 *
 * Sluka's pages and its background worker are served exactly as they are in the
 * extension; this file is the one thing added, as the first script of every
 * page, and it provides the `chrome` object those files expect:
 *
 *   chrome.storage    kept by the desktop app's host, in one file on disk
 *   chrome.runtime    messages and ports between the app's pages, which are all
 *   chrome.tabs       of one origin, so they reach each other over a
 *   chrome.windows    BroadcastChannel with no help from the host
 *   chrome.alarms     timers in the background page
 *   chrome.downloads  files written by the host into the app's downloads folder
 *
 * What a browser has and this has not is left undefined on purpose, never
 * faked: chrome.offscreen, chrome.notifications and the File System Access
 * pickers.  Sluka already checks for each of them and takes the path it takes
 * in Firefox -- a background *page* that opens its helper document as a frame,
 * and backups written through chrome.downloads.
 *
 * A classic script, and synchronous to the last line: `chrome` has to exist
 * before the first module of the page is evaluated.
 *
 * The same file also runs in a page that is not the app's at all: Anki's
 * review screen, where Sluka's own page script reads the cards
 * (anki-page.js puts it there).  Such a page is to Sluka what a web page is
 * to the extension: a tab with a content script in it.  It cannot reach the
 * app's pages itself, so what it would say on the channel between them, and
 * what it would ask of the host, goes through what put it there
 * (`__SLUKA_BOOT__.remote`), and the app's side passes it on (anki-gateway.js).
 */
(() => {
  'use strict';
  if (globalThis.__slukaShim) return;

  const BOOT = globalThis.__SLUKA_BOOT__ || {};
  /** Set where this is a page outside the app: how to reach the app, and where Sluka's files are for this page. */
  const REMOTE = BOOT.remote || null;
  const ORIGIN = location.origin;
  const BASE = REMOTE ? String(REMOTE.base) : `${ORIGIN}/`;
  const API = `${BASE}__sluka__/api/`;
  const EXT_ID = BOOT.id || 'sluka';
  const MANIFEST = BOOT.manifest || {};
  const BG_PATH = '/__sluka__/background.html';

  const NO_RECEIVER = 'Could not establish connection. Receiving end does not exist.';
  const PORT_CLOSED = 'The message port closed before a response was received.';

  /** How long a page waits for the background page to come up before it sends anyway. */
  const BACKGROUND_WAIT_MS = 30000;
  /** How long a context may take to say whether it will answer a message. */
  const ACK_MS = 4000;
  /** How long a context that stopped answering is given before it is forgotten. */
  const PING_MS = 4000;
  /** A page that leaves and comes back within this was a navigation, not a closed tab. */
  const NAVIGATION_MS = 2500;

  /*
   * The folder and file pickers go with the rest: an engine that has them
   * (WebKitGTK has not) would have Sluka half in the way it works in Chrome --
   * a backup folder asked for with a picker -- and half in the way it works in
   * Firefox, where everything is written through chrome.downloads.  That mix
   * exists in no browser and is tested by nobody, so here it is all Firefox's way.
   */
  for (const name of REMOTE || BOOT.pickers === true ? [] : ['showDirectoryPicker', 'showOpenFilePicker', 'showSaveFilePicker']) {
    try {
      delete globalThis[name];
      if (typeof globalThis[name] === 'function') {
        Object.defineProperty(globalThis, name, { value: undefined, configurable: true, writable: true });
      }
    } catch {
      /* an engine that will not let go of it keeps it */
    }
  }

  /*
   * A folder of the app's own in their place (folders.py): Settings → Sync & backup's backup folder, chosen in the
   * system's folder window and kept for good -- Sluka then writes its backup there every few minutes and reads the
   * other devices', as it does in Chrome, which is what syncing through Google Drive is (a folder in My Drive).  The
   * handle Sluka keeps in IndexedDB comes back from it a handle again.
   */
  if (!REMOTE && BOOT.folders === true && BOOT.pickers !== true) installFolders();

  function installFolders() {
    const MARK = '__slukaFolder';
    /** The most of a file sent to the app in one request. */
    const PIECE = 8 * 1024 * 1024;
    const failure = (name, message) => new DOMException(message || name, name);
    const NAMED = /^(NotFoundError|TypeMismatchError|InvalidModificationError|NotAllowedError|NotReadableError)$/;

    async function call(args) {
      const res = await fetch(`${API}folders`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
      });
      let got = {};
      try {
        got = await res.json();
      } catch {
        got = {};
      }
      if (!got.ok) {
        const name = NAMED.test(got.error || '') ? got.error : 'NotReadableError';
        throw failure(name, got.why || got.error || `HTTP ${res.status}`);
      }
      return got;
    }

    function named(name) {
      const n = String(name ?? '');
      if (!n || n === '.' || n === '..' || /[\\/]/.test(n)) throw new TypeError(`Name is not allowed: ${n}`);
      return n;
    }

    class Handle {
      constructor(kind, folder, path, name) {
        this.kind = kind;
        this.name = name;
        // What is kept of it in IndexedDB: the rest is the class's, put back as it comes out (revive).
        this[MARK] = { folder, path: [...path] };
      }

      async isSameEntry(other) {
        const a = this[MARK];
        const b = other?.[MARK];
        return !!b && other.kind === this.kind && a.folder === b.folder && a.path.join('/') === b.path.join('/');
      }

      async queryPermission() {
        const { state } = await call({ op: 'state', folder: this[MARK].folder });
        return state === 'granted' ? 'granted' : 'prompt';
      }

      async requestPermission() {
        return this.queryPermission();
      }
    }

    class FileHandle extends Handle {
      constructor(folder, path, name) {
        super('file', folder, path, name);
      }

      async getFile() {
        const { folder, path } = this[MARK];
        const { at } = await call({ op: 'stat', folder, path });
        const q = `folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(JSON.stringify(path))}`;
        const res = await fetch(`${API}folders/read?${q}`);
        if (res.status === 404) throw failure('NotFoundError', `${this.name}: not found`);
        if (!res.ok) throw failure('NotReadableError', `${this.name}: HTTP ${res.status}`);
        return new File([await res.blob()], this.name, { lastModified: at });
      }

      async createWritable({ keepExistingData = false } = {}) {
        const { folder, path } = this[MARK];
        const { write } = await call({ op: 'begin', folder, path, keep: !!keepExistingData });
        let at = 0;
        let parts = [];
        let size = 0;
        const flush = async (force = false) => {
          if (!size && !force) return;
          const body = new Blob(parts);
          parts = [];
          const res = await fetch(`${API}folders/piece?write=${write}&at=${at}`, { method: 'POST', body });
          if (!res.ok) throw failure('NotReadableError', `${this.name}: HTTP ${res.status}`);
          at += size;
          size = 0;
        };
        const stream = new WritableStream({
          async write(chunk) {
            if (chunk && typeof chunk === 'object' && typeof chunk.type === 'string' && !(chunk instanceof Blob)) {
              if (chunk.type === 'seek') {
                await flush();
                at = Number(chunk.position) || 0;
                return;
              }
              if (chunk.type === 'truncate') {
                await flush();
                at = Number(chunk.size) || 0;
                await flush(true);
                return;
              }
              if (chunk.position != null && Number(chunk.position) !== at + size) {
                await flush();
                at = Number(chunk.position) || 0;
              }
              chunk = chunk.data;
            }
            const part = chunk instanceof Blob ? chunk : new Blob([chunk]);
            parts.push(part);
            size += part.size;
            if (size >= PIECE) await flush();
          },
          async close() {
            await flush();
            await call({ op: 'end', write });
          },
          async abort() {
            parts = [];
            await call({ op: 'abort', write }).catch(() => {});
          },
        });
        // FileSystemWritableFileStream's own calls, each a write of its own.
        const own = async (chunk) => {
          const writer = stream.getWriter();
          try {
            await writer.write(chunk);
          } finally {
            writer.releaseLock();
          }
        };
        stream.write = own;
        stream.seek = (position) => own({ type: 'seek', position });
        stream.truncate = (sizeTo) => own({ type: 'truncate', size: sizeTo });
        return stream;
      }
    }

    class DirHandle extends Handle {
      constructor(folder, path, name) {
        super('directory', folder, path, name);
      }

      async getFileHandle(name, { create = false } = {}) {
        const { folder } = this[MARK];
        const path = [...this[MARK].path, named(name)];
        const { kind } = await call({ op: 'kind', folder, path });
        if (kind === 'directory') throw failure('TypeMismatchError', `${name} is a folder`);
        if (!kind) {
          if (!create) throw failure('NotFoundError', `${name}: not found`);
          await call({ op: 'touch', folder, path });
        }
        return new FileHandle(folder, path, name);
      }

      async getDirectoryHandle(name, { create = false } = {}) {
        const { folder } = this[MARK];
        const path = [...this[MARK].path, named(name)];
        const { kind } = await call({ op: 'kind', folder, path });
        if (kind === 'file') throw failure('TypeMismatchError', `${name} is a file`);
        if (!kind) {
          if (!create) throw failure('NotFoundError', `${name}: not found`);
          await call({ op: 'mkdir', folder, path });
        }
        return new DirHandle(folder, path, name);
      }

      async removeEntry(name, { recursive = false } = {}) {
        const { folder } = this[MARK];
        await call({ op: 'remove', folder, path: [...this[MARK].path, named(name)], recursive: !!recursive });
      }

      async resolve(other) {
        const a = this[MARK];
        const b = other?.[MARK];
        if (!b || b.folder !== a.folder || b.path.length < a.path.length) return null;
        return a.path.every((part, i) => b.path[i] === part) ? b.path.slice(a.path.length) : null;
      }

      async* entries() {
        const { folder, path } = this[MARK];
        const { entries } = await call({ op: 'list', folder, path });
        for (const e of entries) {
          const at = [...path, e.name];
          yield [e.name, e.kind === 'directory' ? new DirHandle(folder, at, e.name) : new FileHandle(folder, at, e.name)];
        }
      }

      async* keys() {
        for await (const [name] of this.entries()) yield name;
      }

      async* values() {
        for await (const [, entry] of this.entries()) yield entry;
      }

      [Symbol.asyncIterator]() {
        return this.entries();
      }
    }

    const revive = (value) => {
      if (!value || typeof value !== 'object' || value instanceof Handle || !value[MARK]) return value;
      const { folder, path } = value[MARK];
      if (typeof folder !== 'string' || !Array.isArray(path)) return value;
      return value.kind === 'file' ? new FileHandle(folder, path, value.name) : new DirHandle(folder, path, value.name);
    };
    for (const [proto, field] of [[globalThis.IDBRequest?.prototype, 'result'], [globalThis.IDBCursorWithValue?.prototype, 'value']]) {
      const own = proto && Object.getOwnPropertyDescriptor(proto, field);
      if (!own?.get) continue;
      Object.defineProperty(proto, field, { ...own, get() { return revive(own.get.call(this)); } });
    }

    globalThis.showDirectoryPicker = async function showDirectoryPicker(options = {}) {
      const res = await fetch(`${API}folders`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'pick', id: String(options?.id || '') }),
      });
      const got = await res.json().catch(() => ({}));
      if (got.cancelled) throw failure('AbortError', 'The user aborted a request.');
      if (!got.ok) throw failure('NotAllowedError', got.error || `HTTP ${res.status}`);
      return new DirHandle(got.folder, [], got.name);
    };
  }

  // ------------------------------------------------------------ small things

  const uid = () => {
    try {
      return crypto.randomUUID();
    } catch {
      return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
    }
  };
  const randomId = () => 1 + Math.floor(Math.random() * 0x3fffffff);
  const later = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /** As the browser passes a message: by its JSON, so what cannot be written down is left out. */
  function wire(value) {
    if (value === undefined) return undefined;
    try {
      const text = JSON.stringify(value);
      return text === undefined ? undefined : JSON.parse(text);
    } catch (err) {
      throw new TypeError(`Could not serialize message: ${err?.message || err}`);
    }
  }

  /** An extension event: addListener, removeListener, hasListener. */
  class Event {
    constructor(onFirst = null) {
      this._listeners = new Set();
      this._onFirst = onFirst;
    }
    addListener(fn) {
      if (typeof fn !== 'function') return;
      const first = !this._listeners.size;
      this._listeners.add(fn);
      if (first) this._onFirst?.();
    }
    removeListener(fn) {
      this._listeners.delete(fn);
    }
    hasListener(fn) {
      return this._listeners.has(fn);
    }
    hasListeners() {
      return this._listeners.size > 0;
    }
    get size() {
      return this._listeners.size;
    }
    /** Every listener called; one that throws does not stop the rest. */
    dispatch(...args) {
      const results = [];
      for (const fn of [...this._listeners]) {
        try {
          results.push(fn(...args));
        } catch (err) {
          console.error('[sluka-desktop] a listener threw', err);
          results.push(undefined);
        }
      }
      return results;
    }
  }

  let lastError;
  /** `fn` as the extension API offers it: a promise, or the callback given last. */
  function callbackOrPromise(fn) {
    return (...args) => {
      const callback = typeof args.at(-1) === 'function' ? args.pop() : null;
      const promise = Promise.resolve().then(() => fn(...args));
      if (!callback) return promise;
      promise.then(
        (value) => callback(value),
        (err) => {
          lastError = { message: String(err?.message || err) };
          try {
            callback();
          } finally {
            lastError = undefined;
          }
        },
      );
      return undefined;
    };
  }

  // ------------------------------------------------------------ the host

  /** The largest request a page may leave behind it as it closes (the engines allow 64 KiB in all). */
  const KEEPALIVE_MOST = 48 * 1024;

  /*
   * Which of the app's windows this page is in, where the app names its windows
   * (Windows' own web view does, before any of the page's scripts run): sent
   * along with every call, so that "close this tab" reaches this window.
   */
  const viewName = () => (typeof globalThis.__SLUKA_VIEW__ === 'string' ? globalThis.__SLUKA_VIEW__ : '');

  async function api(name, body, { raw = null, query = '', lasting = false } = {}) {
    if (REMOTE) {
      // Asked through whatever put this page's Sluka here; files are not carried that way.
      if (raw) throw new Error(`Sluka Desktop: ${name} is not for a page outside the app`);
      return (await REMOTE.call(name, body ?? {})) || {};
    }
    const view = viewName();
    const named = view ? { 'X-Sluka-View': view } : {};
    const init = raw
      ? { method: 'POST', headers: { ...named }, body: raw }
      : { method: 'POST', headers: { 'Content-Type': 'application/json', ...named }, body: JSON.stringify(body ?? {}) };
    let res;
    try {
      /*
       * A write is let finish even if its page is closed under it: Sluka writes
       * a grade as its page is hidden, and a window is often closed right after
       * the last word was graded.  Where the engine will not carry it (too
       * large, too many at once) it is sent the ordinary way.
       */
      if (lasting && !raw && init.body.length <= KEEPALIVE_MOST) {
        try {
          res = await fetch(`${API}${name}${query}`, { ...init, keepalive: true });
        } catch {
          res = null;
        }
      }
      if (!res) res = await fetch(`${API}${name}${query}`, init);
    } catch (err) {
      throw new Error(`Sluka Desktop's host did not answer (${name}): ${err?.message || err}`);
    }
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* an empty answer */
    }
    if (!res.ok) throw new Error(data?.error || `${name}: ${res.status}`);
    return data || {};
  }

  // ------------------------------------------------------------ who this is

  let parentShim = null;
  let isTop = true;
  try {
    isTop = window.top === window;
    if (!isTop) parentShim = window.parent.__slukaShim || null;
  } catch {
    isTop = false;
  }

  function sessionTabId(fresh = false) {
    try {
      let id = fresh ? NaN : Number(sessionStorage.getItem('__sluka_tab'));
      if (!Number.isInteger(id) || id <= 0) {
        id = randomId();
        sessionStorage.setItem('__sluka_tab', String(id));
      }
      return id;
    } catch {
      return randomId();
    }
  }

  const me = {
    id: uid(),
    role: 'tab',
    tabId: null,
    frameId: 0,
    url: location.href,
    title: '',
    born: Date.now(),
    ready: false,
    hasMsg: false,
    hasConn: false,
    focused: false,
    focusedAt: 0,
    win: null,
  };
  if (REMOTE) {
    // A page of somebody else's with Sluka's page script in it: a tab, as a web page is one to the extension.
    me.role = 'tab';
    me.content = true;
    me.tabId = sessionTabId();
    me.ready = true;
  } else if (location.pathname === BG_PATH && (isTop || (parentShim?.holdsBackground === true && window.parent === window.top))) {
    // The page Sluka's worker runs in: a window nobody sees, or (where the windows
    // are a browser's, which has none to hide) a frame of the window whose turn it is.
    me.role = 'background';
  } else if (isTop) {
    me.role = 'tab';
    me.tabId = sessionTabId();
    me.ready = true;
  } else {
    // A frame belongs to what holds it: the background page's frame is the
    // helper document a browser would call "offscreen".
    const holder = parentShim?.context;
    me.role = holder?.role === 'background' || holder?.role === 'offscreen' ? 'offscreen' : 'frame';
    me.tabId = holder?.tabId ?? null;
    me.frameId = randomId();
    me.ready = true;
  }

  const windowBounds = () => ({
    left: Number(window.screenX) || 0,
    top: Number(window.screenY) || 0,
    width: Number(window.outerWidth) || Number(window.innerWidth) || 0,
    height: Number(window.outerHeight) || Number(window.innerHeight) || 0,
  });

  function describe() {
    me.url = location.href;
    me.title = document.title || '';
    if (me.role === 'tab') me.win = windowBounds();
    return { ...me };
  }

  // ------------------------------------------------------------ the bus

  // The app's pages are of one origin and hear each other directly; a page outside is passed what concerns it.
  const bus = REMOTE
    ? { postMessage: (message) => REMOTE.send(message), onmessage: null }
    : new BroadcastChannel('__sluka_bus__');
  /** Every other live context of the app, by its id. */
  const peers = new Map();
  /** Tabs that just left: closed, unless the same tab says hello again at once. */
  const leaving = new Map();

  const post = (message) => {
    try {
      bus.postMessage(message);
    } catch (err) {
      console.error('[sluka-desktop] could not post', message?.k, err);
    }
  };
  const announce = (k = 'info') => post({ k, from: describe() });

  let backgroundSeen = null;
  const backgroundWaiters = [];
  const backgroundPeer = () => [...peers.values()].find((p) => p.role === 'background' && p.ready) || null;
  function noteBackground() {
    if (me.role === 'background' ? !me.ready : !backgroundPeer()) return;
    backgroundSeen = true;
    for (const done of backgroundWaiters.splice(0)) done();
  }
  /** Resolves once the background page is listening; a browser starts its worker the same way, on demand. */
  function whenBackground() {
    if (me.role === 'background' || backgroundPeer()) return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, BACKGROUND_WAIT_MS);
      backgroundWaiters.push(() => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  // tab events, as the background hears them
  const tabsOnCreated = new Event();
  const tabsOnUpdated = new Event();
  const tabsOnRemoved = new Event();
  const tabsOnActivated = new Event();
  const tabsOnReplaced = new Event();
  const windowsOnCreated = new Event();
  const windowsOnRemoved = new Event();
  const windowsOnFocusChanged = new Event();

  const isTabTop = (p) => p && p.role === 'tab' && p.frameId === 0 && p.tabId != null;

  function tabOf(p) {
    if (!isTabTop(p)) return null;
    return {
      id: p.tabId,
      windowId: p.tabId,
      index: 0,
      url: p.url,
      pendingUrl: undefined,
      title: p.title || '',
      active: true,
      highlighted: true,
      pinned: false,
      incognito: false,
      status: 'complete',
      audible: false,
      discarded: false,
      autoDiscardable: false,
      mutedInfo: { muted: false },
      groupId: -1,
      width: p.win?.width || 0,
      height: p.win?.height || 0,
    };
  }

  function windowOf(p, populate = false) {
    if (!isTabTop(p)) return null;
    const win = {
      id: p.tabId,
      focused: !!p.focused,
      incognito: false,
      alwaysOnTop: false,
      type: p.windowType || 'normal',
      state: 'normal',
      left: p.win?.left || 0,
      top: p.win?.top || 0,
      width: p.win?.width || 0,
      height: p.win?.height || 0,
    };
    if (populate) win.tabs = [tabOf(p)];
    return win;
  }

  const everyone = () => [describe(), ...peers.values()];
  const tabPeers = () => everyone().filter(isTabTop);
  const findTab = (tabId) => tabPeers().find((p) => p.tabId === tabId) || null;
  function lastFocusedTab() {
    const tabs = tabPeers();
    if (!tabs.length) return null;
    return tabs.reduce((best, p) => (((p.focusedAt || p.born) > (best.focusedAt || best.born)) ? p : best));
  }

  function learn(info, fresh) {
    const known = peers.get(info.id);
    peers.set(info.id, info);
    if (info.role === 'background' && info.ready) noteBackground();
    if (!isTabTop(info)) return;
    if (!known) {
      const wasLeaving = leaving.get(info.tabId);
      if (wasLeaving) {
        clearTimeout(wasLeaving.timer);
        leaving.delete(info.tabId);
        tabsOnUpdated.dispatch(info.tabId, { status: 'loading', url: info.url }, tabOf(info));
        tabsOnUpdated.dispatch(info.tabId, { status: 'complete' }, tabOf(info));
      } else if (fresh) {
        windowsOnCreated.dispatch(windowOf(info));
        tabsOnCreated.dispatch(tabOf(info));
        tabsOnUpdated.dispatch(info.tabId, { status: 'complete', url: info.url }, tabOf(info));
      }
      settleOpens(info);
      return;
    }
    const change = {};
    if (known.url !== info.url) change.url = info.url;
    if (known.title !== info.title) change.title = info.title;
    if (Object.keys(change).length) tabsOnUpdated.dispatch(info.tabId, change, tabOf(info));
    if (info.focused && !known.focused) {
      windowsOnFocusChanged.dispatch(info.tabId);
      tabsOnActivated.dispatch({ tabId: info.tabId, windowId: info.tabId });
    } else if (!info.focused && known.focused && !tabPeers().some((p) => p.focused)) {
      windowsOnFocusChanged.dispatch(-1);
    }
  }

  function forget(id) {
    const gone = peers.get(id);
    if (!gone) return;
    peers.delete(id);
    dropPeerFromCalls(id, gone.role);
    dropPeerFromPorts(id);
    if (!isTabTop(gone)) return;
    // The same tab opening its next page says hello within a moment.
    const timer = setTimeout(() => {
      leaving.delete(gone.tabId);
      if (findTab(gone.tabId)) return;
      tabsOnRemoved.dispatch(gone.tabId, { windowId: gone.tabId, isWindowClosing: true });
      windowsOnRemoved.dispatch(gone.tabId);
    }, NAVIGATION_MS);
    leaving.set(gone.tabId, { timer });
  }

  // ------------------------------------------------------------ messages

  const onMessage = new Event(() => {
    me.hasMsg = true;
    announce();
  });
  const onConnect = new Event(() => {
    me.hasConn = true;
    announce();
  });

  /**
   * The other contexts answer this one's hello within a few milliseconds; a
   * message sent before they have would find nobody to send to.
   */
  const SETTLE_MS = 120;
  const settled = new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

  /** Messages this context sent and still waits on, by id. */
  const calls = new Map();

  function senderOf(from) {
    let origin = ORIGIN;
    if (from.content) {
      try {
        origin = new URL(from.url).origin;
      } catch {
        origin = '';
      }
    }
    const sender = {
      id: EXT_ID,
      url: from.url,
      origin,
      frameId: from.frameId || 0,
      documentId: from.id,
      documentLifecycle: 'active',
    };
    if (from.tabId != null) {
      const top = findTab(from.tabId);
      sender.tab = tabOf(top) || {
        id: from.tabId, windowId: from.tabId, index: 0, url: from.url, title: from.title || '', active: true,
        highlighted: true, pinned: false, incognito: false, status: 'complete',
      };
    }
    return sender;
  }

  /**
   * Whether what is sent `to` is for context `p`.  Sent to nobody in
   * particular it is for Sluka's own pages and worker, not for the page script
   * in a page outside the app -- which a browser, too, reaches only by its tab.
   */
  const reaches = (to, p) => (to ? p.tabId === to.tabId && (to.frameId == null || p.frameId === to.frameId) : !p.content);

  /**
   * Send `message` and wait for the one answer, as chrome.runtime.sendMessage
   * does: the first context to answer wins; when every context that heard it
   * has declined, the answer is undefined; with nobody there to hear it at
   * all, it fails with the browser's own words, which callers look for.
   */
  async function send(to, message) {
    const payload = wire(message);
    await settled;
    if (!to) await whenBackground();
    const audience = [...peers.values()].filter((p) => p.hasMsg && reaches(to, p));
    if (!audience.length) throw new Error(NO_RECEIVER);
    const id = uid();
    return new Promise((resolve, reject) => {
      const call = {
        waiting: new Set(audience.map((p) => p.id)),
        claimed: new Set(),
        resolve,
        reject,
        timer: null,
      };
      const finish = (settle, value) => {
        clearTimeout(call.timer);
        calls.delete(id);
        settle(value);
      };
      call.done = (value) => finish(resolve, value);
      call.fail = (text) => finish(reject, new Error(text));
      call.check = () => {
        if (call.waiting.size || call.claimed.size || call.moving) return;
        // Heard by all, wanted by none.
        call.done(undefined);
      };
      // A context that never says whether it will answer is asked if it is there.
      const arm = () => {
        clearTimeout(call.timer);
        call.timer = setTimeout(() => {
          for (const peerId of [...call.waiting]) {
            call.waiting.delete(peerId);
            probe(peerId);
          }
          call.check();
        }, ACK_MS);
      };
      arm();
      /*
       * Where Sluka's worker lives in a frame of one of the windows (the end of
       * this file), it changes hands when that window is closed.  What was sent
       * to the worker and never reached it is sent again to the one that comes
       * up next, as a browser holds a message for a worker it is still starting.
       * What the old worker had taken up is not: that fails, as it always has.
       */
      let moves = 0;
      call.again = BOOT.shell === 'browser' && !to ? () => {
        if (moves++ >= 2) {
          call.check();
          return;
        }
        call.moving = true;
        clearTimeout(call.timer);
        whenBackground().then(() => {
          call.moving = false;
          if (!calls.has(id)) return;
          const worker = backgroundPeer();
          if (!worker?.hasMsg) {
            call.check();
            return;
          }
          call.waiting.add(worker.id);
          arm();
          post({ k: 'msg', id, from: describe(), to: null, only: worker.id, data: payload });
        });
      } : null;
      calls.set(id, call);
      post({ k: 'msg', id, from: describe(), to: to || null, data: payload });
    });
  }

  function dropPeerFromCalls(peerId, role) {
    for (const call of [...calls.values()]) {
      const had = call.waiting.delete(peerId);
      const claimed = call.claimed.delete(peerId);
      if (claimed && !call.waiting.size && !call.claimed.size) call.fail(PORT_CLOSED);
      else if (had && role === 'background' && call.again) call.again();
      else if (had) call.check();
    }
  }

  const probes = new Map();
  function probe(peerId) {
    if (!peers.has(peerId) || probes.has(peerId)) return;
    probes.set(peerId, setTimeout(() => {
      probes.delete(peerId);
      forget(peerId);
    }, PING_MS));
    post({ k: 'ping', from: describe(), to: peerId });
  }

  function receive(m) {
    if (!onMessage.size) {
      post({ k: 'ack', id: m.id, by: me.id, claimed: false });
      return;
    }
    let answered = false;
    const sendResponse = (value) => {
      if (answered) return;
      answered = true;
      let data;
      try {
        data = wire(value);
      } catch (err) {
        console.error('[sluka-desktop] an answer could not be sent', err);
      }
      post({ k: 'resp', id: m.id, by: me.id, data });
    };
    const results = onMessage.dispatch(m.data, senderOf(m.from), sendResponse);
    if (answered) return;
    const keeps = results.some((r) => r === true);
    const promised = results.filter((r) => r && typeof r.then === 'function');
    if (!keeps && !promised.length) {
      post({ k: 'ack', id: m.id, by: me.id, claimed: false });
      return;
    }
    post({ k: 'ack', id: m.id, by: me.id, claimed: true });
    if (keeps) return;
    // A listener that answered with a promise: its value is the answer, and
    // one that comes to nothing lets the message go.
    let left = promised.length;
    for (const p of promised) {
      p.then(
        (value) => {
          left--;
          if (value !== undefined) sendResponse(value);
          else if (!left && !answered) post({ k: 'drop', id: m.id, by: me.id });
        },
        (err) => {
          left--;
          if (!answered) post({ k: 'fail', id: m.id, by: me.id, error: String(err?.message || err) });
          answered = true;
        },
      );
    }
  }

  // ------------------------------------------------------------ ports

  /** Open ports of this context, by id. */
  const ports = new Map();

  function makePort({ portId, name, sender, opener }) {
    // `held` is what was posted before the far ends were told of the port:
    // a page posts to a port in the same breath as it opens it.
    const state = { open: true, ends: new Set(), accepted: false, held: opener ? [] : null };
    const port = {
      name,
      sender,
      onMessage: new Event(),
      onDisconnect: new Event(),
      postMessage(message) {
        if (!state.open) throw new Error('Attempting to use a disconnected port object');
        const m = { k: 'port', portId, by: me.id, opener, data: wire(message) };
        if (state.held) state.held.push(m);
        else post(m);
      },
      disconnect() {
        if (!state.open) return;
        state.open = false;
        ports.delete(portId);
        post({ k: 'disc', portId, by: me.id, opener });
      },
    };
    const entry = { port, state, opener };
    /** The far end is gone: said once, with the browser's reason where there is one. */
    entry.closed = (reason) => {
      if (!state.open) return;
      state.open = false;
      ports.delete(portId);
      lastError = reason ? { message: reason } : undefined;
      try {
        port.onDisconnect.dispatch(port);
      } finally {
        lastError = undefined;
      }
    };
    ports.set(portId, entry);
    return entry;
  }

  function connect(to, info = {}) {
    const portId = uid();
    const entry = makePort({ portId, name: String(info?.name || ''), sender: undefined, opener: true });
    (async () => {
      await settled;
      if (!to) await whenBackground();
      if (!entry.state.open) return;
      /*
       * Who the port goes to is settled here, as a browser settles it: several
       * contexts may take one port, and its opener hears "disconnected" only
       * when the last of them has let go -- not when the first one that had no
       * use for it does, before the one that wanted it has said so.
       */
      const audience = [...peers.values()].filter((p) => p.hasConn && reaches(to, p));
      if (!audience.length) {
        // Nobody to take it: the browser closes such a port with these words.
        entry.closed(NO_RECEIVER);
        return;
      }
      for (const p of audience) entry.state.ends.add(p.id);
      post({ k: 'conn', portId, name: entry.port.name, from: describe(), ends: audience.map((p) => p.id) });
      const held = entry.state.held;
      entry.state.held = null;
      for (const m of held) post(m);
    })();
    return entry.port;
  }

  function accept(m) {
    if (!onConnect.size) {
      post({ k: 'conn-no', portId: m.portId, by: me.id });
      return;
    }
    const entry = makePort({ portId: m.portId, name: m.name, sender: senderOf(m.from), opener: false });
    entry.state.ends.add(m.from.id);
    post({ k: 'conn-ok', portId: m.portId, by: me.id });
    onConnect.dispatch(entry.port);
  }

  function dropPeerFromPorts(peerId) {
    for (const entry of [...ports.values()]) {
      if (!entry.state.ends.delete(peerId)) continue;
      if (!entry.state.ends.size) entry.closed(entry.opener && !entry.state.accepted ? NO_RECEIVER : undefined);
    }
  }

  // ------------------------------------------------------------ tab control

  /** What another context asked this tab to do with itself. */
  function control(m) {
    // A page outside the app is not the app's to move or close.
    if (REMOTE || me.role !== 'tab' || m.tabId !== me.tabId) return;
    switch (m.op) {
      case 'navigate':
        if (typeof m.url === 'string') location.href = m.url;
        break;
      case 'reload':
        location.reload();
        break;
      case 'back':
        history.back();
        break;
      case 'forward':
        history.forward();
        break;
      case 'close':
        window.close();
        break;
      default:
    }
  }

  /** chrome.tabs.create and chrome.windows.create waiting for their page to say hello. */
  const opens = [];
  function settleOpens(info) {
    const at = opens.findIndex((o) => info.born >= o.at - 50 && samePage(o.url, info.url));
    if (at < 0) return;
    const [open] = opens.splice(at, 1);
    clearTimeout(open.timer);
    open.resolve(info);
  }
  const samePage = (a, b) => {
    try {
      return new URL(a).pathname === new URL(b).pathname;
    } catch {
      return a === b;
    }
  };

  // ------------------------------------------------------------ storage

  const storageOnChanged = new Event();
  const areas = {};

  function fireStorage(area, changes) {
    areas[area]?.onChanged.dispatch(changes);
    storageOnChanged.dispatch(changes, area);
  }

  function changesOf(oldRaw, newRaw) {
    const changes = {};
    const keys = new Set([...Object.keys(oldRaw || {}), ...Object.keys(newRaw || {})]);
    for (const key of keys) {
      const before = oldRaw?.[key];
      const after = newRaw?.[key];
      if (before === after) continue;
      const change = {};
      if (before !== undefined) change.oldValue = JSON.parse(before);
      if (after !== undefined) change.newValue = JSON.parse(after);
      changes[key] = change;
    }
    return changes;
  }

  function tell(area, changes) {
    if (!Object.keys(changes).length) return;
    // To the others first: this context's listeners may write again at once.
    post({ k: 'storage', area, changes });
    fireStorage(area, changes);
  }

  function makeArea(area) {
    const parse = (items) => {
      const out = {};
      for (const [key, raw] of Object.entries(items || {})) {
        try {
          out[key] = JSON.parse(raw);
        } catch {
          /* a value that was never JSON is not a value */
        }
      }
      return out;
    };
    const self = {
      onChanged: new Event(),
      QUOTA_BYTES: area === 'session' ? 10485760 : 5242880 * 1024,
      get: callbackOrPromise(async (keys) => {
        let ask = null;
        let defaults = null;
        if (typeof keys === 'string') ask = [keys];
        else if (Array.isArray(keys)) ask = keys.map(String);
        else if (keys && typeof keys === 'object') {
          defaults = keys;
          ask = Object.keys(keys);
        }
        if (ask && !ask.length) return {};
        const { items } = await api('storage', { area, op: 'get', keys: ask });
        const got = parse(items);
        if (defaults) {
          for (const [key, value] of Object.entries(defaults)) {
            if (!(key in got) && value !== undefined) got[key] = wire(value);
          }
        }
        return got;
      }),
      set: callbackOrPromise(async (items) => {
        if (!items || typeof items !== 'object') throw new TypeError('Expected an object of items to set');
        const raw = {};
        for (const [key, value] of Object.entries(items)) {
          const text = JSON.stringify(value);
          if (text !== undefined) raw[key] = text;
        }
        if (!Object.keys(raw).length) return;
        const { old } = await api('storage', { area, op: 'set', items: raw }, { lasting: true });
        tell(area, changesOf(old, { ...old, ...raw }));
      }),
      remove: callbackOrPromise(async (keys) => {
        const list = (Array.isArray(keys) ? keys : [keys]).map(String);
        if (!list.length) return;
        const { old } = await api('storage', { area, op: 'remove', keys: list }, { lasting: true });
        tell(area, changesOf(old, {}));
      }),
      clear: callbackOrPromise(async () => {
        const { old } = await api('storage', { area, op: 'clear' }, { lasting: true });
        tell(area, changesOf(old, {}));
      }),
      getBytesInUse: callbackOrPromise(async (keys) => {
        const ask = keys == null ? null : (Array.isArray(keys) ? keys : [keys]).map(String);
        return (await api('storage', { area, op: 'bytes', keys: ask })).bytes || 0;
      }),
      getKeys: callbackOrPromise(async () => (await api('storage', { area, op: 'keys' })).keys || []),
      setAccessLevel: callbackOrPromise(async () => {}),
    };
    areas[area] = self;
    return self;
  }

  // ------------------------------------------------------------ downloads

  const downloadsOnChanged = new Event();
  const downloadsOnCreated = new Event();
  const downloadsOnErased = new Event();

  /** The most of a file sent to the host in one request. */
  const PIECE_BYTES = 8 * 1024 * 1024;

  /**
   * `blob` to the host, which writes it under the name in `query`.  As plain
   * bytes rather than the blob itself, and in pieces: a web view hands a custom
   * address the bytes of a request but not always a blob behind it, and a film
   * read whole would be held in memory twice.
   */
  async function upload(blob, query) {
    if (blob.size <= PIECE_BYTES) {
      return api('download', null, { raw: new Uint8Array(await blob.arrayBuffer()), query });
    }
    const { token } = await api('download', null, { raw: new Uint8Array(0), query: `${query}&stage=begin` });
    for (let at = 0; at < blob.size; at += PIECE_BYTES) {
      const piece = new Uint8Array(await blob.slice(at, at + PIECE_BYTES).arrayBuffer());
      await api('download', null, { raw: piece, query: `?stage=piece&token=${encodeURIComponent(token)}&at=${at}` });
    }
    return api('download', null, { raw: new Uint8Array(0), query: `?stage=end&token=${encodeURIComponent(token)}` });
  }

  async function download(options = {}) {
    const url = String(options.url || '');
    if (!url) throw new Error('Invalid URL');
    let blob;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      blob = await res.blob();
    } catch (err) {
      throw new Error(`Download failed: ${err?.message || err}`);
    }
    const name = options.filename || (() => {
      try {
        return decodeURIComponent(new URL(url).pathname.split('/').pop() || 'download');
      } catch {
        return 'download';
      }
    })();
    const query = `?filename=${encodeURIComponent(name)}&conflict=${encodeURIComponent(options.conflictAction || 'uniquify')}`;
    const got = await upload(blob, query);
    const deltas = got.error
      ? [{ id: got.id, error: { current: got.error }, state: { previous: 'in_progress', current: 'interrupted' } }]
      : [
        { id: got.id, filename: { previous: '', current: got.filename } },
        { id: got.id, state: { previous: 'in_progress', current: 'complete' } },
      ];
    // After the id has been handed back, as a browser tells of a download once it has started it.
    setTimeout(() => {
      for (const delta of deltas) {
        post({ k: 'dl', delta });
        downloadsOnChanged.dispatch(delta);
      }
    }, 0);
    return got.id;
  }

  // ------------------------------------------------------------ alarms

  const alarms = new Map();
  const onAlarm = new Event();

  function armAlarm(name, info = {}) {
    clearAlarm(name);
    const period = Number(info.periodInMinutes) > 0 ? Number(info.periodInMinutes) : null;
    const first = info.when != null
      ? Math.max(0, Number(info.when) - Date.now())
      : (Number(info.delayInMinutes) >= 0 && info.delayInMinutes != null ? Number(info.delayInMinutes) : period || 0) * 60000;
    const alarm = { name, scheduledTime: Date.now() + first, periodInMinutes: period || undefined, timer: null };
    const fire = () => {
      const told = { name, scheduledTime: alarm.scheduledTime, periodInMinutes: alarm.periodInMinutes };
      if (period) {
        alarm.scheduledTime = Date.now() + period * 60000;
        alarm.timer = setTimeout(fire, period * 60000);
      } else {
        alarms.delete(name);
      }
      onAlarm.dispatch(told);
    };
    alarm.timer = setTimeout(fire, first);
    alarms.set(name, alarm);
  }
  function clearAlarm(name) {
    const alarm = alarms.get(name);
    if (!alarm) return false;
    clearTimeout(alarm.timer);
    alarms.delete(name);
    return true;
  }
  const publicAlarm = (a) => a && { name: a.name, scheduledTime: a.scheduledTime, periodInMinutes: a.periodInMinutes };

  // ------------------------------------------------------------ the bus, heard

  bus.onmessage = (event) => {
    const m = event.data;
    if (!m || typeof m !== 'object') return;
    switch (m.k) {
      case 'hello':
        learn(m.from, true);
        // Two windows cannot be the same tab: one opened from another starts with a copy of its number.
        if (isTabTop(m.from) && me.role === 'tab' && me.frameId === 0 && m.from.tabId === me.tabId && m.from.born >= me.born) {
          post({ k: 'clash', to: m.from.id });
        }
        post({ k: 'here', from: describe(), to: m.from.id });
        break;
      case 'here':
        if (m.to === me.id) learn(m.from, false);
        break;
      case 'info':
        learn(m.from, false);
        break;
      case 'bye':
        forget(m.from.id);
        break;
      case 'clash':
        if (m.to === me.id && me.role === 'tab' && me.frameId === 0) {
          post({ k: 'bye', from: describe() });
          me.tabId = sessionTabId(true);
          me.born = Date.now();
          announce('hello');
          hello();
        }
        break;
      case 'ping':
        if (m.to === me.id) post({ k: 'pong', by: me.id, to: m.from.id });
        break;
      case 'pong':
        if (m.to === me.id) {
          clearTimeout(probes.get(m.by));
          probes.delete(m.by);
        }
        break;
      case 'msg':
        if (m.from.id !== me.id && reaches(m.to, me) && (!m.only || m.only === me.id)) receive(m);
        break;
      case 'ack': {
        const call = calls.get(m.id);
        if (!call) break;
        call.waiting.delete(m.by);
        if (m.claimed) call.claimed.add(m.by);
        call.check();
        break;
      }
      case 'resp':
        calls.get(m.id)?.done(m.data);
        break;
      case 'drop': {
        const call = calls.get(m.id);
        if (!call) break;
        call.claimed.delete(m.by);
        call.waiting.delete(m.by);
        call.check();
        break;
      }
      case 'fail':
        calls.get(m.id)?.fail(m.error || PORT_CLOSED);
        break;
      case 'conn':
        if (m.from.id !== me.id && m.ends?.includes(me.id)) accept(m);
        break;
      case 'conn-ok': {
        const entry = ports.get(m.portId);
        if (entry?.opener) entry.state.accepted = true;
        break;
      }
      case 'conn-no': {
        const entry = ports.get(m.portId);
        if (!entry?.opener) break;
        entry.state.ends.delete(m.by);
        if (!entry.state.ends.size) entry.closed(entry.state.accepted ? undefined : NO_RECEIVER);
        break;
      }
      case 'port': {
        const entry = ports.get(m.portId);
        // From the far side only: every end of a port hears the channel.
        if (!entry || !entry.state.open || m.by === me.id || m.opener === entry.opener) break;
        entry.port.onMessage.dispatch(m.data, entry.port);
        break;
      }
      case 'disc': {
        const entry = ports.get(m.portId);
        if (!entry || m.by === me.id || m.opener === entry.opener) break;
        entry.state.ends.delete(m.by);
        // An opener hears it once every end that took the port has let go.
        if (!entry.opener || !entry.state.ends.size) entry.closed();
        break;
      }
      case 'storage':
        fireStorage(m.area, m.changes);
        break;
      case 'dl':
        downloadsOnChanged.dispatch(m.delta);
        break;
      case 'ctl':
        control(m);
        break;
      case 'probe': {
        // For the self-test: how long a timer of a tenth of a second takes here.
        // An engine slows the timers of a page that is not on screen.
        if (m.role !== me.role || me.frameId !== 0) break;
        const asked = performance.now();
        setTimeout(() => {
          post({ k: 'probed', id: m.id, to: m.from, by: me.id, role: me.role, ms: Math.round(performance.now() - asked), hidden: document.hidden });
        }, 100);
        break;
      }
      case 'probed':
        if (m.to === me.id) timerProbes.get(m.id)?.(m);
        break;
      default:
    }
  };

  /** Asks the page of `role` to time a timer; what it found, or null if nothing answered in `wait` ms. */
  const timerProbes = new Map();
  function probe(role, wait = 6000) {
    const id = uid();
    return new Promise((resolve) => {
      const done = (found) => {
        timerProbes.delete(id);
        resolve(found);
      };
      timerProbes.set(id, done);
      setTimeout(() => done(null), wait);
      post({ k: 'probe', id, role, from: me.id });
    });
  }

  // ------------------------------------------------------------ chrome.*

  const runtimeOnInstalled = new Event();
  const runtimeOnStartup = new Event();

  const contextType = (p) => ({ tab: 'TAB', frame: 'TAB', background: 'BACKGROUND', offscreen: 'OFFSCREEN_DOCUMENT', popup: 'POPUP' }[p.role] || 'TAB');

  const runtime = {
    id: EXT_ID,
    getURL: (path = '') => BASE + String(path).replace(/^\/+/, ''),
    getManifest: () => wire(MANIFEST),
    sendMessage(...args) {
      const callback = typeof args.at(-1) === 'function' ? args.pop() : null;
      // (extensionId, message, options?) or (message, options?)
      const message = typeof args[0] === 'string' && (args.length === 3 || (args.length === 2 && args[0] === EXT_ID))
        ? args[1]
        : args[0];
      const promise = send(null, message);
      if (!callback) return promise;
      promise.then(
        (value) => callback(value),
        (err) => {
          lastError = { message: String(err?.message || err) };
          try {
            callback();
          } finally {
            lastError = undefined;
          }
        },
      );
      return undefined;
    },
    onMessage,
    connect(...args) {
      const info = args.find((a) => a && typeof a === 'object') || {};
      return connect(null, info);
    },
    onConnect,
    onInstalled: runtimeOnInstalled,
    onStartup: runtimeOnStartup,
    onSuspend: new Event(),
    onUpdateAvailable: new Event(),
    getPlatformInfo: callbackOrPromise(async () => ({ os: 'linux', arch: 'x86-64', nacl_arch: 'x86-64' })),
    /*
     * Firefox's own call, and the one Sluka asks to learn that the browser
     * gives it no folder picker (lib/downloads-folder.js).  Nor does this app,
     * so backups, books and films are written through chrome.downloads into
     * the app's own downloads folder, exactly as they are in Firefox.
     */
    getBrowserInfo: callbackOrPromise(async () => ({
      name: BOOT.app?.name || 'Sluka Desktop', vendor: 'sluka-desktop', version: BOOT.app?.version || '0', buildID: '0',
    })),
    getContexts: callbackOrPromise(async (filter = {}) => everyone()
      .map((p) => ({
        contextType: contextType(p),
        contextId: p.id,
        tabId: p.tabId ?? -1,
        windowId: p.tabId ?? -1,
        frameId: p.frameId || 0,
        documentId: p.id,
        documentUrl: p.url,
        documentOrigin: ORIGIN,
        incognito: false,
      }))
      .filter((c) => (!filter.contextTypes || filter.contextTypes.includes(c.contextType))
        && (!filter.documentUrls || filter.documentUrls.includes(c.documentUrl))
        && (!filter.tabIds || filter.tabIds.includes(c.tabId))
        && (!filter.windowIds || filter.windowIds.includes(c.windowId))
        && (!filter.contextIds || filter.contextIds.includes(c.contextId)))),
    openOptionsPage: callbackOrPromise(async () => {
      await tabs.create({ url: runtime.getURL(MANIFEST.options_ui?.page || 'dashboard/dashboard.html') });
    }),
    setUninstallURL: callbackOrPromise(async () => {}),
    requestUpdateCheck: callbackOrPromise(async () => ({ status: 'no_update' })),
    reload() {
      location.reload();
    },
  };
  Object.defineProperty(runtime, 'lastError', { get: () => lastError, enumerable: true });

  const shell = (op, args = {}) => api('shell', { op, ...args }).catch((err) => {
    console.warn('[sluka-desktop] window call failed', op, err);
    return { ok: false };
  });

  const isOwn = (url) => {
    try {
      return new URL(url).origin === ORIGIN || String(url).startsWith(BASE);
    } catch {
      return false;
    }
  };

  /** Ask for a window on `url` and answer with the page that opened in it. */
  async function openPage(url, options = {}) {
    const at = Date.now();
    const landed = new Promise((resolve) => {
      const open = { url, at, resolve, timer: null };
      open.timer = setTimeout(() => {
        const i = opens.indexOf(open);
        if (i >= 0) opens.splice(i, 1);
        resolve(null);
      }, 12000);
      opens.push(open);
    });
    const done = await shell('open', { url, ...options });
    const settleNow = (info) => {
      const i = opens.findIndex((o) => o.at === at && o.url === url);
      if (i < 0) return;
      const [open] = opens.splice(i, 1);
      clearTimeout(open.timer);
      open.resolve(info);
    };
    // The window manager brought forward a window it already had on this page.
    if (done?.reusedTabId != null) settleNow(findTab(done.reusedTabId));
    // No window manager (the app run from a plain browser): the browser opens it.
    else if (done && done.handled === false) {
      try {
        window.open(url, '_blank', options.kind === 'popup' ? `popup,noopener,width=${options.width || 480},height=${options.height || 640}` : 'noopener');
      } catch {
        settleNow(null);
      }
    }
    return landed;
  }

  let fakeIds = -1000;
  const fakeTab = (url) => {
    const id = fakeIds--;
    return { id, windowId: id, index: 0, url, title: '', active: false, highlighted: false, pinned: false, incognito: false, status: 'complete' };
  };

  const tabs = {
    TAB_ID_NONE: -1,
    query: callbackOrPromise(async (q = {}) => {
      const focused = lastFocusedTab();
      let list = tabPeers();
      if (q.currentWindow || q.lastFocusedWindow) {
        const here = me.role === 'tab' || me.role === 'frame' ? me.tabId : focused?.tabId;
        list = list.filter((p) => p.tabId === here);
      }
      if (q.windowId != null && q.windowId >= 0) list = list.filter((p) => p.tabId === q.windowId);
      // The pages here make no sound a browser would report; a film on the videos page tells Sluka itself.
      if (q.audible === true) list = [];
      if (q.url) {
        const patterns = (Array.isArray(q.url) ? q.url : [q.url]).map(matchPattern);
        list = list.filter((p) => patterns.some((re) => re.test(p.url)));
      }
      if (q.status && q.status !== 'complete') list = [];
      return list.map(tabOf);
    }),
    get: callbackOrPromise(async (tabId) => {
      const found = tabOf(findTab(tabId));
      if (!found) throw new Error(`No tab with id: ${tabId}.`);
      return found;
    }),
    getCurrent: callbackOrPromise(async () => (me.role === 'tab' || me.role === 'frame' ? tabOf(findTab(me.tabId)) || undefined : undefined)),
    create: callbackOrPromise(async (props = {}) => {
      const url = new URL(props.url || MANIFEST.options_ui?.page || 'dashboard/dashboard.html', BASE).href;
      if (!isOwn(url)) {
        await shell('external', { url });
        return fakeTab(url);
      }
      const info = await openPage(url, { kind: 'tab', active: props.active !== false });
      return tabOf(info) || fakeTab(url);
    }),
    update: callbackOrPromise(async (...args) => {
      const props = args.find((a) => a && typeof a === 'object') || {};
      const tabId = typeof args[0] === 'number' ? args[0] : (me.tabId ?? lastFocusedTab()?.tabId);
      const target = findTab(tabId);
      if (!target) throw new Error(`No tab with id: ${tabId}.`);
      if (typeof props.url === 'string') {
        const url = new URL(props.url, BASE).href;
        if (isOwn(url)) {
          if (tabId === me.tabId && me.role === 'tab') location.href = url;
          else post({ k: 'ctl', tabId, op: 'navigate', url });
        } else {
          await shell('external', { url });
        }
      }
      if (props.active || props.highlighted) await shell('focus', { tabId });
      return tabOf(target);
    }),
    remove: callbackOrPromise(async (ids) => {
      for (const tabId of Array.isArray(ids) ? ids : [ids]) {
        if (!findTab(tabId)) continue;
        const done = await shell('close', { tabId });
        // No window manager behind this page: the tab is asked to close itself.
        if (!done?.handled) post({ k: 'ctl', tabId, op: 'close' });
        if (!done?.handled && tabId === me.tabId) window.close();
      }
    }),
    reload: callbackOrPromise(async (...args) => {
      const tabId = typeof args[0] === 'number' ? args[0] : me.tabId;
      if (tabId === me.tabId && me.role === 'tab') location.reload();
      else post({ k: 'ctl', tabId, op: 'reload' });
    }),
    goBack: callbackOrPromise(async (tabId = me.tabId) => {
      post({ k: 'ctl', tabId, op: 'back' });
      if (tabId === me.tabId) history.back();
    }),
    goForward: callbackOrPromise(async (tabId = me.tabId) => {
      post({ k: 'ctl', tabId, op: 'forward' });
      if (tabId === me.tabId) history.forward();
    }),
    sendMessage(tabId, message, ...rest) {
      const callback = typeof rest.at(-1) === 'function' ? rest.pop() : null;
      const options = rest.find((a) => a && typeof a === 'object') || {};
      const to = { tabId, frameId: Number.isInteger(options.frameId) ? options.frameId : null };
      const promise = send(to, message);
      if (!callback) return promise;
      promise.then(
        (value) => callback(value),
        (err) => {
          lastError = { message: String(err?.message || err) };
          try {
            callback();
          } finally {
            lastError = undefined;
          }
        },
      );
      return undefined;
    },
    connect(tabId, info = {}) {
      return connect({ tabId, frameId: Number.isInteger(info?.frameId) ? info.frameId : null }, info);
    },
    getZoom: callbackOrPromise(async () => 1),
    setZoom: callbackOrPromise(async () => {}),
    captureVisibleTab: callbackOrPromise(async () => {
      throw new Error('Pictures of the window are not available in Sluka Desktop.');
    }),
    onCreated: tabsOnCreated,
    onUpdated: tabsOnUpdated,
    onRemoved: tabsOnRemoved,
    onActivated: tabsOnActivated,
    onReplaced: tabsOnReplaced,
  };

  /** A match pattern (`https://www.lingq.com/*`) as a test of an address. */
  function matchPattern(pattern) {
    if (pattern === '<all_urls>') return /^(https?|file|ftp|chrome-extension):/;
    const escaped = String(pattern).replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
    return new RegExp(`^${escaped}$`);
  }

  const windows = {
    WINDOW_ID_NONE: -1,
    WINDOW_ID_CURRENT: -2,
    get: callbackOrPromise(async (windowId, options = {}) => {
      const id = windowId === -2 ? (me.tabId ?? lastFocusedTab()?.tabId) : windowId;
      const found = windowOf(findTab(id), !!options?.populate);
      if (!found) throw new Error(`No window with id: ${windowId}.`);
      return found;
    }),
    getCurrent: callbackOrPromise(async (options = {}) => {
      const found = windowOf(findTab(me.tabId) || lastFocusedTab(), !!options?.populate);
      if (!found) throw new Error('No current window');
      return found;
    }),
    getLastFocused: callbackOrPromise(async (options = {}) => {
      const found = windowOf(lastFocusedTab(), !!options?.populate);
      if (!found) throw new Error('No last-focused window');
      return found;
    }),
    getAll: callbackOrPromise(async (options = {}) => tabPeers().map((p) => windowOf(p, !!options?.populate))),
    create: callbackOrPromise(async (props = {}) => {
      const first = Array.isArray(props.url) ? props.url[0] : props.url;
      const url = new URL(first || 'dashboard/dashboard.html', BASE).href;
      if (!isOwn(url)) {
        await shell('external', { url });
        const tab = fakeTab(url);
        return { id: tab.id, focused: false, type: 'normal', state: 'normal', tabs: [tab] };
      }
      const bounds = {};
      for (const key of ['left', 'top', 'width', 'height']) if (Number.isFinite(props[key])) bounds[key] = Math.round(props[key]);
      const info = await openPage(url, { kind: props.type === 'popup' ? 'popup' : 'window', state: props.state, focused: props.focused !== false, ...bounds });
      if (!info) {
        const tab = fakeTab(url);
        return { id: tab.id, focused: false, type: props.type || 'normal', state: 'normal', tabs: [tab] };
      }
      return { ...windowOf(info, true), type: props.type || 'normal' };
    }),
    update: callbackOrPromise(async (windowId, props = {}) => {
      const id = windowId === -2 ? me.tabId : windowId;
      const target = findTab(id);
      if (!target) throw new Error(`No window with id: ${windowId}.`);
      const bounds = {};
      for (const key of ['left', 'top', 'width', 'height']) if (Number.isFinite(props[key])) bounds[key] = Math.round(props[key]);
      if (props.state || Object.keys(bounds).length) await shell('state', { tabId: id, state: props.state, ...bounds });
      if (props.focused || props.drawAttention) await shell('focus', { tabId: id });
      return windowOf(target);
    }),
    remove: callbackOrPromise(async (windowId) => tabs.remove(windowId)),
    onCreated: windowsOnCreated,
    onRemoved: windowsOnRemoved,
    onFocusChanged: windowsOnFocusChanged,
  };

  const resolved = (value) => callbackOrPromise(async () => value);
  const noPage = callbackOrPromise(async () => {
    // What a browser says of an extension's own page, which is all there is here.
    throw new Error('Cannot access contents of the page. Extension manifest must request permission to access the respective host.');
  });

  const chrome = {
    runtime,
    storage: {
      local: makeArea('local'),
      session: makeArea('session'),
      sync: makeArea('sync'),
      onChanged: storageOnChanged,
    },
    tabs,
    windows,
    alarms: {
      create: callbackOrPromise(async (...args) => {
        const info = args.find((a) => a && typeof a === 'object') || {};
        armAlarm(typeof args[0] === 'string' ? args[0] : '', info);
      }),
      get: callbackOrPromise(async (name = '') => publicAlarm(alarms.get(name)) || undefined),
      getAll: callbackOrPromise(async () => [...alarms.values()].map(publicAlarm)),
      clear: callbackOrPromise(async (name = '') => clearAlarm(name)),
      clearAll: callbackOrPromise(async () => {
        const had = alarms.size > 0;
        for (const name of [...alarms.keys()]) clearAlarm(name);
        return had;
      }),
      onAlarm,
    },
    downloads: {
      download: callbackOrPromise(download),
      search: callbackOrPromise(async (query = {}) => (await api('downloads', { op: 'search', query })).items || []),
      removeFile: callbackOrPromise(async (id) => {
        await api('downloads', { op: 'removeFile', id });
      }),
      erase: callbackOrPromise(async (query = {}) => {
        if (!Number.isInteger(query.id)) return [];
        await api('downloads', { op: 'erase', id: query.id }).catch(() => {});
        downloadsOnErased.dispatch(query.id);
        return [query.id];
      }),
      show: () => {},
      showDefaultFolder: () => {},
      onChanged: downloadsOnChanged,
      onCreated: downloadsOnCreated,
      onErased: downloadsOnErased,
    },
    action: {
      setBadgeText: resolved(undefined),
      setBadgeBackgroundColor: resolved(undefined),
      setBadgeTextColor: resolved(undefined),
      setTitle: resolved(undefined),
      setIcon: resolved(undefined),
      setPopup: resolved(undefined),
      getBadgeText: resolved(''),
      enable: resolved(undefined),
      disable: resolved(undefined),
      onClicked: new Event(),
    },
    scripting: {
      executeScript: noPage,
      insertCSS: noPage,
      removeCSS: noPage,
      registerContentScripts: resolved(undefined),
      unregisterContentScripts: resolved(undefined),
      getRegisteredContentScripts: resolved([]),
    },
    permissions: {
      contains: resolved(true),
      request: resolved(true),
      remove: resolved(false),
      getAll: callbackOrPromise(async () => ({ permissions: MANIFEST.permissions || [], origins: MANIFEST.host_permissions || [] })),
      onAdded: new Event(),
      onRemoved: new Event(),
    },
    i18n: {
      getUILanguage: () => navigator.language || 'en',
      getMessage: () => '',
      getAcceptLanguages: callbackOrPromise(async () => [...(navigator.languages || ['en'])]),
    },
    extension: {
      inIncognitoContext: false,
      isAllowedIncognitoAccess: resolved(false),
      isAllowedFileSchemeAccess: resolved(false),
    },
  };

  if (REMOTE) {
    // The page's engine may have a `chrome` of its own with other things in it: Sluka's is added to it.
    let target = null;
    try {
      target = typeof globalThis.chrome === 'object' && globalThis.chrome ? Object.assign(globalThis.chrome, chrome) : null;
    } catch {
      target = null;
    }
    if (!target || target.runtime !== runtime) Object.defineProperty(globalThis, 'chrome', { value: chrome, configurable: true, writable: true });
  } else {
    globalThis.chrome = chrome;
  }

  // ------------------------------------------------------------ this page, kept up to date

  function hello() {
    // The host keeps a window for each of the app's own tabs; a page outside the app has its own.
    if (REMOTE || me.role !== 'tab') return;
    api('hello', { tabId: me.tabId, role: me.role, url: location.href, title: document.title || '' }).catch(() => {});
  }

  function noteFocus(focused) {
    if (me.role !== 'tab' || me.focused === focused) return;
    me.focused = focused;
    if (focused) {
      me.focusedAt = Date.now();
      windowsOnFocusChanged.dispatch(me.tabId);
    }
    announce();
  }
  addEventListener('focus', () => noteFocus(true));
  addEventListener('blur', () => noteFocus(false));
  addEventListener('hashchange', () => announce());
  addEventListener('popstate', () => announce());
  addEventListener('pagehide', () => post({ k: 'bye', from: describe() }));
  addEventListener('pageshow', (e) => {
    // Back to a page the engine kept whole: it never said hello again.
    if (e.persisted) {
      announce('hello');
      hello();
    }
  });
  addEventListener('DOMContentLoaded', () => {
    const title = document.querySelector('title');
    if (title) new MutationObserver(() => announce()).observe(title, { childList: true, characterData: true, subtree: true });
    announce();
    hello();
  });
  let resizeTimer = null;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => announce(), 400);
  });

  try {
    me.focused = me.role === 'tab' && document.hasFocus();
    if (me.focused) me.focusedAt = Date.now();
  } catch {
    /* not yet */
  }
  announce('hello');
  hello();

  // Books, dictionaries and films live in the engine's own storage: ask that it be kept.
  try {
    if (!REMOTE) navigator.storage?.persist?.().catch(() => {});
  } catch {
    /* not offered */
  }

  if (REMOTE) {
    REMOTE.listen(
      (message) => bus.onmessage?.({ data: message }),
      // The app is there (again): whoever was known before may be gone, and everyone is greeted anew.
      () => {
        for (const id of [...peers.keys()]) forget(id);
        announce('hello');
      },
    );
  }

  // ------------------------------------------------------------ what went wrong, written down

  let logged = 0;
  let logWindow = Date.now();
  function report(level, text) {
    // In somebody else's page only what is Sluka's is written down: the page's own troubles are its own.
    if (REMOTE && !/sluka/i.test(String(text))) return;
    const now = Date.now();
    if (now - logWindow > 60000) {
      logWindow = now;
      logged = 0;
    }
    if (++logged > 40) return;
    api('log', { level, text: String(text).slice(0, 4000), url: location.pathname + location.hash }).catch(() => {});
  }
  const say = (args) => args.map((a) => {
    if (a instanceof Error) return `${a.name}: ${a.message}${a.stack ? `\n${a.stack}` : ''}`;
    if (typeof a === 'string') return a;
    try {
      return JSON.stringify(a);
    } catch {
      return String(a);
    }
  }).join(' ');
  /** Why a video or sound could not be played, as the engine numbers its reasons. */
  const MEDIA_ERRORS = { 1: 'stopped', 2: 'could not be read', 3: 'could not be decoded', 4: 'a format this engine has no decoder for' };
  let mediaTold = 0;
  addEventListener('error', (e) => {
    if (e.message) {
      report('error', `${e.message} (${e.filename || ''}:${e.lineno || 0})`);
      return;
    }
    const el = e.target;
    if (!el || el === window) return;
    if (typeof HTMLMediaElement === 'function' && el instanceof HTMLMediaElement) {
      const err = el.error;
      const from = String(el.currentSrc || el.src || '').startsWith('blob:') ? 'a file' : (el.currentSrc || el.src || 'nothing');
      report('error', `${el.tagName.toLowerCase()} from ${from}: ${MEDIA_ERRORS[err?.code] || 'failed'}${err?.message ? ` (${err.message})` : ''}`);
      /*
       * A film the engine cannot play is one mpv can.  The app is told, and
       * offers it: it knows which file the page was given, the page does not.
       */
      const local = from === 'a file';
      if (!REMOTE && local && el.tagName === 'VIDEO' && (err?.code === 3 || err?.code === 4) && me.role === 'tab' && me.frameId === 0 && Date.now() - mediaTold > 4000) {
        mediaTold = Date.now();
        api('shell', { op: 'media-failed', code: err.code }).catch(() => {});
      }
      return;
    }
    const address = String(el.src || el.href || '');
    if (REMOTE && !address.startsWith(BASE)) return;
    report('error', `failed to load ${address || el.tagName}`);
  }, true);
  addEventListener('unhandledrejection', (e) => report('error', `unhandled: ${say([e.reason])}`));
  for (const level of ['error', 'warn']) {
    const original = console[level].bind(console);
    console[level] = (...args) => {
      original(...args);
      try {
        report(level, say(args));
      } catch {
        /* the log is not worth a second error */
      }
    };
  }

  // ------------------------------------------------------------ for the app's own scripts

  globalThis.__slukaShim = {
    context: me,
    peers,
    api,
    Event,
    probe,
    /** True in the window that has Sluka's worker in a frame of its own (see the end of this file). */
    holdsBackground: false,
    /** The background page's modules have been evaluated: it can be sent to, and is told how it started. */
    async backgroundStarted() {
      if (me.role !== 'background') return;
      me.ready = true;
      announce();
      noteBackground();
      let start = { startup: true };
      try {
        start = await api('lifecycle', {});
      } catch (err) {
        console.error('[sluka-desktop] could not ask how the app started', err);
      }
      if (start.reason) {
        const details = { reason: start.reason };
        if (start.previousVersion) details.previousVersion = start.previousVersion;
        runtimeOnInstalled.dispatch(details);
      }
      if (start.startup) runtimeOnStartup.dispatch();
    },
  };

  // ------------------------------------------------------------ the worker, where no window can be hidden

  /*
   * A browser that lends the app its windows has none to hide Sluka's
   * background worker in.  There the worker runs wherever a lock the browser
   * keeps says: in a page of its own, if the app could make one nobody sees
   * (bg-ready.js asks for the lock there), and otherwise in a frame of one of
   * the open windows.  A window waits for the lock from the moment it opens;
   * when the holder is closed the next in line has it at once, and the worker
   * starts anew there -- as a browser's own worker does many times a day.
   *
   * The window that holds it also asks the app, over and over, whether to go
   * on.  The question is held open by the app, so it costs nothing, and is how
   * the app knows there is still a window.
   */
  const WORKER_LOCK = 'sluka-desktop:background';
  if (!REMOTE && BOOT.shell === 'browser' && isTop && me.role === 'tab' && navigator.locks?.request) {
    const settled = document.readyState === 'loading'
      ? new Promise((resolve) => addEventListener('DOMContentLoaded', resolve, { once: true }))
      : Promise.resolve();
    navigator.locks.request(WORKER_LOCK, async () => {
      await settled;
      globalThis.__slukaShim.holdsBackground = true;
      // Out of the page's own way: not in its body, and behind a door its scripts and styles cannot open.
      const holder = document.createElement('sluka-desktop-worker');
      holder.style.cssText = 'display:none !important';
      const frame = document.createElement('iframe');
      frame.src = `${BASE}__sluka__/background.html`;
      frame.title = 'Sluka background';
      try {
        holder.attachShadow({ mode: 'closed' }).append(frame);
      } catch {
        holder.append(frame);
      }
      document.documentElement.append(holder);
      for (;;) {
        const asked = Date.now();
        try {
          await api('shell', { op: 'alive' });
        } catch {
          /* the app is not answering: asked again below, a little later */
        }
        // Answered at once means nobody is holding the question open: not asked in a hurry, then.
        if (Date.now() - asked < 1000) await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    }).catch((err) => console.error('[sluka-desktop] this window could not take Sluka\'s background worker', err));
  }

  /*
   * The buttons that turn the floating subtitles on and off and open the game
   * text menu, in each of the app's own windows where the app has them
   * (dock.js): not in the worker's page, a frame, a page of the app's own
   * making, or Anki.
   */
  if (!REMOTE && BOOT.bar && isTop && me.role === 'tab' && !location.pathname.startsWith('/__sluka__/')) {
    const dock = document.createElement('script');
    dock.src = `${BASE}__sluka__/dock.js`;
    dock.async = true;
    (document.head || document.documentElement).append(dock);
  }

  /*
   * Settings → Dictionary → Your own dictionaries: a dictionary in a kind of file Sluka does not read itself made
   * into a Yomitan dictionary by the app first (owndicts.js, dictfiles.py).  Only in the dashboard, in the app.
   */
  if (!REMOTE && isTop && me.role === 'tab' && location.pathname.startsWith('/dashboard/')) {
    const own = document.createElement('script');
    own.src = `${BASE}__sluka__/owndicts.js`;
    own.async = true;
    (document.head || document.documentElement).append(own);
  }

  /*
   * A link to a website is the user's own browser's to open, as it is in the
   * app's other shells: the profile these windows run in is the app's alone.
   */
  if (!REMOTE && BOOT.shell === 'browser' && isTop) {
    const outside = (url) => /^(https?|mailto):/i.test(url) && !isOwn(url);
    addEventListener('click', (e) => {
      if (e.defaultPrevented || e.button !== 0) return;
      const link = e.composedPath?.().find((el) => el instanceof HTMLAnchorElement && el.href);
      if (!link || !outside(link.href)) return;
      e.preventDefault();
      shell('external', { url: link.href });
    }, false);
    const open = window.open;
    window.open = function slukaOpens(url, ...rest) {
      let address = '';
      try {
        address = url ? new URL(String(url), location.href).href : '';
      } catch {
        address = '';
      }
      if (address && outside(address)) {
        shell('external', { url: address });
        return null;
      }
      return open.call(window, url, ...rest);
    };
  }
})();
