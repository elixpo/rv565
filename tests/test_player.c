/* Host test for the player: a mock display assembles stripes into a panel
 * framebuffer (honouring row windows), and a synchronous mock decoder stands
 * in for core 1. On every path (serial with one or two buffers, dual-core,
 * with and without a row window) the panel must show every presented frame
 * exactly, through skips and loops; repeats must not be sent, and a partial
 * delta must send exactly the panel rows scaled from its changed lines.
 *
 * Besides the files given, it builds stored rgb565be clips in memory with
 * partial deltas of several band heights and scattered bands, for an
 * upscaled and a downscaled panel.
 *
 * Usage: test_player file.rv565 [more.rv565 ...] */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rv565_player.h"

#define PW 320
#define PH 240
#define ROWS 24

static uint8_t screen[PW * PH * 2];
static size_t cursor, window_end;
static int queued, failures, writes;
static uint32_t clock_us;
static const rv565_clip_t *g_clip;
static struct { uint16_t index; const uint8_t *prev; uint8_t *dst; size_t len; int pending; } job;

#define FAIL(...) do { fprintf(stderr, "FAIL: " __VA_ARGS__); fputc('\n', stderr); ++failures; } while (0)

static uint32_t fake_micros(void) { return clock_us += 7; }
static void begin(void *c) { (void)c; cursor = 0; window_end = sizeof(screen); ++writes; }
static void begin_rows(void *c, uint16_t first, uint16_t rows)
{
    (void)c;
    if (rows == 0 || first + rows > PH) FAIL("bad row window %u+%u", first, rows);
    cursor = (size_t)first * PW * 2;
    window_end = cursor + (size_t)rows * PW * 2;
    ++writes;
}
static void queue(void *c, const uint8_t *d, size_t n)
{
    (void)c;
    if (++queued > 2) FAIL("more than two stripes queued");
    if (cursor + n > window_end) { FAIL("stripe overruns the window"); return; }
    memcpy(screen + cursor, d, n);
    cursor += n;
}
static void wait_one(void *c) { (void)c; --queued; }
static void end(void *c)
{
    (void)c;
    if (cursor != window_end) FAIL("window not filled");
}

static void dec_start(void *c, uint16_t i, const uint8_t *prev, uint8_t *dst, size_t n)
{
    (void)c;
    if (prev == dst) FAIL("decoder given prev == dst");
    job.index = i; job.prev = prev; job.dst = dst; job.len = n; job.pending = 1;
}
static rv565_status_t dec_finish(void *c, uint32_t *us)
{
    (void)c;
    if (!job.pending) return RV565_ERR_ARG;
    job.pending = 0;
    *us = 1234;
    return rv565_decode(g_clip, job.index, job.prev, job.dst, job.len, NULL, 0);
}

static uint8_t *load(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); *size = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *d = malloc(*size);
    if (fread(d, 1, *size, f) != *size) exit(2);
    fclose(f);
    return d;
}

/* The panel must show frame `index` scaled, exactly. */
static int check_frame(const rv565_clip_t *clip, uint16_t index, const char *mode)
{
    const rv565_header_t *h = &clip->header;
    const size_t fb = rv565_frame_bytes(h);
    uint8_t *frame = malloc(fb), *scratch = malloc(fb);
    static uint8_t expect[PW * PH * 2];
    uint16_t xmap[PW], ymap[PH];
    rv565_status_t st = rv565_seek(clip, index, frame, fb, scratch, fb);
    rv565_build_map(xmap, h->width, PW);
    rv565_build_map(ymap, h->height, PH);
    rv565_scale_stripe(frame, h->width, xmap, PW, ymap, 0, PH, expect);
    free(frame);
    free(scratch);
    if (st != RV565_OK || memcmp(screen, expect, sizeof(screen)) != 0) {
        fprintf(stderr, "FAIL: %s frame %u shown incorrectly\n", mode, index);
        return 1;
    }
    return 0;
}

/* Panel rows a sequential present of frame i must send. */
static unsigned rows_expected(const rv565_clip_t *clip, uint16_t i, int windows)
{
    static rv565_line_run_t runs[4096];
    size_t n;
    if (rv565_changed_lines(clip, i, runs, 4096, &n) != RV565_OK) return 9999;
    if (n == 0) return 0;
    if (!windows || n > RV565_PLAYER_MAX_RUNS) return PH;
    uint16_t ymap[PH];
    rv565_build_map(ymap, clip->header.height, PH);
    unsigned rows = 0;
    for (unsigned d = 0; d < PH; ++d)
        for (size_t r = 0; r < n; ++r)
            if (ymap[d] >= runs[r].first && ymap[d] < runs[r].first + runs[r].count) { ++rows; break; }
    return rows;
}

