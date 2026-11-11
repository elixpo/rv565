/* Host test for the player: a mock display assembles stripes into a
 * framebuffer, and a synchronous mock decoder stands in for core 1. Both
 * the serial and dual-core paths must draw every frame exactly, including
 * delta and repeat frames, skips and loops; repeats must not be re-sent.
 * Usage: test_player file.rv565 [more.rv565 ...] */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rv565_player.h"

#define PW 320
#define PH 240
#define ROWS 24

static uint8_t screen[PW * PH * 2];
static size_t cursor;
static int queued, failures, frames_sent;
static uint32_t clock_us;
static const rv565_clip_t *g_clip;
static struct { uint16_t index; const uint8_t *prev; uint8_t *dst; size_t len; int pending; } job;

#define FAIL(...) do { fprintf(stderr, "FAIL: " __VA_ARGS__); fputc('\n', stderr); ++failures; } while (0)

static uint32_t fake_micros(void) { return clock_us += 7; }
static void begin(void *c) { (void)c; cursor = 0; ++frames_sent; }
static void queue(void *c, const uint8_t *d, size_t n)
{
    (void)c;
    if (++queued > 2) FAIL("more than two stripes queued");
    memcpy(screen + cursor, d, n);
    cursor += n;
}
static void wait_one(void *c) { (void)c; --queued; }
static void end(void *c) { (void)c; }

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
    if (st != RV565_OK || cursor != sizeof(screen) || memcmp(screen, expect, sizeof(screen)) != 0) {
        fprintf(stderr, "FAIL: %s frame %u drawn incorrectly\n", mode, index);
        return 1;
    }
    return 0;
}

static int setup(rv565_player_t *p, const rv565_clip_t *clip, int overlap, int two)
{
    static uint8_t s0[PW * ROWS * 2], s1[PW * ROWS * 2];
    static uint16_t xmap[PW], ymap[PH];
    const size_t fb = rv565_frame_bytes(&clip->header);
    rv565_player_t init = {
        .clip = clip, .panel_width = PW, .panel_height = PH, .stripe_rows = ROWS,
        .stripes = { s0, s1 }, .frames = { malloc(fb), two ? malloc(fb) : NULL },
        .xmap = xmap, .ymap = ymap,
        .display = { NULL, begin, queue, wait_one, end },
        .decoder = { NULL, overlap ? dec_start : NULL, overlap ? dec_finish : NULL, NULL },
        .micros = fake_micros,
    };
    *p = init;
    return rv565_player_init(p);
}

static void teardown(rv565_player_t *p) { free(p->frames[0]); free(p->frames[1]); }

static int has_zlib_delta(const rv565_clip_t *clip)
{
    if (clip->header.codec != RV565_CODEC_ZLIB) return 0;
    for (uint16_t i = 0; i < clip->header.frames; ++i)
        if (rv565_frame_type(clip, i) == RV565_FRAME_DELTA) return 1;
    return 0;
}

static void present_checked(rv565_player_t *p, const rv565_clip_t *clip, uint16_t i, const char *mode)
{
    rv565_frame_stats_t st;
    rv565_status_t s = rv565_player_present(p, i, &st);
    if (s != RV565_OK) { FAIL("%s present %u: %s", mode, i, rv565_strerror(s)); return; }
    failures += check_frame(clip, i, mode);
    if (queued != 0) FAIL("stripes left queued");
    if (job.pending) FAIL("%s: decode left pending", mode);
}

static void run(const rv565_clip_t *clip, int overlap, int two)
{
    char mode[48];
    snprintf(mode, sizeof(mode), "%s/%s", overlap ? "overlap" : "serial", two ? "2 buffers" : "1 buffer");
    rv565_player_t p;
    rv565_status_t st = setup(&p, clip, overlap, two);
    if (!two && has_zlib_delta(clip)) {
        if (st != RV565_ERR_ARG) FAIL("%s: zlib deltas with one buffer accepted", mode);
        teardown(&p);
        return;
    }
    if (st != RV565_OK) { FAIL("init %s: %s", mode, rv565_strerror(st)); teardown(&p); return; }

    /* Sequential: every frame drawn, and a frame is sent exactly when its
     * pixels differ from the previous frame's, i.e. unless it is a repeat. */
    const uint16_t n = clip->header.frames;
    int expected_sends = 0;
    frames_sent = 0;
    for (uint16_t i = 0; i < n; ++i) {
        present_checked(&p, clip, i, mode);
        expected_sends += i == 0 || rv565_frame_type(clip, i) != RV565_FRAME_REPEAT;
    }
    if (frames_sent != expected_sends) FAIL("%s: %d frames sent, expected %d", mode, frames_sent, expected_sends);

    /* Skips, a loop around the end, and the same frame twice. */
    const uint16_t last = (uint16_t)(n - 1);
    const uint16_t order[] = { 0, 1, 2, 5, 6, (uint16_t)(last - 1), last, 0, 1, 1, 7, 3 };
    for (size_t k = 0; k < sizeof(order) / sizeof(order[0]); ++k) {
        if (order[k] < n) present_checked(&p, clip, order[k], mode);
    }
    teardown(&p);
}

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    for (int a = 1; a < argc; ++a) {
        size_t size;
        uint8_t *data = load(argv[a], &size);
        static uint32_t index[65536];
        rv565_clip_t clip;
        rv565_status_t st = rv565_open(&clip, data, size, index, 65536, 0, 0);
        if (st != RV565_OK) { FAIL("%s: %s", argv[a], rv565_strerror(st)); free(data); continue; }
        g_clip = &clip;
        if (clip.header.pixel_format != RV565_PIXEL_RGB565BE) {
            rv565_player_t p;
            if (setup(&p, &clip, 0, 1) != RV565_ERR_UNSUPPORTED) FAIL("%s: pixel format accepted", argv[a]);
            teardown(&p);
        } else {
            run(&clip, 0, 0);
            run(&clip, 0, 1);
            run(&clip, 1, 1);
        }
        free(data);
    }
    if (failures) { fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    fprintf(stderr, "player checks passed on %d clip(s) (serial, serial with two buffers, overlap)\n", argc - 1);
    return 0;
}
