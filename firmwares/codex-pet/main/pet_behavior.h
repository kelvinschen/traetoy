#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
  bool linked, source_bad;
  int running;
  unsigned unread, event, ack;
  int event_kind; /* 1 completed; 2 stopped/failed, never success */
  int preview;    /* -1 live, otherwise an explicit gallery clip */
} pet_input_t;
typedef struct {
  unsigned event, ack, cycle;
  int clip, mode, stage, preview;
  int64_t start, idle_since;
  bool linked;
} pet_behavior_t;
void pet_behavior_init(pet_behavior_t *b, int64_t now);
/* Returns true when playback changes. Original clips keep their original time.
 */
bool pet_behavior_tick(pet_behavior_t *b, const pet_input_t *in, int64_t now);
unsigned pet_behavior_frame(const pet_behavior_t *b, int64_t now);
int pet_clip_find(const char *name);

/* Screen inactivity uses meaningful activity, never transport heartbeats. */
#define PET_SCREEN_DIM_US INT64_C(60000000)
#define PET_BRIGHT_ACTIVE 85
#define PET_BRIGHT_RUNNING 50
#define PET_BRIGHT_IDLE 35
#define PET_SCREEN_IDLE_US INT64_C(3600000000)
typedef struct { int64_t active_at; unsigned event; bool off; unsigned brightness; } pet_power_t;
void pet_power_init(pet_power_t *p, int64_t now);
/* Unread messages win over running; idle uses 85 -> 35 -> 0.
 * Returns true when brightness changes. Stale running>0 stays conservative. */
bool pet_power_tick(pet_power_t *p, int running, unsigned unread, unsigned event, bool key, int64_t now);
