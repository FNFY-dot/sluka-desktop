-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (c) 2026 Sluka.  Part of Sluka Desktop.
--
-- This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
-- License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
-- version.
--
-- This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
-- warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
--
-- You should have received a copy of the GNU General Public License along with this program (LICENSES\GPL-3.0.txt, in
-- Sluka Desktop's folder).  If not, see <https://www.gnu.org/licenses/>.
--[[
Sluka subtitles inside mpv.

With Sluka Desktop running, this script draws the current subtitle line itself,
as Sluka draws it over a video in a browser: the same dark box, the same face
and size for the window, every word coloured by how well you know it.  Point at
a word for Sluka's small card; click it for the panel with its levels.

    point at a word     its card: the word, its reading, what it means
                        (and the video waits while you read)
    click a word        its panel: the dictionary's meanings and the levels;
                        a new word becomes level 1, as a click does in Sluka
    in the panel        click a level, Known or Ignore; the cross, Esc or a
                        click elsewhere puts it away
    1 2 3 4             learning, level 1 to 4        } on the word pointed
    k                   known                          } at, or the one
    x                   ignore                         } whose panel is open
    0                   back to new                    }
    F7                  Sluka's subtitles on and off
    F6                  pause at the end of every line, on and off
    F5                  say the line again

The words, their levels, the dictionary and the look all belong to the app:
this script only draws, and asks.  It talks to the app through mpv's own IPC
socket, which it opens in a folder only you can read, so nothing here uses the
network.  The fonts are the ones Sluka's own stylesheet asks for, looked up on
this computer the way a browser looks them up (fc-list and fc-match), so the
line in mpv is set in the face the same line has in Sluka's own pages.

Without the app running the script does nothing, and mpv shows its own
subtitles as always.  When the app is started later, it finds this player and
the subtitles change over.

The app puts this script where mpv and Celluloid look for scripts each time it
starts ([mpv] attach in its config.ini), so that any video opened in them is
seen -- also where the player is a Flatpak, as Celluloid is in Tails, and can
read no folder but its own.  By hand:   mpv --script=/path/to/sluka.lua FILE

Options (script-opts/sluka.conf, or --script-opts=sluka-NAME=VALUE):
see the table right below.
]]

local mp = require 'mp'
local utils = require 'mp.utils'
local msg = require 'mp.msg'
local options = require 'mp.options'

