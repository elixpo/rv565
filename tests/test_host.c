/* Host test: decode every frame of an RV565 file and check malformed input.
 * Usage: test_host <file.rv565>
 * Prints one FNV-1a hash per frame so tests/check_host.py can compare each
 * frame against Python's zlib. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rv565.h"

static int failures;

#define EXPECT(cond, msg) do { if (!(cond)) { fprintf(stderr, "FAIL: %s\n", msg); ++failures; } } while (0)

static uint32_t fnv1a(const uint8_t *p, size_t n)
{
    uint32_t h = 2166136261u;
    while (n--) { h ^= *p++; h *= 16777619u; }
    return h;
}

static uint8_t *load(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END);
    *size = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(*size + 8);
    if (fread(data, 1, *size, f) != *size) { perror("read"); exit(2); }
    fclose(f);
    return data;
}

static void malformed(const uint8_t *good, size_t size)
{
    uint32_t index[4096];
    rv565_clip_t clip;
    uint8_t *bad = malloc(size + 8);

    memcpy(bad, good, size); bad[0] = 'X';
    EXPECT(rv565_open(&clip, bad, size, index, 4096, 0, 0) == RV565_ERR_MAGIC, "bad magic rejected");
    memcpy(bad, good, size); bad[3] = 5;
    EXPECT(rv565_open(&clip, bad, size, index, 4096, 0, 0) == RV565_ERR_VERSION, "bad version rejected");
    memcpy(bad, good, size); bad[8] = 31;
    EXPECT(rv565_open(&clip, bad, size, index, 4096, 0, 0) == RV565_ERR_HEADER, "version 6: fps > 30 rejected");
    EXPECT(rv565_open(&clip, good, size, index, 4096, 100, 0) == RV565_ERR_HEADER, "width limit enforced");
    EXPECT(rv565_open(&clip, good, size - 1, index, 4096, 0, 0) == RV565_ERR_TRUNCATED, "truncation rejected");
    memcpy(bad, good, size); bad[size] = 0;
    EXPECT(rv565_open(&clip, bad, size + 1, index, 4096, 0, 0) == RV565_ERR_TRAILING, "trailing byte rejected");
    EXPECT(rv565_open(&clip, good, size, index, 1, 0, 0) == RV565_ERR_ARG, "small index rejected");
    free(bad);
}

/* A version 7 clip built in memory: 2x2 rgb888, stored, K = 4, frames key,
 * delta, repeat. */
static void v7_checks(void)
{
    uint8_t file[16 + 3 * (5 + 12) + 5];
    const uint8_t header[16] = { 'R', 'V', '5', 7, 2, 0, 2, 0, 60, 0, 3, 0, 16, RV565_PIXEL_RGB888, RV565_CODEC_STORED, 4 };
    uint8_t f0[12], f1[12];
    for (int k = 0; k < 12; ++k) { f0[k] = (uint8_t)(k * 17); f1[k] = (uint8_t)(k * 17 + (k & 1)); }
    size_t at = 0;
    memcpy(file, header, 16); at = 16;
    file[at++] = 13; file[at++] = 0; file[at++] = 0; file[at++] = 0; file[at++] = RV565_FRAME_KEY;
    memcpy(file + at, f0, 12); at += 12;
    file[at++] = 13; file[at++] = 0; file[at++] = 0; file[at++] = 0; file[at++] = RV565_FRAME_DELTA;
    for (int k = 0; k < 12; ++k) file[at++] = f0[k] ^ f1[k];
    file[at++] = 1; file[at++] = 0; file[at++] = 0; file[at++] = 0; file[at++] = RV565_FRAME_REPEAT;

    uint32_t index[3];
    rv565_clip_t clip;
    EXPECT(rv565_open(&clip, file, at, index, 3, 0, 0) == RV565_OK, "v7: 60 FPS stored clip opens");
    EXPECT(rv565_frame_bytes(&clip.header) == 12 && rv565_bytes_per_pixel(clip.header.pixel_format) == 3,
           "v7: rgb888 frame size");
    EXPECT(rv565_frame_type(&clip, 2) == RV565_FRAME_REPEAT && rv565_keyframe_at_or_before(&clip, 2) == 0,
           "v7: frame types and keyframe lookup");
    uint8_t frame[12], other[12];
    EXPECT(rv565_decode_frame(&clip, 0, frame, 12) == RV565_OK && memcmp(frame, f0, 12) == 0, "v7: keyframe");
    EXPECT(rv565_decode_frame(&clip, 1, frame, 12) == RV565_OK && memcmp(frame, f1, 12) == 0, "v7: stored delta in place");
    EXPECT(rv565_decode(&clip, 2, frame, other, 12, NULL, 0) == RV565_OK && memcmp(other, f1, 12) == 0, "v7: repeat copies");
    EXPECT(rv565_decode(&clip, 1, NULL, other, 12, NULL, 0) == RV565_ERR_ARG, "v7: delta needs prev");
    EXPECT(rv565_seek(&clip, 2, frame, 12, NULL, 0) == RV565_OK && memcmp(frame, f1, 12) == 0, "v7: seek");

    rv565_schedule_report_t report;
    rv565_check_schedule(&clip, &RV565_COST_ESP32S3_180x135, 1000.0f, 0, &report);
    EXPECT(report.max_payload == 12, "v7: payload excludes the type byte");
    rv565_check_schedule(&clip, &RV565_COST_ESP32S3_180x135, 12000.0f, 0, &report);  /* period 16667 us */
    EXPECT(report.late_frames == 2, "v7: repeat costs no decode");

    file[8] = 61;
    EXPECT(rv565_open(&clip, file, at, index, 3, 0, 0) == RV565_ERR_HEADER, "v7: 61 FPS rejected");
    file[8] = 60;
    file[15] = 2;  /* frame 2 (a repeat) would have to be a keyframe */
    EXPECT(rv565_open(&clip, file, at, index, 3, 0, 0) == RV565_ERR_KEYFRAME, "v7: keyframe interval enforced");
    file[15] = 4;

    /* Scaling 1- and 3-byte pixels. */
    const uint8_t gray[4] = { 1, 2, 3, 4 };
    uint16_t xmap[4], ymap[4];
    uint8_t stripe[4 * 4 * 3];
    rv565_build_map(xmap, 2, 4);
    rv565_build_map(ymap, 2, 4);
    EXPECT(rv565_scale_stripe_bpp(gray, 2, 1, xmap, 4, ymap, 0, 4, stripe) == RV565_OK &&
           stripe[0] == 1 && stripe[3] == 2 && stripe[15] == 4, "scale 1 byte/pixel");
    EXPECT(rv565_scale_stripe_bpp(f0, 2, 3, xmap, 4, ymap, 0, 4, stripe) == RV565_OK &&
           memcmp(stripe + 45, f0 + 9, 3) == 0 && memcmp(stripe + 9, f0 + 3, 3) == 0, "scale 3 bytes/pixel");
    EXPECT(rv565_scale_stripe_bpp(f0, 2, 0, xmap, 4, ymap, 0, 4, stripe) == RV565_ERR_ARG, "packed formats not scaled");
    for (int s = RV565_ERR_PARTIAL; s <= RV565_OK; ++s) {
        EXPECT(strcmp(rv565_strerror((rv565_status_t)s), "unknown error") != 0, "every status has a message");
    }
}

