/*
 * A stand-in for LunaHost64.dll, for the tests: the same functions (LunaHost/LunaHostDll.cpp of LunaTranslator
 * 12.1.3.12), called the same way, with a pretend game behind them.
 *
 * What the game does is read from files in the folder FAKE_LUNA_DIR says:
 *
 *   injected-PID    put there by the stand-in injector (fake_inject.py): the hook is in, it connects
 *   hooked-PID      the hook was in already (Luna_CheckIfNeedInject says no): it connects all the same
 *   noconnect-PID   it never connects
 *   script-PID.txt  what the game's text threads say once it is connected (else script.txt), a line each:
 *                     DELAY_MS <tab> ADDR <tab> CTX <tab> CTX2 <tab> NAME <tab> CODE <tab> TEXT  (\n in TEXT: a break)
 *                     DELAY_MS <tab> engine <tab> NAME          the hook found the game's engine
 *                     DELAY_MS <tab> crash                      the host goes down (as a host that is killed)
 *                     DELAY_MS <tab> leave                      the hook leaves the game by itself
 *
 * And what it is told is said back through the host's own messages (HOSTINFO 0, "Console"), for the tests to see.
 */
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wchar.h>

typedef struct
{
    uint32_t processId;
    uint64_t addr;
    uint64_t ctx;
    uint64_t ctx2;
} ThreadParam;

typedef void (*ProcessEvent)(uint32_t pid);
typedef void (*ThreadEventMaybeEmbed)(const wchar_t *code, const char *name, ThreadParam tp, bool embed);
typedef void (*ThreadEvent)(const wchar_t *code, const char *name, ThreadParam tp);
typedef void (*OutputCallback)(const wchar_t *code, const char *name, ThreadParam tp, const wchar_t *text);
typedef void (*HostInfoHandler)(int type, const wchar_t *text);
typedef void (*HookInsertHandler)(uint32_t pid, uint64_t addr, const wchar_t *code);
typedef void (*EmbedCallback)(const wchar_t *text, ThreadParam tp);
typedef wchar_t *(*I18NQueryCallback)(const wchar_t *text);
typedef void (*EmuGameInfoCallback)(const wchar_t *id, const wchar_t *title, const wchar_t *version);

static ProcessEvent on_connect, on_disconnect;
static ThreadEventMaybeEmbed on_create;
static ThreadEvent on_destroy;
static OutputCallback on_output;
static HostInfoHandler on_info;
static HookInsertHandler on_hook;
static I18NQueryCallback on_i18n;
static EmuGameInfoCallback on_emu;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;   /* the host's own data */
static pthread_mutex_t calls = PTHREAD_MUTEX_INITIALIZER;  /* one callback at a time, as the host's mutexes have it */

/* ------------------------------------------------------------------ the host's messages, and their translations */

static const wchar_t *KEYS[] = {L"警告", L"已经注入", L"注入失败", L"无法转换文本 (无效的代码页?)", L"进程 %d 已连接",
                                L"进程 %d 已断开连接", L"文件版本无法匹配，可能无法正常工作，请重新下载！"};
#define NKEYS (sizeof(KEYS) / sizeof(KEYS[0]))
static wchar_t *translated[NKEYS];

static const wchar_t *TR(int i)
{
    return translated[i] ? translated[i] : KEYS[i];
}

static void info(int type, const wchar_t *fmt, ...)
{
    wchar_t buffer[1024];
    va_list args;
    va_start(args, fmt);
    vswprintf(buffer, 1024, fmt, args);
    va_end(args);
    pthread_mutex_lock(&calls);
    if (on_info)
        on_info(type, buffer);
    pthread_mutex_unlock(&calls);
}

/* ------------------------------------------------------------------ the pretend game */

#define MOST 512
typedef struct
{
    bool used;
    ThreadParam tp;
    char name[96];
    wchar_t code[256];
} Thread;
static Thread threads[MOST];

#define PROCS 64
typedef struct
{
    uint32_t pid;
    bool connected;
    bool detached;
    int users;
} Proc;
static Proc procs[PROCS];
static int flush_delay = 100, codepage = 0;

static Proc *proc_of(uint32_t pid, bool make)
{
    for (int i = 0; i < PROCS; i++)
        if (procs[i].pid == pid)
            return &procs[i];
    if (!make)
        return NULL;
    for (int i = 0; i < PROCS; i++)
        if (!procs[i].pid)
        {
            procs[i].pid = pid;
            return &procs[i];
        }
    return NULL;
}

