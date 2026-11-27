// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
/*
 * An offline dictionary of the word panel's Look up key, in Sluka's own small
 * window (dictionaries.py): ?d= which (wiktionary, jmdict, cedict, cccanto,
 * folkets), &lang= the language, &q= the word, &k= its dictionary form, &w=
 * the language's name at Wiktionary.  Not yet installed: what it is, how large,
 * and Install -- downloaded from its makers' own site, read into Sluka's own
 * file, then the word.  Installed: the word's entries, and any other word typed
 * in.  Its foot says whose it is and under which licence, as that asks.
 */

const params = new URLSearchParams(location.search);
const id = params.get('d') || '';
const lang = params.get('lang') || '';
const wiki = params.get('w') || '';
const words = [params.get('q') || '', params.get('k') || ''].filter(Boolean);
const $ = (sel) => document.querySelector(sel);
const main = $('#main');

async function call(name, body) {
  const res = await fetch(`/__sluka__/api/dict/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, lang, ...(wiki ? { name: wiki } : {}), ...body }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};
const megabytes = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);

function foot(state) {
  const f = $('#foot');
  f.textContent = '';
  f.append(`${state.name} — ${state.by}. ${state.licence}. `);
  const a = el('a', '', 'About');
  a.href = state.home;
  a.target = '_blank';
  f.append(a);
  if (state.installed) {
    const drop = el('button', '', 'Remove');
    drop.title = 'Remove this dictionary from this computer';
    drop.onclick = async () => {
      await call('remove', {});
      show();
    };
    f.append(drop);
  }
}

function entries(list) {
  main.textContent = '';
  if (!list.length) {
    main.append(el('p', 'quiet', `${words[0] || 'That'} is not in this dictionary.`));
    return;
  }
  for (const e of list) {
    const box = el('section', 'entry');
    const head = el('div', 'head', e.head);
    if (e.reading) head.append(el('span', 'reading', e.reading));
    box.append(head);
    if (e.also?.length) box.append(el('div', 'also', e.also.join('、')));
    if (e.forms?.length) box.append(el('div', 'also', e.forms.join(', ')));
    const ol = el('ol');
    for (const s of e.senses || []) {
      const li = el('li');
      if (s.pos) li.append(el('span', 'pos', s.pos));
      li.append((s.glosses || []).join('; '));
      if (s.notes) li.append(el('span', 'notes', s.notes));
      ol.append(li);
    }
    box.append(ol);
    main.append(box);
  }
}

async function find(list) {
  const got = await call('lookup', { words: list }).catch(() => null);
  if (got?.ok) entries(got.entries || []);
  else main.replaceChildren(el('p', 'quiet', 'This dictionary could not be read.'));
}

async function offer(state) {
  main.textContent = '';
  main.append(el('p', '', `${state.name} is not on this computer yet. Install it to look words up here, offline: it is downloaded once, from its makers' own site, and nothing you look up leaves this computer.`));
  const size = el('p', 'quiet', 'Finding out how large it is…');
  const go = el('button', 'main', `Install ${state.name}`);
  main.append(size, go);
  call('size', {}).then((s) => {
    if (s?.offline) {
      // (Sluka is set to work offline: nothing to download until config.ini says otherwise)
      size.textContent = s.error || 'Sluka is set to work offline.';
      go.disabled = true;
      return;
    }
    size.textContent = s?.ok && s.size ? `About ${megabytes(s.size)} to download.` : (s?.ok ? '' : `Its site did not answer (${s?.error || 'no answer'}).`);
  }).catch(() => { size.textContent = ''; });
  go.onclick = async () => {
    go.disabled = true;
    await call('install', {});
    follow();
  };
}

async function follow() {
  const bar = el('div', 'bar');
  const fill = el('div');
  bar.append(fill);
  const said = el('p', 'quiet', 'Downloading…');
  main.replaceChildren(said, bar);
  for (;;) {
    const s = await call('state', {}).catch(() => null);
    const job = s?.job;
    if (s?.installed && (!job || job.state === 'ready')) return show();
    if (!job || job.state === 'failed') {
      main.replaceChildren(el('p', '', `It could not be installed: ${job?.error || 'no answer'}.`));
      const again = el('button', '', 'Try again');
      again.onclick = () => s && offer(s);
      main.append(again);
      return;
    }
    if (job.state === 'downloading') {
      said.textContent = job.size ? `Downloading… ${megabytes(job.got)} of ${megabytes(job.size)}` : `Downloading… ${megabytes(job.got || 0)}`;
      fill.style.width = job.size ? `${Math.min(100, (100 * job.got) / job.size)}%` : '15%';
    } else {
      said.textContent = `Reading it in… ${Number(job.entries || 0).toLocaleString()} entries`;
      fill.style.width = '100%';
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

async function show() {
  const state = await call('state', {}).catch(() => null);
  if (!state?.ok) {
    main.replaceChildren(el('p', 'quiet', 'This dictionary is not one Sluka can install.'));
    return;
  }
  $('#name').textContent = `${state.name} · offline${state.entries ? ` · ${Number(state.entries).toLocaleString()} entries` : ''}`;
  document.title = `${words[0] || state.name} — ${state.name}`;
  foot(state);
  if (state.job && ['downloading', 'reading'].includes(state.job.state)) return follow();
  if (!state.installed) return offer(state);
  return find(words);
}

$('#q').value = words[0] || '';
$('#find').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = $('#q').value.trim();
  if (!q) return;
  words.splice(0, words.length, q);
  show();
});
show();
