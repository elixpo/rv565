/* Host test for lv_rv565 inside a real LVGL 9 (built by the Makefile), on a
 * headless RGB565 display whose flush callback keeps the pixels and records
 * the flushed areas. A fake tick drives the widget's timer.
 *
 * For each clip given on the command line it checks that every frame on
 * screen equals an independent decode of that frame (pixel-exact), and that
 * a partial delta flushes only the rows it changes. It also checks looping
 * and LV_EVENT_READY, pause and restart, loading from a file through lv_fs,
 * and that unsupported and invalid clips are refused.
 *
 *   test_lv_rv565 TESTDATA_DIR clip.rv565...
 */

#include "lvgl.h"
#include "lv_rv565.h"
#include "rv565.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SCR_W 64
#define SCR_H 48

static uint16_t fb[SCR_W * SCR_H];          /* what the "panel" shows */
static uint16_t draw_buf[SCR_W * SCR_H];
static uint32_t tick_ms;
static int flushed_rows[SCR_H];              /* rows flushed since the last reset */
static int failures;
static int ready_events;

#define CHECK(cond, ...) do { if(!(cond)) { failures++; printf("  FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while(0)

static uint32_t tick_cb(void) { return tick_ms; }

static void flush_cb(lv_display_t * disp, const lv_area_t * area, uint8_t * px)
{
    const uint16_t * src = (const uint16_t *) px;
    int32_t w = lv_area_get_width(area);
    for(int32_t y = area->y1; y <= area->y2; y++) {
        memcpy(&fb[y * SCR_W + area->x1], &src[(y - area->y1) * w], (size_t) w * 2);
        flushed_rows[y] = 1;
    }
    lv_display_flush_ready(disp);
}

static void ready_cb(lv_event_t * e) { LV_UNUSED(e); ready_events++; }

static uint8_t * read_all(const char * path, size_t * size)
{
    FILE * f = fopen(path, "rb");
    if(!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t * b = malloc((size_t) n);
    if(b && fread(b, 1, (size_t) n, f) != (size_t) n) { free(b); b = NULL; }
    fclose(f);
    *size = (size_t) n;
    return b;
}

/* Expected RGB565 (native) for pixel (x, y) of a decoded frame. */
static uint16_t expected_px(const rv565_header_t * h, const uint8_t * frame, int x, int y)
{
    size_t row = rv565_row_bytes(h->pixel_format, h->width);
    const uint8_t * p = frame + (size_t) y * row;
    switch(h->pixel_format) {
        case RV565_PIXEL_RGB565LE: return (uint16_t)(p[2 * x] | (p[2 * x + 1] << 8));
        case RV565_PIXEL_RGB565BE: return (uint16_t)((p[2 * x] << 8) | p[2 * x + 1]);
        case RV565_PIXEL_GRAY8: {
            lv_color_t c = lv_color_make(p[x], p[x], p[x]);
            return lv_color_to_u16(c);
        }
    }
    return 0;
}

static void refresh(void)
{
    lv_timer_handler();
    lv_refr_now(NULL);
}

static void clear_flushed(void) { memset(flushed_rows, 0, sizeof(flushed_rows)); }

/* Compare the clip's area of the screen with frame `frame`. */
static int screen_matches(const rv565_header_t * h, const uint8_t * frame, int *bad_x, int *bad_y)
{
    for(int y = 0; y < h->height; y++)
        for(int x = 0; x < h->width; x++)
            if(fb[y * SCR_W + x] != expected_px(h, frame, x, y)) { *bad_x = x; *bad_y = y; return 0; }
    return 1;
}

static lv_obj_t * new_player(void)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t * o = lv_rv565_create(lv_screen_active());
    lv_obj_set_pos(o, 0, 0);
    lv_obj_add_event_cb(o, ready_cb, LV_EVENT_READY, NULL);
    ready_events = 0;
    return o;
}

