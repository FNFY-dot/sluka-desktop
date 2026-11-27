--[[
A stand-in for mpv's Lua API: enough of it to run mpv/sluka.lua outside mpv,
and to talk to the script the way the app does (script-message sluka-app /
sluka-mpv).  Where mpv's own behaviour matters to the script it is copied:

  * utils.format_json answers with two values, the text and nil, as mpv 0.36
    does (the cause of "argument 4 is not a string" on Windows);
  * mp.commandv refuses an argument that is not a string or a number, with
    mpv's own words for it;
  * an error inside a callback (observer, timer, key, message) is caught and
    kept, as mpv logs it and carries on -- the tests then fail on it.

Runs under texlua (Lua 5.3); mpv runs the script in LuaJIT (5.1).
]]

local H = {
    props = {},
    observers = {},
    events = {},
    messages = {},
    bindings = {},
    timers = {},
    overlays = {},
    outbox = {},       -- what the script said to the app, decoded
    osd = {},          -- mp.osd_message texts
    errors = {},       -- errors in callbacks
    log = {},          -- msg.* lines
    commands = {},     -- every mp.commandv, as lists of strings
    now = 100.0,
    osd_w = 1920, osd_h = 1080,
    pid = 4242,
    env = {},
    dirs = {},
}

----------------------------------------------------------------- JSON

local function enc_str(s)
    local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
    local body = s:gsub('[%c"\\]', function(c) return map[c] or string.format('\\u%04x', c:byte()) end)
    return '"' .. body .. '"'
end

local function is_array(t)
    local n = 0
    for k in pairs(t) do
        if math.type(k) ~= 'integer' or k < 1 then return false, 0 end
        if k > n then n = k end
    end
    for i = 1, n do if t[i] == nil then return false, 0 end end
    return true, n
end

