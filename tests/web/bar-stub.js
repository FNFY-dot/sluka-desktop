// A stand-in for the app and Sluka's engine, for trying bar.html in a browser (test_bar_page.py).
(() => {
  const queue = [];
  const waiters = [];
  const log = (globalThis.__calls = []);
  globalThis.__shapes = [];
  const push = (m) => {
    queue.push(m);
    if (waiters.length && queue.length) waiters.shift()(queue.splice(0));
  };
  globalThis.__push = push;
  const engine = (msg) => push({ t: 'engine', msg });
  const enc = new TextEncoder();
  const params = new URLSearchParams(location.search);
  const theme = params.get('theme') || 'dark';
  const size = Number(params.get('size') || 1);

  const look = {
    cjk: true, size, pos: 8, bg: 0.84, light: false, line_height: 1.42, spacing: 0.01, spaced: false,
    fonts: {
      cc: ['Noto Sans JP', 'Hiragino Sans', 'Yu Gothic UI', 'Meiryo', 'system-ui', 'sans-serif'],
      ui: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      word: ['Noto Serif JP', 'Source Han Serif', 'Hiragino Mincho ProN', 'Yu Mincho', 'YuMincho', 'MS Mincho', 'serif'],
    },
    font_lang: 'ja', ui_font: 'Segoe UI', scale: 1,
    words: {
      0: { fill: ['3b82f6', 0.4] }, 1: { fill: ['f7a800', 0.522] }, 2: { fill: ['f7a800', 0.348] },
      3: { fill: ['f7a800', 0.209], line: 'f7a800' }, 4: { line: 'f7a800' },
    },
    theme, engine: 'chromium',
    panel: { new: 'a7c7fb', levels: ['facb66', 'fcdc99', 'fdeac2', 'fef5e0'], lines: ['a87200', 'a87200'], fade: false, twin: 'ffb7df' },
    hover_delay: 0.12,
    keys: { 1: '1', 2: '2', 3: '3', 4: '4', 5: 'k', 6: 'x', 0: '0' },
    anki_key: params.has('anki') ? 'p' : '',
    say_key: params.has('tools') ? 'v' : '',
    ask_key: params.has('ai') ? 'f' : '',
    text: {
      known: 'Known', ignore: 'Ignore',
      legend: { parts: [[{ k: '1' }, '–', { k: '4' }, ' level'], [{ k: 'K' }, ' known'], [{ k: 'X' }, ' ignore']], forget: [{ k: '0' }, ' back to new'] },
      labels: { 0: 'New', 1: 'Level 1', 2: 'Level 2', 3: 'Level 3', 4: 'Level 4', 5: 'Known', 6: 'Ignored', 7: 'Linked' },
      also: 'Also',
    },
  };

  const WORDS = [['安芸', 0], ['倫也', 0], ['あき', 0], ['ともや', 0], ['ある', 1], ['春', 3], ['の', 6, true], ['日', 5], ['俺', 4], ['は', 6, true], ['運命', 2], ['と', 1], ['出会い', 1]];
  const status = new Map(WORDS.map(([w, st]) => [w, st]));

  function tokens(text) {
    const toks = [];
    let at = 0;
    for (const [w, , g] of WORDS) {
      const i = text.indexOf(w, at);
      if (i < 0) continue;
      const s = enc.encode(text.slice(0, i)).length;
      const e = s + enc.encode(w).length;
      toks.push({ s, e, key: w, st: g ? 6 : status.get(w), g: g || undefined });
      at = i + w.length;
    }
    return toks;
  }

  function entry(key) {
    if (key === '春') {
      return {
        key, st: status.get(key), label: look.text.labels[status.get(key)],
        head: [{ t: '春', r: 'はる' }],
        reading: [{ text: 'haru', pitch: [{ n: 1, beats: [{ t: 'は', hi: true, rise: true, drop: true }, { t: 'る' }] }] }],
        lead: 'spring', more: ['springtime', 'New Year'],
        senses: ['spring; springtime', 'New Year', "prime (of life); height (of one's prosperity); heyday", 'adolescence; puberty', 'sexuality; sexual desire'],
        also: [], rank: '2,897th most common', none: '',
        looks: 12, looks_title: 'Looked up 12 times',
      };
    }
    return {
      key, st: status.get(key) ?? 0, label: look.text.labels[status.get(key) ?? 0],
      head: [{ t: key }], reading: [{ text: 'yomi' }], lead: 'a meaning', more: ['another'], senses: ['a meaning', 'another'],
      also: [{ head: 'うんめい', gloss: 'fate; destiny' }], rank: '1,234th most common', none: '',
    };
  }

  const ANKI_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" data-mark="add"><rect x="3.5" y="6.5" width="13" height="14" rx="2"/></svg>';


  // With ?own=replace|above|below, one of your own dictionaries has 春, as the engine sends it (mpv-engine.js withOwnDicts).
  const OWN_HTML = '<div class="reading-group rg-dict" data-dict="od-1"><span class="rg-tag" title="From Jitendex, a dictionary you added">Jitendex</span>' +
    '<div class="od-entry"><div class="od-head"><span class="od-hw" lang="ja">春</span><span class="od-reading">はる</span></div>' +
    '<ol class="od-defs"><li>spring (season)</li><li>springtime of life <a href="https://jitendex.org/haru" data-link target="_blank" rel="noopener noreferrer">more</a></li></ol></div></div>';
  const ownOf = (key) => (params.has('own') && key === '春' ? { own: {
    place: params.get('own') || 'replace',
    dicts: [{ title: 'Jitendex', hits: [{ head: key, reading: 'はる', senses: ['spring (season)', 'springtime of life more'] }] }],
    html: OWN_HTML.replaceAll('春', key), css: '.rg-dict[data-dict="od-1"] .od-sc { color: red }',
  } } : {});
  // With ?ai, the AI check is on (Settings → AI check): the ✦ in the head, or with ?ai=wanted, for a word no dictionary
  // has, its button in the meanings (mpv-engine.js askTool).
  const ASK = { title: 'Ask AI to double-check. (F) Sends this word and its sentence to Anthropic.', aria: 'Ask AI to double-check this word',
    label: 'Ask AI if this is a real word (F)', why: 'Sends this word and its sentence to Anthropic.', wait: 'Checking…', wanted: params.get('ai') === 'wanted' };
  const VERDICT = {
    result: { verdict: 'established', confidence: 'high', reading: 'はる', meaning: 'spring, the season', example: '春が来た。',
      exampleTranslation: 'Spring has come.', register: 'neutral', breakdown: '', explanation: 'A common word.',
      ownAnswer: 'Here it is the season the story starts in.\nIt can also mean the prime of life.' },
    labels: { tag: 'Real word', confidence: 'high confidence', reading: 'Reading', register: 'Used in', breakdown: 'Actually', explanation: 'Why', own: 'Your question' },
  };

  async function api(name, body) {
    log.push([name, body]);
    if (name === 'bar/poll') {
      if (body && body.fresh) {
        return { msgs: [{ t: 'state', state: { x: 0.5, y: Number(params.get('y') || 0.9056), width: Number(params.get('w') || 1300), scale: 1, lock: false, through: params.has('through') }, engine: true }] };
      }
      if (queue.length) return { msgs: queue.splice(0) };
      return new Promise((resolve) => {
        let done = false;
        const answer = (msgs) => {
          if (done) return;
          done = true;
          resolve({ msgs });
        };
        waiters.push(answer);
        setTimeout(() => {
          if (done) return;
          waiters.splice(waiters.indexOf(answer), 1);
          answer(queue.splice(0));
        }, 1500);
      });
    }
    if (name === 'bar/say') {
      const m = body.msg;
      setTimeout(() => {
        if (m.t === 'hello') engine({ t: 'ready', v: 2, lang: 'ja', lang_name: 'Japanese', quiet: true, look });
        else if (m.t === 'line') engine({ t: 'tokens', id: m.id, toks: tokens(m.text) });
        else if (m.t === 'lookup') {
          // With ?anki, Settings → Anki has the panel's button on: a pinned panel has its Anki key.
          const anki = params.has('anki') && m.pin ? { anki: { state: 'add', title: 'Add to Anki, into Sluka::Japanese (P)', icon: ANKI_ICON, key: 'p' } } : {};
          // With ?tools, the head's Translate and Look up keys too (mpv-engine.js headTools).
          const tools = params.has('tools') && m.pin ? { tools: {
            say: { title: 'Hear it (V)', icon: '<svg viewBox="0 0 24 24" data-mark="say"><path d="M3 9v6h4l5 4V5L7 9H3z"/></svg>' },
            translate: { title: 'Translate with Google Translate', icon: '<svg viewBox="0 0 24 24" data-mark="tr"><path d="M1 1h4v4H1z"/></svg>' },
            look: { title: 'Look up', icon: '<svg viewBox="0 0 24 24" data-mark="book"><path d="M1 1h4v4H1z"/></svg>', offline: 'offline',
                    links: [{ id: 'jisho', name: 'Jisho', offline: 'jmdict', installed: false }, { id: 'weblio', name: 'Weblio' }] } } } : {};
          if (params.has('ai') && m.pin) tools.tools = { ...(tools.tools || {}), ask: ASK };
          engine({ t: 'entry', id: m.id, tok: m.tok, ...entry(m.key), ...ownOf(m.key), ...anki, ...tools });
        } else if (m.t === 'speak') {
          (globalThis.__spoken ||= []).push(m);
          engine({ t: 'speaking', id: m.id, tok: m.tok, on: true });
          setTimeout(() => engine({ t: 'speaking', id: m.id, tok: m.tok, on: false }), 400);
        } else if (m.t === 'ask') {
          (globalThis.__asks ||= []).push(m);
          engine({ t: 'verdict', id: m.id, tok: m.tok, status: 'loading', label: 'Checking…' });
          setTimeout(() => engine({ t: 'verdict', id: m.id, tok: m.tok, status: params.has('aierror') ? 'error' : 'done',
            ...(params.has('aierror') ? { error: 'The AI check is turned off in Settings.' } : VERDICT) }), 250);
        } else if (m.t === 'open') {
          (globalThis.__opened ||= []).push(m.url);
        } else if (m.t === 'translate') {
          setTimeout(() => engine({ t: 'translation', id: m.id, tok: m.tok, ok: true, text: 'spring', alternatives: [{ pos: 'noun', terms: ['springtime'] }] }), 200);
        } else if (m.t === 'anki') {
          engine({ t: 'anki', id: m.id, tok: m.tok, state: 'queued', title: 'Waiting for Anki…', icon: ANKI_ICON.replace('add', 'queued'), key: 'p' });
          setTimeout(() => engine({ t: 'anki', id: m.id, tok: m.tok, state: 'in', title: 'In Anki, in Sluka::Japanese. Opens its card in Anki (P)', icon: ANKI_ICON, key: 'p' }), 300);
        }
        else if (m.t === 'grade') {
          status.set(m.key, m.status);
          engine({ t: 'status', key: m.key, st: m.status, label: look.text.labels[m.status], graded: true });
        }
      }, 10);
      return { ok: true };
    }
    if (name === 'bar/shape') {
      globalThis.__shapes.push(body);
      return { ok: true };
    }
    return { ok: true };
  }

  globalThis.__slukaShim = { api };
})();