local o = {
    enabled = true,          -- draw Sluka's subtitles when the app is there
    socket_dir = '',         -- folder for the socket; empty: $XDG_RUNTIME_DIR/sluka-mpv (in a Flatpak: the app's own folder there)
    scale = 1.0,             -- everything Sluka draws, larger or smaller: 1.25 is a quarter larger (at 1, the app's own [mpv] scale)
    font = '',               -- a face of your own for the line; empty: the one Sluka's settings choose
    font_size = 0,           -- the line's size in pixels; 0: Sluka's own for the window (its Size setting)
    bottom_margin = -1,      -- the line's distance from the bottom in pixels; -1: Sluka's own (its Position setting)
    max_width = 0.88,        -- widest the line may be, as a share of the picture (Sluka's own)
    pause_on_hover = true,   -- hold the video while the pointer is on a word
    auto_pause = false,      -- stop at the end of every line
    key_toggle = 'F7',
    key_auto_pause = 'F6',
    key_replay = 'F5',
    -- From before the look was Sluka's own; read so that an old sluka.conf is no error, and not used.
    highlight = '',
    popup_font_size = 0,
    popup_max_chars = 0,
}
options.read_options(o, 'sluka')

local VERSION = '0.7'
local PROTOCOL = 2

--[[
One copy per player.  The script can be found twice: in the player's scripts
folder, where the app puts it, and on the command line, where "sluka mpv FILE"
names it.  mpv calls the second of two scripts with one name "sluka2"; that one
steps aside.  (Newer mpv also lets scripts leave each other a note.)
]]
local script_name = mp.get_script_name() or 'sluka'
if script_name:match('^sluka%d+$') or mp.get_property_native('user-data/sluka/script') ~= nil then
    msg.verbose('Sluka\'s script is already at work in this player')
    return
end
pcall(mp.set_property_native, 'user-data/sluka/script', script_name)

--[[
A few lines about what the script met, for the app's log: a player opened from
the desktop has no terminal to say them in.  They are written beside the
socket, where the app reads them.  No file name or title is ever among them.
]]
local notes = { file = nil, early = {}, count = 0 }
local function note(text)
    msg.info(text)
    local entry = os.date('%H:%M:%S') .. ' ' .. text
    if not notes.file then
        if #notes.early < 40 then notes.early[#notes.early + 1] = entry end
        return
    end
    if notes.count >= 300 then return end
    local f = io.open(notes.file, 'a')
    if not f then return end
    notes.count = notes.count + 1
    f:write('[' .. tostring(utils.getpid()) .. '] ' .. entry .. '\n')
    f:close()
end
local function notes_go_to(path)
    notes.file = path
    local early = notes.early
    notes.early = {}
    for _, entry in ipairs(early) do
        local f = io.open(path, 'a')
        if not f then return end
        notes.count = notes.count + 1
        f:write('[' .. tostring(utils.getpid()) .. '] ' .. entry .. '\n')
        f:close()
    end
end
note(string.format('Sluka script %s in %s, %s%s, as "%s"', VERSION, mp.get_property('mpv-version') or 'mpv ?',
    _VERSION or 'Lua ?', (type(jit) == 'table' and jit.version) and (' (' .. jit.version .. ')') or '', script_name))
-- Sluka's word levels (lib/constants.js STATUS).
local NEW, L1, L4, KNOWN, IGNORED, LINKED = 0, 1, 4, 5, 6, 7
-- How long tokens for a line may take before the line is shown plain.
local PLAIN_AFTER = 0.15
-- A line the app never answered for means the app is gone.
local GONE_AFTER = 3.0

local unpack = table.unpack or unpack

----------------------------------------------------------------- state

local app = {
    ready = false,      -- the app answered and said which language
    lang = '',
    lang_name = '',
}

local state = {
    enabled = o.enabled,
    auto_pause = o.auto_pause,
    line = nil,            -- the subtitle line on screen, see new_line()
    line_seq = 0,
    hover = nil,           -- index of the token under the pointer
    pinned = nil,          -- index of the token whose panel a click opened
    popup = nil,           -- the entry shown, as the app sent it
    card = nil,            -- where the card or panel was drawn, and what in it can be clicked
    we_paused = false,     -- the pause is ours, to be taken back
    saved_visibility = nil,
    waiting_since = nil,   -- when the oldest unanswered line was sent
    mouse = { x = -1, y = -1, inside = false },
    socket_file = nil,
    pointer_file = nil,
}

local ov_line = mp.create_osd_overlay('ass-events')
local ov_card = mp.create_osd_overlay('ass-events')
local ov_measure = mp.create_osd_overlay('ass-events')
ov_line.z, ov_card.z = 10, 12

local plain_timer, dwell_timer, gone_timer

----------------------------------------------------------------- small things

-- Windows has pipes where other systems have sockets, and no fontconfig to ask about faces.
local WINDOWS = (mp.get_property('platform') or '') == 'windows' or tostring(package.config or '/'):sub(1, 1) == '\\'
local SEP = WINDOWS and '\\' or '/'

local function run(args)
    local r = mp.command_native({ name = 'subprocess', args = args, playback_only = false, capture_stdout = true, capture_stderr = true })
    if not r or r.status ~= 0 then return nil end
    local out = (r.stdout or ''):gsub('%s+$', '')
    return out
end

--[[
What is drawn is measured in the pixels a web page counts in, so that Sluka's
own sizes can be used as they are: a window's pixels, less the screen's scaling
(and the scale option).  The overlays are given exactly that many units, so on
an ordinary screen one unit is one pixel and nothing drawn is resampled.
]]
local U = { w = 1280, h = 720, k = 1 }
-- The scale the app's own settings ask for ([mpv] scale in its config.ini); the script's option, when set, comes first.
local app_scale = 1
-- What Windows has the player's screen at, as the app said (handlers.ready); nil where it said nothing.
local screen_dpi = nil
local function units()
    local ow, oh = mp.get_osd_size()
    if not ow or not oh or ow <= 0 or oh <= 0 then ow, oh = 1280, 720 end
    local hidpi = mp.get_property_number('display-hidpi-scale', 1) or 1
    if hidpi <= 0 then hidpi = 1 end
    -- An mpv that does not scale itself for the screen (hidpi-window-scale off) says 1 whatever it is; the app
    -- told what Windows has the screen at, which is what Sluka's pages are drawn at.
    if hidpi == 1 and screen_dpi and screen_dpi > 1 and screen_dpi <= 4 then hidpi = screen_dpi end
    local scale = (o.scale and o.scale > 0) and o.scale or 1
    if scale == 1 then scale = app_scale end
    local k = hidpi * scale
    local w, h = math.max(16, math.floor(ow / k + 0.5)), math.max(16, math.floor(oh / k + 0.5))
    local changed = (w ~= U.w or h ~= U.h or k ~= U.k)
    U.w, U.h, U.k = w, h, k
    return changed
end

local function round(v) return math.floor(v + 0.5) end

local function ass_escape(s)
    -- A backslash is kept from starting a tag by a zero-width space after it, as mpv's own scripts do.
    s = s:gsub('\\', '\\\239\187\191')
    s = s:gsub('{', '\\{')
    s = s:gsub('}', '\\}')
    s = s:gsub('\r', '')
    s = s:gsub('\n', ' ')
    -- A space at either end is not dropped by the renderer when it is a hard one.
    s = s:gsub('^ ', '\\h'):gsub(' $', '\\h')
    return s
end

-- RRGGBB as the web writes it -> BBGGRR as ASS wants it.
local function bgr(rgb)
    rgb = tostring(rgb or 'ffffff')
    rgb = rgb:gsub('^#', '')
    if #rgb ~= 6 or rgb:find('[^%x]') then return 'FFFFFF' end
    return (rgb:sub(5, 6) .. rgb:sub(3, 4) .. rgb:sub(1, 2)):upper()
end

-- Opacity 0..1 -> the ASS alpha byte (00 opaque, FF clear).
local function ass_alpha(opacity)
    local a = math.floor((1 - math.max(0, math.min(1, opacity or 0))) * 255 + 0.5)
    return string.format('%02X', a)
end

local function num(n)
    local s = string.format('%.2f', n)
    s = s:gsub('0+$', ''):gsub('%.$', '')
    return s
end

-- One character of UTF-8 at a time.
local UTF8_CHAR = '[\1-\127\194-\244][\128-\191]*'
local function chars(s)
    local _, n = s:gsub('[^\128-\191]', '')
    return n
end

--[[
A message to the app.  mpv's format_json answers with two values -- the text,
and nil or what went wrong -- and commandv takes every value it is handed as
one more argument, refusing a nil ("argument 4 is not a string", mpv 0.36):
so only the text is passed on.  Some builds answer with the text alone, as
the players on Tails evidently did: there the old way went unnoticed.
]]
local function send(m)
    local json, err = utils.format_json(m)
    if type(json) ~= 'string' then
        note('a message to the app could not be written (' .. tostring(m and m.t) .. '): ' .. tostring(err))
        return false
    end
    mp.commandv('script-message', 'sluka-mpv', json)
    return true
end

----------------------------------------------------------------- how Sluka looks

--[[
As the app describes it when it answers (handlers.ready), from Sluka's own
settings; until it has, Sluka's defaults.  The numbers further down that are
not here -- paddings, sizes of the card's parts, its colours -- are those of
Sluka's stylesheets (content/content.css for the line, content/ui.js for the
card and the panel), which the app has no need to send.
]]
local look = {
    cjk = false,             -- a writing set at the full size and on taller rows
    size = 1,                -- SlukaCC's Size: 0.82, 1, 1.2, 1.42
    pos = 8,                 -- its Position: the line's distance from the bottom, in hundredths of the height
    bg = 0.84,               -- its Background: how solid the box is
    light = false,           -- black letters on a white box
    line_height = 1.34,
    spacing = 0.01,          -- between letters, in ems
    spaced = true,           -- whether words stand apart by spaces: a line of ones that do not breaks between any two
    fonts = { cc = { 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif' }, ui = { 'system-ui', 'sans-serif' }, word = { 'Georgia', 'Times New Roman', 'serif' } },
    font_lang = '',          -- what fontconfig calls the language, where a Latin face does not hold its writing
    ui_font = '',            -- the desktop's own font, which is what system-ui means
    theme = 'light',
    words = {                -- what a word of the line wears at each level
        [0] = { fill = { '3b82f6', 0.4 } }, [1] = { fill = { 'f7a800', 0.522 } }, [2] = { fill = { 'f7a800', 0.348 } },
        [3] = { fill = { 'f7a800', 0.209 }, line = 'f7a800' }, [4] = { line = 'f7a800' },
    },
    panel = { new = 'a7c7fb', levels = { 'facb66', 'fcdc99', 'fdeac2', 'fef5e0' }, lines = { 'a87200', 'a87200' }, fade = false },
    hover_delay = 0.12,
    keys = { [0] = '0', [1] = '1', [2] = '2', [3] = '3', [4] = '4', [5] = 'k', [6] = 'x' },
    anki_key = '',           -- the panel's Anki key, while Settings → Anki has the panel's button on ('' otherwise)
    say_key = '',            -- the key that says the open word (Settings → Keyboard, V), where there is a voice
    ask_key = '',            -- the AI check's key for the open panel (Settings → Keyboard, F), where the check is on
    text = { known = 'Known', ignore = 'Ignore', labels = {}, legend = nil },
}

local function by_number(t)
    local out = {}
    for k, v in pairs(t) do
        local n = tonumber(k)
        if n then out[n] = v end
    end
    return out
end

local function adopt_look(l)
    if type(l) ~= 'table' then return end
    for _, k in ipairs({ 'cjk', 'light', 'spaced' }) do
        if type(l[k]) == 'boolean' then look[k] = l[k] end
    end
    for _, k in ipairs({ 'size', 'pos', 'bg', 'line_height', 'spacing', 'hover_delay' }) do
        if type(l[k]) == 'number' then look[k] = l[k] end
    end
    app_scale = (type(l.scale) == 'number' and l.scale >= 0.5 and l.scale <= 4) and l.scale or 1
    screen_dpi = type(l.dpi) == 'number' and l.dpi or nil
    look.engine = type(l.engine) == 'string' and l.engine or ''
    for _, k in ipairs({ 'font_lang', 'ui_font', 'theme' }) do
        if type(l[k]) == 'string' then look[k] = l[k] end
    end
    if type(l.fonts) == 'table' then
        for _, k in ipairs({ 'cc', 'ui', 'word' }) do
            if type(l.fonts[k]) == 'table' and #l.fonts[k] > 0 then look.fonts[k] = l.fonts[k] end
        end
    end
    -- Where there is no fontconfig to ask (Windows), the app has looked the faces up itself.
    look.app_faces = type(l.faces) == 'table' and l.faces or nil
    if type(l.words) == 'table' then look.words = by_number(l.words) end
    if type(l.panel) == 'table' and type(l.panel.levels) == 'table' then look.panel = l.panel end
    if type(l.keys) == 'table' then
        local keys = by_number(l.keys)
        for st, key in pairs(keys) do
            if type(key) == 'string' and #key == 1 then look.keys[st] = key end
        end
    end
    look.anki_key = (type(l.anki_key) == 'string' and #l.anki_key <= 1) and l.anki_key or ''
    look.say_key = (type(l.say_key) == 'string' and #l.say_key <= 1) and l.say_key or ''
    look.ask_key = (type(l.ask_key) == 'string' and #l.ask_key <= 1) and l.ask_key or ''
    if type(l.text) == 'table' then
        look.text = {
            known = type(l.text.known) == 'string' and l.text.known or 'Known',
            ignore = type(l.text.ignore) == 'string' and l.text.ignore or 'Ignore',
            labels = type(l.text.labels) == 'table' and by_number(l.text.labels) or {},
            also = type(l.text.also) == 'string' and l.text.also or nil,
            legend = type(l.text.legend) == 'table' and l.text.legend or nil,
        }
    end
end

-- The card's two palettes (content/ui.js, .theme and .theme[data-theme="light"]).
local THEMES = {
    light = {
        bg = 'ffffff', ring = '21201c', ring_a = 0.14, ring_small_a = 0.12, shade = '21201c', shade_a = 0.14, shade_small_a = 0.12, shade_near_a = 0.06,
        ink = '21201c', body = '34332e', quiet = '46453f', ink2 = '53524c', ink3 = '63625c', reading = '2459c7', inflection = '58634c',
        chip = '21201c', chip_a = 0.06, edge_a = 0.52, kbd_a = 0.04, kbd_edge_a = 0.18, on = '21201c', on_ink = 'ffffff',
        known_dot = '1f9a57', dot_ring_a = 0.22, swatch_edge_a = 0.35, lit_shade_a = 0.35, lit_edge_a = 0.12, hair_a = 0.09,
        accent = '2459c7', btn_ink = '21201c', danger = 'c02b1c', caution_soft = '7a4f00', narrow = 'f7a800',
    },
    dark = {
        bg = '222221', ring = 'ffffff', ring_a = 0.24, ring_small_a = 0.2, shade = '000000', shade_a = 0.36, shade_small_a = 0.32, shade_near_a = 0.3,
        ink = 'f2f0eb', body = 'dedbd4', quiet = 'd6d3cc', ink2 = 'b5b3ad', ink3 = '9a9891', reading = '7ea8ff', inflection = 'b3bda6',
        chip = 'ffffff', chip_a = 0.07, edge_a = 0.46, kbd_a = 0.06, kbd_edge_a = 0.12, on = 'f2f0eb', on_ink = '1a1815',
        known_dot = '5cc98a', dot_ring_a = 0, swatch_edge_a = 0.25, lit_shade_a = 0.5, lit_edge_a = 0.12, hair_a = 0.08,
        accent = '6b9bff', btn_ink = 'e6e3dc', danger = 'ff9c8a', caution_soft = 'ffd46b', narrow = 'ffc43c',
    },
}
-- The same in both: the paper a level's swatch is drawn on, and the filled Known and Ignore.
local PAPER, PAPER_INK, KNOWN_FILL, IGNORE_FILL = 'ffffff', '1a1815', '1a7d44', '5f5d57'
-- The AI check's "Not a word" (content/ui.js --sl-refused), the same in both.
local REFUSED = 'cc3339'

local function theme()
    return THEMES[look.theme] or THEMES.light
end

----------------------------------------------------------------- the faces

--[[
A browser sets a line in the first face of its list that the computer has, and
draws what that face lacks -- kanji, in a Latin one -- in whichever face has
it for the language.  The same is done here, so that the line is the line of
Sluka's pages on this computer: `P` is the face the list comes to, whose
measures also say how tall a word's box is; `G` is the one that holds the
language's own letters.  Where they are two, Latin letters and figures are set
in P and the rest in G, as the browser has them.

fontconfig is asked through its own tools, which every desktop with fonts has.
Without them, the names are handed to the renderer as they are and the sizes
are estimated: the look is then close, not exact.

What a size means differs between the two worlds, and each face's own file
says by how much: the renderer scales a face so that its Windows ascent and
descent together are the size asked for, a web page so that the em is.  So
each face's numbers are read from its file: ascents and descents, per em.
]]
local fontdb = { families = nil, faces = {}, pairs = {}, told = {} }

--[[
The fonts in mpv's own fonts folder (~~/fonts), as they were when this player
started: its renderer reads that folder once, then.  The app puts plain copies
of variable faces there (see plan_for below); one made after this player
started is not in this player's renderer, so it is not asked for here.
]]
local fonts_here = {}
do
    local ok, dir = pcall(mp.command_native, { 'expand-path', '~~/fonts' })
    if ok and type(dir) == 'string' and dir ~= '' then
        for _, name in ipairs(utils.readdir(dir, 'files') or {}) do fonts_here[name] = true end
    end
end

local function u16(s, at)
    local a, b = s:byte(at + 1, at + 2)
    if not b then return nil end
    return a * 256 + b
end
local function i16(s, at)
    local v = u16(s, at)
    if not v then return nil end
    if v >= 32768 then v = v - 65536 end
    return v
end
local function u32(s, at)
    local a, b, c, d = s:byte(at + 1, at + 4)
    if not d then return nil end
    return ((a * 256 + b) * 256 + c) * 256 + d
end

--- A face's vertical measures from its file (TrueType or OpenType, alone or in a collection), per em; nil if it cannot be read.
local function read_metrics(path, index)
    local f = io.open(path, 'rb')
    if not f then return nil end
    local function at(offset, n)
        if not f:seek('set', offset) then return nil end
        local s = f:read(n)
        if not s or #s < n then return nil end
        return s
    end
    local ok, result = pcall(function()
        local base = 0
        local head = at(0, 12)
        if not head then return nil end
        if head:sub(1, 4) == 'ttcf' then
            local count = u32(head, 8)
            local i = (index or 0) % 65536
            if i >= count then i = 0 end
            local where = at(12 + 4 * i, 4)
            if not where then return nil end
            base = u32(where, 0)
            head = at(base, 12)
            if not head then return nil end
        end
        local n = u16(head, 4)
        if not n or n == 0 or n > 512 then return nil end
        local dir = at(base + 12, 16 * n)
        if not dir then return nil end
        local tables = {}
        for i = 0, n - 1 do
            tables[dir:sub(i * 16 + 1, i * 16 + 4)] = u32(dir, i * 16 + 8)
        end
        if not tables.head or not tables.hhea then return nil end
        local th, hh = at(tables.head, 20), at(tables.hhea, 8)
        if not th or not hh then return nil end
        local upm = u16(th, 18)
        if not upm or upm < 16 then return nil end
        local m = { ha = i16(hh, 4) / upm, hd = -i16(hh, 6) / upm }
        m.wa, m.wd = m.ha, m.hd
        local os2 = tables['OS/2'] and at(tables['OS/2'], 78)
        if os2 then
            local win_a, win_d = i16(os2, 74), i16(os2, 76)
            local typo_a, typo_d = i16(os2, 68), -i16(os2, 70)
            -- The renderer goes by the Windows numbers where the face has them.
            if win_a + win_d ~= 0 then m.wa, m.wd = win_a / upm, win_d / upm end
            -- A page goes by the horizontal header, unless the face says its typographic ones are the ones to use.
            local use_typo = math.floor(u16(os2, 62) / 128) % 2 == 1
            if use_typo or (m.ha == 0 and m.hd == 0) then
                if typo_a + typo_d ~= 0 then m.ha, m.hd = typo_a / upm, typo_d / upm end
            end
        end
        if m.wa + m.wd <= 0.2 or m.ha + m.hd <= 0.2 then return nil end
        return m
    end)
    f:close()
    if ok then return result end
    return nil
end

-- Measures for a face whose file could not be read: those of the faces most often met.
local GUESS = { latin = { wa = 0.97, wd = 0.25, ha = 0.95, hd = 0.24 }, cjk = { wa = 1.16, wd = 0.288, ha = 1.16, hd = 0.288 } }

local function clean_name(name)
    name = tostring(name or ''):gsub('\\(.)', '%1')
    name = name:gsub('[{}\\\r\n]', ''):gsub('^%s+', ''):gsub('%s+$', '')
    return name
end

-- A name inside a fontconfig pattern.
local function fc_quote(name)
    return (name:gsub('([\\%-:,=])', '\\%1'))
end

local function fc_match(pattern)
    local out = run({ 'fc-match', '-f', '%{family[0]}\n%{file}\n%{index}\n', pattern })
    if not out then return nil end
    local family, file, index = (out .. '\n'):match('^([^\n]*)\n([^\n]*)\n([^\n]*)')
    family = clean_name(family)
    if family == '' then return nil end
    return family, file, tonumber(index) or 0
end

local function load_families()
    local out = (not WINDOWS) and run({ 'fc-list', ':', 'family' }) or nil
    if not out or out == '' then
        fontdb.families = false
        return
    end
    local set = {}
    for row in out:gmatch('[^\n]+') do
        for name in row:gmatch('[^,]+') do
            name = clean_name(name)
            if name ~= '' then set[name:lower()] = name end
        end
    end
    fontdb.families = set
end

--- The face of a family, with its measures: read once.
local function face(name, file, index, cjk)
    local known = fontdb.faces[name]
    if known then return known end
    if not file and fontdb.families then
        local _, f, i = fc_match(fc_quote(name))
        file, index = f, i
    end
    local m = file and file ~= '' and read_metrics(file, index) or nil
    local out = { name = name, exact = m ~= nil }
    m = m or (cjk and GUESS.cjk or GUESS.latin)
    out.wa, out.wd, out.ha, out.hd = m.wa, m.wd, m.ha, m.hd
    fontdb.faces[name] = out
    return out
end

local GENERIC = { ['system-ui'] = 'ui', ['ui-sans-serif'] = 'ui', ['sans-serif'] = 'sans-serif', ['serif'] = 'serif', ['monospace'] = 'monospace',
    ['-apple-system'] = '', ['blinkmacsystemfont'] = '', ['ui-serif'] = 'serif', ['ui-monospace'] = 'monospace' }

--- The pair of faces a list of them comes to on this computer, for a language: { P = , G = }.
local function resolve(stack, lang, cjk)
    local key = table.concat(stack, '\1') .. '\2' .. lang .. '\2' .. look.ui_font
    local hit = fontdb.pairs[key]
    if hit then return hit end
    if fontdb.families == nil then load_families() end
    local families = fontdb.families

    -- Which kind the list falls back on, for the face that holds the language's letters.
    local kind = 'sans-serif'
    for _, name in ipairs(stack) do
        local g = GENERIC[tostring(name):lower()]
        if g and g ~= '' then
            kind = (g == 'ui') and 'sans-serif' or g
            break
        end
    end

    local P
    if families then
        for _, name in ipairs(stack) do
            local low = tostring(name):lower()
            local g = GENERIC[low]
            if g == nil then
                if families[low] then
                    P = face(families[low], nil, nil, cjk)
                    break
                end
            elseif g == 'ui' then
                -- The desktop's own font, as the app saw it set; else what fontconfig takes system-ui for.
                local ui = look.ui_font
                if ui ~= '' and families[ui:lower()] then
                    P = face(families[ui:lower()], nil, nil, cjk)
                else
                    local family, file, index = fc_match('system-ui')
                    if family then P = face(family, file, index, cjk) end
                end
                if P then break end
            elseif g ~= '' then
                local family, file, index = fc_match(g)
                if family then P = face(family, file, index, cjk) end
                if P then break end
            end
        end
    end
    -- No fontconfig to ask: the renderer is given the first face named (it knows the system's own), or
    -- else the generic name, and finds a face for it itself.
    if not P and not families then
        local first = tostring(stack[1] or ''):lower()
        if first ~= '' and GENERIC[first] == nil then P = face(tostring(stack[1]), '', 0, cjk) end
    end
    if not P then P = face(kind, '', 0, false) end

    local G = P
    if lang ~= '' and families then
        local covered = run({ 'fc-list', ':family=' .. fc_quote(P.name) .. ':lang=' .. lang, 'family' })
        if covered == '' then
            local family, file, index = fc_match(kind .. ':lang=' .. lang)
            if family then G = face(family, file, index, true) end
        end
    end
    local pair = { P = P, G = G }
    fontdb.pairs[key] = pair
    return pair
end

--- A pair of faces as the app found them for one of the three uses, with the measures it read from their files; nil if it sent none.
local function given(use)
    local sent = look.app_faces and look.app_faces[use]
    if type(sent) ~= 'table' or type(sent.P) ~= 'table' then return nil end
    local function one(f, cjk)
        local name = clean_name(f.name)
        if name == '' then return nil end
        local known = fontdb.faces['\1' .. name]
        if known then
            -- The same face for another use may be set in other weights: what the app says now of each is kept.
            if type(f.w) == 'table' then
                known.w = known.w or {}
                for weight, plan in pairs(f.w) do known.w[weight] = plan end
            end
            return known
        end
        local out = { name = name, exact = false, w = type(f.w) == 'table' and f.w or nil }
        local m = cjk and GUESS.cjk or GUESS.latin
        if type(f.wa) == 'number' and type(f.wd) == 'number' and type(f.ha) == 'number' and type(f.hd) == 'number'
            and f.wa + f.wd > 0.2 and f.ha + f.hd > 0.2 then
            m, out.exact = f, true
        end
        out.wa, out.wd, out.ha, out.hd = m.wa, m.wd, m.ha, m.hd
        fontdb.faces['\1' .. name] = out
        return out
    end
    local P = one(sent.P, false)
    if not P then return nil end
    local G = type(sent.G) == 'table' and one(sent.G, true) or P
    if G.name == P.name then G = P end
    return { P = P, G = G }
end

local F = nil   -- the faces in use: cc (the line), ui (the card), word (its headword)
local plan_for
local function faces()
    if F then return F end
    local cc_stack = look.fonts.cc
    if o.font ~= '' then
        cc_stack = { o.font }
        for _, name in ipairs(look.fonts.cc) do cc_stack[#cc_stack + 1] = name end
    end
    F = {
        cc = (o.font == '' and given('cc')) or resolve(cc_stack, look.font_lang, look.cjk),
        ui = given('ui') or resolve(look.fonts.ui, look.font_lang, look.cjk),
        word = given('word') or resolve(look.fonts.word, look.font_lang, look.cjk),
    }
    -- The card's own words are English or the reader's language: its Latin face draws them, and the
    -- language's face what it lacks.
    local said = string.format('%s%s | %s%s | %s%s', F.cc.P.name, F.cc.G ~= F.cc.P and ('+' .. F.cc.G.name) or '',
        F.ui.P.name, F.ui.G ~= F.ui.P and ('+' .. F.ui.G.name) or '', F.word.P.name, F.word.G ~= F.word.P and ('+' .. F.word.G.name) or '')
    if not fontdb.told[said] then
        fontdb.told[said] = true
        local exact = F.cc.G.exact and F.ui.P.exact and F.word.G.exact
        -- Where a face is drawn from another one than its own name says (another weight's, or the app's copy).
        local drawn, seen = {}, {}
        for _, it in ipairs({ { F.cc.P, 500 }, { F.cc.G, 500 }, { F.word.P, 400 }, { F.word.G, 400 } }) do
            local f, weight = it[1], it[2]
            local plan = plan_for(f, weight)
            local said_of = nil
            if plan.copy then said_of = plan.n .. ' (a plain copy the app made of a variable face)'
            elseif (plan.x or 0) > 0 then said_of = f.name .. ' at ' .. plan.b .. ', thickened (the plain copy the app makes of it is used from the next player)'
            elseif plan.n ~= f.name then said_of = plan.n end
            if said_of and not seen[said_of] then
                seen[said_of] = true
                drawn[#drawn + 1] = said_of
            end
        end
        note(string.format('faces (line | card | headword): %s%s%s', said, exact and '' or ((fontdb.families or look.app_faces) and '; a face\'s file could not be read, its sizes are estimated'
            or (WINDOWS and '; the app named no faces, so the renderer chooses them and sizes are estimated'
            or '; fontconfig\'s tools (fc-list, fc-match) did not answer, so faces and sizes are estimated')),
            #drawn > 0 and ('; drawn as ' .. table.concat(drawn, ', ')) or ''))
    end
    return F
end

--[[
How the renderer is to ask for face `f` at `weight`, as the app worked it out
(winfonts.py, plan): the face a browser draws at that weight -- by the older
family name Windows knows it by ("Segoe UI Semibold") -- or, for a variable
face, the plain copy of it at that weight the app made into mpv's fonts
folder, where this player's renderer has it; where it has not (the copy is
newer than the player), the variable face itself, made to look as thick by
`x` (a share of the size).  Without a plan: the face, at the weight.
]]
plan_for = function(f, weight)
    local plan = f.w and f.w[tostring(weight)]
    if type(plan) ~= 'table' or type(plan.n) ~= 'string' or plan.n == '' then return { n = f.name, b = weight } end
    if plan.file and not fonts_here[plan.file] then
        plan = type(plan.via) == 'table' and plan.via or { n = f.name, b = weight }
    end
    return { n = clean_name(plan.n), b = tonumber(plan.b) or weight, x = tonumber(plan.x), copy = plan.file ~= nil and fonts_here[plan.file] or false }
end

--- A page's whole pixels for a face at a size: how far it rises over the line it stands on, and how far it falls under it.
local function rise(f, E) return round(f.ha * E) end
local function fall(f, E) return round(f.hd * E) end

--[[
Text as the renderer is to draw it: in face `pair` at a web page's size `E`,
with the weight and letter spacing said.  Answers the text with its tags, and
how far over the baseline the renderer will put the top of the row -- which is
where it must be told to draw for the baseline to land where a page has it.
]]
local function styled(text, pair, E, weight, spacing, plain)
    local P, G = pair.P, pair.G
    weight = weight or 400
    local lead = string.format('\\fsp%s', num((spacing or 0) * E))
    -- Thickening (see plan_for) is a border in the letters' own colour; where the line has a dark edge round
    -- its letters instead (`plain`), there is room for only one of the two, and the edge is kept.
    local thick = not plain and ((plan_for(P, weight).x or 0) > 0 or (plan_for(G, weight).x or 0) > 0)
    local function tag(f, first)
        local plan = plan_for(f, weight)
        local border = thick and ('\\bord' .. num((plan.x or 0) * E / 2)) or ''
        return '{' .. (first and lead or '') .. '\\fn' .. plan.n .. '\\b' .. tostring(plan.b) .. border .. '\\fs' .. num(E * (f.wa + f.wd)) .. '}'
    end
    if P == G then return tag(P, true) .. ass_escape(text), P.wa * E end
    local out, run_face, buf = {}, nil, {}
    local used_p, used_g = false, false
    local function flush()
        if #buf == 0 then return end
        out[#out + 1] = tag(run_face, #out == 0) .. ass_escape(table.concat(buf))
        buf = {}
    end
    for ch in text:gmatch(UTF8_CHAR) do
        local b1, b2 = ch:byte(1, 2)
        -- Basic Latin to Latin Extended-B, and Latin Extended Additional: the Latin face's.
        local latin = b1 < 0xC9 or (b1 == 0xC9 and (b2 or 0) < 0x90) or (b1 == 0xE1 and (b2 == 0xB8 or b2 == 0xB9 or b2 == 0xBA or b2 == 0xBB))
        local f = latin and P or G
        if f ~= run_face then
            flush()
            run_face = f
        end
        if latin then used_p = true else used_g = true end
        buf[#buf + 1] = ch
    end
    flush()
    if #out == 0 then return tag(P, true), P.wa * E end
    local asc = 0
    if used_p then asc = P.wa * E end
    if used_g then asc = math.max(asc, G.wa * E) end
    return table.concat(out), asc
end

----------------------------------------------------------------- measuring

--[[
How wide a piece of text is, by asking the renderer itself -- the only thing
that knows.  mpv answers with the box of what was drawn, and of that box only
the left and the top edge are exact (the renderer's pictures are padded on the
right and below).  So the text is set flush right against a fixed point,
between two bars: the left edge of the left bar then moves by exactly the
text's width, whatever the first and last letters' own margins are.  Short
texts are measured stretched several times wide, for a finer answer.
]]
local measured = { n = 0, refs = {} }
local BAR = '|'

--- The window measured anew; what was measured for another size of it is not kept, since mpv's answers go by the size it knows.
local function fresh_units()
    if not units() then return false end
    measured = { n = 0, refs = {} }
    return true
end

local function ink_left(data)
    ov_measure.res_x, ov_measure.res_y = U.w, U.h
    ov_measure.hidden = true
    ov_measure.compute_bounds = true
    ov_measure.data = data
    local r = ov_measure:update()
    if not r or not r.x0 or not r.x1 or r.x1 <= r.x0 then return nil end
    return r.x0
end

local function bar_tag()
    local f = faces().ui.P
    return '{\\b400\\fsp0\\fn' .. f.name .. '\\fs' .. num(24 * (f.wa + f.wd)) .. '}' .. BAR
end

local function width_at(body, stretch)
    local x = U.w - 2
    local head = string.format('{\\an9\\pos(%d,4)\\q2\\bord0\\shad0\\blur0\\i0\\fscx%d\\fscy100}', x, stretch * 100)
    local bar = bar_tag()
    local ref_key = bar .. stretch .. ':' .. U.w
    local ref = measured.refs[ref_key]
    if not ref then
        ref = ink_left(head .. bar .. bar)
        if not ref then return nil end
        measured.refs[ref_key] = ref
    end
    local left = ink_left(head .. bar .. body .. bar)
    if not left then return nil end
    -- At the picture's own left edge the drawing was cut off: it is wider than can be measured this way.
    if left <= 0.5 then return nil, true end
    return (ref - left) / stretch
end

--- The width of styled text (styled()'s), of `n` characters at size `E`.
local function advance(body, n, E)
    local hit = measured[body]
    if hit then return hit end
    local room = U.w - 40
    local stretch = math.max(1, math.min(8, math.floor(room / ((n * 1.2 + 2) * E))))
    local w, cut = width_at(body, stretch)
    if not w and cut and stretch > 1 then w = width_at(body, 1) end
    w = w or n * E * 0.6
    if measured.n > 6000 then
        local refs = measured.refs
        measured = { n = 0, refs = refs }
    end
    measured[body] = w
    measured.n = measured.n + 1
    return w
end

--- A piece of text ready to be drawn: its tags, its width, and the measures a page would lay it out by.
local function piece(text, pair, E, weight, spacing)
    local body, asc = styled(text, pair, E, weight, spacing)
    return { body = body, asc = asc, w = advance(body, chars(text), E), E = E, A = rise(pair.P, E), D = fall(pair.P, E) }
end

--- Where the baseline of a row `lh` tall stands under its top, for a piece: as a page centres the letters in the row.
local function base_in(p, lh)
    return (lh - (p.A + p.D)) / 2 + p.A
end

----------------------------------------------------------------- drawing

local function c8(v) return string.format('%d', math.floor(v * 8 + 0.5)) end

--- A rounded rectangle's outline at (x, y), in eighths; `reverse` runs it the other way round, for a hole in a shape.
local function rr_path(x, y, w, h, r, reverse)
    r = math.max(0, math.min(r or 0, w / 2, h / 2))
    local k = r * 0.5523
    local X, Y, W, H = x, y, x + w, y + h
    if not reverse then
        return table.concat({ 'm', c8(X + r), c8(Y), 'l', c8(W - r), c8(Y),
            'b', c8(W - r + k), c8(Y), c8(W), c8(Y + r - k), c8(W), c8(Y + r), 'l', c8(W), c8(H - r),
            'b', c8(W), c8(H - r + k), c8(W - r + k), c8(H), c8(W - r), c8(H), 'l', c8(X + r), c8(H),
            'b', c8(X + r - k), c8(H), c8(X), c8(H - r + k), c8(X), c8(H - r), 'l', c8(X), c8(Y + r),
            'b', c8(X), c8(Y + r - k), c8(X + r - k), c8(Y), c8(X + r), c8(Y) }, ' ')
    end
    return table.concat({ 'm', c8(X + r), c8(Y),
        'b', c8(X + r - k), c8(Y), c8(X), c8(Y + r - k), c8(X), c8(Y + r), 'l', c8(X), c8(H - r),
        'b', c8(X), c8(H - r + k), c8(X + r - k), c8(H), c8(X + r), c8(H), 'l', c8(W - r), c8(H),
        'b', c8(W - r + k), c8(H), c8(W), c8(H - r + k), c8(W), c8(H - r), 'l', c8(W), c8(Y + r),
        'b', c8(W), c8(Y + r - k), c8(W - r + k), c8(Y), c8(W - r), c8(Y), 'l', c8(X + r), c8(Y) }, ' ')
end

--- The outline of a box with rounded corners, in eighths of a unit.
local function round_box(w, h, r)
    r = math.max(0, math.min(r or 0, w / 2, h / 2))
    if r < 0.05 then
        return string.format('m 0 0 l %s 0 %s %s 0 %s', c8(w), c8(w), c8(h), c8(h))
    end
    local k = r * 0.5523
    return table.concat({
        'm', c8(r), '0',
        'l', c8(w - r), '0',
        'b', c8(w - r + k), '0', c8(w), c8(r - k), c8(w), c8(r),
        'l', c8(w), c8(h - r),
        'b', c8(w), c8(h - r + k), c8(w - r + k), c8(h), c8(w - r), c8(h),
        'l', c8(r), c8(h),
        'b', c8(r - k), c8(h), '0', c8(h - r + k), '0', c8(h - r),
        'l', '0', c8(r),
        'b', '0', c8(r - k), c8(r - k), '0', c8(r), '0',
    }, ' ')
end

--[[
One thing drawn: a box (rounded by `r`), filled, or -- with `ring` -- only a
line of that width round its outside; `blur` softens it into a shadow.  Every
event says in a comment what it is (`{=name}`), which the renderer ignores and
the tests read.
]]
local function box(out, name, x, y, w, h, r, color, opacity, ring, blur)
    if w <= 0 or h <= 0 then return end
    local fill_a, ring_w, ring_a = ass_alpha(opacity), 0, 'FF'
    if ring then
        fill_a, ring_w, ring_a = 'FF', ring, ass_alpha(opacity)
    end
    out[#out + 1] = string.format('{=%s}{\\an7\\pos(%s,%s)\\bord%s\\shad0\\blur%s\\1c&H%s&\\1a&H%s&\\3c&H%s&\\3a&H%s&\\p4}%s{\\p0}',
        name, num(x), num(y), num(ring_w), num(blur or 0), bgr(color), fill_a, bgr(color), ring_a, round_box(w, h, r))
end

--[[
What an inset shadow paints inside a rounded box (a page's box-shadow: inset
dx dy 0 colour): the box less the same box moved by (dx, dy) -- a line along
one side that follows the corners round.  Sluka marks levels 3 and 4 so: a
line under the word that curves up at its corners, and for a word with no
fill, a hairline at each side.
]]
local function inset_line(out, name, x, y, w, h, r, dx, dy, color, opacity)
    if w <= 0 or h <= 0 then return end
    -- The moved box reaches past the box itself; only the box's own part of it is drawn.
    out[#out + 1] = string.format('{=%s}{\\an7\\pos(%s,%s)\\bord0\\shad0\\blur0\\1c&H%s&\\1a&H%s&\\clip(%s,%s,%s,%s)\\p4}%s %s{\\p0}',
        name, num(x), num(y), bgr(color), ass_alpha(opacity), num(x), num(y), num(x + w), num(y + h),
        rr_path(0, 0, w, h, r, false), rr_path(dx, dy, w, h, r, true))
end

--- A piece of text with its left end at `x` and its baseline at `base`.
local function text(out, name, x, base, p, color, opacity, edge)
    -- The border colour is the letters' own: a face made thicker by a border (plan_for) stays one colour.
    local outline = string.format('\\bord0\\shad0\\blur0\\3c&H%s&\\3a&H%s&', bgr(color), ass_alpha(opacity or 1))
    if edge and edge > 0 then
        -- A dark edge round the letters, for a box thinned out (content.css --llr-cc-edges).
        outline = string.format('\\bord%s\\shad0\\blur%s\\3c&H%s&\\3a&H%s&', num(p.E * 0.045), num(p.E * 0.07), look.light and 'FFFFFF' or '000000', ass_alpha(edge * 0.85))
    end
    out[#out + 1] = string.format('{=%s}{\\an7\\pos(%s,%s)\\q2%s\\i0\\fscx100\\fscy100\\1c&H%s&\\1a&H%s&}%s',
        name, num(x), num(base - p.asc), outline, bgr(color), ass_alpha(opacity or 1), p.body)
end

----------------------------------------------------------------- the line

--[[
Sluka's subtitle box (content/content.css, .llr-cc and .llr-cc-line), laid out
as a page lays it out:

    size        (13px + 1.65% of the player's width) x Size, and x 0.88 for a
                writing with spaces;
    the box     as wide as its text and 0.55em each side, 0.12em over it and
                0.18em under, corners of 0.4em, near-black at the Background
                setting's strength, a hairline of light on its edge;
    its place   centred, its bottom Position hundredths of the height up;
    too wide    for 88% of the player: drawn up to a tenth smaller where that
                keeps it on one row, and else broken into rows of even length,
                the box brought in to the widest;
    a word      a fill of its level's colour behind it, a pixel short at its
                start so that two words do not run together, a line under
                levels 3 and 4; a white outline round the one pointed at.

Every word also gets the box the pointer is tested against.
]]
local SQUEEZE_MIN = 0.9

-- Marks no row may start with, and marks none may end with.
local NO_START = '^[%s%.,;:!%?%)%]}%%]'
local NO_START_WIDE = { ['、'] = true, ['。'] = true, ['，'] = true, ['．'] = true, ['！'] = true, ['？'] = true, ['）'] = true, ['」'] = true,
    ['』'] = true, ['】'] = true, ['〉'] = true, ['》'] = true, ['〕'] = true, ['］'] = true, ['｝'] = true, ['…'] = true, ['‥'] = true, ['・'] = true,
    ['ー'] = true, ['”'] = true, ['’'] = true, ['»'] = true, ['：'] = true, ['；'] = true, ['々'] = true, ['〜'] = true, ['～'] = true }
local NO_END_WIDE = { ['（'] = true, ['「'] = true, ['『'] = true, ['【'] = true, ['〈'] = true, ['《'] = true, ['〔'] = true, ['［'] = true, ['｛'] = true,
    ['“'] = true, ['‘'] = true, ['«'] = true, ['('] = true, ['['] = true, ['{'] = true }

local PHRASE_END = { ['、'] = true, ['。'] = true, ['，'] = true, ['．'] = true, ['！'] = true, ['？'] = true, ['…'] = true, ['」'] = true, ['』'] = true,
    [','] = true, ['.'] = true, ['!'] = true, ['?'] = true, [';'] = true, ['；'] = true, ['：'] = true }

local function first_char(s) return s:match(UTF8_CHAR) or '' end
local function last_char(s) return s:match(UTF8_CHAR .. '$') or s:match('[\128-\191]*$') or '' end

local function line_size()
    if o.font_size > 0 then return o.font_size end
    return (13 + U.w * 0.0165) * look.size * (look.cjk and 1 or 0.88)
end

--- The line's pieces in order: words (with the number of their token), and what stands between them.
local function pieces_of(line)
    local text = line.text
    local pieces = {}
    local at = 1
    local function gap(to)
        if to >= at then pieces[#pieces + 1] = { text = text:sub(at, to) } end
    end
    for i, tok in ipairs(line.toks or {}) do
        if tok.s + 1 >= at and tok.e >= tok.s + 1 and tok.e <= #text then
            gap(tok.s)
            pieces[#pieces + 1] = { text = text:sub(tok.s + 1, tok.e), tok = i }
            at = tok.e + 1
        end
    end
    gap(#text)
    return pieces
end

--[[
Whether a letter is one of East Asian writing (kana, kanji, their punctuation,
full and half width forms): between two of them a page drops a line break,
where elsewhere it makes it a space (CSS Text, segment break transformation).
]]
local function wide(ch)
    local b1, b2 = ch:byte(1, 2)
    if not b1 or not b2 then return false end
    if b1 >= 0xE3 and b1 <= 0xE9 then return true end                       -- U+3000..U+9FFF
    if b1 == 0xEF and ((b2 >= 0xA4 and b2 <= 0xAB) or b2 >= 0xBC) then return true end -- U+F900..U+FAFF, U+FF00..U+FFEF
    if b1 == 0xF0 and b2 >= 0xA0 then return true end                       -- U+20000.. (more ideographs)
    return false
end

--- A piece's text with its line breaks as a page makes them: none between two East Asian letters, a space elsewhere.
local function soften(text, before, after)
    local out, i = {}, 1
    while true do
        local s, e = text:find('[ \t]*\n[ \t\n]*', i)
        if not s then
            out[#out + 1] = text:sub(i)
            break
        end
        local head = text:sub(i, s - 1)
        out[#out + 1] = head
        local prev = (s > 1) and last_char(text:sub(1, s - 1)) or before
        local next = (e < #text) and first_char(text:sub(e + 1)) or after
        out[#out + 1] = (wide(prev) and wide(next)) and '' or ' '
        i = e + 1
    end
    return table.concat(out)
end

--[[
The line as one paragraph, as Sluka shows a subtitle: the breaks in a cue's
text are where its maker broke it for one size of screen, and a page sets it
on one row where it fits (and breaks it where it does not, by its width).
]]
local function paragraphs(pieces)
    local row = {}
    for i, p in ipairs(pieces) do
        local text = p.text
        if text:find('\n', 1, true) then
            local before = (i > 1) and last_char(pieces[i - 1].text) or ''
            local after = (i < #pieces) and first_char(pieces[i + 1].text) or ''
            text = soften(text, before, after)
        end
        if text ~= '' then row[#row + 1] = { text = text, tok = p.tok } end
    end
    return { row }
end

local function row_text(row, from, to)
    local parts = {}
    for i = from or 1, to or #row do parts[#parts + 1] = row[i].text end
    return table.concat(parts)
end

local function trim_row(row)
    while #row > 0 and not row[#row].text:find('%S') do row[#row] = nil end
    while #row > 0 and not row[1].text:find('%S') do table.remove(row, 1) end
    if #row > 0 then
        row[1] = { text = row[1].text:gsub('^%s+', ''), tok = row[1].tok }
        row[#row] = { text = row[#row].text:gsub('%s+$', ''), tok = row[#row].tok }
    end
    return row
end

--- Whether a row may be broken before its piece `i`.
local function may_break(row, i)
    local before, here = row[i - 1].text, row[i].text
    if before:find('%s$') then return true end
    if here:find('^%s') then return false end
    if look.spaced then return false end
    if here:find(NO_START) or NO_START_WIDE[first_char(here)] then return false end
    if NO_END_WIDE[last_char(before)] then return false end
    return true
end

--- A row too wide for `room` as rows that fit, of lengths as even as they can be.
local function wrap_row(row, room, width_of)
    -- What cannot be broken apart, each with its width.
    local chunks = { { from = 1, to = 1 } }
    for i = 2, #row do
        if may_break(row, i) then chunks[#chunks + 1] = { from = i, to = i } else chunks[#chunks].to = i end
    end
    if #chunks < 2 then return { row } end
    for _, c in ipairs(chunks) do
        local said = row_text(row, c.from, c.to)
        c.w = width_of(said)
        -- A chunk's space at its end takes no room at the end of a row.
        local trimmed = said:gsub('%s+$', '')
        c.tw = (trimmed == said) and c.w or width_of(trimmed)
        -- After a comma or a stop is where a reader breaks a line too.
        c.stop = PHRASE_END[last_char(trimmed)] or false
    end
    local function fill(list, limit)
        local rows, w = { { from = 1, to = 0 } }, 0
        for i, c in ipairs(list) do
            if rows[#rows].to >= rows[#rows].from and w + c.tw > limit then
                rows[#rows + 1] = { from = i, to = i }
                w = c.w
            else
                rows[#rows].to = i
                w = w + c.w
            end
        end
        return rows
    end
    local list = chunks
    local n = #fill(chunks, room)
    if not look.spaced then
        -- Whole phrases to a row, where that takes no more rows than breaking anywhere would.
        local phrases = { { from = chunks[1].from, to = chunks[1].to, w = chunks[1].w, tw = chunks[1].tw, stop = chunks[1].stop } }
        for i = 2, #chunks do
            local c, p = chunks[i], phrases[#phrases]
            if p.stop then
                phrases[#phrases + 1] = { from = c.from, to = c.to, w = c.w, tw = c.tw, stop = c.stop }
            else
                p.to, p.tw, p.w, p.stop = c.to, p.w + c.tw, p.w + c.w, c.stop
            end
        end
        local fits = #phrases > 1
        for _, p in ipairs(phrases) do fits = fits and p.tw <= room end
        if fits and #fill(phrases, room) == n then list = phrases end
    end
    -- The narrowest measure that still gives that many rows makes them even.
    local lo, hi = 0, room
    for _ = 1, 12 do
        local mid = (lo + hi) / 2
        if #fill(list, mid) <= n then hi = mid else lo = mid end
    end
    local out = {}
    for _, r in ipairs(fill(list, hi)) do
        local cut = {}
        for i = list[r.from].from, list[r.to].to do cut[#cut + 1] = row[i] end
        cut = trim_row(cut)
        if #cut > 0 then out[#out + 1] = cut end
    end
    return out
end

local function layout(line)
    fresh_units()
    local pair = faces().cc
    local E = line_size()
    local weight, spacing = 500, look.spacing
    local function width_of(s, size)
        if s == '' then return 0 end
        local body = styled(s, pair, size or E, weight, spacing)
        return advance(body, chars(s), size or E)
    end

    local paras = {}
    for _, row in ipairs(paragraphs(pieces_of(line))) do
        row = trim_row(row)
        if #row > 0 then paras[#paras + 1] = row end
    end
    line.rows, line.boxes, line.box = {}, {}, nil
    if #paras == 0 then return end

    -- On one row each where there is room; a little smaller where that is all it takes; else wrapped.
    local room_for = function(size) return math.max(40, U.w * math.max(0.3, math.min(1, o.max_width)) - 1.1 * size) end
    local widest = 0
    for _, row in ipairs(paras) do
        row.w = width_of(row_text(row))
        widest = math.max(widest, row.w)
    end
    local squeeze = 1
    local room = room_for(E)
    if widest > room + 0.5 and room / widest >= SQUEEZE_MIN then
        squeeze = math.floor(room / widest * 1000) / 1000
    end
    local Es = E * squeeze
    local rows = {}
    if squeeze < 1 then
        for _, row in ipairs(paras) do
            row.w = width_of(row_text(row), Es)
            rows[#rows + 1] = row
        end
    else
        for _, row in ipairs(paras) do
            if row.w > room + 0.5 then
                for _, cut in ipairs(wrap_row(row, room, width_of)) do
                    cut.w = width_of(row_text(cut))
                    rows[#rows + 1] = cut
                end
            else
                rows[#rows + 1] = row
            end
        end
    end

    local inner = 0
    for _, row in ipairs(rows) do inner = math.max(inner, row.w) end
    local pad_x, pad_top, pad_bottom = 0.55 * Es, 0.12 * Es, 0.18 * Es
    local lh = look.line_height * Es
    local bw, bh = inner + 2 * pad_x, #rows * lh + pad_top + pad_bottom
    local bx = round((U.w - bw) / 2)
    local bottom = (o.bottom_margin >= 0) and (U.h - o.bottom_margin) or (U.h * (1 - look.pos / 100))
    local by = round(math.max(4, math.min(U.h - bh - 2, bottom - bh)))
    line.box = { x = bx, y = by, w = bw, h = bh, r = 0.4 * Es }
    line.E = Es

    -- A page stands every row on the baseline its first face gives it, and makes a word's box as tall as that face.
    local A, D = rise(pair.P, Es), fall(pair.P, Es)
    for r, row in ipairs(rows) do
        local top = by + pad_top + (r - 1) * lh
        local base = top + (lh - (A + D)) / 2 + A
        local x = bx + pad_x + (inner - row.w) / 2
        local parts = {}
        local prefix = ''
        local before = 0
        for i, p in ipairs(row) do
            prefix = prefix .. p.text
            -- Where the row stands after this piece: measured from the row's start, so no error adds up.
            local after = (i == #row) and row.w or width_of(prefix, Es)
            if p.tok then
                local x0, x1 = x + before, x + after
                if line.rtl then x0, x1 = x + row.w - after, x + row.w - before end
                local list = line.boxes[p.tok] or {}
                list[#list + 1] = { x0 = x0, x1 = x1, y0 = base - A, y1 = base + D, top = top, bottom = top + lh }
                line.boxes[p.tok] = list
            end
            parts[#parts + 1] = p
            before = after
        end
        line.rows[#line.rows + 1] = { pieces = parts, x = x, base = base, w = row.w }
    end
end

local function clear_overlays()
    ov_line:remove()
    ov_card:remove()
    state.card = nil
end

local function active_token()
    return state.pinned or state.hover
end

local function draw_line()
    local line = state.line
    local pair = faces().cc
    local E = line.E
    local out = {}
    local b = line.box
    local ink = look.light and '111111' or 'ffffff'
    local ground = look.light and 'ffffff' or '080807'

    box(out, 'line-box', b.x, b.y, b.w, b.h, b.r, ground, look.bg)
    if not look.light and look.bg > 0.05 then
        -- A hairline of light just inside the box's edge.
        box(out, 'line-edge', b.x + 1, b.y + 1, b.w - 2, b.h - 2, math.max(0, b.r - 1), 'ffffff', 0.07 * look.bg, 1)
    end

    local hover, pinned = state.hover, state.pinned
    for i, tok in ipairs(line.toks or {}) do
        local wear = look.words[tok.st]
        for _, w in ipairs(line.boxes[i] or {}) do
            local h = w.y1 - w.y0
            if wear and wear.fill and not tok.g then
                -- A pixel short at its start, so that words side by side stay two.
                box(out, 'fill', w.x0 + 1, w.y0, w.x1 - w.x0 - 1, h, 0.12 * E, wear.fill[1], wear.fill[2])
            end
            if wear and wear.line and not tok.g then
                local bx, bw = w.x0 + 1, w.x1 - w.x0 - 1
                if not wear.fill then
                    -- Without a fill the word's box is said by its sides: a hairline of the level's colour.
                    inset_line(out, 'level-side', bx, w.y0, bw, h, 0.12 * E, 1, 0, wear.line, 0.2)
                    inset_line(out, 'level-side', bx, w.y0, bw, h, 0.12 * E, -1, 0, wear.line, 0.2)
                end
                inset_line(out, 'level-line', bx, w.y0, bw, h, 0.12 * E, 0, -0.1 * E, wear.line, 1)
            end
            if i == hover or i == pinned then
                local off = 0.02 * E
                box(out, 'outline', w.x0 - off, w.y0 - off, (w.x1 - w.x0) + 2 * off, h + 2 * off, 0.12 * E + off, ink, 1, 0.08 * E)
            end
        end
    end

    local edge = math.max(0, math.min(1, 1 - look.bg / 0.6))
    for _, row in ipairs(line.rows) do
        local parts, asc = {}, 0
        for _, p in ipairs(row.pieces) do
            local body, a = styled(p.text, pair, E, 500, look.spacing, edge > 0)
            asc = math.max(asc, a)
            local tok = p.tok and line.toks[p.tok]
            local wear = tok and not tok.g and look.words[tok.st]
            if wear and wear.ink then
                -- SlukaCC's own colours: the word itself in its level's colour.
                local own, back = bgr(wear.ink), bgr(ink)
                parts[#parts + 1] = '{\\1c&H' .. own .. '&' .. (edge > 0 and '' or ('\\3c&H' .. own .. '&')) .. '}' .. body
                    .. '{\\1c&H' .. back .. '&' .. (edge > 0 and '' or ('\\3c&H' .. back .. '&')) .. '}'
            else
                parts[#parts + 1] = body
            end
        end
        text(out, 'line-text', row.x, row.base, { body = table.concat(parts), asc = asc, E = E }, ink, 1, edge)
    end
    line.drawn = table.concat(out, '\n')
end

----------------------------------------------------------------- the card and the panel

--[[
Sluka's two boxes for a word, laid out by the numbers of its own stylesheet
(content/ui.js) and drawn piece by piece:

    the card    under the pointer: the word (kana over its kanji), its reading
                with the pitch drawn, its meaning in a word or two, large, the
                next ones small, and the level with how common the word is;
    the panel   for a word clicked: the same head, then what form the line has
                the word in, the dictionary's own meanings, the six buttons
                for its level, and the keys that do the same.

What mpv cannot do is left out rather than drawn dead: the speaker, the
translate and look-up buttons, the box for a meaning of your own, the tab with
a word's characters.  A meaning you wrote in Sluka is shown.
]]
local GLANCE_LONG = 40

--- Text in rows no wider than `room`: broken at its spaces, and a word too long for a row between its letters.
local function wrap_text(s, pair, E, weight, room, max_rows)
    local function width(t)
        return advance((styled(t, pair, E, weight, 0)), chars(t), E)
    end
    local space = width('n n') - width('nn')
    local rows, cur, cur_w = {}, '', 0
    for word in tostring(s):gmatch('%S+') do
        local w = width(word)
        if cur ~= '' and cur_w + space + w > room then
            rows[#rows + 1] = cur
            cur, cur_w = '', 0
        end
        if cur == '' then cur, cur_w = word, w else cur, cur_w = cur .. ' ' .. word, cur_w + space + w end
        while cur_w > room and chars(cur) > 1 do
            local fit = ''
            for ch in cur:gmatch(UTF8_CHAR) do
                if fit ~= '' and width(fit .. ch) > room then break end
                fit = fit .. ch
            end
            rows[#rows + 1] = fit
            cur = cur:sub(#fit + 1)
            cur_w = cur ~= '' and width(cur) or 0
        end
    end
    if cur ~= '' then rows[#rows + 1] = cur end
    if max_rows and #rows > max_rows then
        local last = rows[max_rows]
        while chars(last) > 1 and width(last .. '…') > room do last = last:gsub(UTF8_CHAR .. '$', '') end
        rows[max_rows] = last .. '…'
        for i = #rows, max_rows + 1, -1 do rows[i] = nil end
    end
    local out = {}
    for i, t in ipairs(rows) do out[i] = piece(t, pair, E, weight, 0) end
    return out
end

--- One row cut short with "…" where it is wider than `room`.
local function one_row(s, pair, E, weight, room)
    return wrap_text(s, pair, E, weight, room, 1)[1]
end

--- As wrap_text, the first row `first` wide and the rest `room`: for a row that a label opens.
local function wrap_after(s, pair, E, weight, first, room, max_rows)
    local function width(t)
        return advance((styled(t, pair, E, weight, 0)), chars(t), E)
    end
    local space = width('n n') - width('nn')
    local rows, cur, cur_w = {}, '', 0
    local function fits() return #rows == 0 and first or room end
    for word in tostring(s):gmatch('%S+') do
        local w = width(word)
        if cur ~= '' and cur_w + space + w > fits() then
            rows[#rows + 1] = cur
            cur, cur_w = '', 0
        end
        if cur == '' then cur, cur_w = word, w else cur, cur_w = cur .. ' ' .. word, cur_w + space + w end
        while cur_w > fits() and chars(cur) > 1 do
            local fit = ''
            for ch in cur:gmatch(UTF8_CHAR) do
                if fit ~= '' and width(fit .. ch) > fits() then break end
                fit = fit .. ch
            end
            rows[#rows + 1] = fit
            cur = cur:sub(#fit + 1)
            cur_w = cur ~= '' and width(cur) or 0
        end
    end
    if cur ~= '' then rows[#rows + 1] = cur end
    if max_rows and #rows > max_rows then
        local last = rows[max_rows]
        local lim = max_rows == 1 and first or room
        while chars(last) > 1 and width(last .. '…') > lim do last = last:gsub(UTF8_CHAR .. '$', '') end
        rows[max_rows] = last .. '…'
        for i = #rows, max_rows + 1, -1 do rows[i] = nil end
    end
    local out = {}
    for i, t in ipairs(rows) do out[i] = piece(t, pair, E, weight, 0) end
    return out
end

--[[
The headword at size `E` on a row `lh` tall: each of its pieces along the row,
kana over those that carry them, and how far the block reaches over and under
its baseline.  A reading's row sits on top of its piece's own height, so a
word with kana over it is taller than its row.
]]
local function head_block(head, E, lh)
    local Fc = faces()
    local rt_E = 0.42 * E
    local rt_lh = 1.1 * rt_E
    local A, D = rise(Fc.word.P, E), fall(Fc.word.P, E)
    local items, x, ruby = {}, 0, false
    for _, seg in ipairs(head or {}) do
        local base = piece(tostring(seg.t or ''), Fc.word, E, 400, -0.005)
        local col, rt = base.w, nil
        if type(seg.r) == 'string' and seg.r ~= '' then
            rt = piece(seg.r, Fc.ui, rt_E, 400, 0)
            col = math.max(col, rt.w)
            ruby = true
        end
        items[#items + 1] = { base = base, rt = rt, x = x, col = col }
        x = x + col
    end
    local half = (lh - (A + D)) / 2
    -- The kana's row stands on the top of the letters under it: as WebKit has it, on the face's ascent; as
    -- Chromium has it (the app's pages on Windows), nearer, on the letters' em box -- measured there.
    local over = A
    if look.engine == 'chromium' then over = math.min(A, 0.92 * E) end
    local block = { items = items, w = x, asc = math.max(half + A, ruby and (over + rt_lh) or 0), desc = half + D, A = A, rt_lh = rt_lh }
    function block.draw(out, x0, base, th)
        for _, it in ipairs(items) do
            text(out, 'head', x0 + it.x + (it.col - it.base.w) / 2, base, it.base, th.ink, 1)
            if it.rt then
                local top = base - over - rt_lh + (rt_lh - (it.rt.A + it.rt.D)) / 2
                text(out, 'head-kana', x0 + it.x + (it.col - it.rt.w) / 2, top + it.rt.A, it.rt, th.reading, 1)
            end
        end
    end
    return block
end

--[[
The reading line at size `E` on a row `lh` tall: a part of speech set apart,
the reading, and a Japanese reading's pitch drawn over its kana -- a line over
the high beats that starts a little inside the first of them, a hook after the
beat the pitch falls from, a dashed tail where a flat word stays high, and the
number.  `over` is the room a drawn pitch is given above it.
]]
local function reading_block(reading, E, lh, over, th)
    local Fc = faces()
    local sp = 0.01
    local items, x, pitched, started = {}, 0, false, false
    local function word(s, size, weight, color, gap)
        local p = piece(s, Fc.ui, size, weight, sp * E / size)
        x = x + (started and gap or 0)
        items[#items + 1] = { p = p, x = x, color = color }
        x = x + p.w
        started = true
    end
    for i, r in ipairs(reading or {}) do
        if i > 1 then word('·', E, 400, th.reading, 0.3 * E) end
        local gap = (i > 1) and 0.3 * E or 0
        if type(r.pos) == 'string' and r.pos ~= '' then
            word(r.pos, 12, 500, th.ink3, gap)
            gap = 0.28 * E
        end
        if type(r.text) == 'string' and r.text ~= '' then
            word(r.text, E, 400, th.reading, gap)
            gap = 8
        end
        for _, d in ipairs(type(r.pitch) == 'table' and r.pitch or {}) do
            pitched = true
            x = x + (started and gap or 0)
            started = true
            gap = 8
            local beats = {}
            for _, b in ipairs(d.beats or {}) do
                local p = piece(tostring(b.t or ''), Fc.ui, E, 400, sp)
                local w = p.w + (b.drop and 2 or 0)
                beats[#beats + 1] = { p = p, x = x, w = w, hi = b.hi, rise = b.rise, drop = b.drop, tail = b.tail }
                x = x + w + (b.tail and 9 or 0)
            end
            local size = math.max(12, 0.8 * E)
            local n = piece('[' .. tostring(d.n or 0) .. ']', Fc.ui, size, 600, sp * E / size)
            x = x + 4
            items[#items + 1] = { beats = beats, n = n, nx = x }
            x = x + n.w
        end
    end
    if #items == 0 then return nil end
    local A, D = rise(Fc.ui.P, E), fall(Fc.ui.P, E)
    local half = (lh - (A + D)) / 2
    local block = { w = x, asc = half + A, desc = half + D, pitched = pitched }
    local beat_top = 0
    if pitched then
        local beat_half = (1.25 * E - (A + D)) / 2
        beat_top = 5 + beat_half + A
        block.asc = over + beat_top
        block.desc = math.max(block.desc, beat_half + D)
    end
    function block.draw(out, x0, base)
        for _, it in ipairs(items) do
            if it.p then
                text(out, 'reading', x0 + it.x, base, it.p, it.color, 1)
            else
                local top = base - beat_top
                for _, b in ipairs(it.beats) do
                    text(out, 'pitch-kana', x0 + b.x, base, b.p, th.reading, 1)
                    if b.hi then
                        local inset = b.rise and 2 or 0
                        box(out, 'pitch-high', x0 + b.x + inset, top, b.w - inset, 2, 0, th.reading, 1)
                    end
                    if b.drop then box(out, 'pitch-drop', x0 + b.x + b.w - 2, top, 2, 0.42 * E, 0, th.reading, 1) end
                    if b.tail then
                        box(out, 'pitch-tail', x0 + b.x + b.w + 2, top, 3, 2, 0, th.reading, 1)
                        box(out, 'pitch-tail', x0 + b.x + b.w + 7, top, 2, 2, 0, th.reading, 1)
                    end
                end
                text(out, 'pitch-n', x0 + it.nx, base, it.n, th.ink3, 1)
            end
        end
    end
    return block
end

--- The pill that names a word's level, with a dot in the colour the level has on a page.
local function chip_block(entry, E, lh, pad_y, pad_l, pad_r)
    local label = piece(tostring(entry.label or look.text.labels[entry.st] or ''), faces().ui, E, 600, 0)
    local block = { w = pad_l + 8 + 6 + label.w + pad_r, h = lh + 2 * pad_y, base = pad_y + base_in(label, lh) }
    function block.draw(out, x, y, th)
        box(out, 'chip', x, y, block.w, block.h, block.h / 2, th.chip, th.chip_a)
        local dx, dy = x + pad_l, y + (block.h - 8) / 2
        local st, pal = entry.st or NEW, look.panel
        local function ring(r)
            if th.dot_ring_a > 0 then box(out, 'chip-dot-ring', dx, dy, 8, 8, r, '21201c', th.dot_ring_a, 1) end
        end
        if st == 3 or st == 4 then
            -- Levels 3 and 4 wear a line on a page, so their swatch does too.
            local fill = (st == 3 or pal.fade) and pal.levels[st] or nil
            if fill then box(out, 'chip-dot', dx, dy, 8, 8, st == 3 and 2 or 0, fill, 1) end
            local under = pal.lines and pal.lines[st - 2] or ''
            if under ~= '' then box(out, 'chip-dot-line', dx, dy + 6, 8, 2, 0, under, 1) end
        else
            local color = th.ink3
            if st == NEW then color = pal.new
            elseif st == 1 or st == 2 then color = pal.levels[st]
            elseif st == KNOWN then color = th.known_dot
            elseif st == LINKED then color = pal.twin or pal.new end
            box(out, 'chip-dot', dx, dy, 8, 8, 4, color, 1)
            ring(4)
        end
        text(out, 'chip-label', x + pad_l + 14, y + block.base, label, th.quiet, 1)
    end
    return block
end

--- The box itself: its soft shadow, its ground, the line round it.
local function card_ground(out, x, y, w, h, r, th, small)
    box(out, 'card-shade', x, y + (small and 8 or 12), w, h, r, th.shade, small and th.shade_small_a or th.shade_a, nil, small and 26 or 34)
    box(out, 'card-shade', x, y + 1, w, h, r, th.shade, th.shade_near_a, nil, 2.2)
    -- A page blurs what is behind its panel; here nothing can, so the ground is a little more solid than a page's nine tenths.
    box(out, 'card', x, y, w, h, r, th.bg, 0.95)
    box(out, 'card-ring', x, y, w, h, r, th.ring, small and th.ring_small_a or th.ring_a, 1)
end

--- Sluka's small card (content/ui.js _renderGlance, .glance): { w, h, draw(out, x, y) }.
local function build_glance(entry)
    local th, Fc = theme(), faces()
    local lead = tostring(entry.lead or '')
    local more = {}
    for _, s in ipairs(type(entry.more) == 'table' and entry.more or {}) do more[#more + 1] = tostring(s) end
    local long = chars(lead) > GLANCE_LONG
    for _, s in ipairs(more) do long = long or chars(s) > GLANCE_LONG end
    local room = math.min(long and 440 or 320, U.w - 24) - 24
    local rows, y, widest = {}, 0, 0

    -- The word and its reading, side by side on one baseline where they fit.
    local word = head_block(entry.head, 21, 26.25)
    local reading = reading_block(entry.reading, 13, 18.2, 14, th)
    if reading and word.w + 8 + reading.w <= room then
        local asc = math.max(word.asc, reading.asc)
        local base = y + asc
        rows[#rows + 1] = function(out, x0, y0)
            word.draw(out, x0, y0 + base, th)
            reading.draw(out, x0 + word.w + 8, y0 + base)
        end
        widest = word.w + 8 + reading.w
        y = base + math.max(word.desc, reading.desc)
    else
        local base = y + word.asc
        rows[#rows + 1] = function(out, x0, y0) word.draw(out, x0, y0 + base, th) end
        widest = math.min(word.w, room)
        y = base + word.desc
        if reading then
            local base2 = y + reading.asc
            rows[#rows + 1] = function(out, x0, y0) reading.draw(out, x0, y0 + base2) end
            widest = math.max(widest, math.min(reading.w, room))
            y = base2 + reading.desc
        end
    end

    local function paragraph(s, E, lh, weight, color, name, gap, max_rows)
        y = y + gap
        for _, p in ipairs(wrap_text(s, Fc.ui, E, weight, room, max_rows)) do
            local base = y + base_in(p, lh)
            rows[#rows + 1] = function(out, x0, y0) text(out, name, x0, y0 + base, p, color, 1) end
            widest = math.max(widest, p.w)
            y = y + lh
        end
    end
    -- What it means: the first sense large, a long one a little smaller; the next ones small, on one line.
    if lead ~= '' then
        if chars(lead) > GLANCE_LONG then paragraph(lead, 16, 21.6, 600, th.ink, 'card-lead', 3, 5)
        else paragraph(lead, 19, 24.7, 600, th.ink, 'card-lead', 3, 3) end
    elseif type(entry.none) == 'string' and entry.none ~= '' then
        paragraph(entry.none, 14, 19.6, 400, th.ink2, 'card-none', 3, 2)
    end
    if #more > 0 then paragraph(table.concat(more, ' · '), 14, 19.6, 400, th.ink2, 'card-more', 1, 3) end

    -- Its level, and how common it is.
    local chip = chip_block(entry, 11, 17, 0, 6, 7)
    local rank = (type(entry.rank) == 'string' and entry.rank ~= '') and one_row(entry.rank, Fc.ui, 12, 400, math.max(40, room - chip.w - 6)) or nil
    local chip_y = y + 6
    rows[#rows + 1] = function(out, x0, y0)
        chip.draw(out, x0, y0 + chip_y, th)
        if rank then text(out, 'card-rank', x0 + chip.w + 6, y0 + chip_y + chip.base, rank, th.ink2, 1) end
    end
    widest = math.max(widest, chip.w + (rank and (6 + rank.w) or 0))
    y = chip_y + 17.3

    local card = { w = math.ceil(widest + 24), h = y + 17, small = true }
    function card.draw(out, x, yy)
        card_ground(out, x, yy, card.w, card.h, 14, th, true)
        for _, row in ipairs(rows) do row(out, x + 12, yy + 8) end
    end
    return card
end

--[[
The head's keys' marks, as the extension draws them (content/ui.js TRANSLATE_ICON, BOOK_ICON; lib/anki-icon.js),
traced from their SVG paths into mpv's drawings, 18 pixels square: the Translate mark filled, the others lines
(\bord, along each line there and back).
]]
local ICONS = {
    translate = 'm 9.65 11.3 l 7.75 9.42 l 7.77 9.4 b 9.04 7.99 9.99 6.31 10.55 4.5 l 12.75 4.5 l 12.75 3 l 7.5 3 l 7.5 1.5 l 6 1.5 l 6 3 l 0.75 3 l 0.75 4.49 l 9.13 4.49 b 8.62 5.94 7.83 7.31 6.75 8.51 b 6.05 7.74 5.47 6.89 5.02 6 l 3.52 6 b 4.06 7.22 4.81 8.38 5.75 9.42 l 1.94 13.18 l 3 14.25 l 6.75 10.5 l 9.08 12.83 l 9.65 11.3 m 13.88 7.5 l 12.38 7.5 l 9 16.5 l 10.5 16.5 l 11.34 14.25 l 14.9 14.25 l 15.75 16.5 l 17.25 16.5 l 13.88 7.5 m 11.91 12.75 l 13.12 9.5 l 14.34 12.75 l 11.91 12.75',
    book = 'm 3 4.12 b 3 3.5 3.5 3 4.12 3 l 8.25 3 l 8.25 14.25 l 4.12 14.25 b 3.5 14.25 3 14.75 3 15.38 m 15 4.12 b 15 3.5 14.5 3 13.88 3 l 9.75 3 l 9.75 14.25 l 13.88 14.25 b 14.5 14.25 15 14.75 15 15.38',
    anki = 'm 4.12 4.88 l 10.88 4.88 b 11.7 4.88 12.38 5.55 12.38 6.38 l 12.38 13.88 b 12.38 14.7 11.7 15.38 10.88 15.38 l 4.12 15.38 b 3.3 15.38 2.62 14.7 2.62 13.88 l 2.62 6.38 b 2.62 5.55 3.3 4.88 4.12 4.88 m 5.62 2.62 l 12.75 2.62 b 13.99 2.62 15 3.63 15 4.88 l 15 12 l 15 4.88 b 15 3.63 13.99 2.62 12.75 2.62 l 5.62 2.62',
    anki_add = 'm 7.5 7.88 l 7.5 12.38 l 7.5 7.88 m 5.25 10.12 l 9.75 10.12 l 5.25 10.12',
    anki_move = 'm 4.88 10.12 l 9.75 10.12 l 4.88 10.12 m 7.88 8.25 l 9.75 10.12 l 7.88 12 l 9.75 10.12 l 7.88 8.25',
    anki_queued = 'm 7.5 7.88 l 7.5 10.12 l 9 11.25 l 7.5 10.12 l 7.5 7.88',
    speaker = 'm 1.75 5.25 l 1.75 8.75 l 4.08 8.75 l 7 11.08 l 7 2.92 l 4.08 5.25 l 1.75 5.25',
    speaker_waves = 'm 9.04 4.96 b 10.15 6.09 10.15 7.91 9.04 9.04 b 10.15 7.91 10.15 6.09 9.04 4.96 m 10.68 3.33 b 12.68 5.37 12.68 8.63 10.68 10.68 b 12.68 8.63 12.68 5.37 10.68 3.33',
    anki_in = 'm 5.06 10.12 l 6.75 11.81 l 9.75 8.44 l 6.75 11.81 l 5.06 10.12',
    anki_asleep = 'm 6.38 8.25 l 6.38 12 l 6.38 8.25 m 8.62 8.25 l 8.62 12 l 8.62 8.25',
    -- The AI check's ✦ (content/ui.js .ai-key .glyph), drawn: a font may not have it.
    sparkle = 'm 9 3.5 b 9.45 7.45 10.55 8.55 14.5 9 b 10.55 9.45 9.45 10.55 9 14.5 b 8.55 10.55 7.45 9.45 3.5 9 b 7.45 8.55 8.55 7.45 9 3.5',
}

local function draw_icon(out, name, x, y, drawing, color, stroked)
    if stroked then
        out[#out + 1] = string.format('{=%s}{\\an7\\pos(%s,%s)\\bord0.6\\shad0\\blur0\\1a&HFF&\\3c&H%s&\\3a&H00&\\p1}%s{\\p0}',
            name, num(x), num(y), bgr(color), drawing)
    else
        out[#out + 1] = string.format('{=%s}{\\an7\\pos(%s,%s)\\bord0\\shad0\\blur0\\1c&H%s&\\1a&H00&\\p1}%s{\\p0}',
            name, num(x), num(y), bgr(color), drawing)
    end
end


--[[
The AI check (Settings → AI check), as a page's panel has it (content/ui.js _askState, _askBlock, _renderVerdict).
Where the dictionaries answered, a quiet ✦ among the head's keys; where neither Sluka's nor yours has the word,
asking is the main thing left to do, and a button says so in the meanings, with what pressing it sends.  The answer
goes under the meanings: whether it is a real word and how sure, its meaning, an example of its own with its
translation, where it is used, why -- and the answer to your own request (its Advanced) under "Your question".
Once answered, it is not asked again.
]]
local function verdict_for(entry)
    local v = state.verdict
    if v and entry and v.id == entry.id and v.tok == entry.tok then return v end
    return nil
end

local function ask_settled(entry)
    local v = verdict_for(entry)
    return v ~= nil and v.status ~= 'error'
end

--- The check's part of the meanings, as rows measured before they are placed: { h, items = { { h, draw, region } } }.
local function ask_rows(entry, th, W)
    local Fc = faces()
    local items, total = {}, 0
    local function add(h, draw, region)
        items[#items + 1] = { h = h, draw = draw, region = region }
        total = total + h
    end
    local ask = type(entry.tools) == 'table' and type(entry.tools.ask) == 'table' and entry.tools.ask or nil
    local v = verdict_for(entry)
    if not v and not (ask and ask.wanted) then return { h = 0, items = items } end
    local wide = W - 32
    local function str(x) return type(x) == 'string' and x or '' end
    local function para(s, pair, E, lh, weight, color, name, max_rows, top_gap, x_in)
        top_gap, x_in = top_gap or 0, x_in or 0
        local lines = wrap_text(s, pair, E, weight, wide - x_in, max_rows)
        add(top_gap + #lines * lh, function(out, x0, top)
            for i, p in ipairs(lines) do text(out, name, x0 + 16 + x_in, top + top_gap + (i - 1) * lh + base_in(p, lh), p, color, 1) end
        end)
    end
    -- A hairline across the panel, between the meanings and the check.
    add(11, function(out, x0, top) box(out, 'panel-ask-rule', x0, top + 4, W, 1, 0, th.chip, th.hair_a) end)
    if v and v.status == 'loading' then
        para(str(v.label) ~= '' and v.label or 'Checking…', Fc.ui, 13, 20, 400, th.ink2, 'panel-ask-wait', 1)
    elseif v and v.status == 'error' then
        para(str(v.error) ~= '' and v.error or 'The check failed.', Fc.ui, 13, 19, 400, th.danger, 'panel-ask-error', 4)
    elseif v then
        local r = type(v.result) == 'table' and v.result or {}
        local labels = type(v.labels) == 'table' and v.labels or {}
        local tag = piece(str(labels.tag) ~= '' and labels.tag or str(r.verdict), Fc.ui, 12, 600, 0)
        local conf = str(labels.confidence) ~= '' and piece(labels.confidence, Fc.ui, 12, 400, 0) or nil
        local fills = { established = { KNOWN_FILL, 1, 'ffffff' }, narrow = { th.narrow, 0.2, th.caution_soft }, not_a_word = { REFUSED, 1, 'ffffff' } }
        local f = fills[str(r.verdict)] or { th.chip, 0.12, th.btn_ink }
        add(22, function(out, x0, top)
            box(out, 'panel-vd-tag', x0 + 16, top + 1, tag.w + 18, 20, 10, f[1], f[2])
            text(out, 'panel-vd-tag-text', x0 + 25, top + 1 + base_in(tag, 20), tag, f[3], 1)
            if conf then text(out, 'panel-vd-conf', x0 + 16 + tag.w + 26, top + 1 + base_in(conf, 20), conf, th.ink3, 1) end
        end)
        if str(r.meaning) ~= '' then para(r.meaning, Fc.ui, 14, 20, 400, th.ink, 'panel-vd-meaning', 4, 6) end
        if str(r.example) ~= '' then
            local ex = wrap_text(r.example, Fc.word, 15, 400, wide - 12, 3)
            local tr = str(r.exampleTranslation) ~= '' and wrap_text(r.exampleTranslation, Fc.ui, 13, 400, wide - 12, 2) or {}
            local h = #ex * 21.75 + #tr * 18.5
            add(8 + h + 4, function(out, x0, top)
                box(out, 'panel-vd-ex-edge', x0 + 16, top + 8, 2, h + 4, 0, th.chip, th.hair_a * 2)
                for i, p in ipairs(ex) do text(out, 'panel-vd-ex', x0 + 28, top + 10 + (i - 1) * 21.75 + base_in(p, 21.75), p, th.body, 1) end
                for i, p in ipairs(tr) do text(out, 'panel-vd-ex-tr', x0 + 28, top + 10 + #ex * 21.75 + (i - 1) * 18.5 + base_in(p, 18.5), p, th.quiet, 1) end
            end)
        end
        for _, field in ipairs({ 'reading', 'register', 'breakdown', 'explanation' }) do
            local value = str(r[field])
            if value ~= '' then
                local lab = piece((str(labels[field]) ~= '' and labels[field] or field) .. ':', Fc.ui, 13, 600, 0)
                local rows = wrap_after(value, Fc.ui, 13, 400, math.max(30, wide - lab.w - 4), wide, 3)
                add(4 + #rows * 19, function(out, x0, top)
                    for i, p in ipairs(rows) do
                        local base = top + 4 + (i - 1) * 19 + base_in(p, 19)
                        if i == 1 then text(out, 'panel-vd-label', x0 + 16, base, lab, th.ink3, 1) end
                        text(out, 'panel-vd-line', x0 + 16 + (i == 1 and (lab.w + 4) or 0), base, p, th.quiet, 1)
                    end
                end)
            end
        end
        local own = str(r.ownAnswer):gsub('^%s+', ''):gsub('%s+$', '')
        if own ~= '' then
            local head = piece(str(labels.own) ~= '' and labels.own or 'Your question', Fc.ui, 12, 600, 0)
            add(10 + 8 + 17, function(out, x0, top)
                box(out, 'panel-vd-own-rule', x0 + 16, top + 10, wide, 1, 0, th.chip, th.hair_a)
                text(out, 'panel-vd-own-head', x0 + 16, top + 18 + base_in(head, 17), head, th.ink3, 1)
            end)
            -- Its paragraphs as the model wrote them (content/ui.js .vd-own-text, pre-line).
            local budget = 12
            for part in (own .. '\n'):gmatch('(.-)\n') do
                if budget <= 0 then break end
                if part:match('^%s*$') then
                    add(6, function() end)
                else
                    local lines = wrap_text(part, Fc.ui, 13.5, 400, wide, budget)
                    budget = budget - #lines
                    add(#lines * 19.6, function(out, x0, top)
                        for i, p in ipairs(lines) do text(out, 'panel-vd-own', x0 + 16, top + (i - 1) * 19.6 + base_in(p, 19.6), p, th.ink, 1) end
                    end)
                end
            end
        end
    end
    if ask and ask.wanted and not ask_settled(entry) then
        local gap = v and 8 or 2
        local label = one_row(str(ask.label) ~= '' and ask.label or 'Ask AI if this is a real word', Fc.ui, 13, 500, wide - 20)
        add(gap + 32, function(out, x0, top)
            box(out, 'panel-ask-go', x0 + 16, top + gap, wide, 32, 8, th.chip, th.chip_a)
            text(out, 'panel-ask-go-label', x0 + 16 + (wide - label.w) / 2, top + gap + base_in(label, 32), label, th.btn_ink, 1)
        end, { x0 = 16, y0 = gap, x1 = 16 + wide, y1 = gap + 32, act = 'ask' })
        if str(ask.why) ~= '' then para(ask.why, Fc.ui, 12, 17, 400, th.ink3, 'panel-ask-why', 2, 6) end
    end
    add(4, function() end)
    return { h = total, items = items }
end

--[[
Sluka's panel for a word clicked (content/ui.js _renderPanel, as it is over
SlukaCC's subtitles): { w, h, draw(out, x, y), regions }.  `tall` is the room
it has above the line; meanings that do not fit it are left off from the end,
since nothing here can be scrolled.
]]
local function build_panel(entry, tall)
    local th, Fc = theme(), faces()
    local W = 360
    local rows, regions = {}, {}
    local y = 7

    -- The head: the word, the cross that puts the panel away, and under them the reading, the level, the place.
    local word = head_block(entry.head, 30, 30)
    -- The speaker, in the head's top left corner with the word beside it (content/ui.js .head > .say): the reading's
    -- colour, filled in while the word is said.
    local say = type(entry.tools) == 'table' and type(entry.tools.say) == 'table'
    local word_x = say and 52 or 16
    -- Level with the word itself, under its furigana: centred where a word of 30 is.
    local say_top = math.floor(y + word.asc - 27 + 0.5)
    do
        local base = y + word.asc
        rows[#rows + 1] = function(out, x0, y0) word.draw(out, x0 + word_x, y0 + base, th) end
        y = base + word.desc
    end
    if say then
        local lit = entry.speaking == true
        rows[#rows + 1] = function(out, x0, y0)
            box(out, 'panel-say', x0 + 15, y0 + say_top, 28, 28, 14, th.reading, lit and 1 or 0.1)
            local ink = lit and th.bg or th.reading
            draw_icon(out, 'panel-say-mark', x0 + 22, y0 + say_top + 7, ICONS.speaker, ink, false)
            out[#out + 1] = string.format('{=panel-say-waves}{\\an7\\pos(%s,%s)\\bord0.55\\shad0\\blur0\\1a&HFF&\\3c&H%s&\\3a&H00&\\p1}%s{\\p0}',
                num(x0 + 22), num(y0 + say_top + 7), bgr(ink), ICONS.speaker_waves)
        end
        regions[#regions + 1] = { x0 = 13, y0 = say_top - 2, x1 = 45, y1 = say_top + 30, act = 'speak' }
    end
    rows[#rows + 1] = function(out, x0, y0)
        local cx, cy = x0 + W - 22, y0 + 19
        for _, d in ipairs({ { 1, 1 }, { 1, -1 } }) do
            local a, b = 4.6, 0.55
            out[#out + 1] = string.format('{=close}{\\an7\\pos(%s,%s)\\bord0\\shad0\\blur0\\1c&H%s&\\1a&H00&\\p4}m %s %s l %s %s %s %s %s %s{\\p0}', num(cx), num(cy), bgr(th.ink3),
                c8(-a - b * d[2]), c8(-a * d[2] + b), c8(-a + b * d[2]), c8(-a * d[2] - b), c8(a + b * d[2]), c8(a * d[2] - b), c8(a - b * d[2]), c8(a * d[2] + b))
        end
    end
    regions[#regions + 1] = { x0 = W - 36, y0 = 5, x1 = W - 8, y1 = 33, act = 'close' }
    -- The head's keys, left of the cross, as a page's panel has them (content/ui.js headKeys): Translate, Look up
    -- (its menu under the head) and Anki (where Settings → Anki has the panel's button on), with the extension's marks.
    local tools = type(entry.tools) == 'table' and entry.tools or {}
    local anki = type(entry.anki) == 'table' and type(entry.anki.state) == 'string' and entry.anki.state ~= '' and entry.anki or nil
    local keys = {}
    if type(tools.translate) == 'table' then keys[#keys + 1] = 'translate' end
    if type(tools.look) == 'table' and type(tools.look.links) == 'table' and #tools.look.links > 0 then keys[#keys + 1] = 'look' end
    if anki then keys[#keys + 1] = 'anki' end
    if type(tools.ask) == 'table' and not tools.ask.wanted and not ask_settled(entry) then keys[#keys + 1] = 'ask' end
    for k, act in ipairs(keys) do
        local cx = W - 52 - (#keys - k) * 30
        local ink = (act == 'anki' and anki.state == 'in') and '22c55e' or ((act == 'look' and state.look_open) and th.ink or th.ink3)
        rows[#rows + 1] = function(out, x0, y0)
            local x, yy = x0 + cx - 9, y0 + 19 - 9
            if act == 'translate' then
                draw_icon(out, 'panel-translate', x, yy, ICONS.translate, ink, false)
            elseif act == 'look' then
                draw_icon(out, 'panel-look', x - 2, yy, ICONS.book, ink, true)
                local caret = piece('▾', Fc.ui, 9, 400, 0)
                text(out, 'panel-look-caret', x + 15.5, yy + 9 + base_in(caret, 9) - 4.5, caret, ink, 1)
            elseif act == 'ask' then
                draw_icon(out, 'panel-ask', x, yy, ICONS.sparkle, th.reading, false)
            else
                draw_icon(out, 'panel-anki', x, yy, ICONS.anki, ink, true)
                draw_icon(out, 'panel-anki-mark', x, yy, ICONS['anki_' .. anki.state] or ICONS.anki_add, ink, true)
            end
        end
        regions[#regions + 1] = { x0 = cx - 14, y0 = 5, x1 = cx + 14, y1 = 33, act = act }
    end
    -- The Look up menu, open: the sites, and beside each that can be had offline, its dictionary offline.
    if state.look_open and type(tools.look) == 'table' and type(tools.look.links) == 'table' then
        local items = {}
        for _, link in ipairs(tools.look.links) do
            if type(link) == 'table' and type(link.id) == 'string' then
                items[#items + 1] = { id = link.id, name = tostring(link.name or link.id) }
                if type(link.offline) == 'string' and link.offline ~= '' then
                    items[#items + 1] = { id = link.id, offline = true, installed = link.installed == true,
                                          name = tostring(link.name or link.id) .. ' · ' .. tostring(tools.look.offline or 'offline') }
                end
            end
        end
        local top = y + 4
        rows[#rows + 1] = function(out, x0, y0)
            box(out, 'panel-menu', x0 + 12, y0 + top, W - 24, #items * 26 + 8, 10, th.chip, th.chip_a)
        end
        for n, item in ipairs(items) do
            local ry = top + 4 + (n - 1) * 26
            local label = one_row(item.name, Fc.ui, 13.5, 400, W - 110)
            local state_label = item.offline and piece(item.installed and '✓' or 'Install', Fc.ui, 12, 400, 0) or nil
            rows[#rows + 1] = function(out, x0, y0)
                text(out, 'panel-menu-row', x0 + 22, y0 + ry + 13 + base_in(label, 18) - 9, label, item.offline and th.ink2 or th.ink, 1)
                if state_label then
                    text(out, 'panel-menu-state', x0 + W - 22 - state_label.w, y0 + ry + 13 + base_in(state_label, 18) - 9, state_label,
                        item.installed and '22c55e' or th.ink3, 1)
                end
            end
            regions[#regions + 1] = { x0 = 14, y0 = ry, x1 = W - 14, y1 = ry + 26, act = 'site', site = item.id, offline = item.offline }
        end
        y = top + #items * 26 + 8 + 4
    end

    local reading = reading_block(entry.reading, 15, 19.5, 14, th)
    local chip = chip_block(entry, 11.5, 16, 1, 6, 8)
    local rank = (type(entry.rank) == 'string' and entry.rank ~= '') and one_row(entry.rank, Fc.ui, 12.5, 400, 300) or nil
    do
        -- Side by side while they fit, each row's parts centred on one another; then on a row of their own.
        local sub = {}
        if reading then sub[#sub + 1] = { w = reading.w, h = reading.asc + reading.desc, draw = function(out, x, top) reading.draw(out, x, top + reading.asc) end } end
        sub[#sub + 1] = { w = chip.w, h = chip.h, draw = function(out, x, top) chip.draw(out, x, top, th) end }
        if rank then sub[#sub + 1] = { w = rank.w, h = 16.25, draw = function(out, x, top) text(out, 'panel-rank', x, top + base_in(rank, 16.25), rank, th.ink3, 1) end } end
        y = y + 2
        local i = 1
        while i <= #sub do
            local j, w, h = i, sub[i].w, sub[i].h
            while j < #sub and w + 10 + sub[j + 1].w <= W - 30 do
                j = j + 1
                w, h = w + 10 + sub[j].w, math.max(h, sub[j].h)
            end
            local top, from, to = y, i, j
            rows[#rows + 1] = function(out, x0, y0)
                local x = x0 + 16
                for k = from, to do
                    sub[k].draw(out, x, y0 + top + (h - sub[k].h) / 2)
                    x = x + sub[k].w + 10
                end
            end
            y = y + h + ((j < #sub) and 2 or 0)
            i = j + 1
        end
        y = y + 3
    end
    local head_h = y

    -- The foot is of one height whatever is said above it: the six levels, and the keys for them.
    local legend = look.text.legend
    local foot_h = 6 + 34 + 4 + (legend and 22 or 4)

    -- The meanings, as many as there is room for.
    local body = {}
    local by = 2 + 2 + 2
    local function body_row(h, draw)
        body[#body + 1] = { y = by, h = h, draw = draw }
        by = by + h
    end
    local room = math.max(60, math.min(300, (tall or 400) - head_h - foot_h))
    -- The AI check's rows, measured first: the meanings leave them room, as nothing here can be scrolled.
    local ask = ask_rows(entry, th, W)
    local full_room = room
    if ask.h > 0 then
        full_room = math.max(60, math.min(560, (tall or 400) - head_h - foot_h))
        room = math.max(72, full_room - ask.h)
    end
    local tr = type(entry.tr) == 'table' and entry.tr or nil
    if tr then
        local said = tr.status == 'loading' and '…' or (tr.status == 'error' and tostring(tr.error or '') or tostring(tr.text or ''))
        local lines = wrap_text(said ~= '' and said or '…', Fc.ui, 15, tr.status == 'done' and 600 or 400, W - 48, 3)
        local alts = {}
        for _, a in ipairs(type(tr.alternatives) == 'table' and tr.alternatives or {}) do
            if type(a) == 'table' and type(a.terms) == 'table' and #a.terms > 0 then
                alts[#alts + 1] = ((type(a.pos) == 'string' and a.pos ~= '') and (a.pos .. ' ') or '') .. table.concat(a.terms, ', ')
            end
        end
        local alt = #alts > 0 and one_row(table.concat(alts, ' · '), Fc.ui, 12.5, 400, W - 48) or nil
        local by_label = piece('Google Translate', Fc.ui, 11, 400, 0)
        local h = 8 + 16 + #lines * 21 + (alt and 18 or 0) + 8
        body_row(h + 6, function(out, x0, top)
            box(out, 'panel-gtr', x0 + 12, top + 2, W - 24, h, 9, th.chip, th.chip_a)
            text(out, 'panel-gtr-by', x0 + 22, top + 10 + base_in(by_label, 14), by_label, th.ink3, 1)
            for i, p in ipairs(lines) do
                text(out, 'panel-gtr-text', x0 + 22, top + 26 + (i - 1) * 21 + base_in(p, 21), p, tr.status == 'done' and th.ink or th.ink3, 1)
            end
            if alt then text(out, 'panel-gtr-alt', x0 + 22, top + 26 + #lines * 21 + base_in(alt, 18), alt, th.ink3, 1) end
        end)
    end
    if type(entry.inflection) == 'table' and entry.inflection.why then
        local p = one_row(tostring(entry.inflection.form or '') .. ' — ' .. tostring(entry.inflection.why), Fc.ui, 12, 400, W - 32)
        body_row(21, function(out, x0, top) text(out, 'panel-form', x0 + 16, top + base_in(p, 18), p, th.inflection, 1) end)
    end
    local listed = 0
    local function sense(s, marker, color)
        local lines = wrap_text(s, Fc.ui, 15, 400, W - 32 - 20, 4)
        -- A hairline between one meaning and the next.
        local rule = (listed > 0) and 1 or 0
        local h = rule + 8 + #lines * 22.5
        if by + h + 4 > room and #body > 0 then return false end
        listed = listed + 1
        local mark = marker and piece(marker, Fc.ui, 12, 400, 0) or nil
        body_row(h, function(out, x0, top)
            if rule > 0 then box(out, 'panel-rule', x0 + 36, top, W - 52, 1, 0, th.chip, th.hair_a) end
            for i, p in ipairs(lines) do
                local base = top + rule + 4 + (i - 1) * 22.5 + base_in(p, 22.5)
                if i == 1 and mark then text(out, 'panel-number', x0 + 36 - 5 - mark.w, base, mark, th.ink3, 1) end
                text(out, 'panel-sense', x0 + 36, base, p, color, 1)
            end
        end)
        return true
    end
    if #body == 0 then by = by + 2 end
    local shown = 0
    --[[
    Your own dictionaries (Settings → Dictionary → Your own dictionaries), each under its name, their meanings as
    text (lib/own-dicts/render.js glanceSenses): instead of Sluka's, above them or under them, as Settings says.
    ]]
    local own = type(entry.own) == 'table' and type(entry.own.dicts) == 'table' and #entry.own.dicts > 0 and entry.own or nil
    local place = own and tostring(own.place or 'replace') or ''
    local function own_rows()
        for _, d in ipairs(own.dicts) do
            if type(d) == 'table' then
                if by + 26 + 4 > room and #body > 0 then return end
                local name = one_row(tostring(d.title or ''), Fc.ui, 12, 600, W - 60)
                body_row(26, function(out, x0, top)
                    box(out, 'panel-own-tag', x0 + 16, top + 4, name.w + 14, 18, 9, th.chip, th.chip_a)
                    text(out, 'panel-own-name', x0 + 23, top + 4 + base_in(name, 18), name, th.accent, 1)
                end)
                listed = 0
                for _, h in ipairs(type(d.hits) == 'table' and d.hits or {}) do
                    if type(h) == 'table' then
                        local hw = type(h.head) == 'string' and h.head or ''
                        local rd = type(h.reading) == 'string' and h.reading or ''
                        if (hw ~= '' and hw ~= entry.key) or rd ~= '' then
                            if by + 22 + 4 > room then return end
                            local hp = hw ~= '' and one_row(hw, Fc.word, 15, 400, W - 140) or nil
                            local rp = rd ~= '' and one_row(rd, Fc.ui, 13, 500, W - 52 - (hp and (hp.w + 8) or 0)) or nil
                            body_row(22, function(out, x0, top)
                                local x = x0 + 36
                                if hp then
                                    text(out, 'panel-own-head', x, top + base_in(hp, 22), hp, th.ink, 1)
                                    x = x + hp.w + 8
                                end
                                if rp then text(out, 'panel-own-reading', x, top + base_in(rp, 22), rp, th.reading, 1) end
                            end)
                            listed = 0
                        end
                        for i, sn in ipairs(type(h.senses) == 'table' and h.senses or {}) do
                            if not sense(tostring(sn), i .. '.', th.body) then return end
                        end
                    end
                end
            end
        end
    end
    if type(entry.mine) == 'string' and entry.mine ~= '' then sense(entry.mine, '✎', th.ink) end
    if own and place ~= 'below' then own_rows() end
    local senses = (place ~= 'replace' and type(entry.senses) == 'table') and entry.senses or {}
    for i, s in ipairs(senses) do
        if not sense(tostring(s), i .. '.', th.body) then break end
        shown = i
    end
    if #senses == 0 and not own and not (type(entry.mine) == 'string' and entry.mine ~= '') then
        local none = (type(entry.none) == 'string' and entry.none ~= '') and entry.none or tostring(entry.lead or '')
        if none ~= '' then
            local lines = wrap_text(none, Fc.ui, 14, 400, W - 32, 3)
            body_row(6 + #lines * 21, function(out, x0, top)
                for i, p in ipairs(lines) do text(out, 'panel-none', x0 + 16, top + 4 + (i - 1) * 21 + base_in(p, 21), p, th.ink2, 1) end
            end)
        end
    end
    local left = (place == 'replace') and 0 or ((#senses - shown) + (tonumber(entry.senses_more) or 0))
    -- The word's other readings, a line each; and how many meanings there was no room for.
    local also_label = (type(look.text.also) == 'string' and look.text.also ~= '') and piece(look.text.also, Fc.ui, 12, 600, 0) or nil
    for i, a in ipairs((place ~= 'replace' and type(entry.also) == 'table') and entry.also or {}) do
        if by + 24 + 4 > room then break end
        local lead_w = also_label and (also_label.w + 8) or 0
        local head = piece(tostring(a.head or ''), Fc.ui, 13, 400, 0)
        local gloss = one_row(tostring(a.gloss or ''), Fc.ui, 12.5, 400, math.max(60, W - 32 - lead_w - head.w - 8))
        body_row(24, function(out, x0, top)
            if also_label and i == 1 then text(out, 'panel-also-label', x0 + 16, top + 6 + base_in(also_label, 18), also_label, th.ink3, 1) end
            text(out, 'panel-also', x0 + 16 + lead_w, top + 6 + base_in(head, 18), head, th.reading, 1)
            text(out, 'panel-also-gloss', x0 + 16 + lead_w + head.w + 8, top + 6 + base_in(gloss, 18), gloss, th.ink2, 1)
        end)
    end
    if left > 0 and shown > 0 and by + 20 + 4 <= room + 20 then
        local p = piece('+' .. left, Fc.ui, 12, 600, 0)
        body_row(20, function(out, x0, top) text(out, 'panel-more', x0 + 36, top + 2 + base_in(p, 16), p, th.ink3, 1) end)
    end
    if own and place == 'below' then own_rows() end
    -- The check's answer under the meanings (or its button), as much of it as there is room for.
    room = full_room
    for _, it in ipairs(ask.items) do
        if by + it.h > room + 4 and #body > 0 then break end
        if it.region then
            regions[#regions + 1] = { x0 = it.region.x0, y0 = head_h + by + it.region.y0, x1 = it.region.x1, y1 = head_h + by + it.region.y1,
                                      act = it.region.act }
        end
        body_row(it.h, it.draw)
    end
    local body_h = by + 4
    local body_top = head_h
    y = head_h + body_h

    -- The six levels, the word's own filled in its colour.
    local bar_x, bar_y = 12, y + 6
    local unit = (336 - 4 - 10) / 7.1
    local buttons = {
        { st = 1, w = unit, label = '1' }, { st = 2, w = unit, label = '2' }, { st = 3, w = unit, label = '3' }, { st = 4, w = unit, label = '4' },
        { st = KNOWN, w = unit * 1.55, label = look.text.known }, { st = IGNORED, w = unit * 1.55, label = look.text.ignore },
    }
    do
        local x = bar_x + 2
        for _, b in ipairs(buttons) do
            b.x = x
            b.p = one_row(b.label, Fc.ui, 13, 600, b.w - 8)
            regions[#regions + 1] = { x0 = x - 1, y0 = bar_y + 2, x1 = x + b.w + 1, y1 = bar_y + 32, act = 'grade', st = b.st }
            x = x + b.w + 2
        end
    end
    local pal = look.panel
    rows[#rows + 1] = function(out, x0, y0)
        local top = y0 + bar_y
        box(out, 'levels', x0 + bar_x, top, 336, 34, 17, th.chip, th.chip_a)
        box(out, 'levels-edge', x0 + bar_x + 1, top + 1, 334, 32, 16, th.chip, th.edge_a, 1)
        for _, b in ipairs(buttons) do
            local bx, btop = x0 + b.x, top + 2
            local lit = entry.st == b.st
            local ink = th.ink
            local base = btop + base_in(b.p, 30)
            if lit then
                local fill = th.on
                ink = th.on_ink
                if b.st >= 1 and b.st <= 3 then fill, ink = pal.levels[b.st], PAPER_INK
                elseif b.st == KNOWN then fill, ink = KNOWN_FILL, 'ffffff'
                elseif b.st == IGNORED then fill, ink = IGNORE_FILL, 'ffffff' end
                box(out, 'level-lit-shade', bx, btop + 1, b.w, 30, 15, '000000', th.lit_shade_a, nil, 2.6)
                box(out, 'level-lit', bx, btop, b.w, 30, 15, fill, 1)
                box(out, 'level-lit-edge', bx + 1, btop + 1, b.w - 2, 28, 14, '000000', th.lit_edge_a, 1)
                text(out, 'level-label', bx + (b.w - b.p.w) / 2, base, b.p, ink, 1)
            elseif b.st >= 1 and b.st <= 4 then
                -- Beside the number, a patch of page with that level on it.
                local sx = bx + (b.w - (14 + 6 + b.p.w)) / 2
                local sy = btop + 10
                local fill = (b.st < 4 or pal.fade) and pal.levels[b.st] or PAPER
                box(out, 'level-swatch', sx, sy, 14, 10, 2, fill, 1)
                local under = (b.st >= 3 and pal.lines) and pal.lines[b.st - 2] or ''
                if under ~= '' then box(out, 'level-swatch-line', sx, sy + 8, 14, 2, 0, under, 1) end
                box(out, 'level-swatch-edge', sx, sy, 14, 10, 2, th.chip, th.swatch_edge_a, 1)
                text(out, 'level-label', sx + 20, base, b.p, ink, 1)
            else
                text(out, 'level-label', bx + (b.w - b.p.w) / 2, base, b.p, ink, 1)
            end
        end
    end
    y = bar_y + 34 + 4

    -- The keys that do the same, each in its little cap.
    if legend then
        local parts = {}
        for _, part in ipairs(type(legend.parts) == 'table' and legend.parts or {}) do parts[#parts + 1] = part end
        if entry.st ~= NEW and type(legend.forget) == 'table' then parts[#parts + 1] = legend.forget end
        local items, x = {}, 0
        for i, part in ipairs(parts) do
            if i > 1 then
                local dot = piece('·', Fc.ui, 11, 400, 0)
                items[#items + 1] = { p = dot, x = x + 3.2 }
                x = x + 3.2 + dot.w + 3.2
            end
            for _, seg in ipairs(type(part) == 'table' and part or {}) do
                if type(seg) == 'table' and seg.k then
                    local p = piece(tostring(seg.k), Fc.ui, 11, 600, 0)
                    local w = math.max(14, p.w + 6)
                    items[#items + 1] = { p = p, x = x + (w - p.w) / 2, key = true, kx = x, kw = w }
                    x = x + w
                elseif type(seg) == 'string' and seg ~= '' then
                    -- A space at either end of a piece is the room between a key and its word.
                    local lead_sp = seg:match('^%s+') and 3.2 or 0
                    local trail = seg:match('%s+$') and 3.2 or 0
                    local core = seg:gsub('^%s+', ''):gsub('%s+$', '')
                    if core ~= '' then
                        local p = piece(core, Fc.ui, 11, 400, 0)
                        items[#items + 1] = { p = p, x = x + lead_sp }
                        x = x + lead_sp + p.w + trail
                    else
                        x = x + math.max(lead_sp, trail)
                    end
                end
            end
        end
        local top = y
        if x <= W - 28 then
            rows[#rows + 1] = function(out, x0, y0)
                for _, it in ipairs(items) do
                    local base = y0 + top + base_in(it.p, 16)
                    if it.key then
                        box(out, 'key', x0 + 16 + it.kx, y0 + top + 0.5, it.kw, 15, 4, th.chip, th.kbd_a)
                        box(out, 'key-edge', x0 + 16 + it.kx + 1, y0 + top + 1.5, it.kw - 2, 13, 3, th.chip, th.kbd_edge_a, 1)
                        box(out, 'key-edge', x0 + 16 + it.kx + 2, y0 + top + 14.5, it.kw - 4, 1, 0, th.chip, th.kbd_edge_a)
                        text(out, 'key-label', x0 + 16 + it.x, base, it.p, th.quiet, 1)
                    else
                        text(out, 'legend', x0 + 16 + it.x, base, it.p, th.ink3, 1)
                    end
                end
            end
        end
        y = y + 16 + 6
    else
        y = y + 4
    end

    local panel = { w = W, h = y, regions = regions }
    function panel.draw(out, x, yy)
        card_ground(out, x, yy, W, panel.h, 16, th, false)
        for _, row in ipairs(rows) do row(out, x, yy) end
        for _, row in ipairs(body) do row.draw(out, x, yy + body_top + row.y) end
    end
    return panel
end

--- Over the line and centred on its word, as far as the picture lets it be; under the line where there is no room over it.
local function place(card, line, idx)
    local w = line.boxes[idx] and line.boxes[idx][1]
    if not w then return nil end
    local b = line.box
    local x = math.max(8, math.min(U.w - card.w - 8, (w.x0 + w.x1) / 2 - card.w / 2))
    local y = b.y - 8 - card.h
    if y < 8 then
        local under = b.y + b.h + 8
        y = (under + card.h <= U.h - 8) and under or 8
    end
    return round(x), round(y)
end

local function draw_card()
    local line, idx, entry = state.line, active_token(), state.popup
    if not line or not line.box or not idx or not entry or entry.tok ~= idx or entry.id ~= line.id then
        ov_card:remove()
        state.card = nil
        return
    end
    local pinned = (state.pinned == idx)
    local card = pinned and build_panel(entry, line.box.y - 16) or build_glance(entry)
    local x, y = place(card, line, idx)
    if not x then
        ov_card:remove()
        state.card = nil
        return
    end
    local out = {}
    card.draw(out, x, y)
    state.card = { x = x, y = y, w = card.w, h = card.h, regions = card.regions or {}, pinned = pinned }
    ov_card.res_x, ov_card.res_y = U.w, U.h
    ov_card.data = table.concat(out, '\n')
    ov_card:update()
end

local function draw()
    local line = state.line
    if not state.enabled or not app.ready or not line or line.text == '' or not line.box then
        clear_overlays()
        return
    end
    draw_line()
    ov_line.res_x, ov_line.res_y = U.w, U.h
    ov_line.data = line.drawn
    ov_line:update()
    draw_card()
end

----------------------------------------------------------------- mpv's own subtitles

local function hide_native()
    if state.saved_visibility == nil then
        state.saved_visibility = mp.get_property_native('sub-visibility')
        mp.set_property_native('sub-visibility', false)
    end
end

local function show_native()
    if state.saved_visibility ~= nil then
        mp.set_property_native('sub-visibility', state.saved_visibility)
        state.saved_visibility = nil
    end
end

----------------------------------------------------------------- the pointer and the keys

local bound_keys = nil   -- the names of the keys held while a word is pointed at or open

local function release_pause()
    if state.we_paused then
        state.we_paused = false
        mp.set_property_native('pause', false)
    end
end

local function unbind_keys()
    if not bound_keys then return end
    for _, name in ipairs(bound_keys) do mp.remove_key_binding(name) end
    bound_keys = nil
end

local function ask_meaning(pin)
    local line, idx = state.line, active_token()
    if not line or not idx or not line.toks[idx] then return end
    local tok = line.toks[idx]
    -- A card already up says the same as the one that would be asked for; a click asks all the same, for it files the word.
    if not pin and state.popup and state.popup.id == line.id and state.popup.tok == idx then return end
    send({ t = 'lookup', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e), pin = pin and true or nil,
           paused = pin and mp.get_property_native('pause') == true or nil })
end

local function grade(status)
    local line, idx = state.line, active_token()
    if not line or not idx or not line.toks[idx] then return end
    local tok = line.toks[idx]
    if tok.g then
        mp.osd_message('Sluka: a piece of grammar, not a word to grade')
        return
    end
    send({ t = 'grade', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e), status = status })
end

--- A temporary file's path, for a picture of the frame on screen (the app takes it for the card, and deletes it).
local shots = 0
local function shot_path()
    shots = shots + 1
    local dir = os.getenv('TEMP') or os.getenv('TMP') or os.getenv('TMPDIR') or '/tmp'
    local name = string.format('sluka-shot-%d-%d.jpg', utils.getpid and utils.getpid() or 0, shots)
    return utils.join_path(dir, name), name
end

--- The word open into Anki (the panel's Anki key, or its key): with the line's times in the file, the file itself,
--- its sound track, and the frame on screen -- for its card's clip and picture (mpv-engine.js anki).
local function pick_anki()
    local line, idx = state.line, active_token()
    if not line or not idx or not line.toks or not line.toks[idx] then return end
    local tok = line.toks[idx]
    if tok.g then return end
    local m = { t = 'anki', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e),
                start = line.sub_start, ['end'] = line.sub_end, title = mp.get_property('media-title') or '' }
    local path = mp.get_property('path') or ''
    if path ~= '' and not path:find('^%a[%w+.-]*://') then
        local dir = mp.get_property('working-directory') or ''
        m.path = (dir ~= '' and not path:find('^/') and not path:find('^%a:[\\/]') and not path:find('^\\\\')) and utils.join_path(dir, path) or path
    end
    for _, track in ipairs(mp.get_property_native('track-list') or {}) do
        if track.type == 'audio' and track.selected then m.aid = track['src-id'] end
    end
    local full, name = shot_path()
    if mp.commandv('screenshot-to-file', full, 'video') then m.shot = name end
    send(m)
end

--- The open word said (the head's speaker, or its key): pressed again while it is, it stops.
local function speak_word()
    local line, idx = state.line, active_token()
    if not line or not idx or not line.toks or not line.toks[idx] then return end
    local tok = line.toks[idx]
    send({ t = 'speak', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e) })
end

--- The open word into Google Translate (the head's Translate key): its translation is shown in the panel.
local function translate_word()
    local line, idx = state.line, active_token()
    if not line or not idx or not line.toks or not line.toks[idx] or not state.popup then return end
    local tok = line.toks[idx]
    state.popup.tr = { status = 'loading' }
    draw_card()
    send({ t = 'translate', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e) })
end

--- A site of the Look up menu, or its dictionary offline, in a small window of Sluka's own.
local function look_site(site, offline)
    local line, idx = state.line, active_token()
    state.look_open = false
    if not line or not idx or not line.toks or not line.toks[idx] or type(site) ~= 'string' then return end
    local tok = line.toks[idx]
    send({ t = 'look', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e), site = site, offline = offline and true or nil })
    draw_card()
end

--- The open word asked of the AI check (the ✦, its button, or its key): once, its answer drawn in the panel.
local function ask_ai()
    local line, idx = state.line, active_token()
    local p = state.popup
    if not line or not idx or not line.toks or not line.toks[idx] or not p or not state.pinned then return end
    if type(p.tools) ~= 'table' or type(p.tools.ask) ~= 'table' or ask_settled(p) then return end
    local tok = line.toks[idx]
    state.verdict = { id = p.id, tok = p.tok, status = 'loading', label = p.tools.ask.wait }
    draw_card()
    send({ t = 'ask', id = line.id, tok = idx, key = tok.key, text = line.text:sub(tok.s + 1, tok.e) })
end

--[[
The check's key (Settings → Keyboard, F) is the panel's only while it is open: a press is a request on your key,
and with no panel open the key is mpv's again (F, full screen).
]]
local ask_keys = nil

local function bind_ask()
    if ask_keys or look.ask_key == '' then return end
    ask_keys = {}
    local seen = {}
    for _, k in ipairs({ look.ask_key:lower(), look.ask_key:upper() }) do
        if not seen[k] then
            seen[k] = true
            local name = 'sluka-ask-' .. k
            ask_keys[#ask_keys + 1] = name
            mp.add_forced_key_binding(k, name, ask_ai)
        end
    end
end

local function unbind_ask()
    if not ask_keys then return end
    for _, name in ipairs(ask_keys) do mp.remove_key_binding(name) end
    ask_keys = nil
end

local function unpin()
    if not state.pinned then return end
    state.pinned = nil
    mp.remove_key_binding('sluka-unpin')
    unbind_ask()
    if not state.hover then
        state.popup = nil
        unbind_keys()
        release_pause()
    elseif state.popup and state.popup.tok ~= state.hover then
        state.popup = nil
    end
    draw()
end

--- What of the open panel is under a point: one of its buttons, the panel itself (true), or nothing.
local function panel_at(x, y)
    local c = state.card
    if not c or not c.pinned then return nil end
    if x < c.x or x > c.x + c.w or y < c.y or y > c.y + c.h then return nil end
    for _, r in ipairs(c.regions) do
        if x >= c.x + r.x0 and x <= c.x + r.x1 and y >= c.y + r.y0 and y <= c.y + r.y1 then return r end
    end
    return true
end

local function on_click()
    local m = state.mouse
    local hit = panel_at(m.x / U.k, m.y / U.k)
    if type(hit) == 'table' then
        if hit.act == 'close' then unpin() elseif hit.act == 'grade' then grade(hit.st) elseif hit.act == 'anki' then pick_anki()
        elseif hit.act == 'speak' then speak_word()
        elseif hit.act == 'ask' then ask_ai()
        elseif hit.act == 'translate' then translate_word()
        elseif hit.act == 'look' then state.look_open = not state.look_open; draw_card()
        elseif hit.act == 'site' then look_site(hit.site, hit.offline) end
    elseif hit then
        return   -- a click on the panel itself is not one beside it
    elseif state.pinned and state.pinned == state.hover then
        unpin()
    elseif state.hover then
        state.pinned = state.hover
        -- Esc puts the panel away, and is mpv's own key again once it has.
        mp.add_forced_key_binding('ESC', 'sluka-unpin', unpin)
        bind_ask()
        ask_meaning(true)
        draw()
    else
        unpin()
    end
end

local function bind_keys()
    if bound_keys then return end
    bound_keys = { 'sluka-click' }
    mp.add_forced_key_binding('MBTN_LEFT', 'sluka-click', on_click)
    local seen = {}
    for status, key in pairs(look.keys) do
        local both = { key }
        if key:lower() ~= key:upper() then both = { key:lower(), key:upper() } end
        for _, k in ipairs(both) do
            if not seen[k] then
                seen[k] = true
                local name = 'sluka-grade-' .. k
                bound_keys[#bound_keys + 1] = name
                mp.add_forced_key_binding(k, name, function() grade(status) end)
            end
        end
    end
    local say = look.say_key
    if say ~= '' then
        for _, k in ipairs({ say:lower(), say:upper() }) do
            if not seen[k] then
                seen[k] = true
                local name = 'sluka-say-' .. k
                bound_keys[#bound_keys + 1] = name
                mp.add_forced_key_binding(k, name, speak_word)
            end
        end
    end
    local anki = look.anki_key
    if anki ~= '' then
        for _, k in ipairs({ anki:lower(), anki:upper() }) do
            if not seen[k] then
                seen[k] = true
                local name = 'sluka-anki-' .. k
                bound_keys[#bound_keys + 1] = name
                mp.add_forced_key_binding(k, name, pick_anki)
            end
        end
    end
end

local function token_at(x, y)
    local line = state.line
    if not line or not line.boxes then return nil end
    for i, list in pairs(line.boxes) do
        for _, b in ipairs(list) do
            if x >= b.x0 and x <= b.x1 and y >= b.top and y <= b.bottom then return i end
        end
    end
    return nil
end

local function set_hover(idx)
    if idx == state.hover then return end
    state.hover = idx
    if dwell_timer then dwell_timer:kill() end
    if idx then
        bind_keys()
        if o.pause_on_hover and not mp.get_property_native('pause') then
            state.we_paused = true
            mp.set_property_native('pause', true)
        end
        if not state.pinned then
            state.popup = nil
            dwell_timer = mp.add_timeout(math.max(0.02, look.hover_delay), function() ask_meaning(false) end)
        end
    elseif not state.pinned then
        state.popup = nil
        unbind_keys()
        release_pause()
    end
    draw()
end

local function refresh_hover()
    local m = state.mouse
    if not state.enabled or not app.ready or not m.inside then
        set_hover(nil)
        return
    end
    local x, y = m.x / U.k, m.y / U.k
    -- Over the open panel the pointer is on the panel, whatever lies under it.
    if panel_at(x, y) then
        set_hover(nil)
        return
    end
    set_hover(token_at(x, y))
end

mp.observe_property('mouse-pos', 'native', function(_, v)
    if not v then return end
    state.mouse.x, state.mouse.y = v.x or -1, v.y or -1
    state.mouse.inside = v.hover ~= false
    refresh_hover()
end)

----------------------------------------------------------------- lines

local function drop_line()
    state.line = nil
    state.hover = nil
    if state.pinned then
        mp.remove_key_binding('sluka-unpin')
        unbind_ask()
    end
    state.pinned = nil
    state.popup = nil
    state.waiting_since = nil
    if plain_timer then plain_timer:kill() end
    if dwell_timer then dwell_timer:kill() end
    unbind_keys()
    clear_overlays()
end

local function app_gone(why)
    if not app.ready then return end
    app.ready = false
    note('the app is not answering' .. (why and (': ' .. why) or ''))
    drop_line()
    release_pause()
    show_native()
end

-- A line laid out and drawn; an error in either is said once and leaves mpv's own subtitles to show the line.
local function show(line)
    local ok, err = pcall(function()
        layout(line)
        refresh_hover()
        draw()
    end)
    if ok then return true end
    note('the line could not be drawn: ' .. tostring(err))
    clear_overlays()
    show_native()
    return false
end

local function new_line(text)
    text = (text or ''):gsub('\r', '')
    -- Not a new line when the text is the one already up: seeking inside a line, or a property told twice.
    if state.line and state.line.text == text then return end
    drop_line()
    if text == '' or not text:find('%S') then
        release_pause()
        return
    end
    if not state.enabled or not app.ready then return end

    state.line_seq = state.line_seq + 1
    local line = {
        id = state.line_seq,
        text = text,
        toks = nil,
        sub_end = mp.get_property_number('sub-end'),
        sub_start = mp.get_property_number('sub-start'),
        paused_at_end = false,
    }
    state.line = line
    hide_native()
    -- When the line starts and ends in the file: the app counts its words once half of it has played (as SlukaCC does).
    send({ t = 'line', id = line.id, text = text, start = mp.get_property_number('sub-start'), ['end'] = line.sub_end })
    if not state.waiting_since then state.waiting_since = mp.get_time() end

    -- Shown plain if its words are slow in coming, so no line is ever missing.
    plain_timer = mp.add_timeout(PLAIN_AFTER, function()
        if state.line == line and not line.box then
            line.toks = line.toks or {}
            show(line)
        end
    end)
    if gone_timer then gone_timer:kill() end
    gone_timer = mp.add_timeout(GONE_AFTER, function()
        if state.waiting_since and mp.get_time() - state.waiting_since >= GONE_AFTER - 0.05 then app_gone('no answer') end
    end)
end

mp.observe_property('sub-text', 'string', function(_, text)
    new_line(text)
end)

-- Another size of window, or another screen: everything is laid out again for it.
local function resized()
    local line = state.line
    if fresh_units() and line and line.box then show(line) end
end
mp.observe_property('osd-dimensions', 'native', resized)
mp.observe_property('display-hidpi-scale', 'native', resized)

-- Stop at the end of the line, once, a little before it is taken away.
mp.observe_property('time-pos', 'number', function(_, t)
    local line = state.line
    if not t or not line or not state.auto_pause or line.paused_at_end then return end
    if not line.sub_end then line.sub_end = mp.get_property_number('sub-end') end
    if line.sub_end and t >= line.sub_end - 0.12 and t <= line.sub_end + 0.5 then
        line.paused_at_end = true
        mp.set_property_native('pause', true)
    end
end)

-- A pause the viewer made or ended is theirs from then on.
mp.observe_property('pause', 'bool', function(_, paused)
    if not paused then state.we_paused = false end
end)

----------------------------------------------------------------- the app

local function sub_lang()
    return mp.get_property('current-tracks/sub/lang') or ''
end

-- Subtitles that are pictures (as on a disc) have no words in them to read.
local PICTURE_SUBS = { hdmv_pgs_subtitle = true, dvd_subtitle = true, dvb_subtitle = true, xsub = true }

-- 'text', 'pictures' or 'none', and the track's format as mpv names it.
local function sub_kind()
    local codec = mp.get_property('current-tracks/sub/codec') or ''
    if codec == '' then return 'none', '' end
    if PICTURE_SUBS[codec] then return 'pictures', codec end
    return 'text', codec
end

local SUB_NOTICE = {
    none = 'no subtitle track is on',
    pictures = 'these subtitles are pictures, which Sluka cannot read',
}

----------------------------------------------------------------- how long it was heard

--[[
The minutes on Sluka's Home page are worked out by the app (app/web/progress.js)
the way Sluka's own Your videos page works them out (videos/listen-clock.js):
between two looks at the player, the smaller of the time that passed and how
far the file moved on, while it played with its sound on.  This only looks --
every second while the file plays, and at every change (a pause, the sound
off, a seek, the end) -- so that what a look says held for the whole stretch
after it.  A look also says the file's title, which is the film's name in
Sluka's Listening tab and part of how the app tells which language it is in,
and the language its audio track is marked with, the other part.  Neither is
written into any log.
]]
local CLOCK_EVERY = 1
local clock = { last = nil, failed = false }

local function audio_on()
    if mp.get_property('current-tracks/audio/id') then return true end
    local aid = mp.get_property('aid') or ''
    return aid:match('^%d+$') ~= nil
end

local function clock_look()
    local pos = mp.get_property_number('time-pos')
    local play = pos ~= nil and not mp.get_property_bool('pause', false) and not mp.get_property_bool('idle-active', false)
        and not mp.get_property_bool('eof-reached', false) and not mp.get_property_bool('seeking', false)
    local sound = play and audio_on() and not mp.get_property_bool('mute', false)
        and (mp.get_property_number('volume', 100) or 100) > 0
    return {
        t = 'clock', at = mp.get_time(), pos = pos, play = play, sound = sound,
        title = mp.get_property('media-title') or '', alang = mp.get_property('current-tracks/audio/lang') or '',
    }
end

-- A look: each second's (`tick`) while the file plays; on a change, only where what it says is not what the last said;
-- the last one (`whole`) whatever it says.
local function send_clock(tick, whole)
    if not app.ready then return end
    local ok, err = pcall(function()
        local look = clock_look()
        local last = clock.last
        local changed = not last or look.play ~= last.play or look.sound ~= last.sound or look.title ~= last.title
            or look.alang ~= last.alang
        if not changed and not whole and not (tick and look.play) then return end
        clock.last = look
        send(look)
    end)
    if not ok and not clock.failed then
        clock.failed = true
        note('the player could not be looked at for the time heard: ' .. tostring(err))
    end
end

mp.add_periodic_timer(CLOCK_EVERY, function() send_clock(true) end)
for _, name in ipairs({ 'pause', 'mute', 'volume', 'seeking', 'idle-active', 'eof-reached', 'aid',
                         'current-tracks/audio/lang', 'media-title' }) do
    mp.observe_property(name, 'native', function() send_clock(false) end)
end

local function say_hello()
    -- The language a subtitle track is marked with is all the app is told about the file.
    send({ t = 'hello', v = PROTOCOL, pid = utils.getpid(), sub_lang = sub_lang() })
end

local handlers = {}

function handlers.hello()
    say_hello()
end

function handlers.ready(m)
    local was_ready = app.ready
    app.ready = true
    app.lang = m.lang or ''
    app.lang_name = m.lang_name or app.lang
    -- (an app that answers again may be one started since, which has seen no look of this player's yet)
    clock.last = nil
    -- How Sluka is set to look, as its own settings have it now.
    adopt_look(m.look)
    F = nil
    unbind_keys()
    fresh_units()
    if not was_ready then
        local kind, codec = sub_kind()
        note(string.format('the app answered: %s; subtitles: %s%s; drawing for %dx%d at %s', app.lang ~= '' and app.lang or '?', kind,
            codec ~= '' and (' (' .. codec .. ')') or '', U.w, U.h, num(U.k)))
        if type(m.v) == 'number' and m.v ~= PROTOCOL then
            note(string.format('the app speaks version %s of what this script speaks version %d of: one of the two is older', tostring(m.v), PROTOCOL))
        end
        if not m.quiet then
            -- Said on the picture, so that it can be seen that Sluka is there.
            local text = 'Sluka: ' .. (app.lang_name ~= '' and app.lang_name or 'connected')
            if SUB_NOTICE[kind] and mp.get_property('path') then text = text .. ' \194\183 ' .. SUB_NOTICE[kind] end
            mp.osd_message(text, SUB_NOTICE[kind] and 4 or 2)
        end
    end
    -- The line on screen now, asked for again under the new language or colours.
    local text = mp.get_property('sub-text') or ''
    state.line = nil
    new_line(text)
end

function handlers.tokens(m)
    local line = state.line
    state.waiting_since = nil
    if not line or m.id ~= line.id or type(m.toks) ~= 'table' then return end
    line.toks = m.toks
    line.rtl = m.rtl and true or false
    if plain_timer then plain_timer:kill() end
    show(line)
end

function handlers.entry(m)
    local line = state.line
    if not line or m.id ~= line.id or m.tok ~= active_token() then return end
    local old = state.popup
    if old and old.id == m.id and old.tok == m.tok then
        if old.tr and not m.tr then m.tr = old.tr end  -- (the same word told again: its translation kept)
    else
        state.look_open = false
        state.verdict = nil
    end
    state.popup = m
    draw_card()
end

function handlers.status(m)
    local line = state.line
    if not line or not line.toks then return end
    local changed = false
    for _, tok in ipairs(line.toks) do
        if tok.key == m.key and tok.st ~= m.st then
            tok.st = m.st
            changed = true
        end
    end
    if state.popup and state.popup.key == m.key then
        state.popup.st = m.st
        state.popup.label = m.label or state.popup.label
    end
    -- Known and ignored are done with: the panel is put away, as Sluka puts its own away.
    if m.graded and (m.st == KNOWN or m.st == IGNORED) and state.pinned and line.toks[state.pinned] and line.toks[state.pinned].key == m.key then
        state.pinned = nil
        mp.remove_key_binding('sluka-unpin')
        unbind_ask()
        if not state.hover then
            state.popup = nil
            unbind_keys()
            release_pause()
        end
    end
    if (changed or m.graded) and line.box then draw() end
end

--- The open word's speaker lit while it is said, and put out when it stops.
function handlers.speaking(m)
    local p = state.popup
    if not p or p.id ~= m.id or p.tok ~= m.tok then return end
    p.speaking = m.on == true
    if state.pinned then draw_card() end
end

--- Google's translation of the open word.
function handlers.translation(m)
    local p = state.popup
    if not p or p.id ~= m.id or p.tok ~= m.tok then return end
    p.tr = m.ok and { status = 'done', text = m.text, alternatives = m.alternatives } or { status = 'error', error = m.error }
    if state.pinned then draw_card() end
end

--- What the AI check said of the open word, or that it is on its way.
function handlers.verdict(m)
    local p = state.popup
    if not p or p.id ~= m.id or p.tok ~= m.tok then return end
    state.verdict = m
    if state.pinned then draw_card() end
end

--- The open panel's Anki key told again (the pick taken, the card made).
function handlers.anki(m)
    local p = state.popup
    if not p or p.id ~= m.id or p.tok ~= m.tok then return end
    p.anki = (type(m.state) == 'string' and m.state ~= '') and { state = m.state, title = m.title, key = m.key } or nil
    if state.pinned then draw_card() end
end

function handlers.say(m)
    if m.text then mp.osd_message('Sluka: ' .. tostring(m.text), m.seconds or 3) end
end

function handlers.bye()
    app_gone('closed')
end

mp.register_script_message('sluka-app', function(json)
    local m = utils.parse_json(json or '')
    if type(m) ~= 'table' or not m.t then return end
    local handler = handlers[m.t]
    if handler then
        local ok, err = pcall(handler, m)
        if not ok then note('error while handling "' .. tostring(m.t) .. '": ' .. tostring(err)) end
    end
end)

-- Another subtitle track, another file: the app may want another language.
mp.observe_property('current-tracks/sub/lang', 'string', function()
    if app.ready then send({ t = 'track', sub_lang = sub_lang() }) end
end)

-- Another track may be one of pictures, which only mpv can draw: its subtitles
-- are given back until a line of text arrives again.
mp.observe_property('sid', 'native', function()
    drop_line()
    release_pause()
    show_native()
    if app.ready and state.enabled then new_line(mp.get_property('sub-text') or '') end
end)

-- A file Sluka can do nothing with is noted for the app's log, so that "nothing
-- happened" has its reason there: the formats, never the name.  A file with
-- words to read is not noted at all.
mp.register_event('file-loaded', function()
    local kind, codec = sub_kind()
    if kind == 'text' then return end
    note(string.format('a file was opened without subtitles Sluka can read: video %s, subtitles: %s%s%s', mp.get_property('video-format') or 'none', kind,
        codec ~= '' and (' (' .. codec .. ')') or '', sub_lang() ~= '' and (', marked ' .. sub_lang()) or ''))
    if app.ready and state.enabled and kind == 'pictures' then
        mp.osd_message('Sluka: ' .. SUB_NOTICE.pictures, 4)
    end
end)

----------------------------------------------------------------- keys of the script's own

local function toggle()
    state.enabled = not state.enabled
    if state.enabled then
        mp.osd_message(app.ready and 'Sluka subtitles: on' or 'Sluka subtitles: on (waiting for Sluka Desktop)')
        state.line = nil
        new_line(mp.get_property('sub-text') or '')
    else
        mp.osd_message('Sluka subtitles: off')
        drop_line()
        release_pause()
        show_native()
    end
end

local function toggle_auto_pause()
    state.auto_pause = not state.auto_pause
    mp.osd_message('Sluka: pause at the end of each line ' .. (state.auto_pause and 'on' or 'off'))
end

local function replay()
    mp.commandv('sub-seek', '0')
    mp.set_property_native('pause', false)
    if state.line then state.line.paused_at_end = false end
end

mp.add_key_binding(o.key_toggle ~= '' and o.key_toggle or nil, 'toggle', toggle)
mp.add_key_binding(o.key_auto_pause ~= '' and o.key_auto_pause or nil, 'auto-pause', toggle_auto_pause)
mp.add_key_binding(o.key_replay ~= '' and o.key_replay or nil, 'replay-line', replay)

----------------------------------------------------------------- the socket the app finds this player by

local function is_dir(path)
    local info = utils.file_info(path)
    return info ~= nil and info.is_dir == true
end

-- The name of the Flatpak this player runs as, if it is one (Celluloid in Tails is).
local function flatpak_id()
    local id = os.getenv('FLATPAK_ID')
    if id and id ~= '' then return id end
    local f = io.open('/.flatpak-info', 'r')
    if not f then return nil end
    local text = '\n' .. (f:read('*a') or '')
    f:close()
    return text:match('\nname=([^\r\n]+)')
end

-- The folder for the socket, and whether that folder is this script's alone.
--[[
Windows: a setting of the environment as mpv itself gives it, which is in
UTF-8, the way mpv's own functions take a path.  Lua's os.getenv may give it
as the system's older programs see it, which is the way Lua's own file
functions take one.  For a user name in English letters the two are the same.
]]
local function win_env(name)
    if utils.get_env_list then
        local ok, list = pcall(utils.get_env_list)
        if ok and type(list) == 'table' then
            for _, entry in ipairs(list) do
                local key, value = tostring(entry):match('^([^=]+)=(.*)$')
                if key and key:upper() == name and value ~= '' then return value end
            end
        end
    end
    return os.getenv(name)
end

local function win_folder(get)
    -- The app has the same words for this folder (config.py, local_dir).
    local base = get('LOCALAPPDATA')
    if not base or base == '' then base = get('TEMP') or get('TMP') or '.' end
    return base .. '\\sluka-desktop\\mpv'
end

local function socket_place()
    if o.socket_dir ~= '' then return o.socket_dir, true end
    if WINDOWS then
        state.plain_dir = win_folder(os.getenv)
        return win_folder(win_env), true
    end
    local runtime = os.getenv('XDG_RUNTIME_DIR')
    local app = flatpak_id()
    if app and runtime and runtime ~= '' then
        -- A Flatpak sees a runtime folder of its own.  The one folder in it that
        -- the rest of the system sees as well is the app's, and the Sluka app
        -- looks there for the players it knows.
        local shared = runtime .. '/app/' .. app
        local own = shared .. '/sluka-mpv'
        if not is_dir(own) then run({ 'mkdir', '-p', '-m', '700', own }) end
        if is_dir(own) then return own, true end
        return shared, false
    end
    if runtime and runtime ~= '' then return runtime .. '/sluka-mpv', true end
    return '/tmp/sluka-mpv-' .. (run({ 'id', '-u' }) or 'user'), true
end

--[[
Windows: mpv's IPC there is a named pipe, which is in no folder.  The pipe is
named after this player's process, so the app finds it among the pipes there
are; and a note in the app's folder says which pipe it is, for a player that
was started with a pipe of its own.
]]
local function open_pipe(dir)
    local name = tostring(utils.getpid())
    local prefix = '\\\\.\\pipe\\'
    local existing = mp.get_property('options/input-ipc-server') or mp.get_property('input-ipc-server') or ''
    local pipe = existing
    if pipe == '' then
        pipe = prefix .. 'sluka-mpv-' .. name
        local ok, err = mp.set_property('options/input-ipc-server', pipe)
        if not ok then ok, err = mp.set_property('input-ipc-server', pipe) end
        if not ok then
            note('the pipe could not be opened at ' .. pipe .. ': ' .. tostring(err))
            return
        end
    elseif pipe:sub(1, #prefix) ~= prefix then
        pipe = prefix .. pipe   -- as mpv itself does with a bare name
    end
    local path = dir .. SEP .. name .. '.path'
    local f = io.open(path, 'w')
    if f then
        f:write(pipe)
        f:close()
        state.pointer_file = path
    end
    if existing ~= '' then
        note('this player has a pipe of its own (' .. pipe .. ')' .. (f and '; the app is told of it in ' .. path or ', and ' .. path .. ' could not be written to say where'))
    else
        note('waiting for the app at ' .. pipe)
    end
end

local function open_socket()
    local dir, own = socket_place()
    if WINDOWS then
        -- The app makes this folder when it starts; made here for a player opened before the app ever ran
        -- (and for an app whose Python is the Microsoft Store's, which can make no folder others see).
        if not is_dir(dir) then run({ 'cmd', '/d', '/c', 'mkdir', dir }) end
        -- Written with Lua's own functions, so named as those take a name (win_env).
        local files = state.plain_dir or dir
        notes_go_to(files .. SEP .. 'script.log')
        open_pipe(files)
        return
    end
    if own and not is_dir(dir) then run({ 'mkdir', '-p', '-m', '700', dir }) end
    local name = tostring(utils.getpid())
    if flatpak_id() then
        -- A sandbox numbers its processes from one, so the number alone does
        -- not tell two players apart.
        math.randomseed(os.time() + math.floor((mp.get_time() % 1) * 1000000))
        name = string.format('%s-%x%04x', name, os.time() % 0x10000000, math.random(0, 0xffff))
    end
    -- In a folder that is not this script's alone, the name says whose the file is.
    if not own then name = 'sluka-' .. name end
    notes_go_to(dir .. '/' .. (own and 'script.log' or 'sluka-script.log'))
    if not is_dir(dir) then note('the folder for the socket could not be made: ' .. dir) end
    local existing = mp.get_property('options/input-ipc-server') or mp.get_property('input-ipc-server') or ''
    if existing ~= '' then
        -- mpv was started with a socket of its own: the app is told where it is.
        local path = dir .. '/' .. name .. '.path'
        local f = io.open(path, 'w')
        if f then
            f:write(existing)
            f:close()
            state.pointer_file = path
            note('this player has a socket of its own (' .. existing .. '); the app is told of it in ' .. path)
        else
            note('this player has a socket of its own, and ' .. path .. ' could not be written to say where')
        end
        return
    end
    local path = dir .. '/' .. name .. '.sock'
    -- mpv opens its socket anew when this option is changed while it runs,
    -- which is how other scripts give every player a socket of its own too.
    local ok, err = mp.set_property('options/input-ipc-server', path)
    if not ok then ok, err = mp.set_property('input-ipc-server', path) end
    if ok then
        state.socket_file = path
        note('waiting for the app at ' .. path)
    else
        note('the socket could not be opened at ' .. path .. ': ' .. tostring(err))
    end
end

mp.register_event('shutdown', function()
    -- The last stretch heard, up to now, before the player goes.
    pcall(send_clock, false, true)
    pcall(send, { t = 'bye' })
    show_native()
    if state.pointer_file then os.remove(state.pointer_file) end
    if state.socket_file then os.remove(state.socket_file) end
end)

open_socket()