local function encode(v)
    local ty = type(v)
    if v == nil then return 'null' end
    if ty == 'boolean' then return tostring(v) end
    if ty == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then error('a number JSON cannot hold') end
        if math.floor(v) == v and math.abs(v) < 2 ^ 53 then return string.format('%d', math.floor(v)) end
        return string.format('%.17g', v)
    end
    if ty == 'string' then return enc_str(v) end
    if ty == 'table' then
        local arr, n = is_array(v)
        if arr and n > 0 then
            local out = {}
            for i = 1, n do out[i] = encode(v[i]) end
            return '[' .. table.concat(out, ',') .. ']'
        end
        local keys = {}
        for k in pairs(v) do keys[#keys + 1] = k end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        local out = {}
        for _, k in ipairs(keys) do out[#out + 1] = enc_str(tostring(k)) .. ':' .. encode(v[k]) end
        return '{' .. table.concat(out, ',') .. '}'
    end
    error('cannot write a ' .. ty .. ' as JSON')
end

local function decode(s)
    local pos = 1
    local function ws() pos = s:find('[^ \t\r\n]', pos) or (#s + 1) end
    local value
    local function str()
        assert(s:sub(pos, pos) == '"', 'a string expected at ' .. pos)
        pos = pos + 1
        local out = {}
        while true do
            local c = s:sub(pos, pos)
            if c == '' then error('a string without its end') end
            if c == '"' then pos = pos + 1 break end
            if c == '\\' then
                local e = s:sub(pos + 1, pos + 1)
                if e == 'u' then
                    local cp = tonumber(s:sub(pos + 2, pos + 5), 16)
                    pos = pos + 6
                    if cp >= 0xD800 and cp <= 0xDBFF and s:sub(pos, pos + 1) == '\\u' then
                        local lo = tonumber(s:sub(pos + 2, pos + 5), 16)
                        cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo - 0xDC00)
                        pos = pos + 6
                    end
                    out[#out + 1] = utf8.char(cp)
                else
                    local map = { ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b', f = '\f', n = '\n', r = '\r', t = '\t' }
                    out[#out + 1] = map[e] or e
                    pos = pos + 2
                end
            else
                local j = s:find('["\\]', pos) or (#s + 1)
                out[#out + 1] = s:sub(pos, j - 1)
                pos = j
            end
        end
        return table.concat(out)
    end
    function value()
        ws()
        local c = s:sub(pos, pos)
        if c == '{' then
            pos = pos + 1
            local t = {}
            ws()
            if s:sub(pos, pos) == '}' then pos = pos + 1 return t end
            while true do
                ws()
                local k = str()
                ws()
                assert(s:sub(pos, pos) == ':', 'a colon expected at ' .. pos)
                pos = pos + 1
                t[k] = value()
                ws()
                local d = s:sub(pos, pos)
                pos = pos + 1
                if d == '}' then return t end
                assert(d == ',', 'a comma expected at ' .. (pos - 1))
            end
        elseif c == '[' then
            pos = pos + 1
            local t = {}
            ws()
            if s:sub(pos, pos) == ']' then pos = pos + 1 return t end
            local i = 0
            while true do
                i = i + 1
                t[i] = value()
                ws()
                local d = s:sub(pos, pos)
                pos = pos + 1
                if d == ']' then return t end
                assert(d == ',', 'a comma expected at ' .. (pos - 1))
            end
        elseif c == '"' then
            return str()
        elseif s:sub(pos, pos + 3) == 'true' then
            pos = pos + 4
            return true
        elseif s:sub(pos, pos + 4) == 'false' then
            pos = pos + 5
            return false
        elseif s:sub(pos, pos + 3) == 'null' then
            pos = pos + 4
            return nil
        end
        local num = s:match('^-?%d+%.?%d*[eE]?[-+]?%d*', pos)
        assert(num and #num > 0, 'not JSON at ' .. pos .. ': ' .. s:sub(pos, pos + 20))
        pos = pos + #num
        return tonumber(num)
    end
    local v = value()
    ws()
    return v, pos <= #s and s:sub(pos) or ''
end

H.encode, H.decode = encode, decode

----------------------------------------------------------------- calling back into the script, as mpv does

local function call(what, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then
        H.errors[#H.errors + 1] = what .. ': ' .. tostring(err)
        io.stderr:write('[fake mpv] Lua error in ' .. what .. ': ' .. tostring(err) .. '\n')
    end
    return ok
end

----------------------------------------------------------------- properties

local function as_string(v)
    if v == nil then return nil end
    if type(v) == 'boolean' then return v and 'yes' or 'no' end
    if type(v) == 'table' then return encode(v) end
    return tostring(v)
end

function H.set_prop(name, value)
    H.props[name] = value
    for _, ob in ipairs(H.observers) do
        if ob.name == name then call('observer of ' .. name, ob.fn, name, H.typed(ob.kind, value)) end
    end
end

function H.typed(kind, v)
    if kind == 'string' then return as_string(v) end
    if kind == 'number' then return tonumber(v) end
    if kind == 'bool' then
        if type(v) == 'boolean' then return v end
        return v == 'yes'
    end
    return v
end

----------------------------------------------------------------- mp

local mp = {}

function mp.get_property(name, def)
    local v = as_string(H.props[name])
    if v == nil then return def end
    return v
end
function mp.get_property_native(name, def)
    local v = H.props[name]
    if v == nil then return def end
    return v
end
function mp.get_property_number(name, def)
    local v = tonumber(H.props[name])
    if v == nil then return def end
    return v
end
function mp.get_property_bool(name, def)
    local v = H.props[name]
    if v == nil then return def end
    return v == true or v == 'yes'
end
function mp.set_property(name, v)
    H.set_prop(name, v)
    return true
end
mp.set_property_native = mp.set_property

function mp.observe_property(name, kind, fn)
    H.observers[#H.observers + 1] = { name = name, kind = kind, fn = fn }
end

function mp.register_event(name, fn) H.events[name] = fn end
function mp.register_script_message(name, fn) H.messages[name] = fn end

function mp.commandv(...)
    local n = select('#', ...)
    local args = { ... }
    for i = 1, n do
        local a = args[i]
        if type(a) == 'number' then
            args[i] = tostring(a)
        elseif type(a) ~= 'string' then
            -- mpv, player/lua.c script_commandv: luaL_error(L, "argument %d is not a string", n)
            error(string.format('argument %d is not a string', i), 2)
        end
    end
    H.commands[#H.commands + 1] = args
    if args[1] == 'script-message' and args[2] == 'sluka-mpv' then
        assert(n == 3, 'a message to the app is one argument')
        H.outbox[#H.outbox + 1] = assert(decode(args[3]))
    end
    return true
end

function mp.command_native(t)
    if type(t) == 'table' and t[1] == 'expand-path' then
        return (tostring(t[2]):gsub('^~~', H.config_dir or '/mpv-config'))
    end
    if type(t) == 'table' and t.name == 'subprocess' then
        H.subprocesses = (H.subprocesses or 0) + 1
        return { status = 0, stdout = '', stderr = '' }
    end
    return {}
end

function mp.osd_message(text, seconds) H.osd[#H.osd + 1] = { text = text, seconds = seconds } end
function mp.get_time() return H.now end
function mp.get_osd_size() return H.osd_w, H.osd_h end
function mp.get_script_name() return 'sluka' end

local function bind(key, name, fn, forced)
    if type(name) == 'function' then name, fn = key, name end
    H.bindings[name] = { key = key, fn = fn, forced = forced }
end
function mp.add_key_binding(key, name, fn) bind(key, name, fn, false) end
function mp.add_forced_key_binding(key, name, fn) bind(key, name, fn, true) end
function mp.remove_key_binding(name) H.bindings[name] = nil end

local Timer = {}
Timer.__index = Timer
function Timer:kill() self.active = false end
function Timer:stop() self.active = false end
function Timer:resume()
    self.active = true
    self.due = H.now + self.seconds
end
function Timer:is_enabled() return self.active end

function mp.add_timeout(seconds, fn)
    local t = setmetatable({ seconds = seconds, fn = fn, due = H.now + seconds, active = true }, Timer)
    H.timers[#H.timers + 1] = t
    return t
end
function mp.add_periodic_timer(seconds, fn)
    local t = mp.add_timeout(seconds, fn)
    t.periodic = true
    return t
end

-- How wide the renderer would draw some ASS text: a stand-in good enough for the script's arithmetic.
local function text_width(data)
    local fs, sx, w = 20, 100, 0
    local i = 1
    while i <= #data do
        local c = data:sub(i, i)
        if c == '{' then
            local j = data:find('}', i, true) or #data
            local tag = data:sub(i, j)
            local size = tag:match('\\fs(%d[%d%.]*)')
            if size then fs = tonumber(size) end
            local scale = tag:match('\\fscx(%d[%d%.]*)')
            if scale then sx = tonumber(scale) end
            i = j + 1
        else
            local ch = data:match('^[\1-\127\194-\244][\128-\191]*', i) or c
            if ch == '\\' and data:sub(i + 1, i + 1):match('[hN{}]') then
                ch = data:sub(i, i + 1)
            end
            if ch ~= '\239\187\191' then
                local wide = ch:byte(1) >= 0xE3
                w = w + fs * (wide and 1.0 or 0.5) * sx / 100
            end
            i = i + #ch
        end
    end
    return w, fs
end
H.text_width = text_width

local Overlay = {}
Overlay.__index = Overlay
function Overlay:update()
    self.updates = (self.updates or 0) + 1
    if self.hidden then
        self.shown = nil
    else
        self.shown = self.data
    end
    if not self.compute_bounds then return {} end
    local x = tonumber(self.data:match('\\pos%(([%d%.%-]+),')) or 0
    local w, fs = text_width(self.data)
    if self.data:find('\\an9', 1, true) then
        return { x0 = x - w, y0 = 4, x1 = x, y1 = 4 + fs }
    end
    return { x0 = x, y0 = 4, x1 = x + w, y1 = 4 + fs }
end
function Overlay:remove() self.shown = nil end

function mp.create_osd_overlay(format)
    local ov = setmetatable({ format = format, data = '', res_x = 0, res_y = 720, z = 0 }, Overlay)
    H.overlays[#H.overlays + 1] = ov
    return ov
end

----------------------------------------------------------------- mp.utils, mp.msg, mp.options

local utils = {}
function utils.format_json(v)
    local ok, out = pcall(encode, v)
    if ok then
        if os.getenv('FAKE_MPV_ONE_VALUE') then return out end   -- builds that answer with the text alone
        return out, nil   -- mpv 0.36: two values
    end
    return nil, 'error'
end
function utils.parse_json(s)
    local ok, v, rest = pcall(decode, s)
    if not ok then return nil, v end
    return v, nil, rest
end
function utils.getpid() return H.pid end
function utils.file_info(path)
    if H.dirs[path] then return { is_dir = true, is_file = false } end
    local f = io.open(path, 'rb')
    if f then
        f:close()
        return { is_dir = false, is_file = true }
    end
    return nil, 'no such file'
end
function utils.readdir(dir, filter)
    local listed = H.listing and H.listing[dir]
    if not listed then return nil, 'no such folder' end
    local out = {}
    for _, name in ipairs(listed) do out[#out + 1] = name end
    return out
end
function utils.get_env_list()
    local out = {}
    for k, v in pairs(H.env) do out[#out + 1] = k .. '=' .. v end
    return out
end
function utils.join_path(a, b) return a .. '/' .. b end
function utils.split_path(p) return p:match('^(.-)([^/\\]*)$') end

local msg = {}
for _, level in ipairs({ 'fatal', 'error', 'warn', 'info', 'verbose', 'debug', 'trace' }) do
    msg[level] = function(...)
        local parts = {}
        for i = 1, select('#', ...) do parts[#parts + 1] = tostring((select(i, ...))) end
        H.log[#H.log + 1] = level .. ': ' .. table.concat(parts, ' ')
    end
end

local options = { read_options = function() end }

mp.utils, mp.msg, mp.options = utils, msg, options

----------------------------------------------------------------- driving the script

function H.install()
    package.preload['mp'] = function() return mp end
    package.preload['mp.utils'] = function() return utils end
    package.preload['mp.msg'] = function() return msg end
    package.preload['mp.options'] = function() return options end
end

function H.load(path)
    H.install()
    local chunk = assert(loadfile(path))
    call('the script', chunk)
    -- mpv tells every observer the property's value once, after the script's first run.
    for _, ob in ipairs(H.observers) do
        call('observer of ' .. ob.name, ob.fn, ob.name, H.typed(ob.kind, H.props[ob.name]))
    end
end

--- A message from the app, as script-message sluka-app <json>.
function H.app_says(m)
    local fn = assert(H.messages['sluka-app'], 'the script listens for no sluka-app message')
    call('message ' .. tostring(m.t), fn, encode(m))
end

--- What the script said since the last look.
function H.said()
    local out = H.outbox
    H.outbox = {}
    return out
end

function H.advance(seconds)
    local stop = H.now + seconds
    while true do
        local next_t
        for _, t in ipairs(H.timers) do
            if t.active and t.due <= stop and (not next_t or t.due < next_t.due) then next_t = t end
        end
        if not next_t then break end
        H.now = next_t.due
        if next_t.periodic then next_t.due = H.now + next_t.seconds else next_t.active = false end
        call('timer', next_t.fn)
    end
    H.now = stop
end

function H.press(name_or_key)
    for name, b in pairs(H.bindings) do
        if name == name_or_key or b.key == name_or_key then
            call('key ' .. tostring(b.key), b.fn)
            return true
        end
    end
    return false
end

function H.event(name, data)
    local fn = H.events[name]
    if fn then call('event ' .. name, fn, data) end
end

function H.mouse(x, y, inside)
    H.set_prop('mouse-pos', { x = x, y = y, hover = inside ~= false })
end

return H
