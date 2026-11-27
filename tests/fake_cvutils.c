/*
 * A stand-in for LunaTranslator 12.1.3.12's CVUtils.dll, for the tests: the functions ocrd.py's BuiltinReader calls
 * (CVUtils/localocr.cpp, LunaTranslator's CVUtils.py), called the same way; what is "read" is the test picture's
 * first row (fake_ocr.h).
 *
 *   FAKE_ORT_FAIL     OcrLoadRuntime says no (ONNX Runtime cannot start: an old C++ runtime)
 *   FAKE_OCR_SLEEP_MS each read takes this long
 */
#include <stdarg.h>
#include <stdbool.h>
#include <unistd.h>
#include <sys/stat.h>

#include "fake_ocr.h"

typedef void (*DetectCallback)(float, float, float, float, float, float, float, float, const char *);
typedef void (*ErrorCallback)(const char *);

typedef struct
{
    int w, h;
    unsigned char *bgr;
} Mat;

typedef struct
{
    int threads;
} Ocr;

bool OcrLoadRuntime(void)
{
    fake_log("cvutils", "runtime");
    return getenv("FAKE_ORT_FAIL") == NULL;
}

void *OcrInit(const wchar_t *det, const wchar_t *rec, const wchar_t *keys, int32_t threads, bool gpu, uint64_t luid,
              const char *device, ErrorCallback err)
{
    char paths[3][4096];
    const wchar_t *wide[3] = {det, rec, keys};
    for (int i = 0; i < 3; i++)
    {
        fake_narrow(wide[i], paths[i], sizeof(paths[i]));
        struct stat st;
        if (stat(paths[i], &st) != 0)
        {
            char text[4200];
            snprintf(text, sizeof(text), "cannot open %.4000s", paths[i]);
            err(text);
            return NULL;
        }
    }
    const char *slash = strrchr(paths[0], '/');
    fake_log("cvutils", "init det=%s threads=%d gpu=%d luid=%llu device=%s", slash ? slash + 1 : paths[0], threads, gpu ? 1 : 0,
             (unsigned long long)luid, device ? device : "");
    Ocr *ocr = calloc(1, sizeof(Ocr));
    ocr->threads = threads;
    return ocr;
}

void OcrDestroy(void *ocr)
{
    fake_log("cvutils", "destroy");
    free(ocr);
}

void *cvMatFromBGR888(void *ptr, int w, int h, int bytesPerLine)
{
    Mat *mat = calloc(1, sizeof(Mat));
    mat->w = w;
    mat->h = h;
    mat->bgr = malloc((size_t)w * h * 3 + 1);
    for (int y = 0; y < h; y++)
        memcpy(mat->bgr + (size_t)y * w * 3, (unsigned char *)ptr + (size_t)y * bytesPerLine, (size_t)w * 3);
    return mat;
}

void cvMatDestroy(void *mat)
{
    if (!mat)
        return;
    free(((Mat *)mat)->bgr);
    free(mat);
}

void OcrDetect(void *ocr, void *m, int32_t mode, DetectCallback cb, ErrorCallback err)
{
    Mat *mat = (Mat *)m;
    if (!ocr || !mat)
    {
        err("no model");
        return;
    }
    const char *sleep_ms = getenv("FAKE_OCR_SLEEP_MS");
    if (sleep_ms)
        usleep((useconds_t)atoi(sleep_ms) * 1000);
    fake_log("cvutils", "detect mode=%d %dx%d", mode, mat->w, mat->h);
    FakeLine lines[64];
    int factor = fake_factor(mat->bgr, mat->w, 3, 1);
    int n = fake_lines(mat->bgr, mat->w, 3, 0, factor, lines, 64);
    for (int i = 0; i < n; i++)
    {
        FakeLine *l = &lines[i];
        cb(l->x, l->y, l->x + l->w, l->y, l->x + l->w, l->y + l->h, l->x, l->y + l->h, l->text);
    }
}