static const char *folder(void)
{
    const char *dir = getenv("FAKE_LUNA_DIR");
    return dir ? dir : ".";
}

static bool marked(const char *what, uint32_t pid)
{
    char path[1024];
    struct stat st;
    snprintf(path, sizeof path, "%s/%s-%u", folder(), what, pid);
    return stat(path, &st) == 0;
}

static void unmark(const char *what, uint32_t pid)
{
    char path[1024];
    snprintf(path, sizeof path, "%s/%s-%u", folder(), what, pid);
    unlink(path);
}

static void utf8_to_wide(const char *in, wchar_t *out, size_t room)
{
    size_t n = 0;
    const unsigned char *s = (const unsigned char *)in;
    while (*s && n + 1 < room)
    {
        uint32_t c = *s++;
        if (c == '\\' && *s == 'n')
        {
            s++;
            c = '\n';
        }
        else if (c >= 0xF0)
        {
            c = ((c & 7) << 18) | ((s[0] & 63) << 12) | ((s[1] & 63) << 6) | (s[2] & 63);
            s += 3;
        }
        else if (c >= 0xE0)
        {
            c = ((c & 15) << 12) | ((s[0] & 63) << 6) | (s[1] & 63);
            s += 2;
        }
        else if (c >= 0xC0)
        {
            c = ((c & 31) << 6) | (s[0] & 63);
            s += 1;
        }
        out[n++] = (wchar_t)c;
    }
    out[n] = 0;
}

static Thread *thread_for(uint32_t pid, uint64_t addr, uint64_t ctx, uint64_t ctx2, const char *name, const wchar_t *code)
{
    Thread *found = NULL;
    bool made = false;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < MOST && !found; i++)
        if (threads[i].used && threads[i].tp.processId == pid && threads[i].tp.addr == addr && threads[i].tp.ctx == ctx &&
            threads[i].tp.ctx2 == ctx2)
            found = &threads[i];
    for (int i = 0; i < MOST && !found; i++)
        if (!threads[i].used)
        {
            found = &threads[i];
            found->used = true;
            found->tp.processId = pid;
            found->tp.addr = addr;
            found->tp.ctx = ctx;
            found->tp.ctx2 = ctx2;
            snprintf(found->name, sizeof found->name, "%s", name);
            wcsncpy(found->code, code, 255);
            found->code[255] = 0;
            made = true;
        }
    pthread_mutex_unlock(&lock);
    if (found && made)
    {
        pthread_mutex_lock(&calls);
        if (on_create)
            on_create(found->code, found->name, found->tp, false);
        pthread_mutex_unlock(&calls);
    }
    return found;
}

static void say(Thread *t, const wchar_t *text)
{
    pthread_mutex_lock(&calls);
    if (on_output)
        on_output(t->code, t->name, t->tp, text);
    pthread_mutex_unlock(&calls);
}

static void gone(uint32_t pid)
{
    for (int i = 0; i < MOST; i++)
    {
        pthread_mutex_lock(&lock);
        bool his = threads[i].used && threads[i].tp.processId == pid;
        Thread copy = threads[i];
        if (his)
            threads[i].used = false;
        pthread_mutex_unlock(&lock);
        if (his)
        {
            pthread_mutex_lock(&calls);
            if (on_destroy)
                on_destroy(copy.code, copy.name, copy.tp);
            pthread_mutex_unlock(&calls);
        }
    }
}

static bool stopped(Proc *p)
{
    pthread_mutex_lock(&lock);
    bool out = p->detached;
    pthread_mutex_unlock(&lock);
    return out;
}

