// Firmware-resident RV565 frame decoding for OreoOS on ESP32-S3.
//
// The Python side parses the container (version 6 or 7, see docs/FORMAT.md)
// and hands each frame body to this module, which decodes it into a reused
// frame buffer without allocating a Python bytes object or running Deflate or
// the XOR pass through the MicroPython layer. The ESP32-S3 ROM already
// contains miniz's tinfl, which inflates zlib bodies.
//
//   inflate_frame(body, frame)            keyframe: frame = inflate(body)
//   inflate_delta(body, prev, frame[, scratch])
//                                         delta: frame = prev XOR inflate(body);
//                                         in place (prev is frame) needs a
//                                         scratch buffer of len(frame) bytes
//   xor_frame(frame, other)               frame ^= other (stored deltas)
//
// A repeat frame needs nothing: the previous frame is already decoded.
// Every function raises ValueError unless the body inflates to exactly
// len(frame) bytes and the buffers have that length.

#include <stddef.h>
#include <stdint.h>

#include "py/runtime.h"
#include "miniz.h"

static void inflate_exact(const mp_buffer_info_t *src, void *dst, size_t len) {
    if (src->len == 0 || len == 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("empty RV565 frame buffer"));
    }
    const size_t written = tinfl_decompress_mem_to_mem(
        dst, len, src->buf, src->len, TINFL_FLAG_PARSE_ZLIB_HEADER);
    if (written != len) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid RV565 frame"));
    }
}

typedef uint32_t __attribute__((may_alias)) xor_word_t;

static void xor_into(uint8_t *dst, const uint8_t *src, size_t len) {
    size_t k = 0;
    if ((((uintptr_t)dst | (uintptr_t)src) & 3u) == 0) {
        xor_word_t *d32 = (xor_word_t *)(void *)dst;
        const xor_word_t *s32 = (const xor_word_t *)(const void *)src;
        for (size_t w = len / 4u; w != 0; --w) {
            *d32++ ^= *s32++;
        }
        k = len & ~(size_t)3u;
    }
    for (; k < len; ++k) {
        dst[k] ^= src[k];
    }
}

static mp_obj_t oreo_rv565_inflate_frame(mp_obj_t source_obj,
                                          mp_obj_t destination_obj) {
    mp_buffer_info_t source;
    mp_buffer_info_t destination;
    mp_get_buffer_raise(source_obj, &source, MP_BUFFER_READ);
    mp_get_buffer_raise(destination_obj, &destination, MP_BUFFER_WRITE);
    inflate_exact(&source, destination.buf, destination.len);
    return mp_obj_new_int_from_uint(destination.len);
}
static MP_DEFINE_CONST_FUN_OBJ_2(
    oreo_rv565_inflate_frame_obj,
    oreo_rv565_inflate_frame
);

static mp_obj_t oreo_rv565_inflate_delta(size_t n_args, const mp_obj_t *args) {
    mp_buffer_info_t source, prev, frame;
    mp_get_buffer_raise(args[0], &source, MP_BUFFER_READ);
    mp_get_buffer_raise(args[1], &prev, MP_BUFFER_READ);
    mp_get_buffer_raise(args[2], &frame, MP_BUFFER_WRITE);
    if (prev.len != frame.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("RV565 frame sizes differ"));
    }
    if (prev.buf != frame.buf) {
        inflate_exact(&source, frame.buf, frame.len);
        xor_into(frame.buf, prev.buf, frame.len);
    } else {
        mp_buffer_info_t scratch;
        if (n_args < 4) {
            mp_raise_ValueError(MP_ERROR_TEXT("in-place RV565 delta needs a scratch buffer"));
        }
        mp_get_buffer_raise(args[3], &scratch, MP_BUFFER_WRITE);
        if (scratch.len < frame.len) {
            mp_raise_ValueError(MP_ERROR_TEXT("RV565 scratch buffer too small"));
        }
        inflate_exact(&source, scratch.buf, frame.len);
        xor_into(frame.buf, scratch.buf, frame.len);
    }
    return mp_obj_new_int_from_uint(frame.len);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    oreo_rv565_inflate_delta_obj, 3, 4,
    oreo_rv565_inflate_delta
);

static mp_obj_t oreo_rv565_xor_frame(mp_obj_t frame_obj, mp_obj_t other_obj) {
    mp_buffer_info_t frame, other;
    mp_get_buffer_raise(frame_obj, &frame, MP_BUFFER_WRITE);
    mp_get_buffer_raise(other_obj, &other, MP_BUFFER_READ);
    if (frame.len != other.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("RV565 frame sizes differ"));
    }
    xor_into(frame.buf, other.buf, frame.len);
    return mp_obj_new_int_from_uint(frame.len);
}
static MP_DEFINE_CONST_FUN_OBJ_2(
    oreo_rv565_xor_frame_obj,
    oreo_rv565_xor_frame
);

static const mp_rom_map_elem_t oreo_rv565_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__oreo_rv565)},
    {MP_ROM_QSTR(MP_QSTR_FORMAT_VERSION), MP_ROM_INT(7)},
    {MP_ROM_QSTR(MP_QSTR_inflate_frame),
     MP_ROM_PTR(&oreo_rv565_inflate_frame_obj)},
    {MP_ROM_QSTR(MP_QSTR_inflate_delta),
     MP_ROM_PTR(&oreo_rv565_inflate_delta_obj)},
    {MP_ROM_QSTR(MP_QSTR_xor_frame),
     MP_ROM_PTR(&oreo_rv565_xor_frame_obj)},
};
static MP_DEFINE_CONST_DICT(
    oreo_rv565_module_globals,
    oreo_rv565_module_globals_table
);

const mp_obj_module_t oreo_rv565_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&oreo_rv565_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR__oreo_rv565, oreo_rv565_module);
