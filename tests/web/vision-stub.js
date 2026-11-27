// A stand-in for the app and Sluka's engine, for trying vision.html in a browser (test_vision_page.py).
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

  const look = {
    fonts: {
      cc: ['Noto Sans JP', 'Hiragino Sans', 'Yu Gothic UI', 'Meiryo', 'system-ui', 'sans-serif'],
      ui: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      word: ['Noto Serif JP', 'Source Han Serif', 'Hiragino Mincho ProN', 'Yu Mincho', 'YuMincho', 'MS Mincho', 'serif'],
    },
    font_lang: 'ja', theme: params.get('theme') || 'dark',
    say_key: params.has('tools') ? 'v' : '',
    ask_key: params.has('ai') ? 'f' : '',
    words: {
      0: { fill: ['3b82f6', 0.4] }, 1: { fill: ['f7a800', 0.522] }, 2: { fill: ['f7a800', 0.348] },
      3: { fill: ['f7a800', 0.209], line: 'f7a800' }, 4: { line: 'f7a800' },
    },
    panel: { new: 'a7c7fb', levels: ['facb66', 'fcdc99', 'fdeac2', 'fef5e0'], lines: ['a87200', 'a87200'], fade: false, twin: 'ffb7df' },
    hover_delay: 0.05,
    keys: { 1: '1', 2: '2', 3: '3', 4: '4', 5: 'k', 6: 'x', 0: '0' },
    text: {
      known: 'Known', ignore: 'Ignore',
      labels: { 0: 'New', 1: 'Level 1', 2: 'Level 2', 3: 'Level 3', 4: 'Level 4', 5: 'Known', 6: 'Ignored', 7: 'Linked' },
      also: 'Also',
    },
  };

  // Sluka's words, in the order the lines say them: [word, level, grammar].
  const WORDS = [['わかった', 1], ['面倒', 0], ['くさい', 3], ['何', 5], ['で', 6, true], ['公衆電話', 0], ['に', 6, true],
    ['戻る', 2], ['の', 6, true], ['も', 6, true], ['面倒', 0], ['な', 6, true], ['ん', 6, true], ['で', 6, true],
    ['オマエ', 4], ['やっと', 1], ['いて', 2], ['くれ', 5], ['真面目', 0], ['な', 6, true], ['学生', 5], ['生活', 1], ['を', 6, true], ['送れ', 2]];
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
    return {
      key, st: status.get(key) ?? 0, label: look.text.labels[status.get(key) ?? 0],
      head: key === '面倒' ? [{ t: '面倒', r: 'めんどう' }] : [{ t: key }],
      reading: [{ text: key === '面倒' ? 'mendou' : 'yomi' }],
      lead: key === '面倒' ? 'trouble; difficulty' : 'a meaning', more: ['bother'], senses: ['trouble; difficulty; care', 'bother'],
      also: [], rank: '3,120th most common', none: '',
      // (looked up four times before: the engine says so from the third, as Sluka's panel shows it)
      ...(key === '面倒' ? { looks: 4, looks_title: 'Looked up 4 times' } : {}),
    };
  }


  // With ?own=replace|above|below, one of your own dictionaries has 春, as the engine sends it (mpv-engine.js withOwnDicts).
  const OWN_HTML = '<div class="reading-group rg-dict" data-dict="od-1"><span class="rg-tag" title="From Jitendex, a dictionary you added">Jitendex</span>' +
    '<div class="od-entry"><div class="od-head"><span class="od-hw" lang="ja">春</span><span class="od-reading">はる</span></div>' +
    '<ol class="od-defs"><li>spring (season)</li><li>springtime of life <a href="https://jitendex.org/haru" data-link target="_blank" rel="noopener noreferrer">more</a></li></ol></div></div>';
  const ownOf = (key) => (params.has('own') && key === '面倒' ? { own: {
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
    if (name === 'vision/poll') {
      if (body && body.fresh) return { msgs: [{ t: 'state', engine: true, auto: true, front: true }, { t: 'status', state: 'waiting', text: '' }] };
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
    if (name === 'vision/say') {
      const m = body.msg;
      setTimeout(() => {
        if (m.t === 'hello') engine({ t: 'ready', v: 2, lang: 'ja', lang_name: 'Japanese', quiet: true, look });
        else if (m.t === 'line') engine({ t: 'tokens', id: m.id, toks: tokens(m.text) });
        else if (m.t === 'lookup') {
          // With ?tools, a pinned panel has the head's keys: Translate, Look up and Anki (mpv-engine.js headTools).
          const keys = params.has('tools') && m.pin ? {
            anki: { state: 'add', title: 'Add to Anki, into Sluka::Japanese (P)', icon: '<svg viewBox="0 0 24 24" width="18" height="18" data-mark="add"><rect x="3.5" y="6.5" width="13" height="14" rx="2"/></svg>', key: 'p' },
            tools: {
              say: { title: 'Hear it (V)', icon: '<svg viewBox="0 0 24 24" data-mark="say"><path d="M3 9v6h4l5 4V5L7 9H3z"/></svg>' },
              translate: { title: 'Translate with Google Translate', icon: '<svg viewBox="0 0 24 24" data-mark="tr"><path d="M1 1h4v4H1z"/></svg>' },
              look: { title: 'Look up', icon: '<svg viewBox="0 0 24 24" data-mark="book"><path d="M1 1h4v4H1z"/></svg>', offline: 'offline',
                      links: [{ id: 'jisho', name: 'Jisho', offline: 'jmdict', installed: true }, { id: 'weblio', name: 'Weblio' }] },
            },
          } : {};
          if (params.has('ai') && m.pin) keys.tools = { ...(keys.tools || {}), ask: ASK };
          engine({ t: 'entry', id: m.id, tok: m.tok, ...entry(m.key), ...ownOf(m.key), ...keys });
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
          setTimeout(() => engine({ t: 'translation', id: m.id, tok: m.tok, ok: true, text: 'trouble', alternatives: [{ pos: 'noun', terms: ['bother', 'nuisance'] }] }), 200);
        } else if (m.t === 'grade') {
          status.set(m.key, m.status);
          engine({ t: 'status', key: m.key, st: m.status, label: look.text.labels[m.status], graded: true });
        }
      }, 10);
      return { ok: true };
    }
    if (name === 'vision/shape') {
      globalThis.__shapes.push(body);
      return { ok: true };
    }
    return { ok: true };
  }

  globalThis.__slukaShim = { api };
})();
