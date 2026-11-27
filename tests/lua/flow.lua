--[[
The script in a player, met by the app as on Windows: hello, ready (with the
faces the app looked up), a line and its words, a word pointed at, clicked,
graded, put away; a Japanese line; a long one that has to be broken; the
player closing.  Every message the script sends must reach the app, and no
callback may fail.

    texlua flow.lua /path/to/sluka.lua [windows|linux]
]]

local here = arg[0]:match('^(.*)[/\\]') or '.'
local H = dofile(here .. '/fake_mpv.lua')
local script = assert(arg[1], 'the script to run')
local platform = arg[2] or 'windows'

local failures = 0
local function check(ok, what)
    if ok then
        print('  ok   ' .. what)
    else
        failures = failures + 1
        print('  FAIL ' .. what)
    end
end

local function only(list, t)
    local out = {}
    for _, m in ipairs(list) do if m.t == t then out[#out + 1] = m end end
    return out
end

-- The player, before the script runs.
local tmp = os.getenv('SLUKA_TEST_TMP') or '/tmp'
COPY_FILE = 'Sluka-NotoSansJP-500-0a1b2c3d.ttf'
COPY_HERE = os.getenv('FAKE_COPY_HERE') == '1'
H.config_dir = tmp .. '/mpv'
H.listing = { [tmp .. '/mpv/fonts'] = COPY_HERE and { COPY_FILE, 'something-else.ttf' } or { 'something-else.ttf' } }
H.props['platform'] = platform
H.props['mpv-version'] = 'mpv 0.36.0'
H.props['options/input-ipc-server'] = ''
H.props['input-ipc-server'] = ''
H.props['sub-visibility'] = true
H.props['pause'] = false
H.props['sub-text'] = ''
H.props['current-tracks/sub/lang'] = 'eng'
H.props['current-tracks/sub/codec'] = 'ass'
H.props['display-hidpi-scale'] = 1
H.props['osd-dimensions'] = { w = 1920, h = 1080 }
H.props['path'] = 'F:\\videos\\episode.mkv'
H.env.LOCALAPPDATA = tmp
if platform == 'windows' then H.dirs[tmp .. '\\sluka-desktop\\mpv'] = true end

print('the script, loaded in a ' .. platform .. ' player')
H.load(script)
check(#H.errors == 0, 'it loads without an error')
if platform == 'windows' then
    check(tostring(H.props['options/input-ipc-server']):find('^\\\\%.\\pipe\\sluka%-mpv%-4242$') ~= nil,
        'it opens the pipe \\\\.\\pipe\\sluka-mpv-4242 (' .. tostring(H.props['options/input-ipc-server']) .. ')')
end

print('the app says hello')
H.app_says({ t = 'hello', app = '0.5.1' })
local said = H.said()
check(#H.errors == 0, 'no error while handling hello')
local hello = only(said, 'hello')[1]
check(hello ~= nil, 'the script answers hello')
check(hello and hello.v == 2 and hello.pid == 4242 and hello.sub_lang == 'eng', 'with its protocol, process and the track\'s language')

-- What the engine sends back (app/web/mpv-engine.js, look() and facesFor()).
local function face(name, wa, wd) return { name = name, wa = wa, wd = wd, ha = wa, hd = wd } end
local LOOK = {
    cjk = false, size = 1, pos = 8, bg = 0.84, light = false, line_height = 1.34, spacing = 0.01, spaced = true, anki_key = 'p', say_key = 'v', ask_key = 'f',
    fonts = { cc = { 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif' }, ui = { 'system-ui', 'Segoe UI', 'sans-serif' },
        word = { 'Georgia', 'Times New Roman', 'serif' } },
    font_lang = '', ui_font = 'Segoe UI', scale = 1,
    words = { ['0'] = { fill = { '3b82f6', 0.4 } }, ['1'] = { fill = { 'f7a800', 0.522 } }, ['2'] = { fill = { 'f7a800', 0.348 } },
        ['3'] = { fill = { 'f7a800', 0.209 }, line = 'f7a800' }, ['4'] = { line = 'f7a800' } },
    theme = 'dark',
    panel = { new = 'a7c7fb', levels = { 'facb66', 'fcdc99', 'fdeac2', 'fef5e0' }, lines = { 'a87200', 'a87200' }, fade = false, twin = 'ffb7df' },
    hover_delay = 0.12,
    keys = { ['0'] = '0', ['1'] = '1', ['2'] = '2', ['3'] = '3', ['4'] = '4', ['5'] = 'k', ['6'] = 'x' },
    text = {
        known = 'Known', ignore = 'Ignore', also = 'Also',
        labels = { ['0'] = 'New', ['1'] = 'Level 1', ['2'] = 'Level 2', ['3'] = 'Level 3', ['4'] = 'Level 4', ['5'] = 'Known', ['6'] = 'Ignored' },
        legend = { parts = { { { k = '1' }, '–', { k = '4' }, ' level' }, { { k = 'K' }, ' known' }, { { k = 'X' }, ' ignore' } },
            forget = { { k = '0' }, ' back to new' } },
    },
    faces = {
        cc = { P = face('Segoe UI', 1.0723, 0.2654), G = face('Segoe UI', 1.0723, 0.2654) },
        ui = { P = face('Segoe UI', 1.0723, 0.2654), G = face('Segoe UI', 1.0723, 0.2654) },
        word = { P = face('Georgia', 0.9171, 0.2192), G = face('Georgia', 0.9171, 0.2192) },
    },
}

print('the app is ready')
H.app_says({ t = 'ready', v = 2, lang = 'en', lang_name = 'English', quiet = false, look = LOOK })
check(#H.errors == 0, 'no error while handling ready')
local osd = H.osd[#H.osd]
check(osd and osd.text:find('Sluka: English', 1, true) ~= nil, 'the picture says Sluka is there (' .. tostring(osd and osd.text) .. ')')

print('a subtitle line')
H.set_prop('sub-text', 'Hello brave new world')
said = H.said()
local line = only(said, 'line')[1]
check(line ~= nil and line.text == 'Hello brave new world', 'the line goes to the app')
check(H.props['sub-visibility'] == false, 'mpv\'s own subtitle is hidden for it')
local toks = {
    { s = 0, e = 5, key = 'hello', st = 0 }, { s = 6, e = 11, key = 'brave', st = 1 },
    { s = 12, e = 15, key = 'new', st = 3 }, { s = 16, e = 21, key = 'world', st = 5 },
}
H.app_says({ t = 'tokens', id = line and line.id or 1, toks = toks })
check(#H.errors == 0, 'no error while drawing the line')
local ov_line, ov_card = H.overlays[1], H.overlays[2]
local drawn = ov_line.shown or ''
check(drawn:find('{=line-box}', 1, true) and drawn:find('{=line-text}', 1, true), 'the line is drawn: its box and its text')
local fills = select(2, drawn:gsub('{=fill}', ''))
check(fills == 3, 'three words wear a fill (new, 1, 3): ' .. fills)
check(drawn:find('\\fnSegoe UI', 1, true) ~= nil, 'in the face the app named')
local fx, fy = drawn:match('{=fill}{\\an7\\pos%(([%d%.]+),([%d%.]+)%)')
fx, fy = tonumber(fx), tonumber(fy)
check(fx ~= nil, 'the first word\'s box is found at ' .. tostring(fx) .. ',' .. tostring(fy))

print('the pointer on the first word')
H.mouse((fx or 0) + 4, (fy or 0) + 4)
check(H.props['pause'] == true, 'the video waits')
H.advance(0.3)
said = H.said()
local ask = only(said, 'lookup')[1]
check(ask ~= nil and ask.key == 'hello' and ask.text == 'Hello' and ask.tok == 1, 'its card is asked for')
local entry = {
    t = 'entry', id = line and line.id or 1, tok = 1, key = 'hello', st = 0, label = 'New',
    head = { { t = 'Hello' } }, reading = { { text = 'həˈləʊ' } }, lead = 'a greeting', more = { 'hi there' },
    senses = { 'used as a greeting', 'used to begin a telephone call' }, senses_more = 2,
    also = { { head = 'hullo', gloss = 'the same' } }, rank = 'among the 500 commonest', none = '',
    inflection = { form = 'Hello', why = 'capitalised' },
}
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the card')
check((ov_card.shown or '') ~= '', 'the card is drawn')

print('a click on the word')
H.press('MBTN_LEFT')
said = H.said()
local pin = only(said, 'lookup')[1]
check(pin ~= nil and pin.pin == true, 'its panel is asked for')
check(pin and pin.paused == true, 'saying the video is paused (a word is said by itself only then)')
entry.st, entry.label = 1, 'Level 1'
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the panel')
check((ov_card.shown or '') ~= '', 'the panel is drawn')
check(H.bindings['sluka-unpin'] ~= nil, 'Esc puts it away')

print('the key 2')
H.press('2')
said = H.said()
local g = only(said, 'grade')[1]
check(g ~= nil and g.status == 2 and g.key == 'hello', 'the word is graded 2')
H.app_says({ t = 'status', key = 'hello', st = 2, label = 'Level 2', graded = true })
check(#H.errors == 0, 'no error while showing the new level')

print('the panel\'s Anki key')
entry.anki = { state = 'add', title = 'Add to Anki, into Sluka::English (P)', key = 'p' }
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the panel with its Anki key')
check((ov_card.shown or ''):find('{=panel-anki}', 1, true) ~= nil, 'the Anki key is drawn in the head')
H.set_prop('media-title', 'A film')
H.set_prop('path', 'films/a film.mkv')
H.set_prop('working-directory', '/home/me')
H.set_prop('track-list', { { type = 'video', selected = true, ['src-id'] = 1 }, { type = 'audio', selected = true, ['src-id'] = 2 } })
H.press('p')
said = H.said()
local pick = only(said, 'anki')[1]
check(pick ~= nil and pick.key == 'hello' and pick.text == 'Hello' and pick.tok == 1, 'the word goes to Anki by its key')
check(pick and pick.path == '/home/me/films/a film.mkv' and pick.aid == 2 and pick.title == 'A film', 'with the file, its sound track, its title')
check(pick and type(pick.shot) == 'string' and pick.shot:find('^sluka%-shot%-') ~= nil, 'and the frame on screen')
local shot_cmd = nil
for _, c in ipairs(H.commands) do if c[1] == 'screenshot-to-file' then shot_cmd = c end end
check(shot_cmd ~= nil and shot_cmd[3] == 'video' and shot_cmd[2]:find(pick and pick.shot or '?', 1, true), 'taken without the subtitles')
H.app_says({ t = 'anki', id = entry.id, tok = 1, state = 'in', title = 'In Anki', key = 'p' })
check(#H.errors == 0, 'no error while showing it is in Anki')
check((ov_card.shown or ''):find('{=panel-anki-mark}', 1, true) ~= nil, 'the key shows the word is in Anki')
check((ov_card.shown or ''):find('22C55E', 1, true) ~= nil or (ov_card.shown or ''):find('5EC522', 1, true) ~= nil, 'in green')

print('the panel\'s Translate and Look up keys')
entry.anki = nil
entry.tools = { translate = { title = 'Translate' }, look = { title = 'Look up', offline = 'offline',
    links = { { id = 'wiktionary', name = 'Wiktionary', offline = 'wiktionary', installed = true }, { id = 'reverso', name = 'Reverso' } } } }
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the keys')
check((ov_card.shown or ''):find('{=panel-translate}', 1, true) ~= nil and (ov_card.shown or ''):find('{=panel-look}', 1, true) ~= nil, 'Translate and Look up drawn')
check((ov_card.shown or ''):find('{=panel-anki}', 1, true) == nil, 'no Anki key while it is off')
H.app_says({ t = 'translation', id = entry.id, tok = 1, ok = true, text = 'greetings', alternatives = { { pos = 'noun', terms = { 'hi' } } } })
check(#H.errors == 0, 'no error while showing the translation')
check((ov_card.shown or ''):find('greetings', 1, true) ~= nil and (ov_card.shown or ''):find('Google Translate', 1, true) ~= nil, 'Google\'s translation in the panel')
H.app_says(entry)
check((ov_card.shown or ''):find('greetings', 1, true) ~= nil, 'and kept while the word is told again')

print('the panel\'s speaker')
check((ov_card.shown or ''):find('{=panel-say}', 1, true) == nil, 'none where the engine offers no voice')
entry.tools.say = { title = 'Hear it (V)', icon = '<svg/>' }
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the speaker')
local drawn_card = ov_card.shown or ''
check(drawn_card:find('{=panel-say}', 1, true) ~= nil and drawn_card:find('{=panel-say-mark}', 1, true) ~= nil, 'the speaker drawn in the head')
H.press('v')
said = H.said()
local spoken = only(said, 'speak')[1]
check(spoken ~= nil and spoken.key == 'hello' and spoken.text == 'Hello' and spoken.tok == 1, 'V says the word')
H.app_says({ t = 'speaking', id = entry.id, tok = 1, on = true })
check(#H.errors == 0, 'no error while it is said')
check((ov_card.shown or ''):match('{=panel%-say}[^\n]-\\1a&H00&') ~= nil, 'lit while it is said')
H.app_says({ t = 'speaking', id = entry.id, tok = 1, on = false })
check((ov_card.shown or ''):match('{=panel%-say}[^\n]-\\1a&H00&') == nil, 'and put out after')

print('the AI check\'s key, and what it says')
check(H.bindings['sluka-ask-f'] ~= nil and H.bindings['sluka-ask-F'] ~= nil, 'F is the open panel\'s')
check((ov_card.shown or ''):find('{=panel-ask}', 1, true) == nil, 'no key where the check is off')
entry.tools.ask = { title = 'Ask AI to double-check. (F)', wanted = false, wait = 'Checking…',
    label = 'Ask AI if this is a real word (F)', why = 'Sends this word and its sentence to Anthropic.' }
H.app_says(entry)
check(#H.errors == 0, 'no error while drawing the key')
check((ov_card.shown or ''):find('{=panel-ask}', 1, true) ~= nil, 'the key among the head\'s keys')
H.press('f')
said = H.said()
local asked = only(said, 'ask')[1]
check(asked ~= nil and asked.key == 'hello' and asked.text == 'Hello' and asked.tok == 1, 'F asks the check about the word')
check((ov_card.shown or ''):find('Checking…', 1, true) ~= nil, 'the panel says it is checking')
check((ov_card.shown or ''):find('{=panel-ask}', 1, true) == nil, 'and the key is gone once asked')
H.press('f')
check(#only(H.said(), 'ask') == 0, 'asked once')
H.app_says({ t = 'verdict', id = entry.id, tok = 1, status = 'done',
    result = { verdict = 'established', confidence = 'high', meaning = 'a greeting', example = 'Hello there!', exampleTranslation = 'Salut !',
        reading = '', register = 'informal', breakdown = '', explanation = 'A common word.', ownAnswer = 'Here it greets.\n\nAlways a greeting.' },
    labels = { tag = 'Real word', confidence = 'high confidence', register = 'Used in', explanation = 'Why', own = 'Your question' } })
check(#H.errors == 0, 'no error while drawing the answer')
local shown = ov_card.shown or ''
check(shown:find('{=panel-vd-tag}', 1, true) ~= nil and shown:find('Real word', 1, true) ~= nil, 'what the check says of the word')
check(shown:find('Used in:', 1, true) ~= nil and shown:find('Hello there!', 1, true) ~= nil, 'where it is used, an example of it')
check(shown:find('Your question', 1, true) ~= nil and shown:find('Here it greets.', 1, true) ~= nil and shown:find('Always a greeting.', 1, true) ~= nil,
    'and the answer to your own request')
check(shown:find('used as a greeting', 1, true) ~= nil and shown:find('used as a greeting', 1, true) < shown:find('Real word', 1, true),
    'under the meanings')
H.app_says(entry)
check((ov_card.shown or ''):find('Real word', 1, true) ~= nil, 'kept while the word is told again')

print('the check where no dictionary has the word: its button')
H.app_says({ t = 'verdict', id = entry.id, tok = 1, status = 'error', error = 'The AI check is turned off in Settings.' })
entry.tools.ask.wanted = true
H.app_says(entry)
shown = ov_card.shown or ''
check(#H.errors == 0, 'no error while drawing the button')
check(shown:find('{=panel-ask-error}', 1, true) ~= nil and shown:find('turned off in', 1, true) ~= nil, 'what went wrong said')
check(shown:find('{=panel-ask-go}', 1, true) ~= nil and shown:find('{=panel-ask}', 1, true) == nil, 'a button in the meanings, not a key in the head')
check(shown:find('{=panel-ask-why}', 1, true) ~= nil and shown:find('Sends this word and its sentence to', 1, true) ~= nil, 'with what pressing it sends')
local gx, gy = shown:match('{=panel%-ask%-go}{\\an7\\pos%(([%d%.]+),([%d%.]+)%)')
H.mouse(tonumber(gx or 0) + 20, tonumber(gy or 0) + 10)
H.press('MBTN_LEFT')
asked = only(H.said(), 'ask')[1]
check(asked ~= nil and asked.key == 'hello', 'a click on it asks')
entry.tools.ask = nil

print('your own dictionaries')
entry.own = { place = 'replace', dicts = { { title = 'Jitendex', hits = { { head = 'hello', reading = 'hə', senses = { 'a word of greeting', 'a call for attention' } } } } } }
H.app_says(entry)
shown = ov_card.shown or ''
check(#H.errors == 0, 'no error while drawing them')
check(shown:find('{=panel-own-name}', 1, true) ~= nil and shown:find('Jitendex', 1, true) ~= nil, 'under the dictionary\'s name')
check(shown:find('a word of greeting', 1, true) ~= nil and shown:find('used as a greeting', 1, true) == nil, 'instead of Sluka\'s meanings')
entry.own.place = 'below'
H.app_says(entry)
shown = ov_card.shown or ''
check((shown:find('used as a greeting', 1, true) or 1e9) < (shown:find('a word of greeting', 1, true) or 0), 'or under them')
entry.own.place = 'above'
H.app_says(entry)
shown = ov_card.shown or ''
check((shown:find('a word of greeting', 1, true) or 1e9) < (shown:find('used as a greeting', 1, true) or 0), 'or above them')
entry.own = nil
H.app_says(entry)

print('Esc, and the pointer away')
H.press('ESC')
check(H.bindings['sluka-ask-f'] == nil and H.bindings['sluka-ask-F'] == nil, 'F is mpv\'s again once the panel is put away')
H.mouse(5, 5)
check(#H.errors == 0, 'no error')
check(H.props['pause'] == false, 'the video goes on')

print('the line ends')
H.set_prop('sub-text', '')
check(ov_line.shown == nil, 'nothing is drawn')

print('a cue with a break of its own, as Sluka shows it: on one row')
H.set_prop('sub-text', '')
H.set_prop('sub-text', 'Hello brave\nnew world')
said = H.said()
line = only(said, 'line')[1]
H.app_says({ t = 'tokens', id = line and line.id or 0, toks = {
    { s = 0, e = 5, key = 'hello', st = 0 }, { s = 6, e = 11, key = 'brave', st = 3 }, { s = 12, e = 15, key = 'new', st = 4 }, { s = 16, e = 21, key = 'world', st = 1 } } })
drawn = ov_line.shown or ''
check(select(2, drawn:gsub('{=line%-text}', '')) == 1, 'one row, the break a space')
check(drawn:find('brave new', 1, true) ~= nil or drawn:find('brave}{', 1, true) == nil, 'with a space where the break was')
check(drawn:find('{=level-line}', 1, true) and drawn:find('\\clip(', 1, true), 'a level 3 and 4 word: a line under it that follows its corners')
check(select(2, drawn:gsub('{=level%-side}', '')) == 2, 'and the level 4 word, which has no fill: a hairline at each side')

print('a long line, broken into rows')
local long = 'This is a rather long line of a film that will not fit on one row of the picture at all, whatever the size'
H.set_prop('sub-text', long)
said = H.said()
line = only(said, 'line')[1]
toks = {}
local at = 0
for word in long:gmatch('%S+') do
    local s = long:find(word, at + 1, true) - 1
    toks[#toks + 1] = { s = s, e = s + #word, key = word:lower():gsub('%p', ''), st = 0 }
    at = s + #word
end
H.app_says({ t = 'tokens', id = line and line.id or 0, toks = toks })
drawn = ov_line.shown or ''
check(#H.errors == 0, 'no error while laying out')
check(select(2, drawn:gsub('{=line%-text}', '')) >= 2, 'in two rows or more')

print('a Japanese line')
LOOK.cjk, LOOK.spaced, LOOK.font_lang, LOOK.line_height = true, false, 'ja', 1.42
LOOK.fonts.cc = { 'Noto Sans JP', 'Yu Gothic UI', 'Meiryo', 'system-ui', 'sans-serif' }
-- Windows 11's Noto Sans JP is a variable face: the app planned a plain copy of it at 500 (winfonts.py, plan).
local noto = face('Noto Sans JP', 1.448, 0.0)
noto.wd = 0.288
noto.w = { ['500'] = { n = 'Sluka Noto Sans JP 500', b = 500, file = COPY_FILE, via = { n = 'Noto Sans JP', b = 500, x = 0.0394 } } }
LOOK.faces.cc = { P = noto, G = noto }
local ui = face('Segoe UI', 1.0723, 0.2654)
ui.w = { ['400'] = { n = 'Segoe UI', b = 400 }, ['500'] = { n = 'Segoe UI', b = 400 }, ['600'] = { n = 'Segoe UI Semibold', b = 600 } }
LOOK.faces.ui = { P = ui, G = ui }
H.app_says({ t = 'ready', v = 2, lang = 'ja', lang_name = 'Japanese', quiet = true, look = LOOK })
H.said()
local ja = '今日はいい\n天気ですね'
H.set_prop('sub-text', ja)
said = H.said()
line = only(said, 'line')[1]
check(line ~= nil and line.text == ja, 'it goes to the app as UTF-8')
H.app_says({ t = 'tokens', id = line and line.id or 0, toks = { { s = 0, e = 6, key = '今日', st = 0 }, { s = 6, e = 9, key = 'は', st = 6, g = true },
    { s = 9, e = 15, key = 'いい', st = 2 }, { s = 16, e = 22, key = '天気', st = 4 } } })
drawn = ov_line.shown or ''
check(select(2, drawn:gsub('{=line%-text}', '')) == 1, 'its break gone between two Japanese letters: one row')
check(drawn:find('い 天', 1, true) == nil, 'with no space put in')
check(#H.errors == 0, 'no error while drawing it')
if COPY_HERE then
    check(drawn:find('\\fnSluka Noto Sans JP 500\\b500\\fs', 1, true) ~= nil, 'its letters in the plain copy at 500 this player has')
else
    check(drawn:find('\\fnNoto Sans JP\\b500\\bord0.88\\fs', 1, true) ~= nil, 'its letters in the variable face, thickened: the copy came after this player')
    check(drawn:find('\\3c&HFFFFFF&', 1, true) ~= nil, 'by a border in the letters\' own colour')
end
-- A word pointed at: the card's lead (600) in Segoe UI Semibold, as a browser has it.
local jx, jy = drawn:match('{=fill}{\\an7\\pos%(([%d%.]+),([%d%.]+)%)')
H.mouse((tonumber(jx) or 0) + 4, (tonumber(jy) or 0) + 4)
H.advance(0.3)
said = H.said()
local jask = only(said, 'lookup')[1]
H.app_says({ t = 'entry', id = line and line.id or 0, tok = jask and jask.tok or 1, key = '今日', st = 0, label = 'New',
    head = { { t = '今日', r = 'きょう' } }, reading = { { text = 'kyou' } }, lead = 'today', more = { 'this day' }, senses = { 'today' }, also = {}, rank = '', none = '' })
check((ov_card.shown or ''):find('\\fnSegoe UI Semibold\\b600', 1, true) ~= nil, 'the card\'s lead in Segoe UI Semibold at 600')
check(#H.errors == 0, 'no error while drawing that card')
H.mouse(5, 5)

print('another track, and the player closing')
H.set_prop('current-tracks/sub/lang', 'jpn')
said = H.said()
check(only(said, 'track')[1] ~= nil, 'the app is told of the other track')
H.event('shutdown')
said = H.said()
check(only(said, 'bye')[1] ~= nil, 'and that the player is gone')
check(H.props['sub-visibility'] == true, 'mpv\'s own subtitles are as they were')

if #H.errors > 0 then
    print('errors inside the script:')
    for _, e in ipairs(H.errors) do print('  ' .. e) end
end
for _, l in ipairs(H.log) do
    if l:find('error', 1, true) or l:find('could not', 1, true) then print('  (script said) ' .. l) end
end
print(failures == 0 and #H.errors == 0 and 'ALL GOOD' or (failures .. ' failed'))
os.exit((failures == 0 and #H.errors == 0) and 0 or 1)