static void test_clip(const char * path)
{
    size_t size;
    uint8_t * data = read_all(path, &size);
    if(!data) { failures++; printf("  FAIL: can't read %s\n", path); return; }

    rv565_header_t h;
    rv565_parse_header(data, size, 0, 0, &h);
    uint32_t * index = malloc(sizeof(uint32_t) * h.frames);
    rv565_clip_t clip;
    rv565_status_t st = rv565_open(&clip, data, size, index, h.frames, 0, 0);
    size_t S = rv565_frame_bytes(&h);
    uint8_t * ref = malloc(S), * scratch = malloc(S);
    int supported = h.pixel_format == RV565_PIXEL_RGB565LE || h.pixel_format == RV565_PIXEL_RGB565BE ||
                    h.pixel_format == RV565_PIXEL_GRAY8;

    lv_image_dsc_t src = { 0 };
    src.data = data;
    src.data_size = (uint32_t) size;
    src.header.magic = LV_IMAGE_HEADER_MAGIC;   /* marks it a variable source */

    lv_obj_t * o = new_player();
    clear_flushed();
    lv_rv565_set_src(o, &src);
    refresh();

    if(!supported) {
        CHECK(!lv_rv565_is_loaded(o), "%s: unsupported format loaded", path);
        CHECK(lv_rv565_get_error(o) == RV565_ERR_UNSUPPORTED, "%s: error %d", path, (int) lv_rv565_get_error(o));
        goto out;
    }
    CHECK(st == RV565_OK, "%s: rv565_open %d", path, st);
    CHECK(lv_rv565_is_loaded(o), "%s: not loaded (error %d)", path, (int) lv_rv565_get_error(o));
    CHECK(lv_rv565_get_frame_count(o) == h.frames, "%s: frame count", path);
    CHECK(lv_obj_get_width(o) == h.width && lv_obj_get_height(o) == h.height, "%s: size", path);

    int partial_checked = 0;
    for(uint32_t i = 0; i < h.frames; i++) {
        if(i > 0) {
            clear_flushed();
            tick_ms += 1000 / h.fps + 1;
            refresh();
        }
        rv565_seek(&clip, (uint16_t) i, ref, S, scratch, S);
        int bx = 0, by = 0;
        CHECK(lv_rv565_get_frame(o) == i, "%s: on frame %u, expected %u", path,
              (unsigned) lv_rv565_get_frame(o), (unsigned) i);
        CHECK(screen_matches(&h, ref, &bx, &by), "%s: frame %u differs at (%d,%d)", path, (unsigned) i, bx, by);

        if(i > 0 && rv565_frame_type(&clip, (uint16_t) i) == RV565_FRAME_PARTIAL) {
            rv565_line_run_t runs[16];
            size_t n = 0;
            rv565_changed_lines(&clip, (uint16_t) i, runs, 16, &n);
            int changed[SCR_H] = { 0 };
            /* LVGL widens an invalidated area by a pixel, so allow one row
             * around each band; a whole-widget redraw still fails. */
            for(size_t r = 0; r < n; r++)
                for(int y = (int) runs[r].first - 1; y <= runs[r].first + runs[r].count; y++)
                    if(y >= 0 && y < SCR_H) changed[y] = 1;
            if(getenv("RV565_DEBUG")) {   /* print changed vs flushed rows */
                printf("    frame %u changed:", (unsigned) i);
                for(size_t r = 0; r < n; r++) printf(" %u+%u", runs[r].first, runs[r].count);
                printf("  flushed:");
                for(int y = 0; y < SCR_H; y++) if(flushed_rows[y]) printf(" %d", y);
                printf("\n");
            }
            for(int y = 0; y < SCR_H; y++)
                CHECK(!flushed_rows[y] || changed[y], "%s: partial frame %u flushed unchanged row %d",
                      path, (unsigned) i, y);
            partial_checked++;
        }
        if(i > 0 && rv565_frame_type(&clip, (uint16_t) i) == RV565_FRAME_REPEAT) {
            for(int y = 0; y < SCR_H; y++)
                CHECK(!flushed_rows[y], "%s: repeat frame %u flushed row %d", path, (unsigned) i, y);
        }
    }

    /* Wrap around: one more step plays frame 0 and sends LV_EVENT_READY. */
    tick_ms += 1000 / h.fps + 1;
    refresh();
    CHECK(ready_events == 1, "%s: %d READY events after one pass", path, ready_events);
    CHECK(lv_rv565_get_frame(o) == 0, "%s: didn't loop to frame 0", path);
    printf("  ok %s (%u frames%s)\n", path, (unsigned) h.frames, partial_checked ? ", partial rows checked" : "");
out:
    lv_obj_delete(o);
    free(ref);
    free(scratch);
    free(index);
    free(data);
}