static int setup(rv565_player_t *p, const rv565_clip_t *clip, int overlap, int two, int windows)
{
    static uint8_t s0[PW * ROWS * 2], s1[PW * ROWS * 2];
    static uint16_t xmap[PW], ymap[PH];
    const size_t fb = rv565_frame_bytes(&clip->header);
    rv565_player_t init = {
        .clip = clip, .panel_width = PW, .panel_height = PH, .stripe_rows = ROWS,
        .stripes = { s0, s1 }, .frames = { malloc(fb), two ? malloc(fb) : NULL },
        .xmap = xmap, .ymap = ymap,
        .display = { NULL, begin, queue, wait_one, end, windows ? begin_rows : NULL },
        .decoder = { NULL, overlap ? dec_start : NULL, overlap ? dec_finish : NULL, NULL },
        .micros = fake_micros,
    };
    *p = init;
    return rv565_player_init(p);
}

static void teardown(rv565_player_t *p) { free(p->frames[0]); free(p->frames[1]); }

static int needs_two(const rv565_clip_t *clip)
{
    if (clip->header.codec != RV565_CODEC_ZLIB) return 0;
    for (uint16_t i = 0; i < clip->header.frames; ++i) {
        const int t = rv565_frame_type(clip, i);
        if (t == RV565_FRAME_DELTA || t == RV565_FRAME_PARTIAL) return 1;
    }
    return 0;
}

static unsigned present_checked(rv565_player_t *p, const rv565_clip_t *clip, uint16_t i, const char *mode)
{
    rv565_frame_stats_t st;
    rv565_status_t s = rv565_player_present(p, i, &st);
    if (s != RV565_OK) { FAIL("%s present %u: %s", mode, i, rv565_strerror(s)); return 0; }
    failures += check_frame(clip, i, mode);
    if (queued != 0) FAIL("stripes left queued");
    if (job.pending) FAIL("%s: decode left pending", mode);
    return st.rows_sent;
}

static unsigned long total_rows, partial_rows, partial_frames;

static void run(const rv565_clip_t *clip, int overlap, int two, int windows)
{
    char mode[64];
    snprintf(mode, sizeof(mode), "%s/%s/%s", overlap ? "overlap" : "serial",
             two ? "2 buffers" : "1 buffer", windows ? "row windows" : "full writes");
    rv565_player_t p;
    rv565_status_t st = setup(&p, clip, overlap, two, windows);
    if (!two && needs_two(clip)) {
        if (st != RV565_ERR_ARG) FAIL("%s: zlib deltas with one buffer accepted", mode);
        teardown(&p);
        return;
    }
    if (st != RV565_OK) { FAIL("init %s: %s", mode, rv565_strerror(st)); teardown(&p); return; }
    memset(screen, 0x5A, sizeof(screen));

    /* Sequential: each frame sends exactly the rows its changes need. */
    const uint16_t n = clip->header.frames;
    for (uint16_t i = 0; i < n; ++i) {
        const unsigned rows = present_checked(&p, clip, i, mode);
        const unsigned want = i == 0 ? PH : rows_expected(clip, i, windows);
        if (rows != want) FAIL("%s: frame %u sent %u rows, expected %u", mode, i, rows, want);
        total_rows += rows;
        if (windows && rv565_frame_type(clip, i) == RV565_FRAME_PARTIAL) {
            ++partial_frames;
            partial_rows += rows;
        }
    }

    /* Skips (catch-up through deltas and partials), a loop around the end,
     * the same frame twice, and backwards. */
    const uint16_t last = (uint16_t)(n - 1);
    const uint16_t order[] = { 0, 1, 2, 5, 6, (uint16_t)(last - 1), last, 0, 1, 1, 7, 3,
                               4, 9, 10, 11, 15, 14, 13, 20, 21, 29, 30, 31 };
    for (size_t k = 0; k < sizeof(order) / sizeof(order[0]); ++k) {
        if (order[k] < n) present_checked(&p, clip, order[k], mode);
    }
    teardown(&p);
}

static void play(const rv565_clip_t *clip, const char *name)
{
    g_clip = clip;
    if (clip->header.pixel_format != RV565_PIXEL_RGB565BE) {
        rv565_player_t p;
        if (setup(&p, clip, 0, 1, 1) != RV565_ERR_UNSUPPORTED) FAIL("%s: pixel format accepted", name);
        teardown(&p);
        return;
    }
    for (int windows = 0; windows < 2; ++windows) {
        run(clip, 0, 0, windows);
        run(clip, 0, 1, windows);
        run(clip, 1, 1, windows);
    }
}

/* Stored rgb565be clip with keyframes every K, and random repeats, full
 * deltas and partial deltas (band heights 1-12, scattered bands). */
