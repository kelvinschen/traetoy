#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define COMPANION_BLE_FRAME_MAX 7200
/* Six-byte LE fragment header: message id, complete byte count, offset. */
typedef struct { uint16_t id,total,used; uint8_t bytes[COMPANION_BLE_FRAME_MAX]; } companion_ble_frame_t;
/* -1 malformed, 0 partial, 1 complete. Offset zero starts a fresh message. */
int companion_ble_fragment(companion_ble_frame_t *s,const uint8_t *p,size_t n);

/* Decompress authenticated payload; rejects malformed/oversized data. */
int companion_ble_unpack(const uint8_t *p,size_t n,char *out,size_t capacity);