static void test_loop_pause_file(const char * dir)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/rgb565le_zlib_partial_k5.rv565", dir);

    /* From a file through lv_fs (LV_USE_FS_STDIO, letter A). */
    char fspath[600];
    snprintf(fspath, sizeof(fspath), "A:%s", path);
    lv_obj_t * o = new_player();
    lv_rv565_set_src(o, fspath);
    refresh();
    CHECK(lv_rv565_is_loaded(o), "file source didn't load (error %d)", (int) lv_rv565_get_error(o));

    /* Play once: stop on the last frame with one READY event. */
    lv_rv565_set_loop_count(o, 1);
    for(int i = 0; i < 30; i++) { tick_ms += 90; refresh(); }
    CHECK(ready_events == 1, "loop count 1: %d READY events", ready_events);
    CHECK(lv_rv565_get_frame(o) == lv_rv565_get_frame_count(o) - 1, "loop count 1: on frame %u",
          (unsigned) lv_rv565_get_frame(o));

    /* Restart, then pause: the frame stays put. */
    lv_rv565_set_loop_count(o, LV_RV565_LOOP_FOREVER);
    lv_rv565_restart(o);
    refresh();
    CHECK(lv_rv565_get_frame(o) == 0, "restart: on frame %u", (unsigned) lv_rv565_get_frame(o));
    tick_ms += 90; refresh();
    lv_rv565_pause(o);
    uint32_t f = lv_rv565_get_frame(o);
    for(int i = 0; i < 5; i++) { tick_ms += 90; refresh(); }
    CHECK(lv_rv565_get_frame(o) == f, "pause: moved from %u to %u", (unsigned) f, (unsigned) lv_rv565_get_frame(o));
    lv_rv565_resume(o);
    tick_ms += 90; refresh();
    CHECK(lv_rv565_get_frame(o) == f + 1, "resume: on frame %u", (unsigned) lv_rv565_get_frame(o));

    /* Falling far behind decodes at most LV_RV565_MAX_CATCHUP frames per call. */
    lv_rv565_restart(o);
    refresh();
    tick_ms += 5000; refresh();
    CHECK(lv_rv565_get_frame(o) == LV_RV565_MAX_CATCHUP, "catch-up: on frame %u",
          (unsigned) lv_rv565_get_frame(o));

    /* A missing file and an invalid clip are refused. */
    lv_rv565_set_src(o, "A:/nonexistent.rv565");
    CHECK(!lv_rv565_is_loaded(o), "missing file loaded");
    snprintf(path, sizeof(path), "%s/invalid_trailing_bytes.rv565", dir);
    snprintf(fspath, sizeof(fspath), "A:%s", path);
    lv_rv565_set_src(o, fspath);
    CHECK(!lv_rv565_is_loaded(o) && lv_rv565_get_error(o) == RV565_ERR_TRAILING,
          "invalid clip: loaded=%d error=%d", lv_rv565_is_loaded(o), (int) lv_rv565_get_error(o));
    lv_obj_delete(o);
    printf("  ok file source, loop count, pause/resume/restart, catch-up, refusals\n");
}

int main(int argc, char ** argv)
{
    if(argc < 3) {
        fprintf(stderr, "usage: %s TESTDATA_DIR clip.rv565...\n", argv[0]);
        return 2;
    }
    lv_init();
    lv_tick_set_cb(tick_cb);
    lv_display_t * disp = lv_display_create(SCR_W, SCR_H);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(disp, draw_buf, NULL, sizeof(draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, flush_cb);
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_black(), 0);
    refresh();

    printf("LVGL %d.%d.%d\n", LVGL_VERSION_MAJOR, LVGL_VERSION_MINOR, LVGL_VERSION_PATCH);
    for(int i = 2; i < argc; i++) test_clip(argv[i]);
    test_loop_pause_file(argv[1]);

    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