static uint32_t rng = 12345;
static uint32_t next_rand(void) { rng = rng * 1103515245u + 12345u; return rng >> 8; }

/* A zlib stream of stored Deflate blocks: valid zlib without a compressor. */
static size_t zlib_store(const uint8_t *in, size_t n, uint8_t *out)
{
    size_t o = 0;
    uint32_t a = 1, b = 0;
    out[o++] = 0x78; out[o++] = 0x01;
    size_t left = n;
    do {
        const size_t chunk = left < 65535 ? left : 65535;
        out[o++] = chunk == left;
        out[o++] = (uint8_t)chunk; out[o++] = (uint8_t)(chunk >> 8);
        out[o++] = (uint8_t)~chunk; out[o++] = (uint8_t)(~chunk >> 8);
        memcpy(out + o, in + (n - left), chunk);
        o += chunk;
        left -= chunk;
    } while (left != 0);
    for (size_t i = 0; i < n; ++i) { a = (a + in[i]) % 65521u; b = (b + a) % 65521u; }
    const uint32_t adler = b << 16 | a;
    out[o++] = (uint8_t)(adler >> 24); out[o++] = (uint8_t)(adler >> 16);
    out[o++] = (uint8_t)(adler >> 8); out[o++] = (uint8_t)adler;
    return o;
}

static uint8_t *make_clip(uint16_t w, uint16_t h, uint16_t frames, uint8_t k, int zlib,
                          uint8_t *truth, size_t *size)
{
    const size_t row = (size_t)w * 2, fb = row * h;
    uint8_t *out = malloc(16 + (size_t)frames * (4 + 1 + 1 + 1024 + fb));
    uint8_t *prev = calloc(1, fb), *cur = malloc(fb);
    const uint8_t header[16] = { 'R', 'V', '5', 7, (uint8_t)w, (uint8_t)(w >> 8), (uint8_t)h,
                                 (uint8_t)(h >> 8), 24, 0, (uint8_t)frames, (uint8_t)(frames >> 8),
                                 16, RV565_PIXEL_RGB565BE, zlib ? RV565_CODEC_ZLIB : RV565_CODEC_STORED, k };
    uint8_t *tmp = malloc(fb);
    memcpy(out, header, 16);
    size_t at = 16;
    for (uint16_t i = 0; i < frames; ++i) {
        const uint32_t r = next_rand() % 6;
        uint8_t *rec = out + at;
        size_t len;
        uint8_t *dptr = NULL;  /* codec data of this record, stored form */
        size_t dlen = 0;
        if (i % k == 0 || r == 0) {  /* keyframe, or full delta */
            for (size_t b = 0; b < fb; ++b) cur[b] = (uint8_t)next_rand();
            const int key = i % k == 0;
            rec[4] = key ? RV565_FRAME_KEY : RV565_FRAME_DELTA;
            for (size_t b = 0; b < fb; ++b) rec[5 + b] = key ? cur[b] : cur[b] ^ prev[b];
            len = 1 + fb;
            dptr = rec + 5;
            dlen = fb;
        } else if (r == 1) {
            memcpy(cur, prev, fb);
            rec[4] = RV565_FRAME_REPEAT;
            len = 1;
        } else {
            const uint8_t band = (uint8_t)(1 + next_rand() % 12);
            const uint32_t bands = (h + band - 1u) / band, mask_len = (bands + 7u) / 8u;
            uint8_t *mask = rec + 6;
            memset(mask, 0, mask_len);
            for (uint32_t b = 0; b < bands; ++b)
                if (next_rand() % 3 == 0) mask[b >> 3] |= (uint8_t)(1u << (b & 7));
            if (r == 5) memset(mask, 0, mask_len);
            if (r == 5 || next_rand() % 4 == 0) {  /* last band only, or add it */
                mask[(bands - 1) >> 3] |= (uint8_t)(1u << ((bands - 1) & 7));
            }
            int any = 0;
            for (uint32_t m = 0; m < mask_len; ++m) any |= mask[m];
            if (!any) {
                const uint32_t b = next_rand() % bands;
                mask[b >> 3] |= (uint8_t)(1u << (b & 7));
            }
            memcpy(cur, prev, fb);
            rec[4] = RV565_FRAME_PARTIAL;
            rec[5] = band;
            uint32_t changed = 0;
            for (uint32_t b = 0; b < bands; ++b) changed += mask[b >> 3] >> (b & 7) & 1;
            uint8_t *shifts = mask + mask_len, *data = shifts + 2 * changed;
            size_t pos = 0, k = 0;
            for (uint32_t b = 0; b < bands; ++b) {
                if (!(mask[b >> 3] >> (b & 7) & 1)) continue;
                const uint32_t first = b * band, end = first + band < h ? first + band : h;
                /* Mostly small shifts, some none, some past the line. */
                int dx = (int)(next_rand() % 11) - 5, dy = (int)(next_rand() % (2u * band - 1u)) - (band - 1);
                if (next_rand() % 4 == 0) dx = dy = 0;
                if (next_rand() % 16 == 0) dx = next_rand() % 2 ? (int)row + 3 : -(int)row - 1;
                if (dx > 127) dx = 127;
                if (dx < -128) dx = -128;
                shifts[2 * k] = (uint8_t)(int8_t)dx;
                shifts[2 * k + 1] = (uint8_t)(int8_t)dy;
                ++k;
                for (uint32_t y = first; y < end; ++y) {
                    for (size_t j = 0; j < row; ++j) {
                        const int32_t sy = (int32_t)y - dy;
                        const long sj = (long)j - dx;
                        const uint8_t pred = (sy >= (int32_t)first && sy < (int32_t)end && sj >= 0 && sj < (long)row)
                            ? prev[(size_t)sy * row + (size_t)sj] : 0;
                        const size_t x = (size_t)y * row + j;
                        cur[x] = next_rand() % 8 == 0 ? (uint8_t)next_rand() : pred;
                        data[pos++] = cur[x] ^ pred;
                    }
                }
            }
            len = 2 + mask_len + 2 * changed + pos;
            dptr = data;
            dlen = pos;
        }
        if (zlib && dptr != NULL) {
            memcpy(tmp, dptr, dlen);
            len = len - dlen + zlib_store(tmp, dlen, dptr);
        }
        memcpy(truth + (size_t)i * fb, cur, fb);
        rec[0] = (uint8_t)len; rec[1] = (uint8_t)(len >> 8);
        rec[2] = (uint8_t)(len >> 16); rec[3] = (uint8_t)(len >> 24);
        at += 4 + len;
        memcpy(prev, cur, fb);
    }
    free(prev); free(cur); free(tmp);
    *size = at;
    return out;
}

