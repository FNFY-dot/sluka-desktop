/*
 * A stand-in for the app, for dock.js in a plain page: shim.api answered here, the game text's state kept
 * here as gametext.py keeps it, and changed by the test through __S / __bump.
 *
 *   ?engine=broken   Sluka's engine with a file missing (an antivirus took it); "Look again" puts it back
 *   ?ocr=old         Sluka's own OCR cannot start here (an old C++ runtime): "auto" takes Windows' OCR
 */
(() => {
  const query = new URLSearchParams(location.search);
  globalThis.__SLUKA_BOOT__ = {
    bar: true,
    games: query.get('games') !== 'no',
    barButton: query.get('corner') || 'bottom-left',
    openShadow: true,
  };
  globalThis.__calls = [];
  let barOn = false;
  const ENGINE = {
    name: 'LunaHook', version: 'LunaTranslator 12.1.3.12', folder: 'C:\\Sluka\\engine',
    source: 'https://github.com/HIllya51/LunaTranslator/tree/v12.1.3.12', missing: [], error: '', kinds: [32, 64], running: false,
  };
  const broken = query.get('engine') === 'broken';
  const S = {
    version: 1,
    mode: query.get('mode') || 'game',
    settings: {
      mode: query.get('mode') || 'game', flush_ms: 500, codepage: 932, repeats: 'auto', join: true, codes: true, copy: false,
      auto_pick: true, auto_hook: true, skip_own: true, clip_most: 1000,
      ocr_engine: 'auto', ocr_mode: 'auto', ocr_interval_ms: 1500, ocr_lang: 'ja', ocr_vertical: 'auto', ocr_furigana: true,
      ocr_capture: 'screen', ocr_front: true,
      vision_engine: 'lens', vision_auto: true, vision_furigana: true, vision_capture: 'screen',
      vision_key_read: 'Alt+S', vision_key_auto: '', vision_key_clear: 'Alt+V', vision_key_pause: 'Alt+P', vision_key_freeze: 'Alt+F',
      lens_ok: false,
    },
    engine: broken
      ? { ...ENGINE, missing: ['LunaHook32.dll'], error: 'Some of the engine’s files are missing from C:\\Sluka\\engine: LunaHook32.dll. An antivirus (Windows Security) may have taken them away.' }
      : { ...ENGINE },
    game: null,
    threads: [],
    selected: [],
    picked: '',
    picking: 0,
    attach: null,
    clipboard: { watching: false, error: '' },
    last: { text: '', at: 0, from: '' },
    log: [],
    bar: { on: false, here: true },
    admin: false,
    choices: { flush: [50, 100, 200, 300, 500, 800, 1200, 2000], codepages: [932, 65001, 936, 950, 949, 0], intervals: [500, 1000, 1500] },
    suggested: null,
    screen: { active: false, running: false, error: '', engines: {}, auto: '', target: null, selecting: false,
      last: { text: '', engine: '', ms: 0, at: 0, lines: 0 }, excluded: null, kept: 0, listening: false,
      keys: { read: { key: '', error: '', held: false, note: '' }, select: { key: '', error: '', held: false, note: '' },
        once: { key: '', error: '', held: false, note: '' }, toggle: { key: '', error: '', held: false, note: '' } } },
    vision: { active: false, running: false, error: '', engines: {}, target: null, status: { state: '', text: '' }, picking: 0,
      shown: false, front: true, last: { at: 0, ms: 0, lines: 0, engine: '', why: '', text: '' }, page: false, excluded: null,
      keys: { read: { key: 'Alt+S', error: '', held: true, note: '' }, auto: { key: '', error: '', held: false, note: '' },
        clear: { key: 'Alt+V', error: '', held: true, note: '' }, pause: { key: 'Alt+P', error: '', held: true, note: '' },
        freeze: { key: 'Alt+F', error: '', held: true, note: '' } }, listening: false, frozen: '' },
  };
  // As hotkeys.py writes a key (a few of them).
  function keyName(vk) {
    if (vk >= 65 && vk <= 90) return String.fromCharCode(vk);
    if (vk >= 48 && vk <= 57) return String.fromCharCode(vk);
    if (vk >= 112 && vk <= 135) return `F${vk - 111}`;
    return { 32: 'Space', 19: 'Pause', 45: 'Insert' }[vk] || '';
  }
  const old = query.get('ocr') === 'old';
  const ENGINES = {
    builtin: old
      ? { ok: false, why: 'its ONNX Runtime needs Microsoft’s C++ runtime 14.40 or later, and this Python came with an older one (vcruntime140.dll 14.38.33135.0)' }
      : { ok: true, why: 'offline, in the engine folder: Japanese, Chinese and English (PP-OCRv5)' },
    windows: { ok: true, why: 'offline, Windows’ own; its languages here: 日本語, English (United States)', languages: [['ja', '日本語'], ['en-US', 'English (United States)']] },
    lens: { ok: true, why: 'online: each picture of the box is sent to Google' },
  };
  function lookAtReaders() {
    setTimeout(() => {
      S.screen.engines = JSON.parse(JSON.stringify(ENGINES));
      S.screen.auto = old ? 'windows' : 'builtin';
      bump();
    }, 80);
  }
  // As the app does: the Screen tab chosen before, the screen reader is running, and has looked.
  if (S.mode === 'screen') {
    S.screen.active = true;
    S.screen.running = true;
    lookAtReaders();
  }
  let waiting = [];
  const copy = () => JSON.parse(JSON.stringify(S));
  function bump() {
    S.version += 1;
    S.settings.mode = S.mode;
    const now = waiting;
    waiting = [];
    for (const answer of now) answer(copy());
  }
  globalThis.__S = S;
  globalThis.__bump = bump;
  const PROCESSES = [
    { pid: 4242, title: '桜の詩', exe: 'sakura.exe', path: 'C:\\Games\\Sakura\\sakura.exe', bits: 32, known: true, current: false },
    { pid: 77, title: 'Admin game', exe: 'admingame.exe', path: 'C:\\Games\\Admin\\admingame.exe', bits: 64, known: false, current: false },
  ];

  globalThis.__slukaShim = {
    api: async (name, body = {}) => {
      __calls.push([name, JSON.parse(JSON.stringify(body))]);
      switch (name) {
        case 'bar/status':
          return { on: barOn };
        case 'bar/toggle':
          barOn = !barOn;
          return { on: barOn };
        case 'games/state':
          if (body.brief) {
            return { version: S.version, mode: S.mode, game: S.game && { exe: S.game.exe, state: S.game.state }, selected: S.selected.length,
              engine: !S.engine.error, vision: { window: S.vision.target ? S.vision.target.title : '', status: S.vision.status.state } };
          }
          if (body.wait && body.since === S.version) return new Promise((answer) => waiting.push(answer));
          return copy();
        case 'games/mode':
          S.mode = body.mode;
          if (body.mode === 'clipboard') S.clipboard.watching = true;
          S.screen.active = body.mode === 'screen';
          S.screen.running = S.screen.active;
          if (S.screen.active) lookAtReaders();
          else S.screen.target = null;
          S.vision.active = body.mode === 'vision';
          S.vision.running = S.vision.active;
          bump();
          return { ok: true, mode: body.mode };
        case 'games/vision-engines':
          S.vision.engines = {
            lens: { ok: true, why: 'online: each picture of the box is sent to Google' },
            builtin: { ok: true, why: 'offline, in the engine folder' },
            windows: { ok: false, why: 'Windows has no OCR for ja here' },
          };
          bump();
          return { ok: true };
        case 'games/vision-pick':
          S.vision.picking = 10;
          bump();
          return { ok: true, picking: true };
        case 'games/vision-read':
        case 'games/vision-clear':
        case 'games/vision-forget':
          return { ok: true };
        case 'games/ocr-engines':
          lookAtReaders();
          return { ok: true };
        case 'games/ocr-keys-listen':
          S.screen.listening = !!body.on;
          bump();
          return { ok: true };
        case 'games/ocr-key': {
          S.screen.listening = false;
          const slot = S.screen.keys[body.action];
          if (body.clear) {
            Object.assign(slot, { key: '', error: '', held: false, note: '' });
            bump();
            return { ok: true, key: '' };
          }
          const name = keyName(body.vk);
          const mods = [['Ctrl', body.ctrl], ['Alt', body.alt], ['Shift', body.shift], ['Win', body.win]].filter(([, on]) => on).map(([m]) => m);
          const printable = !/^F\d+$|^Pause$|^Insert$/.test(name);
          if (!name) return { ok: false, error: 'that key cannot be one' };
          if (printable && !(body.ctrl || body.alt || body.win)) return { ok: false, error: `${name} alone types: take it with Ctrl or Alt` };
          const key = [...mods, name].join('+');
          const note = body.ctrl && body.alt && printable
            ? `${key}: Ctrl+Alt is AltGr on many keyboards, so AltGr+${name} types nothing while Sluka has it (Ctrl+Shift or Alt+Shift keep AltGr free)` : '';
          Object.assign(slot, { key, error: '', held: true, note });
          bump();
          return { ok: true, key };
        }
        case 'games/ocr-select':
          S.screen.selecting = true;
          bump();
          setTimeout(() => {
            S.screen.selecting = false;
            S.screen.target = { hwnd: 42420, pid: 4242, title: '桜の詩', class: 'GameWindow', exe: 'sakura.exe', box: [50, 350, 600, 110],
              client: [700, 500], state: 'watching', status: 'waiting', status_text: '', engine: S.settings.ocr_engine === 'auto' ? S.screen.auto : S.settings.ocr_engine,
              how: 'screen', since: Date.now() / 1000, error: '', kept: true };
            S.screen.last = { text: '今日はいい天気ですね\n散歩に行こうか', engine: S.screen.target.engine, ms: 140, at: Date.now() / 1000, lines: 2 };
            S.screen.excluded = true;
            S.screen.kept = 1;
            S.last = { text: '今日はいい天気ですね散歩に行こうか', at: Date.now() / 1000, from: 'screen' };
            bump();
          }, 400);
          return { ok: true };
        case 'games/ocr-cancel':
          S.screen.selecting = false;
          bump();
          return { ok: true };
        case 'games/ocr-once':
          S.screen.last = { ...S.screen.last, text: '空がとても青い', at: Date.now() / 1000 };
          bump();
          return { ok: true };
        case 'games/ocr-stop':
          S.screen.target.state = 'stopped';
          bump();
          return { ok: true };
        case 'games/ocr-start':
          S.screen.target.state = 'watching';
          bump();
          return { ok: true };
        case 'games/ocr-forget':
          S.screen.target.kept = false;
          S.screen.kept = 0;
          bump();
          return { ok: true };
        case 'games/processes':
          return { ok: true, processes: PROCESSES, admin: false };
        case 'games/rescan':
          if (S.mode === 'screen') lookAtReaders();
          if (S.engine.error && globalThis.__fixed) S.engine = { ...ENGINE };
          bump();
          return { ok: !S.engine.error, engine: S.engine };
        case 'games/attach': {
          const p = PROCESSES.find((x) => x.pid === body.pid);
          if (p.pid === 77 && !body.elevate) {
            const answer = { ok: false, admin: true, error: 'admingame.exe runs as administrator. Sluka can put its hook in as administrator: Windows asks you first.' };
            S.attach = { ...answer, pid: 77, at: Date.now() / 1000 };
            bump();
            return answer;
          }
          S.attach = null;
          S.mode = 'game';
          S.game = { pid: body.pid, pids: [body.pid], connected: [], exe: p.exe, title: p.title, path: p.path, bits: p.bits, state: 'attaching',
            since: Date.now() / 1000, error: '', engine: '', codes: [], remembered: false, auto: true, pchooks: false, elevated: !!body.elevate };
          S.engine.running = true;
          bump();
          return { ok: true };
        }
        case 'games/detach':
          S.game = null;
          S.threads = [];
          S.selected = [];
          bump();
          return { ok: true };
        case 'games/select': {
          if (body.only) S.selected = body.on ? [body.id] : [];
          else if (body.on && !S.selected.includes(body.id)) S.selected.push(body.id);
          else if (!body.on) S.selected = S.selected.filter((id) => id !== body.id);
          S.picked = S.selected.length ? 'you' : '';
          bump();
          return { ok: true, selected: S.selected };
        }
        case 'games/hookcode':
          if (!/@/.test(body.code || '') || /\s/.test(body.code.trim())) return { ok: false, error: 'That is not a hook code.' };
          S.game.codes.push(body.code.trim());
          bump();
          return { ok: true, code: body.code.trim() };
        case 'games/pchooks':
          S.game.pchooks = !!body.on;
          bump();
          return { ok: true };
        case 'games/settings':
          Object.assign(S.settings, body.settings || {});
          bump();
          return { ok: true, settings: S.settings };
        case 'games/pick':
          S.picking = 10;
          bump();
          return { ok: true };
        case 'games/cancel-pick':
          S.picking = 0;
          bump();
          return { ok: true };
        default:
          return { ok: true };
      }
    },
  };
})();