static void play(Proc *p)
{
    char path[1024];
    snprintf(path, sizeof path, "%s/script-%u.txt", folder(), p->pid);
    FILE *f = fopen(path, "r");
    if (!f)
    {
        snprintf(path, sizeof path, "%s/script.txt", folder());
        f = fopen(path, "r");
    }
    if (!f)
        return;
    char line[8192];
    while (fgets(line, sizeof line, f))
    {
        line[strcspn(line, "\r\n")] = 0;
        char *fields[8] = {0};
        int n = 0;
        char *rest = line;
        while (n < 7)
        {
            fields[n++] = rest;
            char *tab = strchr(rest, '\t');
            if (!tab)
                break;
            *tab = 0;
            rest = tab + 1;
        }
        if (n < 2)
            continue;
        usleep((useconds_t)atoi(fields[0]) * 1000);
        if (stopped(p))
            break;
        if (!strcmp(fields[1], "crash"))
            abort();
        if (!strcmp(fields[1], "leave"))
        {
            /* The hook leaves the game by itself (as one that fails in it): its threads go, it disconnects. */
            pthread_mutex_lock(&lock);
            p->detached = true;
            pthread_mutex_unlock(&lock);
            break;
        }
        if (!strcmp(fields[1], "engine") && n >= 3)
        {
            wchar_t name[256];
            utf8_to_wide(fields[2], name, 256);
            info(4, L"%ls", name);
            continue;
        }
        if (n < 7)
            continue;
        wchar_t code[256], *text = malloc(sizeof(wchar_t) * 8192);
        utf8_to_wide(fields[5], code, 256);
        utf8_to_wide(fields[6], text, 8192);
        Thread *t = thread_for(p->pid, strtoull(fields[1], NULL, 16), strtoull(fields[2], NULL, 16),
                               strtoull(fields[3], NULL, 16), fields[4], code);
        if (t)
            say(t, text);
        free(text);
    }
    fclose(f);
}

static void *connection(void *arg)
{
    Proc *p = arg;
    uint32_t pid = p->pid;
    /* As the hook in a game does: it connects once it is in (and the host's pipes are there). */
    for (int i = 0; i < 1500; i++)
    {
        if (stopped(p))
            goto out;
        if (!marked("noconnect", pid) && (marked("injected", pid) || marked("hooked", pid)))
            break;
        usleep(10000);
        if (i == 1499)
            goto out;
    }
    pthread_mutex_lock(&lock);
    p->connected = true;
    pthread_mutex_unlock(&lock);
    pthread_mutex_lock(&calls);
    if (on_connect)
        on_connect(pid);
    pthread_mutex_unlock(&calls);
    info(0, TR(4), (int)pid);
    play(p);
    while (!stopped(p))
        usleep(10000);
    /* Let go: the hook leaves the game, its threads go, the pipe breaks. */
    gone(pid);
    unmark("injected", pid);
    pthread_mutex_lock(&calls);
    if (on_disconnect)
        on_disconnect(pid);
    pthread_mutex_unlock(&calls);
    info(0, TR(5), (int)pid);
out:
    pthread_mutex_lock(&lock);
    p->connected = false;
    p->users--;
    if (!p->users)
        p->pid = 0;
    pthread_mutex_unlock(&lock);
    return NULL;
}

/* ------------------------------------------------------------------ LunaHostDll.cpp */

#define C_LUNA_API __attribute__((visibility("default")))

C_LUNA_API void Luna_Start(ProcessEvent Connect, ProcessEvent Disconnect, ThreadEventMaybeEmbed Create, ThreadEvent Destroy,
                           OutputCallback Output, HostInfoHandler hostinfo, HookInsertHandler hookinsert, EmbedCallback embed,
                           I18NQueryCallback i18nQueryCallback, EmuGameInfoCallback emuGameInfoCallback)
{
    (void)embed;
    on_connect = Connect;
    on_disconnect = Disconnect;
    on_create = Create;
    on_destroy = Destroy;
    on_output = Output;
    on_info = hostinfo;
    on_hook = hookinsert;
    on_i18n = i18nQueryCallback;
    on_emu = emuGameInfoCallback;
}

C_LUNA_API void *Luna_AllocString(const wchar_t *str)
{
    size_t n = wcslen(str) + 1;
    wchar_t *out = malloc(n * sizeof(wchar_t));
    wcscpy(out, str);
    return out;
}

C_LUNA_API void Luna_ResetLang(void)
{
    int done = 0;
    for (size_t i = 0; i < NKEYS; i++)
    {
        wchar_t *answer = on_i18n ? on_i18n(KEYS[i]) : NULL;
        if (!answer)
            continue;
        free(translated[i]);
        translated[i] = answer; /* (the host keeps a copy and frees what it was given; this one keeps it) */
        done++;
    }
    info(0, L"lang %d", done);
}

