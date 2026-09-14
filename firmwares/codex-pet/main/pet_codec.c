#include "pet_codec.h"
#include <string.h>
void pet_decoder_init(pet_decoder_t *d, const uint8_t *data, size_t size) {
  memset(d, 0, sizeof(*d));
  memset(d->pixels, 0xee, PET_PACKED);
  d->data = data;
  d->size = size;
  d->frame = -1;
}
static bool unpack(pet_decoder_t *d, unsigned frame, pet_rect_t *r) {
  const pet_frame_record_t *f = &pet_frames[frame];
  if (f->offset > d->size || f->size > d->size - f->offset)
    return false;
  size_t src = f->size, dst = PET_PACKED;
  tinfl_init(&d->inflate);
  tinfl_status result = tinfl_decompress(
      &d->inflate, d->data + f->offset, &src, d->scratch, d->scratch, &dst,
      TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
  if (result != TINFL_STATUS_DONE || dst != PET_PACKED || src != f->size)
    return false;
  int minx = PET_W, miny = PET_W, maxx = -1, maxy = -1;
  for (int y = 0; y < PET_W; y++) {
    int row_min = PET_W, row_max = -1;
    for (int x = 0; x < PET_W; x += 8) {
      unsigned i = (unsigned)(y * (PET_W / 2) + x / 2);
      uint32_t old, delta;
      memcpy(&old, d->pixels + i, sizeof(old));
      memcpy(&delta, d->scratch + i, sizeof(delta));
      uint32_t value = f->key ? delta : old ^ delta;
      if (value == old)
        continue;
      memcpy(d->pixels + i, &value, sizeof(value));
      if (x < row_min)
        row_min = x;
      row_max = x + 7;
    }
    if (row_max < 0)
      continue;
    if (row_min < minx)
      minx = row_min;
    if (row_max > maxx)
      maxx = row_max;
    if (y < miny)
      miny = y;
    maxy = y;
    pet_rect_t *stripe = &d->stripes[y / 16];
    if (!stripe->w)
      *stripe = (pet_rect_t){row_min, y, row_max - row_min + 1, 1};
    else {
      int right = stripe->x + stripe->w;
      if (row_max + 1 > right)
        right = row_max + 1;
      if (row_min < stripe->x)
        stripe->x = row_min;
      if (y < stripe->y) {
        stripe->h += stripe->y - y;
        stripe->y = y;
      }
      if (y >= stripe->y + stripe->h)
        stripe->h = y - stripe->y + 1;
      stripe->w = right - stripe->x;
    }
  }
  if (r)
    *r = (pet_rect_t){minx, miny, maxx < 0 ? 0 : maxx - minx + 1,
                      maxy < 0 ? 0 : maxy - miny + 1};
  d->frame = (int)frame;
  return true;
}
bool pet_decode(pet_decoder_t *d, unsigned clip, unsigned frame,
                pet_rect_t *r) {
  if (!d || clip >= PET_CLIP_COUNT || frame >= pet_clips[clip].count)
    return false;
  memset(d->stripes, 0, sizeof(d->stripes));
  unsigned target = pet_clips[clip].start + frame;
  if ((int)target == d->frame) {
    *r = (pet_rect_t){0};
    return true;
  }
  unsigned key = pet_clips[clip].start + (frame / 60) * 60;
  /* Forward catch-up must not restart a whole GOP for every missed frame. */
  if (d->frame >= (int)pet_clips[clip].start && d->frame < (int)target &&
      d->frame + 1 >= (int)key) {
    pet_rect_t total = {0};
    for (unsigned i = (unsigned)(d->frame + 1); i <= target; i++) {
      pet_rect_t part;
      if (!unpack(d, i, &part))
        return false;
      if (!part.w || !part.h)
        continue;
      if (!total.w)
        total = part;
      else {
        int right = total.x + total.w, bottom = total.y + total.h;
        if (part.x + part.w > right)
          right = part.x + part.w;
        if (part.y + part.h > bottom)
          bottom = part.y + part.h;
        if (part.x < total.x)
          total.x = part.x;
        if (part.y < total.y)
          total.y = part.y;
        total.w = right - total.x;
        total.h = bottom - total.y;
      }
    }
    *r = total;
    return true;
  }
  for (unsigned i = key; i <= target; i++)
    if (!unpack(d, i, NULL))
      return false;
  for (int i = 0; i < PET_W / 16; i++)
    d->stripes[i] = (pet_rect_t){0, i * 16, PET_W, 16};
  *r = (pet_rect_t){0, 0, PET_W, PET_W};
  return true;
}
