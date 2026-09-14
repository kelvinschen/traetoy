#pragma once
#include "../vendor/miniz/miniz.h"
#include "pet_assets.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define PET_PACKED (PET_W * PET_W / 2)
typedef struct {
  int x, y, w, h;
} pet_rect_t;
typedef struct {
  uint8_t pixels[PET_PACKED], scratch[PET_PACKED];
  tinfl_decompressor inflate;
  const uint8_t *data;
  size_t size;
  int frame;
  pet_rect_t stripes[PET_W / 16];
} pet_decoder_t;
void pet_decoder_init(pet_decoder_t *d, const uint8_t *data, size_t size);
bool pet_decode(pet_decoder_t *d, unsigned clip, unsigned frame,
                pet_rect_t *dirty);
