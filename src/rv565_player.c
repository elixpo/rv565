#include "rv565_player.h"

#include <string.h>

rv565_status_t rv565_player_init(rv565_player_t *p)
{
    if (p == NULL || p->clip == NULL || p->micros == NULL ||
            p->display.begin_frame == NULL || p->display.queue_stripe == NULL ||
            p->display.wait_stripe == NULL || p->display.end_frame == NULL ||
            p->stripes[0] == NULL || p->stripes[1] == NULL || p->frames[0] == NULL ||
            p->xmap == NULL || p->ymap == NULL || p->stripe_rows == 0 ||
            p->panel_width == 0 || p->panel_height == 0) {
        return RV565_ERR_ARG;
    }
    const rv565_header_t *h = &p->clip->header;
    if (h->pixel_format != RV565_PIXEL_RGB565BE) {
        return RV565_ERR_UNSUPPORTED;
    }
    if (p->decoder.start != NULL && (p->decoder.finish == NULL || p->frames[1] == NULL)) {
        return RV565_ERR_ARG;
    }
    /* With one buffer, deltas decode in place, which a zlib delta can only
     * do through a scratch buffer as large as a second frame. */
    if (p->frames[1] == NULL && h->codec == RV565_CODEC_ZLIB) {
        for (uint16_t i = 0; i < h->frames; ++i) {
            if (rv565_frame_type(p->clip, i) == RV565_FRAME_DELTA) {
                return RV565_ERR_ARG;
            }
        }
    }
    rv565_build_map(p->xmap, h->width, p->panel_width);
    rv565_build_map(p->ymap, h->height, p->panel_height);
    p->current = 0;
    p->held[0] = p->held[1] = -1;
    p->gen[0] = p->gen[1] = 0;
    p->sent = -1;
    p->sent_gen = 0;
    p->ready_inflate_us = 0;
    return RV565_OK;
}

/* Scale and transfer one decoded frame through the two stripes. Scaling of
 * stripe n+1 overlaps the DMA transfer of stripe n. */
static void send_frame(rv565_player_t *p, const uint8_t *frame, rv565_frame_stats_t *s)
{
    const rv565_header_t *h = &p->clip->header;
    const size_t stripe_row_bytes = (size_t)p->panel_width * 2u;
    const uint32_t start = p->micros();

    p->display.begin_frame(p->display.ctx);
    int current = 0;
    uint16_t row = 0;
    uint16_t rows = p->stripe_rows < p->panel_height ? p->stripe_rows : p->panel_height;

    uint32_t t = p->micros();
    rv565_scale_stripe(frame, h->width, p->xmap, p->panel_width, p->ymap, row, rows, p->stripes[current]);
    s->scale_us += p->micros() - t;

    while (row < p->panel_height) {
        p->display.queue_stripe(p->display.ctx, p->stripes[current], rows * stripe_row_bytes);
        const uint16_t next_row = (uint16_t)(row + rows);
        const uint16_t left = (uint16_t)(p->panel_height - next_row);
        const uint16_t next_rows = next_row < p->panel_height
            ? (left < p->stripe_rows ? left : p->stripe_rows) : 0;
        if (next_rows != 0) {
            t = p->micros();
            rv565_scale_stripe(frame, h->width, p->xmap, p->panel_width, p->ymap,
                               next_row, next_rows, p->stripes[current ^ 1]);
            s->scale_us += p->micros() - t;
        }
        t = p->micros();
        p->display.wait_stripe(p->display.ctx);
        s->wait_us += p->micros() - t;
        row = next_row;
        rows = next_rows;
        current ^= 1;
    }
    p->display.end_frame(p->display.ctx);
    s->transfer_us = p->micros() - start;
}

/* Decode one record synchronously on the critical path. */
static rv565_status_t decode_one(rv565_player_t *p, uint16_t j, const uint8_t *prev,
                                 uint8_t *dst, uint32_t *us)
{
    const size_t frame_bytes = rv565_frame_bytes(&p->clip->header);
    const uint32_t t = p->micros();
    rv565_status_t status;
    if (p->decoder.start != NULL) {
        p->decoder.start(p->decoder.ctx, j, prev, dst, frame_bytes);
        return p->decoder.finish(p->decoder.ctx, us);
    }
    if (p->decoder.decode != NULL) {
        status = p->decoder.decode(p->decoder.ctx, j, prev, dst, frame_bytes);
    } else {
        status = rv565_decode(p->clip, j, prev, dst, frame_bytes, NULL, 0);
    }
    *us = p->micros() - t;
    return status;
}

