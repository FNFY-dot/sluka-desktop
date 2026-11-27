--[[
The script's looks at the player, for the time heard (app/web/progress.js): one
a second while a file plays and one at each change of what a look says, none
while it is paused and nothing changes, a last one when the player closes; and
each line with when it starts and ends.

    texlua clock.lua /path/to/sluka.lua
]]

local here = arg[0]:match('^(.*)[/\\]') or '.'
local H = dofile(here .. '/fake_mpv.lua')
local script = assert(arg[1], 'the script to run')

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

local tmp = os.getenv('SLUKA_TEST_TMP') or '/tmp'
H.config_dir = tmp .. '/mpv'
H.listing = { [tmp .. '/mpv/fonts'] = {} }
H.props['platform'] = 'linux'
H.props['mpv-version'] = 'mpv 0.36.0'
H.props['options/input-ipc-server'] = ''
H.props['input-ipc-server'] = ''
H.props['sub-visibility'] = true
H.props['pause'] = false
H.props['sub-text'] = ''
H.props['current-tracks/sub/lang'] = 'jpn'
H.props['current-tracks/sub/codec'] = 'ass'
H.props['display-hidpi-scale'] = 1
H.props['osd-dimensions'] = { w = 1920, h = 1080 }
H.props['path'] = '/videos/episode.mkv'
H.props['media-title'] = '日常 第1話'
H.props['current-tracks/audio/id'] = 1
H.props['current-tracks/audio/lang'] = 'jpn'
H.props['aid'] = 1
H.props['volume'] = 100
H.props['mute'] = false
H.props['time-pos'] = 10.0
H.props['idle-active'] = false
H.props['eof-reached'] = false
H.props['seeking'] = false

print('the script, loaded')
H.load(script)
check(#H.errors == 0, 'it loads without an error')

print('before the app is there')
H.advance(3)
check(#only(H.said(), 'clock') == 0, 'no look is sent to nobody')

print('the app says hello, and is ready')
H.app_says({ t = 'hello', app = '0.12.3' })
H.said()
H.app_says({ t = 'ready', v = 2, lang = 'ja', lang_name = 'Japanese', quiet = true, look = {} })
check(#H.errors == 0, 'no error while getting ready')
H.said()

print('three seconds of the file playing')
local looks = {}
for i = 1, 3 do
    H.props['time-pos'] = 10.0 + i
    H.advance(1)
    for _, m in ipairs(only(H.said(), 'clock')) do looks[#looks + 1] = m end
end
check(#looks == 3, 'a look each second (' .. #looks .. ')')
local first = looks[1] or {}
check(first.play == true and first.sound == true, 'playing, and heard')
check(first.pos == 11 and type(first.at) == 'number', 'where in the file, and mpv\'s own clock (' .. tostring(first.pos) .. ', ' .. tostring(first.at) .. ')')
check(first.title == '日常 第1話' and first.alang == 'jpn', 'the title and the audio track\'s language (' .. tostring(first.title) .. ', ' .. tostring(first.alang) .. ')')
check(looks[3] and looks[3].at - looks[1].at == 2, 'a second apart on mpv\'s clock')

print('paused')
H.set_prop('pause', true)
local said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == false and said[1].sound == false, 'a look at once: not playing')
H.advance(5)
check(#only(H.said(), 'clock') == 0, 'and none while it stays paused')
H.set_prop('volume', 80)
check(#only(H.said(), 'clock') == 0, 'nor for a change that changes nothing a look says')

print('playing again, the sound off')
H.set_prop('mute', true)
check(#only(H.said(), 'clock') == 0, 'muted while paused: a look would say the same')
H.set_prop('pause', false)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == true and said[1].sound == false, 'playing, not heard')
H.props['time-pos'] = 14.0
H.advance(1)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].sound == false, 'and so each second')
H.set_prop('mute', false)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].sound == true, 'the sound back on: a look at once')

print('the volume at nothing, then a file without sound')
H.set_prop('volume', 0)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].sound == false, 'nothing heard at volume 0')
H.set_prop('volume', 100)
H.said()
H.props['current-tracks/audio/id'] = nil
H.set_prop('aid', 'no')
said = only(H.said(), 'clock')
check(#said == 1 and said[1].sound == false and said[1].play == true, 'no audio track: playing, not heard')
H.props['current-tracks/audio/id'] = 1
H.set_prop('aid', 1)
H.said()

print('a seek')
H.set_prop('seeking', true)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == false, 'seeking is not playing')
H.props['time-pos'] = 120.0
H.set_prop('seeking', false)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == true and said[1].pos == 120, 'playing again where the seek went')

print('a line, with when it starts and ends')
H.props['sub-start'] = 120.5
H.props['sub-end'] = 123.25
H.set_prop('sub-text', 'こんにちは')
local line = only(H.said(), 'line')[1]
check(line ~= nil and line.start == 120.5 and line['end'] == 123.25, 'start ' .. tostring(line and line.start) .. ', end ' .. tostring(line and line['end']))

print('another file')
H.set_prop('media-title', 'Another film')
said = only(H.said(), 'clock')
check(#said == 1 and said[1].title == 'Another film', 'a look at once, with the new title')
H.set_prop('current-tracks/audio/lang', 'eng')
said = only(H.said(), 'clock')
check(#said == 1 and said[1].alang == 'eng', 'and with another audio track\'s language')

print('the end of the file')
H.set_prop('eof-reached', true)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == false, 'at the end: not playing')
H.advance(3)
check(#only(H.said(), 'clock') == 0, 'and quiet after')

print('the app gone and back, the player closing')
H.set_prop('eof-reached', false)
H.said()
H.app_says({ t = 'bye' })
H.advance(2)
check(#only(H.said(), 'clock') == 0, 'no looks while the app is gone')
H.app_says({ t = 'ready', v = 2, lang = 'ja', lang_name = 'Japanese', quiet = true, look = {} })
H.said()
H.props['time-pos'] = 130.0
H.advance(1)
said = only(H.said(), 'clock')
check(#said == 1 and said[1].play == true, 'looks again once it is back')
H.props['time-pos'] = 130.4
H.event('shutdown')
said = H.said()
local last, bye = nil, nil
for i, m in ipairs(said) do
    if m.t == 'clock' then last = i end
    if m.t == 'bye' then bye = i end
end
check(last ~= nil and bye ~= nil and last < bye, 'a last look, then bye')
check(last and said[last].pos == 130.4, 'the last look says where it stopped')

if #H.errors > 0 then
    print('errors inside the script:')
    for _, e in ipairs(H.errors) do print('  ' .. e) end
end
print(failures == 0 and #H.errors == 0 and 'ALL GOOD' or (failures .. ' failed'))
os.exit((failures == 0 and #H.errors == 0) and 0 or 1)
