// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * What the desktop's tools add to Sluka's Home page: words read, minutes
 * listened, and subtitle words.  Written into the same day records Sluka's own
 * pages write, by the same messages to its worker (MSG.READ_WORDS,
 * MSG.LISTEN_LOCAL_VIDEO, MSG.LISTEN_NARRATED), so that the worker's queue
 * keeps every write in turn and a minute heard in mpv is the same kind of
 * minute as one heard on Your videos.
 *
 *   mpv        Listening, by the rule of Sluka's Your videos page
 *              (videos/listen-clock.js): between two looks at the player (the
 *              script's "clock"), the smaller of the time that passed and how
 *              far the file moved on, while it played with its sound on.  Only
 *              a film Sluka can tell is in a language you learn counts: its
 *              audio or subtitle track is marked with one, or its subtitles or
 *              its title are written in one.  Time heard before anything says
 *              so is held, and counted once something does; a film nothing
 *              ever names counts nothing.  Banked a minute at a time as the
 *              film's row in the Listening tab, as Your videos banks one.
 *              A subtitle line half of which has played is subtitle words
 *              (`cc`), as SlukaCC counts a caption (lib/reading.js
 *              CueCoverage, CUE_SHARE): once a file, however often it is
 *              heard again.
 *
 *   the floating subtitles, Sluka Vision
 *              Words read, as a page's are (lib/reading.js): the text on
 *              screen is paid for at the reader's own pace, earliest first,
 *              for as long as it is up and the reader is there, and never more
 *              than once a day (today's record, lib/stats.js readToday).  The
 *              pace is learned here, from how fast the lines go by, as a page
 *              learns it from how fast its text scrolls past; until there is
 *              enough of that it is the pace Sluka knows from pages, or its
 *              starting one.  Kept apart from the pages' (PACE_KEY): it is
 *              measured another way, and reading on pages is left as it was.
 *              Only the words in the language's own writing count (no English
 *              menu read as Japanese), and nothing does where Settings ›
 *              Reading › Count words read says only Sluka's reader and books.
 *
 *   a game     Half of the time it was played, as listening (gametext.py
 *              PlayClock says how long): a game's sound is voices and music
 *              and the rest, and half of it is the measure chosen for the
 *              voices.  Only while the game's text is in a language you learn:
 *              some of it was read here in the last half hour.
 *
 * Nothing here writes to storage but the pace (its own key); nothing here can
 * stop a line being shown: the engine calls in only after it has answered.
 */

/** How often owed time is paid for and what is owed looked at (the engine's timer). */
export const TICK_MS = 5000;
/** Words read are written at most this often (content/exposure.js FLUSH_EVERY_MS). */
export const READ_EVERY_MS = 30000;
/** Minutes heard, at most this often (lib/listening.js FLUSH_EVERY_MS). */
export const LISTEN_EVERY_MS = 60000;
/** Less than this much heard is not worth a write (videos/listen-clock.js MIN_BANK_MS). */
const MIN_BANK_MS = 1000;

/** Today's record names the text of each tool under one document of its own. */
export const DOC_PREFIX = 'sluka-desktop:';
/** The pace learned from lines, per language: { lang: [units a minute] } (lib/reading.js withSamples). */
export const PACE_KEY = 'sluka-desktop:linePace';

/**
 * No new text, no word pointed at or graded for this long: the reader is not
 * there.  Longer than a page's two minutes (lib/reading.js IDLE_AFTER_MS):
 * a screen of a game is read with nothing else happening, and is only ever
 * worth its own words however long it stays up.
 */
export const LINE_IDLE_MS = 5 * 60000;
/** Lines that went from the screen, kept to know them again: so many, for so long. */
const GONE_KEPT = 60;
const GONE_KEPT_MS = 20 * 60000;
/** Read again a little differently (a screen read off twice), or a letter at a time: the same line. */
const SAME_SHARE = 0.8;
/** Shorter than this, two texts are the same line only when they are equal. */
const SAME_FROM = 6;
/** A screen gone faster than this many times the fastest pace was skipped through, not read. */
const SKIM = 1.5;
/** How long today's record of what was read is trusted before it is read again. */
const MEMORY_MS = 10 * 60000;

/** The share of a game's time played that is listening, and the most one report may carry. */
export const PLAYED_SHARE = 0.5;
const PLAYED_MOST_MS = 5 * 60000;
/** Text in the language read here this recently: the game being played is in it. */
export const GAME_TEXT_MS = 30 * 60000;

/** The most time held for a film nothing has yet said the language of. */
const HELD_MOST_MS = 6 * 3600000;
/** The most one stretch between two looks may count (they come a second apart). */
const STEP_MOST_MS = 5 * 60000;
/** Another player heard this recently is still playing: two films at once are one minute lived, counted once. */
const BOTH_MS = 2500;
/** Subtitle lines kept for their playing to be followed, and text kept to tell the language by. */
const LINES_KEPT = 40;
const SAMPLE_CHARS = 4000;
/** More subtitle text than this since the last look at it, and an unsure film's is looked at again. */
const JUDGE_AGAIN_CHARS = 200;

const EPS = 1e-6;

/**
 * The writing a language's own words are in.  A word of a game's text or a
 * subtitle counts only in it: an English menu over a Japanese game, or the
 * English subtitles of a film, are no Japanese read.  The languages written
 * in the Latin alphabet have no such test, and count every word.
 */
const OWN_WRITING = {
  zh: /\p{Script=Han}/u,
  yue: /\p{Script=Han}/u,
  ja: /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u,
  ko: /\p{Script=Hangul}/u,
  th: /\p{Script=Thai}/u,
  el: /\p{Script=Greek}/u,
  ru: /\p{Script=Cyrillic}/u,
  uk: /\p{Script=Cyrillic}/u,
  ar: /\p{Script=Arabic}/u,
};
const LETTER = /\p{L}/u;

/** Whether `piece`, a word of a line read as `lang`, is a word of that language. */
export function inWriting(lang, piece) {
  const own = OWN_WRITING[lang];
  return own ? own.test(piece) : LETTER.test(piece);
}

/** A text as it is compared with another: its letters and numbers, folded. */
export function textKey(text) {
  return String(text || '').normalize('NFKC').replace(/[\s\p{P}\p{S}]+/gu, '').toLowerCase();
}

/** How alike two texts are, 0-1: the share of their pairs of letters they have in common. */
export function likeness(a, b) {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const pairs = new Map();
  for (let i = 0; i < a.length - 1; i++) {
    const p = a.slice(i, i + 2);
    pairs.set(p, (pairs.get(p) || 0) + 1);
  }
  let both = 0;
  for (let i = 0; i < b.length - 1; i++) {
    const p = b.slice(i, i + 2);
    const n = pairs.get(p);
    if (n) {
      both++;
      pairs.set(p, n - 1);
    }
  }
  return (2 * both) / (a.length + b.length - 2);
}

/** Whether two keys (`textKey`) are the same line: equal, one the start of the other, or alike but for a letter or two. */
export function sameLine(a, b) {
  if (a === b) return true;
  const short = Math.min(a.length, b.length);
  if (short < SAME_FROM) return false;
  if (a.startsWith(b) || b.startsWith(a)) return true;
  if (short / Math.max(a.length, b.length) < SAME_SHARE) return false;
  return likeness(a, b) >= SAME_SHARE;
}

/** A file's name as a film's: "Mi pelicula.mp4" is "Mi pelicula" (videos/listen-clock.js filmName). */
export function filmName(name) {
  return String(name || '').trim().replace(/\.(?=[a-z0-9]*[a-z])[a-z0-9]{2,4}$/i, '');
}

/** A reply that says the message is not known to the worker at all, rather than that it failed. */
function unsupported(res) {
  return res?.ok === false && /^(unknown message|unsupported)/.test(String(res.error || ''));
}

/**
 * The tracking, given what it needs:
 *
 *   S              Sluka's modules, by name (the engine imports and checks them): MSG, KEY;
 *                  lib/reading.js's paceUnit, paceFrom, withSamples, hashText, PACE_LIMITS,
 *                  PACE_SAMPLES_NEEDED, SAMPLE_MIN_MS, SAMPLE_MIN_UNITS, CUE_SHARE, CUE_MAX_STEP_S;
 *                  lib/stats.js's recordReading, recordDayDeltas, readingMemory;
 *                  lib/listening.js's textLanguage, sameLanguage, creditLocalVideo, retire, archive,
 *                  startOfDay; and, where Sluka has it, lib/languages.js's strongestLanguage
 *   settings()     Sluka's settings now
 *   studied()      the languages you learn
 *   trackLanguage  a track's language code (jpn, ja, ...) as one of Sluka's, or null
 *   ask(message)   a message to Sluka's worker, and its answer
 *   storage        chrome.storage.local
 *   now()          the time, in ms
 *   report(err)    a failure, for the console
 *   log(text)      a line for the app's log (never a title or a line of text)
 *   nameOf(lang)   a language's name, for the log
 */
export function startProgress({ S, settings, studied, trackLanguage, ask, storage, now = () => Date.now(), report = () => {}, log = () => {},
  nameOf = (lang) => lang }) {
  /** The floating subtitles' and Sluka Vision's reading, by player key. */
  const readers = new Map();
  /** mpv players' films, by player key. */
  const films = new Map();
  /** Today's record of what was read, per language and document: { at, blocks: { hash: units } }. */
  const memories = new Map();
  /** Pace measurements: this tool's (PACE_KEY) and the pages' (lib/stats.js readingMemory), per language. */
  let ownSamples = null;
  const pageSamples = new Map();
  /** Measurements not yet written, per language. */
  const newSamples = new Map();
  let writingSamples = false;

  const counting = () => settings()?.countReading !== 'sluka';
  const add = (map, key, n) => map.set(key, (map.get(key) || 0) + n);
  /** One write of a player's after another: a player that goes while one is out still has the rest written. */
  const serial = (st, fn) => {
    const next = (st.chain || Promise.resolve()).then(fn, fn);
    st.chain = next.catch(() => {});
    return next;
  };

  // ------------------------------------------------------------ writing it down

  /** Words read and subtitle words, to the worker; true once they are written. */
  async function deliverReading(lang, body) {
    let res;
    try {
      res = await ask({ type: S.MSG.READ_WORDS, lang, ...body });
    } catch {
      return false;
    }
    if (res?.ok) return true;
    if (!unsupported(res)) return false;
    // A Sluka whose worker does not take it: written here, as its pages write where there is no worker.
    await S.recordReading(lang, body);
    return true;
  }

  /** A film's minutes, to the worker: the day's listening and the film's row in the Listening tab. */
  async function deliverFilm({ lang, title, ms }) {
    let res;
    try {
      res = await ask({ type: S.MSG.LISTEN_LOCAL_VIDEO, lang, title, ms });
    } catch {
      return false;
    }
    if (res?.ok) return true;
    if (!unsupported(res)) return false;
    // As Your videos writes it where no one else will (videos/listen-clock.js writeHere): the row, then the day.
    const at = now();
    const got = await storage.get([S.KEY.listenRecent, S.KEY.listenHistory]);
    const today = S.creditLocalVideo(got[S.KEY.listenRecent] || [], { title, lang, ms, now: at, platform: 'pc' });
    const split = S.retire(today, S.startOfDay(at));
    const payload = { [S.KEY.listenRecent]: split.recent };
    if (split.retired.length) payload[S.KEY.listenHistory] = S.archive(got[S.KEY.listenHistory] || [], split.retired, at);
    await storage.set(payload);
    await S.recordDayDeltas(lang, { listenedMs: ms });
    return true;
  }

  /** A game's minutes: the day's listening alone, as a page read aloud gives it. */
  async function deliverHeard(lang, ms) {
    let res;
    try {
      res = await ask({ type: S.MSG.LISTEN_NARRATED, lang, ms });
    } catch {
      return false;
    }
    if (res?.ok) return true;
    if (!unsupported(res)) return false;
    await S.recordDayDeltas(lang, { listenedMs: ms });
    return true;
  }

  // ------------------------------------------------------------ the pace

  async function loadSamples() {
    if (ownSamples) return ownSamples;
    const got = await storage.get(PACE_KEY).catch(() => ({}));
    const kept = got?.[PACE_KEY];
    ownSamples = kept && typeof kept === 'object' ? { ...kept } : {};
    return ownSamples;
  }

  /** The reader's pace in `lang`, units a minute: learned from lines, else from pages, else Sluka's starting pace. */
  async function paceOf(lang, unit) {
    const own = (await loadSamples())[lang] || [];
    if (own.length >= S.PACE_SAMPLES_NEEDED) return S.paceFrom(own, unit);
    return S.paceFrom(pageSamples.get(lang) || [], unit);
  }

  async function writeSamples() {
    if (writingSamples || !newSamples.size) return;
    writingSamples = true;
    const taken = new Map(newSamples);
    newSamples.clear();
    try {
      const got = await storage.get(PACE_KEY);
      const all = { ...(got?.[PACE_KEY] && typeof got[PACE_KEY] === 'object' ? got[PACE_KEY] : {}) };
      for (const [lang, { unit, rates }] of taken) all[lang] = S.withSamples(all[lang], rates, unit);
      await storage.set({ [PACE_KEY]: all });
      ownSamples = all;
      for (const st of readers.values()) st.pace = await paceOf(st.lang, st.unit);
    } catch (err) {
      for (const [lang, value] of taken) {
        const waiting = newSamples.get(lang);
        newSamples.set(lang, waiting ? { unit: value.unit, rates: [...value.rates, ...waiting.rates] } : value);
      }
      report(err);
    } finally {
      writingSamples = false;
    }
  }

  // ------------------------------------------------------------ today's record

  /** What today's record says was read of `doc` in `lang`: { hash: units }. */
  async function memoryOf(lang, doc) {
    const name = `${lang}\n${doc}`;
    const known = memories.get(name);
    if (known && now() - known.at < MEMORY_MS) return known.blocks;
    let blocks = known?.blocks || {};
    try {
      const got = await S.readingMemory(lang, doc);
      // What was paid here since the record was last read is in it already, or on its way: the larger of the two.
      blocks = { ...(got?.today || {}) };
      for (const [hash, units] of Object.entries(known?.blocks || {})) blocks[hash] = Math.max(blocks[hash] || 0, units);
      pageSamples.set(lang, Array.isArray(got?.samples) ? got.samples : []);
    } catch (err) {
      report(err);
    }
    memories.set(name, { at: now(), blocks });
    return blocks;
  }

  function remember(lang, doc, paid) {
    const known = memories.get(`${lang}\n${doc}`);
    if (!known) return;
    for (const [hash, units] of Object.entries(paid)) known.blocks[hash] = Math.max(known.blocks[hash] || 0, units);
  }

  // ------------------------------------------------------------ lines on screen

  /** A text's paragraphs, each with the words of it that count: { key, hash, units, words }. */
  function partsOf(text, words, lang, unit) {
    const parts = [];
    let start = 0;
    const ends = [];
    for (let i = text.indexOf('\n'); i >= 0; i = text.indexOf('\n', i + 1)) ends.push(i);
    ends.push(text.length);
    for (const end of ends) {
      const key = textKey(text.slice(start, end));
      const inside = words.filter((w) => w.at >= start && w.at < end && inWriting(lang, w.text));
      if (key && inside.length) {
        const units = unit === 'chars' ? inside.reduce((n, w) => n + w.text.length, 0) : inside.length;
        parts.push({ key, hash: S.hashText(key), units, words: inside.length });
      }
      start = end + 1;
    }
    return parts;
  }

  function blockOf(part, prepaid) {
    const paid = Math.min(part.units, Math.max(0, Number(prepaid) || 0));
    return {
      key: part.key,
      hash: part.hash,
      units: part.units,
      words: part.words,
      paid,
      credited: part.units > 0 ? Math.floor((part.words * paid) / part.units + EPS) : 0,
    };
  }

  function readerOf(key, kind, lang, unit) {
    const at = now();
    return {
      key,
      kind,
      lang,
      unit,
      doc: DOC_PREFIX + kind,
      pace: S.paceFrom([], unit),
      screen: [],
      shown: true,
      lastPay: at,
      lastActive: at,
      screenMs: 0,
      gone: [],
      owed: 0,
      touched: new Set(),
      win: null,
      textAt: 0,
      heardMs: 0,
      flushedAt: at,
      bankedAt: at,
      flushing: false,
      again: false,
      chain: null,
    };
  }

  /**
   * The time from the last payment to `at`, paid for on the screen as it was:
   * at the reader's pace, earliest words first, for as long as the screen was
   * showing and the reader was there -- and never past a line's own words.
   */
  function pay(st, at) {
    const from = st.lastPay;
    st.lastPay = at;
    if (!st.shown || !st.screen.length || !(at > from)) return;
    const active = Math.max(0, Math.min(at, st.lastActive + LINE_IDLE_MS) - from);
    if (!active) return;
    st.screenMs += active;
    if (!counting()) return;
    let budget = (active / 60000) * st.pace;
    for (const b of st.screen) {
      if (!(budget > EPS)) break;
      const left = b.units - b.paid;
      if (!(left > EPS)) continue;
      const take = Math.min(left, budget);
      b.paid += take;
      budget -= take;
      const credited = Math.floor((b.words * b.paid) / b.units + EPS);
      if (credited > b.credited) {
        st.owed += credited - b.credited;
        b.credited = credited;
      }
      st.touched.add(b);
    }
  }

  /**
   * A measurement of pace from the text that went off the screen: `left`
   * units, up for the time the screen was (st.screenMs).  Gathered over at
   * least what a page's measurement takes (SAMPLE_MIN_MS, SAMPLE_MIN_UNITS),
   * and thrown away when the reader was away, skipped through, or went back.
   */
  function measure(st, left) {
    if (!(left > 0)) return;
    const fastest = (S.PACE_LIMITS[st.unit] || S.PACE_LIMITS.words)[1];
    const ms = st.screenMs;
    if (!(ms > 0) || ms >= LINE_IDLE_MS || left / (ms / 60000) > fastest * SKIM) {
      st.win = null;
      return;
    }
    const w = st.win || (st.win = { units: 0, ms: 0 });
    w.units += left;
    w.ms += ms;
    if (w.units < S.SAMPLE_MIN_UNITS[st.unit] || w.ms < S.SAMPLE_MIN_MS) return;
    const rate = w.units / (w.ms / 60000);
    st.win = null;
    // Faster than anybody reads is a skim, measured: thrown away, as a page throws one away.
    if (rate > fastest) return;
    const waiting = newSamples.get(st.lang);
    if (waiting) waiting.rates.push(rate);
    else newSamples.set(st.lang, { unit: st.unit, rates: [rate] });
  }

  /** The screen made of `parts`: lines still up, lines back, and new ones with what today's record says of them. */
  function nextScreen(st, parts, memory, at) {
    const old = st.screen;
    const kept = new Set();
    const screen = [];
    let back = false;
    for (const part of parts) {
      let b = old.find((o) => !kept.has(o) && sameLine(o.key, part.key));
      if (!b) {
        const i = st.gone.findIndex((g) => !kept.has(g.block) && sameLine(g.block.key, part.key));
        if (i >= 0) {
          b = st.gone[i].block;
          st.gone.splice(i, 1);
          back = true;
        }
      }
      if (b) {
        // The same line, grown (typed out a letter at a time) or read again: what was paid of it stays paid.
        if (part.units > b.units) {
          b.units = part.units;
          b.words = Math.max(b.words, part.words);
          b.key = part.key;
          b.hash = part.hash;
        }
      } else {
        b = blockOf(part, memory[part.hash]);
      }
      kept.add(b);
      screen.push(b);
    }
    let left = 0;
    for (const o of old) {
      if (kept.has(o)) continue;
      left += o.units;
      st.gone.unshift({ block: o, at });
    }
    st.gone = st.gone.filter((g) => at - g.at <= GONE_KEPT_MS).slice(0, GONE_KEPT);
    return { screen, left, back };
  }

  async function readLine(player, kind, L, text, words) {
    const unit = S.paceUnit(L.id);
    let st = readers.get(player.key);
    if (st && st.lang !== L.id) {
      // Text in another of your languages: what this one owes is written (alongside: no line waits on a write).
      flushReader(st).catch(report);
      bankPlayed(st).catch(report);
      st = null;
    }
    if (!st) {
      st = readerOf(player.key, kind, L.id, unit);
      readers.set(player.key, st);
    }
    const memory = await memoryOf(L.id, st.doc);
    st.pace = await paceOf(L.id, unit);
    if (readers.get(player.key) !== st) return;
    const at = now();
    pay(st, at);
    const parts = partsOf(String(text || ''), words || [], L.id, unit);
    if (parts.length) st.textAt = at;
    const before = st.screen;
    const { screen, left, back } = nextScreen(st, parts, memory, at);
    const changed = screen.length !== before.length || screen.some((b, i) => b !== before[i]);
    // A line on the floating subtitles is on screen; Sluka Vision's words are while its page says so (shown).
    if (!st.shown && kind === 'bar') {
      st.shown = true;
      st.lastActive = at;
    }
    if (!changed) return;
    // New text is the reader moving on.
    st.lastActive = at;
    if (back) st.win = null;
    else measure(st, left);
    st.screen = screen;
    st.screenMs = 0;
  }

  async function flushReader(st) {
    if (st.flushing) {
      st.again = true;
      return;
    }
    st.flushing = true;
    try {
      do {
        st.again = false;
        pay(st, now());
        const words = st.owed;
        const touched = [...st.touched];
        const paid = {};
        for (const b of touched) if (b.paid > 0) paid[b.hash] = Math.round(b.paid * 10) / 10;
        const docs = Object.keys(paid).length ? { [st.doc]: paid } : null;
        if (!words && !docs) break;
        st.owed = 0;
        st.touched.clear();
        const ok = await deliverReading(st.lang, { words, docs, unit: st.unit }).catch((err) => {
          report(err);
          return false;
        });
        if (!ok) {
          st.owed += words;
          for (const b of touched) st.touched.add(b);
          break;
        }
        remember(st.lang, st.doc, paid);
      } while (st.again);
    } finally {
      st.flushing = false;
      st.flushedAt = now();
    }
  }

  /** Half of the time a game was played, owed as listening, written. */
  function bankPlayed(st) {
    st.bankedAt = now();
    return serial(st, async () => {
      const ms = Math.round(st.heardMs);
      if (ms < MIN_BANK_MS) return;
      st.heardMs -= ms;
      const ok = await deliverHeard(st.lang, ms).catch((err) => {
        report(err);
        return false;
      });
      if (!ok) st.heardMs += ms;
    });
  }

  // ------------------------------------------------------------ films in mpv

  function filmOf(player) {
    let st = films.get(player.key);
    if (!st) {
      st = {
        key: player.key,
        last: null,
        title: null,
        alang: '',
        subLang: player.subLang || '',
        owed: new Map(),
        held: 0,
        unsent: [],
        lines: [],
        heard: new Set(),
        cc: new Map(),
        sample: '',
        byText: undefined,
        judgedAt: -1,
        how: null,
        countedMs: 0,
        lostMs: 0,
        heardAt: 0,
        since: 0,
        bankedAt: now(),
        chain: null,
      };
      films.set(player.key, st);
    }
    return st;
  }

  const HOW = {
    audio: 'its audio track says so',
    subtitles: 'its subtitle track says so',
    text: 'its subtitles are written in it',
    title: 'its title is written in it',
  };

  /** What became of a file's time, for the log: never its name. */
  function told(st) {
    const minutes = (ms) => `${Math.round(ms / 6000) / 10} min`;
    const lost = st.lostMs + st.held;
    const named = st.how?.lang ? nameOf(st.how.lang) || st.how.lang : '?';
    if (st.countedMs >= 30000) log(`mpv: ${minutes(st.countedMs)} heard and counted as ${named} (${HOW[st.how?.why] || 'as far as can be told'})`);
    if (lost >= 30000) {
      const why = st.how?.no === 'audio' ? 'its audio track is in a language you do not learn'
        : st.how?.no === 'subtitles' ? 'its subtitles are in a language you do not learn, and nothing else says what it is in'
          : 'nothing says it is in a language you learn (no track marked with one, no subtitles or title written in one)';
      log(`mpv: ${minutes(lost)} heard and not counted: ${why}`);
    }
  }

  /** Another file in the player: nothing of the last one's lines or language carries over. */
  function newFile(st) {
    told(st);
    st.lines = [];
    st.heard.clear();
    st.sample = '';
    st.byText = undefined;
    st.judgedAt = -1;
    st.held = 0;
    st.how = null;
    st.countedMs = 0;
    st.lostMs = 0;
  }

  /** Which of your languages the subtitles' own text is in, or null where it cannot be told (yet). */
  async function bySubtitles(st, langs) {
    if (st.byText) return st.byText;
    if (!st.sample.trim() || (st.judgedAt >= 0 && st.sample.length - st.judgedAt < JUDGE_AGAIN_CHARS)) return null;
    st.judgedAt = st.sample.length;
    let found = null;
    try {
      if (S.strongestLanguage) found = await S.strongestLanguage(st.sample, langs);
    } catch (err) {
      report(err);
    }
    if (!found) {
      const named = S.textLanguage(st.sample);
      found = named ? langs.find((id) => S.sameLanguage(named, id)) || null : null;
    }
    if (found) st.byText = found;
    return found;
  }

  /**
   * Which language a film is heard in, as far as can be told: { lang }, or
   * { no } where something says it is in a language you do not learn, or
   * { unsure } where nothing says anything yet.
   */
  async function judge(st) {
    const langs = studied();
    const audio = trackLanguage(st.alang);
    if (audio) return langs.includes(audio) ? { lang: audio, why: 'audio' } : { no: 'audio' };
    const subs = trackLanguage(st.subLang);
    if (subs && langs.includes(subs)) return { lang: subs, why: 'subtitles' };
    if (!subs) {
      const found = await bySubtitles(st, langs);
      if (found) return { lang: found, why: 'text' };
    }
    const named = S.textLanguage(st.title || '');
    const byTitle = named ? langs.find((id) => S.sameLanguage(named, id)) : null;
    if (byTitle) return { lang: byTitle, why: 'title' };
    return subs ? { no: 'subtitles' } : { unsure: true };
  }

  /** Whether the subtitles are in `lang`: their track says so, or (unmarked) their own text does. */
  function subtitlesIn(st, lang) {
    const subs = trackLanguage(st.subLang);
    if (subs) return subs === lang;
    return !!st.byText && (st.byText === lang || S.sameLanguage(st.byText, lang));
  }

  /** The file played from `from` to `to` (seconds): the lines it went through, and those now half heard. */
  function cover(st, from, to) {
    for (const ln of st.lines) {
      if (ln.done) continue;
      const overlap = Math.min(ln.end, to) - Math.max(ln.start, from);
      if (overlap > 0) ln.played += overlap;
      if (ln.played < S.CUE_SHARE * (ln.end - ln.start)) continue;
      ln.done = true;
      // Heard before in this file: seeking back to hear it again is listening again, not more reading.
      if (st.heard.has(ln.key)) continue;
      st.heard.add(ln.key);
      if (ln.words > 0 && counting() && subtitlesIn(st, ln.lang)) add(st.cc, ln.lang, ln.words);
    }
  }

  async function filmLine(player, L, text, words, m) {
    const st = filmOf(player);
    st.subLang = player.subLang || '';
    if (st.sample.length < SAMPLE_CHARS) {
      st.sample += (st.sample ? '\n' : '') + String(text || '').slice(0, SAMPLE_CHARS - st.sample.length);
    }
    if (!trackLanguage(st.subLang)) await bySubtitles(st, studied());
    const start = Number(m?.start);
    const end = Number(m?.end);
    if (m?.start == null || m?.end == null || !Number.isFinite(start) || !Number.isFinite(end) || !(end > start)) return;
    const counted = (words || []).filter((w) => inWriting(L.id, w.text)).length;
    st.lines.push({ key: Math.round(start * 1000), start, end, words: counted, lang: L.id, played: 0, done: false });
    if (st.lines.length > LINES_KEPT) st.lines.splice(0, st.lines.length - LINES_KEPT);
  }

  async function clock(player, m) {
    const at = Number(m?.at) * 1000;
    if (!Number.isFinite(at)) return;
    const st = filmOf(player);
    const pos = m.pos == null ? NaN : Number(m.pos);
    const look = { at, pos, play: m.play === true, sound: m.sound === true };
    const title = String(m.title ?? '').slice(0, 300);
    const alang = String(m.alang ?? '').slice(0, 16);
    st.subLang = player.subLang || '';
    if (st.title !== null && title !== st.title) {
      // Another file: the last one's minutes are its own, under its own name.
      stage(st);
      newFile(st);
      bankFilm(st).catch(report);
      st.title = title;
      st.alang = alang;
      st.last = look;
      return;
    }
    st.title = title;
    st.alang = alang;
    const prev = st.last;
    st.last = look;
    if (!prev || !Number.isFinite(prev.pos) || !Number.isFinite(look.pos)) return;
    const wall = look.at - prev.at;
    const moved = (look.pos - prev.pos) * 1000;
    // Lines are heard only by playing through them: not by a seek, which moves further than the time it took.
    if (prev.play && wall > 0 && moved > 0 && moved <= Math.max(S.CUE_MAX_STEP_S * 1000, wall * 3)) cover(st, prev.pos, look.pos);
    if (!prev.sound || !(wall > 0) || !(moved > 0)) return;
    const ms = Math.min(wall, moved, STEP_MOST_MS);
    const verdict = await judge(st);
    st.how = verdict;
    if (verdict.no) {
      st.lostMs += st.held + ms;
      st.held = 0;
      return;
    }
    // Two films heard at once are one minute lived: the one heard first is counted, as Sluka counts one tab of two.
    // (One in a language you do not learn never hides the other.)
    const heardNow = now();
    if ([...films.values()].some((o) => o !== st && heardNow - o.heardAt <= BOTH_MS && o.since && (!st.since || o.since < st.since))) return;
    if (!st.since || heardNow - st.heardAt > BOTH_MS) st.since = heardNow;
    st.heardAt = heardNow;
    if (verdict.lang) {
      const heard = st.held + ms;
      st.held = 0;
      add(st.owed, verdict.lang, heard);
      st.countedMs += heard;
    } else {
      st.held = Math.min(HELD_MOST_MS, st.held + ms);
    }
  }

  /** What a film owes, made chunks to send, under the film's name now: a chunk a language. */
  function stage(st) {
    const title = filmName(st.title || '');
    for (const [lang, ms] of [...st.owed]) {
      const whole = Math.round(ms);
      if (whole < MIN_BANK_MS) continue;
      st.owed.set(lang, ms - whole);
      const same = st.unsent.find((c) => c.lang === lang && c.title === title);
      if (same) same.ms += whole;
      else st.unsent.push({ lang, title, ms: whole });
    }
  }

  /** What a film owes, written: its minutes, and its subtitle words. */
  function bankFilm(st) {
    st.bankedAt = now();
    stage(st);
    return serial(st, async () => {
      const batch = st.unsent.splice(0);
      for (const chunk of batch) {
        const ok = await deliverFilm(chunk).catch((err) => {
          report(err);
          return false;
        });
        // Not written: offered again with the next minute.
        if (!ok) st.unsent.push(chunk);
      }
      for (const [lang, n] of [...st.cc]) {
        if (!(n > 0)) continue;
        st.cc.delete(lang);
        const ok = await deliverReading(lang, { words: 0, cc: n, unit: S.paceUnit(lang) }).catch((err) => {
          report(err);
          return false;
        });
        if (!ok) add(st.cc, lang, n);
      }
    });
  }

  // ------------------------------------------------------------ what the engine says

  return {
    /** A line the engine has cut into words (`words`: { text, at } for each, at its place in `text`). */
    async line(player, kind, L, text, words, m) {
      if (!L?.id) return;
      if (kind === 'mpv') await filmLine(player, L, text, words, m);
      else await readLine(player, kind, L, text, words);
    },

    /** A look at an mpv player (mpv/sluka.lua send_clock). */
    clock,

    /** Another subtitle track: its text is looked at afresh for the language. */
    track(player) {
      const st = films.get(player.key);
      if (!st) return;
      st.subLang = player.subLang || '';
      st.sample = '';
      st.byText = undefined;
      st.judgedAt = -1;
    },

    /** The floating subtitles' line, or Sluka Vision's words, put away or shown again. */
    shown(player, on) {
      const st = readers.get(player.key);
      if (!st) return;
      const at = now();
      pay(st, at);
      st.shown = !!on;
      if (on) st.lastActive = at;
      else flushReader(st).catch(report);
    },

    /** A word pointed at, opened or graded: the reader is there. */
    active(player) {
      const st = readers.get(player.key);
      if (!st) return;
      const at = now();
      pay(st, at);
      st.lastActive = at;
    },

    /** Time a game was played (the app's play clock), with the floating subtitles or Sluka Vision on it. */
    played(player, m) {
      const st = readers.get(player.key);
      const ms = Math.min(PLAYED_MOST_MS, Math.max(0, Number(m?.ms) || 0));
      if (!st || !ms) return;
      if (!(st.textAt && now() - st.textAt <= GAME_TEXT_MS)) return;
      st.heardMs += ms * PLAYED_SHARE;
    },

    /** A player gone: what it owes, written (its state let go of at once, so a player of the same name starts afresh). */
    async gone(key) {
      const reader = readers.get(key);
      const film = films.get(key);
      readers.delete(key);
      films.delete(key);
      if (reader) {
        await flushReader(reader);
        await bankPlayed(reader);
      }
      if (film) {
        told(film);
        await bankFilm(film);
      }
    },

    /** The timer's: time paid for, and what is due written. */
    tick() {
      const at = now();
      for (const st of readers.values()) {
        pay(st, at);
        if (at - st.flushedAt >= READ_EVERY_MS) flushReader(st).catch(report);
        if (at - st.bankedAt >= LISTEN_EVERY_MS) bankPlayed(st).catch(report);
      }
      for (const st of films.values()) if (at - st.bankedAt >= LISTEN_EVERY_MS) bankFilm(st).catch(report);
      if (newSamples.size) writeSamples().catch(report);
    },

    /**
     * The way out (the page going): everything owed, sent without waiting for
     * an answer, as a page's last flush is (content/exposure.js _flushOut).
     */
    out() {
      const at = now();
      const fire = (message) => {
        try {
          Promise.resolve(ask(message)).catch(() => {});
        } catch {
          /* the page is going; there is nowhere left to say it */
        }
      };
      for (const st of readers.values()) {
        pay(st, at);
        const paid = {};
        for (const b of st.touched) if (b.paid > 0) paid[b.hash] = Math.round(b.paid * 10) / 10;
        if (st.owed || Object.keys(paid).length) {
          fire({ type: S.MSG.READ_WORDS, lang: st.lang, words: st.owed, docs: { [st.doc]: paid }, unit: st.unit });
        }
        st.owed = 0;
        st.touched.clear();
        if (st.heardMs >= MIN_BANK_MS) fire({ type: S.MSG.LISTEN_NARRATED, lang: st.lang, ms: Math.round(st.heardMs) });
        st.heardMs = 0;
      }
      for (const st of films.values()) {
        const title = filmName(st.title || '');
        for (const [lang, ms] of st.owed) if (ms >= MIN_BANK_MS) st.unsent.push({ lang, title, ms: Math.round(ms) });
        st.owed.clear();
        for (const chunk of st.unsent.splice(0)) fire({ type: S.MSG.LISTEN_LOCAL_VIDEO, ...chunk });
        for (const [lang, n] of st.cc) if (n > 0) fire({ type: S.MSG.READ_WORDS, lang, words: 0, cc: n, unit: S.paceUnit(lang) });
        st.cc.clear();
      }
    },

    /** For the tests, and the log: what is being followed now. */
    peek() {
      return {
        readers: [...readers.values()].map((st) => ({
          key: st.key, lang: st.lang, pace: st.pace, shown: st.shown, owed: st.owed, heardMs: st.heardMs,
          screen: st.screen.map((b) => ({ key: b.key, units: b.units, words: b.words, paid: b.paid, credited: b.credited })),
          win: st.win && { ...st.win },
        })),
        films: [...films.values()].map((st) => ({
          key: st.key, title: st.title, owed: Object.fromEntries(st.owed), held: st.held, cc: Object.fromEntries(st.cc),
          unsent: st.unsent.map((c) => ({ ...c })), byText: st.byText ?? null,
        })),
        samples: Object.fromEntries([...newSamples].map(([lang, v]) => [lang, [...v.rates]])),
      };
    },
  };
}
