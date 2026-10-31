/* ST7789 initialisation sequence shared by the platform ports. Values are
 * those used by the RV565 benchmark firmware on a 2.0" 320x240 IPS panel. */
#ifndef RV565_ST7789_INIT_H
#define RV565_ST7789_INIT_H

#include <stdint.h>

/* A step whose len has this flag sends no data: it issues the command and
 * then waits data[0] milliseconds. Otherwise len is the data byte count. */
#define RV565_ST7789_DELAY 0x80

typedef struct {
    uint8_t cmd;
    uint8_t len;      /* data bytes, optionally | RV565_ST7789_DELAY */
    uint8_t data[5];
} rv565_st7789_step_t;

/* MADCTL 0x60 selects landscape 320x240; inversion is required by IPS panels. */
static const rv565_st7789_step_t RV565_ST7789_INIT[] = {
    { 0x01, RV565_ST7789_DELAY | 1, { 150 } },               /* software reset */
    { 0x11, RV565_ST7789_DELAY | 1, { 120 } },               /* sleep out */
    { 0x3A, 1, { 0x55 } },                                   /* RGB565 */
    { 0x36, 1, { 0x60 } },                                   /* landscape */
    { 0xB2, 5, { 0x0C, 0x0C, 0x00, 0x33, 0x33 } },           /* porch */
    { 0xC6, 1, { 0x0F } },                                   /* 60 Hz scan */
    { 0xC0, 1, { 0x2C } },
    { 0xC2, 1, { 0x01 } },
    { 0xC3, 1, { 0x12 } },
    { 0xC4, 1, { 0x20 } },
    { 0xBB, 1, { 0x20 } },
    { 0x2A, 4, { 0x00, 0x00, 0x01, 0x3F } },                 /* columns 0..319 */
    { 0x2B, 4, { 0x00, 0x00, 0x00, 0xEF } },                 /* rows 0..239 */
    { 0x21, 0, { 0 } },                                      /* inversion on */
    { 0x13, 0, { 0 } },                                      /* normal mode */
    { 0x29, RV565_ST7789_DELAY | 1, { 20 } },                /* display on */
};

#define RV565_ST7789_RAMWR 0x2C

#endif /* RV565_ST7789_INIT_H */
