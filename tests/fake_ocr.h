/*
 * What the stand-ins for LunaTranslator's OCR libraries share (fake_cvutils.c, fake_nativeutils.c): the text in a
 * test's picture, and a log of what they were asked.
 *
 * A test's picture of a text box carries what is "written" in it in its first row (ocrfake.py draws it): pixel i's
 * blue is byte i of the lines "x,y,w,h,text\n" (UTF-8, the box of each line in the picture as drawn), a 0 after the
 * last; the greens of that row go 0x40, 0xC0, 0x40, ... a pixel each -- so a picture made bigger (each pixel n x n)
 * is told by how long the first green lasts, and its lines are found there all the same.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

typedef struct
{
    float x, y, w, h;
    char text[512];
} FakeLine;

/* How many times bigger the picture is than drawn: the first run of one green in the first row. */
static int fake_factor(const unsigned char *row, int width, int step, int green)
{
    int n = 1;
    while (n < width && row[n * step + green] == row[green])
        n++;
    return n;
}

/* The lines written in the first row: up to `most`, scaled by `factor`; how many. */
static int fake_lines(const unsigned char *row, int width, int step, int blue, int factor, FakeLine *out, int most)
{
    static char payload[65536];
    int length = 0;
    for (int i = 0; i * factor < width && length < (int)sizeof(payload) - 1; i++)
    {
        unsigned char b = row[i * factor * step + blue];
        if (!b)
            break;
        payload[length++] = (char)b;
    }
    payload[length] = 0;
    int count = 0;
    char *save = NULL;
    for (char *line = strtok_r(payload, "\n", &save); line && count < most; line = strtok_r(NULL, "\n", &save))
    {
        FakeLine *l = &out[count];
        int used = 0;
        if (sscanf(line, "%f,%f,%f,%f,%n", &l->x, &l->y, &l->w, &l->h, &used) != 4 || used <= 0)
            continue;
        snprintf(l->text, sizeof(l->text), "%s", line + used);
        l->x *= factor;
        l->y *= factor;
        l->w *= factor;
        l->h *= factor;
        count++;
    }
    return count;
}

/* UTF-8 to wchar_t (UTF-32 here, as the Windows libraries' UTF-16 is to ctypes' c_wchar_p there). */
static void fake_widen(const char *in, wchar_t *out, size_t most)
{
    size_t n = 0;
    const unsigned char *s = (const unsigned char *)in;
    while (*s && n + 1 < most)
    {
        uint32_t c = *s++;
        int more = 0;
        if (c >= 0xF0)
            c &= 0x07, more = 3;
        else if (c >= 0xE0)
            c &= 0x0F, more = 2;
        else if (c >= 0xC0)
            c &= 0x1F, more = 1;
        while (more-- > 0 && (*s & 0xC0) == 0x80)
            c = (c << 6) | (*s++ & 0x3F);
        out[n++] = (wchar_t)c;
    }
    out[n] = 0;
}

static void fake_narrow(const wchar_t *in, char *out, size_t most)
{
    size_t n = 0;
    for (; in && *in && n + 4 < most; in++)
    {
        uint32_t c = (uint32_t)*in;
        if (c < 0x80)
            out[n++] = (char)c;
        else if (c < 0x800)
            out[n++] = (char)(0xC0 | (c >> 6)), out[n++] = (char)(0x80 | (c & 0x3F));
        else if (c < 0x10000)
            out[n++] = (char)(0xE0 | (c >> 12)), out[n++] = (char)(0x80 | ((c >> 6) & 0x3F)), out[n++] = (char)(0x80 | (c & 0x3F));
        else
            out[n++] = (char)(0xF0 | (c >> 18)), out[n++] = (char)(0x80 | ((c >> 12) & 0x3F)),
            out[n++] = (char)(0x80 | ((c >> 6) & 0x3F)), out[n++] = (char)(0x80 | (c & 0x3F));
    }
    out[n] = 0;
}

/* A line of what the library was asked, in FAKE_OCR_DIR/<name>.log. */
static void fake_log(const char *name, const char *format, ...)
{
    const char *dir = getenv("FAKE_OCR_DIR");
    if (!dir)
        return;
    char path[4096];
    snprintf(path, sizeof(path), "%s/%s.log", dir, name);
    FILE *f = fopen(path, "a");
    if (!f)
        return;
    va_list args;
    va_start(args, format);
    vfprintf(f, format, args);
    va_end(args);
    fputc('\n', f);
    fclose(f);
}