/* Bring source frame `index` into a frame buffer and return which one. A
 * frame already decoded (the prefetch, or the presented frame) costs nothing;
 * otherwise decoding resumes from the latest buffered frame on the chain from
 * the keyframe at or before `index`, or from that keyframe. */
static rv565_status_t bring(rv565_player_t *p, uint16_t index, int *out,
                            rv565_frame_stats_t *s)
{
    const int buffers = p->frames[1] != NULL ? 2 : 1;
    for (int b = 0; b < buffers; ++b) {
        if (p->held[b] == (int32_t)index) {
            if (b != p->current) {
                s->inflate_us = p->ready_inflate_us;  /* prefetched */
            }
            *out = b;
            return RV565_OK;
        }
    }
    const int32_t key = rv565_keyframe_at_or_before(p->clip, index);
    if (key < 0) {
        return (rv565_status_t)key;
    }
    int b = p->current;
    uint32_t j = (uint32_t)key;
    for (int c = 0; c < buffers; ++c) {
        if (p->held[c] >= key && p->held[c] < (int32_t)index && p->held[c] + 1 > (int32_t)j) {
            b = c;
            j = (uint32_t)p->held[c] + 1u;
        }
    }
    for (; j <= index; ++j) {
        if (rv565_frame_type(p->clip, (uint16_t)j) == RV565_FRAME_REPEAT && p->held[b] == (int32_t)j - 1) {
            p->held[b] = (int32_t)j;  /* same pixels: nothing to decode */
            continue;
        }
        const int dst = buffers == 2 ? b ^ 1 : b;
        p->held[dst] = -1;
        ++p->gen[dst];
        uint32_t us = 0;
        const rv565_status_t status = decode_one(p, (uint16_t)j, p->frames[b], p->frames[dst], &us);
        s->inflate_us += us;
        ++s->decoded;
        if (status != RV565_OK) {
            return status;
        }
        p->held[dst] = (int32_t)j;
        b = dst;
    }
    *out = b;
    return RV565_OK;
}

rv565_status_t rv565_player_present(rv565_player_t *p, uint16_t index,
                                    rv565_frame_stats_t *stats)
{
    rv565_frame_stats_t local;
    rv565_frame_stats_t *s = stats != NULL ? stats : &local;
    memset(s, 0, sizeof(*s));
    const rv565_header_t *h = &p->clip->header;
    if (index >= h->frames) {
        return RV565_ERR_RANGE;
    }
    const uint32_t work_start = p->micros();
    int b;
    rv565_status_t status = bring(p, index, &b, s);
    if (status != RV565_OK) {
        return status;
    }
    p->current = b;

    /* Dual-core path: decode the next frame into the other buffer while this
     * one is transferred. A repeat needs no decode (it stays in this buffer);
     * a delta reads this buffer, which the display only reads too. */
    const uint16_t next = (uint16_t)((index + 1u) % h->frames);
    const int other = b ^ 1;
    const int prefetch = p->decoder.start != NULL && next != index &&
                         p->held[other] != (int32_t)next &&
                         rv565_frame_type(p->clip, next) != RV565_FRAME_REPEAT;
    if (prefetch) {
        p->held[other] = -1;
        ++p->gen[other];
        p->decoder.start(p->decoder.ctx, next, p->frames[b], p->frames[other],
                         rv565_frame_bytes(h));
    }

    /* A frame whose pixels are already on the panel (a repeat, or the same
     * frame again) is not sent. */
    if (p->sent != b || p->sent_gen != p->gen[b]) {
        send_frame(p, p->frames[b], s);
        p->sent = b;
        p->sent_gen = p->gen[b];
        s->sent = 1;
    }

    if (prefetch) {
        status = p->decoder.finish(p->decoder.ctx, &p->ready_inflate_us);
        if (status != RV565_OK) {
            return status;
        }
        p->held[other] = (int32_t)next;
    }
    s->work_us = p->micros() - work_start;
    return RV565_OK;
}
