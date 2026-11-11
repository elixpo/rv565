/* RV565 player: the paper's stripe pipeline, independent of any platform.
 *
 * Per frame the player scales the decoded frame into two alternating
 * stripes and hands them to the display driver, so stripe n+1 is scaled
 * while stripe n is transferred by DMA. With a decoder backend, the next
 * frame is decoded on another core during that transfer (dual-core
 * overlap); without one, frames are decoded inline (serial path).
 *
 * Frames are RGB565 big-endian, the order the bundled ST7789 drivers and
 * the TFT_eSPI/LovyanGFX examples send; rv565_player_init() rejects other
 * pixel formats with RV565_ERR_UNSUPPORTED.
 *
 * Delta and repeat frames (format version 7): the two frame buffers
 * ping-pong, so a delta decodes into the buffer that is not on screen with
 * the presented frame as its base, and a repeat decodes nothing and is not
 * sent to the display again. When the pacer skips frames, the player
 * applies the skipped records it needs (at most K-1 after a keyframe)
 * without displaying them.
 *
 * Platform ports (port/esp32, port/rp2) implement the two ops tables.
 */
#ifndef RV565_PLAYER_H
#define RV565_PLAYER_H

#include "rv565.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Display driver. At most two stripes are queued at once. */
typedef struct {
    void *ctx;
    /* Start a full-screen write (address window and RAMWR). */
    void (*begin_frame)(void *ctx);
    /* Queue one stripe for DMA; may return before the transfer ends. */
    void (*queue_stripe)(void *ctx, const uint8_t *data, size_t length);
    /* Block until the oldest queued stripe has been transferred. */
    void (*wait_stripe)(void *ctx);
    /* Finish the write (release chip select). */
    void (*end_frame)(void *ctx);
} rv565_display_ops_t;

/* Optional decoder backend. The player always passes prev != dst, so a
 * backend can call rv565_decode(clip, index, prev, dst, dst_len, NULL, 0). */
typedef struct {
    void *ctx;
    /* Begin decoding frame `index` into `dst` asynchronously (another core).
     * `prev` holds frame index-1 for a delta; it is read, never written, and
     * the display may be reading it at the same time. */
    void (*start)(void *ctx, uint16_t index, const uint8_t *prev,
                  uint8_t *dst, size_t dst_len);
    /* Wait for the started frame; reports its decode time. */
    rv565_status_t (*finish)(void *ctx, uint32_t *inflate_us);
    /* Serial path only (start == NULL): decode synchronously instead of
     * rv565_decode(), e.g. for another codec. NULL uses rv565_decode(). */
    rv565_status_t (*decode)(void *ctx, uint16_t index, const uint8_t *prev,
                             uint8_t *dst, size_t dst_len);
} rv565_decoder_ops_t;

typedef struct {
    uint32_t inflate_us;  /* decode time of the presented frame (and any catch-up) */
    uint32_t scale_us;    /* cumulative stripe scaling */
    uint32_t wait_us;     /* cumulative wait for DMA */
    uint32_t transfer_us; /* whole display write (0 if not sent) */
    uint32_t work_us;     /* frame work on the critical path */
    uint16_t decoded;     /* records decoded on the critical path */
    uint8_t  sent;        /* 1 if the frame went to the display; 0 if unchanged */
} rv565_frame_stats_t;

typedef struct {
    /* Configuration: fill before rv565_player_init(). */
    const rv565_clip_t *clip;
    uint16_t panel_width;
    uint16_t panel_height;
    uint16_t stripe_rows;           /* rows per stripe, e.g. 24 */
    uint8_t *stripes[2];            /* DMA-capable, panel_width*stripe_rows*2 each */
    /* Decoded frames, rv565_frame_bytes() each. frames[1] is required for
     * overlap and for clips with zlib deltas; otherwise it may be NULL. */
    uint8_t *frames[2];
    uint16_t *xmap;                 /* panel_width entries */
    uint16_t *ymap;                 /* panel_height entries */
    rv565_display_ops_t display;
    rv565_decoder_ops_t decoder;    /* start == NULL selects the serial path */
    uint32_t (*micros)(void);       /* monotonic microsecond clock */

    /* State. */
    int current;                    /* buffer holding the presented frame */
    int32_t held[2];                /* source frame in each buffer, -1 if none */
    uint32_t gen[2];                /* bumped whenever a buffer is rewritten */
    int sent;                       /* buffer last sent to the display, -1 if none */
    uint32_t sent_gen;              /* its gen[] when it was sent */
    uint32_t ready_inflate_us;      /* decode time of the prefetched frame */
} rv565_player_t;

/* Validate the configuration and build the scaling maps. Returns
 * RV565_ERR_UNSUPPORTED for pixel formats other than RGB565 big-endian, and
 * RV565_ERR_ARG if the clip has zlib deltas and frames[1] is NULL. */
rv565_status_t rv565_player_init(rv565_player_t *p);

/* Present one source frame and, with a decoder backend, prefetch the next. */
rv565_status_t rv565_player_present(rv565_player_t *p, uint16_t index,
                                    rv565_frame_stats_t *stats);

#ifdef __cplusplus
}
#endif

#endif /* RV565_PLAYER_H */