C_LUNA_API void Luna_Settings(int flushDelay, int defaultCodepage, int maxBufferSize, int maxHistorySize, bool enablePCHooks)
{
    flush_delay = flushDelay;
    codepage = defaultCodepage;
    /* As the real host does on an error: something printed to its standard output, which is not the app's to read. */
    printf("fake host: settings\n");
    fflush(stdout);
    info(0, L"settings flush=%d codepage=%d buffer=%d history=%d pc=%d", flushDelay, defaultCodepage, maxBufferSize,
         maxHistorySize, (int)enablePCHooks);
}

C_LUNA_API void Luna_SettingsEx(uint32_t pid, uint32_t waittime, uint8_t fontCharSet, bool fontCharSetEnabled, wchar_t *fontFamily,
                                uint32_t displaymode, bool fastskipignore, bool clearText, bool changeFontSize, float FontSizeRelative,
                                bool tryvehhook, const wchar_t *unityfontdir)
{
    info(0, L"settingsex pid=%u wait=%u charset=%d/%d font=[%ls] mode=%u skip=%d clear=%d size=%d/%.1f veh=%d unity=[%ls]", pid,
         waittime, (int)fontCharSet, (int)fontCharSetEnabled, fontFamily, displaymode, (int)fastskipignore, (int)clearText,
         (int)changeFontSize, (double)FontSizeRelative, (int)tryvehhook, unityfontdir);
}

C_LUNA_API bool Luna_CheckIfNeedInject(uint32_t pid)
{
    if (marked("hooked", pid))
    {
        info(0, L"%ls", TR(1));
        return false;
    }
    return true;
}

C_LUNA_API void Luna_ConnectProcess(uint32_t pid)
{
    pthread_mutex_lock(&lock);
    Proc *p = proc_of(pid, true);
    if (p)
    {
        p->detached = false;
        p->users++;
    }
    pthread_mutex_unlock(&lock);
    if (!p)
        return;
    pthread_t t;
    pthread_create(&t, NULL, connection, p);
    pthread_detach(t);
}

C_LUNA_API void Luna_DetachProcess(uint32_t pid)
{
    pthread_mutex_lock(&lock);
    Proc *p = proc_of(pid, false);
    if (p)
        p->detached = true;
    pthread_mutex_unlock(&lock);
}

C_LUNA_API void Luna_InsertHookCode(uint32_t pid, const wchar_t *hookcode)
{
    static int made = 0;
    pthread_mutex_lock(&lock);
    Proc *p = proc_of(pid, false);
    bool here = p && p->connected;
    int n = made++;
    pthread_mutex_unlock(&lock);
    if (!here)
        return;
    char name[32];
    snprintf(name, sizeof name, "UserHook%d", n);
    pthread_mutex_lock(&calls);
    if (on_hook)
        on_hook(pid, 0x7000 + n, hookcode);
    pthread_mutex_unlock(&calls);
    Thread *t = thread_for(pid, 0x7000 + n, 0, 0, name, hookcode);
    if (t)
        say(t, L"ユーザーフックの一行");
}

C_LUNA_API void Luna_InsertPCHooks(uint32_t pid, int which)
{
    pthread_mutex_lock(&lock);
    Proc *p = proc_of(pid, false);
    bool here = p && p->connected;
    pthread_mutex_unlock(&lock);
    info(0, L"pchooks pid=%u which=%d", pid, which);
    if (!here)
        return;
    Thread *t = which == 0 ? thread_for(pid, 0x9000, 0, 0, "GetGlyphOutlineW", L"HW@0:gdi32.dll:GetGlyphOutlineW")
                           : thread_for(pid, 0x9100, 0, 0, "TextOutW", L"HQ@0:gdi32.dll:TextOutW");
    if (t)
        say(t, which == 0 ? L"一" : L"Windowsの文字");
}

C_LUNA_API void Luna_RemoveHook(uint32_t pid, uint64_t addr)
{
    info(0, L"remove pid=%u addr=%llx", pid, (unsigned long long)addr);
}

C_LUNA_API void Luna_SyncThread(ThreadParam tp, bool sync)
{
    info(0, L"sync pid=%u addr=%llx ctx=%llx ctx2=%llx on=%d", tp.processId, (unsigned long long)tp.addr,
         (unsigned long long)tp.ctx, (unsigned long long)tp.ctx2, (int)sync);
}

C_LUNA_API void Luna_QueryThreadHistory(ThreadParam tp, bool latest, void (*callback)(const wchar_t *))
{
    (void)tp;
    (void)latest;
    callback(L"");
}