int main(int argc, char **argv)
{
    static uint32_t index[65536];
    int clips = 0;
    for (int a = 1; a < argc; ++a, ++clips) {
        size_t size;
        uint8_t *data = load(argv[a], &size);
        rv565_clip_t clip;
        rv565_status_t st = rv565_open(&clip, data, size, index, 65536, 0, 0);
        if (st != RV565_OK) FAIL("%s: %s", argv[a], rv565_strerror(st));
        else play(&clip, argv[a]);
        free(data);
    }
    /* Upscaled (40x30 -> 320x240) and downscaled (24x400 -> 320x240). */
    const struct { uint16_t w, h, frames; uint8_t k; int zlib; } synth[] = {
        { 40, 30, 48, 12, 0 }, { 24, 400, 40, 10, 0 }, { 40, 30, 40, 255, 0 },
        { 40, 30, 48, 12, 1 }, { 24, 400, 40, 10, 1 },
    };
    for (size_t s = 0; s < sizeof(synth) / sizeof(synth[0]); ++s, ++clips) {
        size_t size;
        const size_t fb = (size_t)synth[s].w * synth[s].h * 2;
        uint8_t *truth = malloc(synth[s].frames * fb), *frame = malloc(fb), *scratch = malloc(fb);
        uint8_t *data = make_clip(synth[s].w, synth[s].h, synth[s].frames, synth[s].k,
                                  synth[s].zlib, truth, &size);
        rv565_clip_t clip;
        rv565_status_t st = rv565_open(&clip, data, size, index, 65536, 0, 0);
        if (st != RV565_OK) {
            FAIL("synthetic clip %zu: %s", s, rv565_strerror(st));
        } else {
            /* The decoder agrees with the generator's frames (spec semantics). */
            for (uint16_t i = 0; i < synth[s].frames; ++i) {
                if (rv565_seek(&clip, i, frame, fb, scratch, fb) != RV565_OK ||
                        memcmp(frame, truth + (size_t)i * fb, fb) != 0) {
                    FAIL("synthetic clip %zu: frame %u decodes wrongly", s, i);
                }
            }
            play(&clip, "synthetic");
        }
        free(data); free(truth); free(frame); free(scratch);
    }
    if (partial_frames == 0 || partial_rows >= partial_frames * PH)
        FAIL("partial deltas did not save rows (%lu rows over %lu frames)", partial_rows, partial_frames);
    if (failures) { fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    fprintf(stderr, "player checks passed on %d clip(s) (serial 1/2 buffers, overlap; row windows and full writes); "
            "partial deltas sent %lu of %lu panel rows\n", clips, partial_rows, partial_frames * PH);
    return 0;
}
