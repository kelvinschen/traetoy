#pragma once
#include "companion_protocol.h"
#include "pet_behavior.h"
#include "pet_codec.h"
#include "pet_pages.h"
typedef struct {
  pet_input_t input;
  bool screen_off;
  unsigned brightness;
  companion_state_t state;
  int page, selected, count, elapsed, alert_kind;
  unsigned version, dropped;
  char host[49];
  uint8_t tile[COMPANION_TILE_BYTES];
  unsigned fps10;
  companion_metadata_t usage;
  int cards, card_count, source_count, battery, link_age, info_age, transport;
  unsigned uptime;
  bool cards_known, sources_healthy[COMPANION_SOURCES_MAX], usage_fresh;
  char expires[COMPANION_CARDS_MAX][17], sources[COMPANION_SOURCES_MAX][24];
  char card_status[COMPANION_CARDS_MAX][16];
} pet_view_t;
typedef struct {
  const pet_view_t *view;
  const uint8_t *pixels, *previous;
  unsigned blend; /* 0..256, new-frame weight */
  int clip;
  bool linked, quota_fresh;
  int avatar_y; /* top of the 192px sprite, default 58 */
  unsigned reveal; /* 0..256 */
} pet_paint_t;
uint16_t pet_rgb(unsigned r, unsigned g, unsigned b);
int pet_quota_window(const companion_state_t *s);
void pet_paint(const pet_paint_t *p, pet_rect_t area, uint16_t *out);
pet_rect_t pet_content_bounds(const uint8_t *pixels);

/* Fixed-point, reversible 380 ms screen-space movement. */
typedef struct { int from, position, target; int64_t at; } pet_layout_t;
void pet_layout_init(pet_layout_t *l, int64_t now);
int pet_layout_tick(pet_layout_t *l, bool expanded, int64_t now);
