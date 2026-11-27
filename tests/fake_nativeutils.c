/*
 * A stand-in for LunaTranslator 12.1.3.12's NativeUtils.dll, for the tests: the functions ocrd.py calls (as
 * LunaTranslator's NativeUtils.py declares them), called the same way.
 *
 *   winrt_OCR            Windows' OCR: the BMP it is given read as fake_ocr.h says; like Windows' own, it puts a space
 *                        between Japanese words (here: between any two letters past ASCII)
 *   FAKE_OCR_LANGS       the languages Windows has the OCR of (default "ja,en-US")
 *   FAKE_PACKAGE_DIR     where the Snipping Tool's package is (its folder SnippingTool in it); unset: not there
 *   glens_*              Google Lens' request and answer, in a form the tests' stand-in for Google reads and writes:
 *                          request  "LENSREQ" W H N (4 bytes each) PNG      (N: the bytes it was given to send too)
 *                          answer   "LENSRES\n" then a line each: TEXT \t CENTER_X \t CENTER_Y \t W \t H  (0 to 1)
 */
#include <stdarg.h>
#include <stdbool.h>

#include "fake_ocr.h"

typedef void (*OcrCallback)(float, float, float, float, const wchar_t *);
typedef void (*LanguageCallback)(const wchar_t *, const wchar_t *);
typedef void (*BytesCallback)(char *, size_t);
typedef void (*PathCallback)(const wchar_t *);
typedef void (*LensCallback)(const char *, float, float, float, float);
typedef void (*SelectCallback)(int, int, int, int, int, int, char *, size_t);

static const char *languages(void)
{
    const char *found = getenv("FAKE_OCR_LANGS");
    return found ? found : "ja,en-US";
}

static const char *language_name(const char *tag)
{
    if (!strcmp(tag, "ja"))
        return "日本語";
    if (!strcmp(tag, "en-US"))
        return "English (United States)";
    if (!strcmp(tag, "zh-Hans-CN"))
        return "中文(简体)";
    return tag;
}

bool winrt_OCR_check_language_valid(const wchar_t *tag)
{
    char want[64], list[1024];
    fake_narrow(tag, want, sizeof(want));
    snprintf(list, sizeof(list), "%s", languages());
    char *save = NULL;
    for (char *one = strtok_r(list, ",", &save); one; one = strtok_r(NULL, ",", &save))
        if (!strcmp(one, want))
            return true;
    return false;
}

void winrt_OCR_get_AvailableRecognizerLanguages(LanguageCallback cb)
{
    char list[1024];
    snprintf(list, sizeof(list), "%s", languages());
    char *save = NULL;
    for (char *one = strtok_r(list, ",", &save); one; one = strtok_r(NULL, ",", &save))
    {
        wchar_t tag[64], name[128];
        fake_widen(one, tag, 64);
        fake_widen(language_name(one), name, 128);
        cb(tag, name);
    }
}

void winrt_OCR(const unsigned char *data, size_t size, const wchar_t *lang, OcrCallback cb)
{
    char tag[64];
    fake_narrow(lang, tag, sizeof(tag));
    if (size < 54 || data[0] != 'B' || data[1] != 'M')
    {
        fake_log("winocr", "not a bmp");
        return;
    }
    uint32_t offset, bits;
    int32_t w, h;
    memcpy(&offset, data + 10, 4);
    memcpy(&w, data + 18, 4);
    memcpy(&h, data + 22, 4);
    bits = data[28] | (data[29] << 8);
    int top_down = h < 0;
    if (h < 0)
        h = -h;
    int px = (int)bits / 8;
    size_t stride = (((size_t)w * bits + 31) / 32) * 4;
    const unsigned char *row0 = data + offset + (top_down ? 0 : (size_t)(h - 1) * stride);
    fake_log("winocr", "ocr lang=%s %dx%d bits=%u", tag, w, h, bits);
    if (!winrt_OCR_check_language_valid(lang))
        return;
    FakeLine lines[64];
    int factor = fake_factor(row0, w, px, 1);
    int n = fake_lines(row0, w, px, 0, factor, lines, 64);
    for (int i = 0; i < n; i++)
    {
        wchar_t wide[512], spaced[1024];
        fake_widen(lines[i].text, wide, 512);
        size_t k = 0;
        for (size_t j = 0; wide[j] && k + 2 < 1024; j++)
        {
            if (j && wide[j] > 0x7F && wide[j - 1] > 0x7F)
                spaced[k++] = L' ';
            spaced[k++] = wide[j];
        }
        spaced[k] = 0;
        FakeLine *l = &lines[i];
        cb(l->x, l->y, l->x + l->w, l->y + l->h, spaced);
    }
}

void GetPackagePathByPackageFamily(const wchar_t *family, PathCallback cb)
{
    char name[256];
    fake_narrow(family, name, sizeof(name));
    const char *dir = getenv("FAKE_PACKAGE_DIR");
    fake_log("native", "package %s", name);
    if (dir && !strcmp(name, "Microsoft.ScreenSketch_8wekyb3d8bbwe"))
    {
        wchar_t wide[4096];
        fake_widen(dir, wide, 4096);
        cb(wide);
    }
}

void glens_create_request(uint64_t number, const char *bytes, size_t length, const char *png, size_t png_length, int32_t w,
                          int32_t h, BytesCallback cb)
{
    size_t size = 7 + 12 + png_length;
    char *out = malloc(size);
    memcpy(out, "LENSREQ", 7);
    uint32_t n = (uint32_t)length;
    memcpy(out + 7, &w, 4);
    memcpy(out + 11, &h, 4);
    memcpy(out + 15, &n, 4);
    memcpy(out + 19, png, png_length);
    fake_log("native", "lens request %dx%d png=%zu nonce=%zu", w, h, png_length, length);
    (void)bytes;
    (void)number;
    cb(out, size);
    free(out);
}

void glens_parse_response(const char *data, size_t size, LensCallback cb)
{
    if (size < 8 || memcmp(data, "LENSRES\n", 8))
        return;
    char *copy = malloc(size - 8 + 1);
    memcpy(copy, data + 8, size - 8);
    copy[size - 8] = 0;
    char *save = NULL;
    for (char *line = strtok_r(copy, "\n", &save); line; line = strtok_r(NULL, "\n", &save))
    {
        char *tab = strchr(line, '\t');
        float cx, cy, bw, bh;
        if (!tab)
            continue;
        *tab = 0;
        if (sscanf(tab + 1, "%f\t%f\t%f\t%f", &cx, &cy, &bw, &bh) == 4)
            cb(line, cx, cy, bw, bh);
    }
    free(copy);
}

void CreateSelectRangeWindow(void *parent, float alpha, int r, int g, int b, float width, SelectCallback cb)
{
    /* (the tests' pretend screen picks the box itself) */
    (void)parent, (void)alpha, (void)r, (void)g, (void)b, (void)width, (void)cb;
}