int main(int argc, char **argv)
{
    if (argc != 2) { fprintf(stderr, "usage: %s file.rv565\n", argv[0]); return 2; }
    size_t size;
    uint8_t *data = load(argv[1], &size);

    static uint32_t index[65536];
    rv565_clip_t clip;
    rv565_status_t st = rv565_open(&clip, data, size, index, 65536, 320, 240);
    EXPECT(st == RV565_OK, rv565_strerror(st));
    if (st != RV565_OK) return 1;
    printf("header %u %u %u %u\n", clip.header.width, clip.header.height,
           clip.header.fps, clip.header.frames);

    const size_t fb = rv565_frame_bytes(&clip.header);
    uint8_t *frame = malloc(fb);
    for (uint16_t i = 0; i < clip.header.frames; ++i) {
        st = rv565_decode_frame(&clip, i, frame, fb);
        EXPECT(st == RV565_OK, "frame decodes");
        printf("frame %u %08x\n", i, fnv1a(frame, fb));
    }
    EXPECT(rv565_decode_frame(&clip, clip.header.frames, frame, fb) == RV565_ERR_RANGE, "range checked");
    EXPECT(rv565_decode_frame(&clip, 0, frame, fb - 1) == RV565_ERR_ARG, "short buffer rejected");

    /* Scaling 180x135 -> 320x240 must reproduce the source pixel at mapped coords. */
    uint16_t xmap[320], ymap[240];
    rv565_build_map(xmap, clip.header.width, 320);
    rv565_build_map(ymap, clip.header.height, 240);
    uint8_t stripe[320 * 24 * 2];
    rv565_scale_stripe(frame, clip.header.width, xmap, 320, ymap, 216, 24, stripe);
    const uint8_t *src = frame + ((size_t)ymap[239] * clip.header.width + xmap[319]) * 2;
    EXPECT(stripe[(23 * 320 + 319) * 2] == src[0] && stripe[(23 * 320 + 319) * 2 + 1] == src[1], "scaler maps last pixel");

    rv565_schedule_report_t report;
    rv565_check_schedule(&clip, &RV565_COST_ESP32S3_180x135, 31312.0f, 0, &report);
    printf("schedule serial late %u worst %.1f max_payload %u\n", report.late_frames, report.worst_frame_us, report.max_payload);
    rv565_check_schedule(&clip, &RV565_COST_ESP32S3_180x135, 31312.0f, 1, &report);
    printf("schedule overlap late %u worst %.1f\n", report.late_frames, report.worst_frame_us);
    /* RP2350 measured: 33.419 ms transfer. The test pattern's 256-byte frames
     * inflate in about 8.17 ms, so even the serial path just fits 41.667 ms. */
    rv565_check_schedule(&clip, &RV565_COST_RP2350_180x135, 33419.0f, 0, &report);
    EXPECT(report.late_frames == 0 && report.worst_frame_us < 41667.0f, "RP2350 model: test pattern fits serially");
    EXPECT(rv565_predict_inflate_us(&RV565_COST_RP2350_180x135, 30000) + 33419.0f > 41667.0f,
           "RP2350 model: a 30 KB film frame is late serially");

    rv565_pacer_t pacer;
    rv565_pacer_start(&pacer, &clip.header, 0xFFFFF000u); /* exercise timer wrap */
    uint32_t wait;
    EXPECT(rv565_pacer_advance(&pacer, 0xFFFFF000u + 1000u, &wait) == 0 && pacer.frame == 1, "pacer on time");
    /* 200 ms in: deadlines at 83.3, 125, 166.7 ms are passed by more than a
     * period, so frames 2 and 3 are skipped and frame 4 is due (already late). */
    EXPECT(rv565_pacer_advance(&pacer, 0xFFFFF000u + 200000u, &wait) == 2 && pacer.frame == 4 && wait == 0,
           "pacer skips when late");

    malformed(data, size);
    v7_checks();
    free(frame);
    free(data);
    if (failures) { fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    fprintf(stderr, "all host checks passed\n");
    return 0;
}
