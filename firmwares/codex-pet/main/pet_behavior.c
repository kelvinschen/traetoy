#include "pet_behavior.h"
#include "pet_assets.h"
#include <string.h>
int pet_clip_find(const char *name) {
  for (int i = 0; i < PET_CLIP_COUNT; i++)
    if (!strcmp(name, pet_clips[i].name)) return i;
  return -1;
}
static void choose(pet_behavior_t *b, const char *name, int64_t now) {
  b->clip = pet_clip_find(name);
  if (b->clip < 0) b->clip = 0;
  b->start = now;
}
void pet_behavior_init(pet_behavior_t *b, int64_t now) {
  *b = (pet_behavior_t){.preview = -1, .mode = -1, .idle_since = now};
  choose(b, "idle", now);
}
unsigned pet_behavior_frame(const pet_behavior_t *b, int64_t now) {
  uint64_t n = now > b->start ? (uint64_t)(now - b->start) * PET_FPS / 1000000 : 0;
  const pet_clip_t *c = &pet_clips[b->clip];
  if (n >= c->count) n = c->loop_start + (n - c->loop_start) % (c->count - c->loop_start);
  return (unsigned)n;
}
bool pet_behavior_tick(pet_behavior_t *b, const pet_input_t *in, int64_t now) {
  // Acknowledgement owns its full interval. New results remain in the stack;
  // repeated acknowledgements can pop messages without restarting playback.
  if (b->mode == 4 && b->preview < 0 && in->preview < 0 &&
      now - b->start < (int64_t)pet_clips[b->clip].reaction * 1000000 / PET_FPS) {
    b->event = in->event;
    b->ack = in->ack;
    return false;
  }
  int mode;
  bool force = false;
  if (in->event != b->event) {
    b->event = in->event;
    mode = in->event_kind == 1 ? 2 : 3;
    force = true;
  } else if (in->ack != b->ack) {
    b->ack = in->ack;
    mode = 4;
    force = true;
  } else if (in->preview >= 0 && in->preview < PET_CLIP_COUNT) {
    if (b->preview == in->preview &&
        now - b->start < (int64_t)pet_clips[b->clip].count * 1000000 / PET_FPS) return false;
    b->preview = in->preview;
    b->clip = in->preview;
    b->start = now;
    return true;
  } else {
    bool reaction = (b->mode == 2 || b->mode == 3 || b->mode == 4) &&
        now - b->start < (int64_t)pet_clips[b->clip].reaction * 1000000 / PET_FPS;
    bool same_result = in->unread && b->mode == (in->event_kind == 1 ? 2 : 3);
    if (reaction && b->preview < 0 && (b->mode == 4 || same_result)) return false;
    // The displayed immutable result owns the avatar until it leaves the
    // message stack. Background work/link changes must not hide its notification.
    mode = in->unread ? (in->event_kind == 1 ? 2 : 3) :
           !in->linked || in->source_bad ? 0 : in->running > 0 ? 1 : 6;
  }
  if (!force && mode == b->mode && b->preview < 0) return false;
  b->preview = -1;
  b->mode = mode;
  static const char *names[] = {"offline", "work", "done", "stop", "ack", "offline", "idle"};
  choose(b, names[mode], now);
  // Revealing an older unread result must not replay its arrival reaction.
  if (!force && (mode == 2 || mode == 3))
    b->start -= (int64_t)pet_clips[b->clip].reaction * 1000000 / PET_FPS;
  return true;
}

void pet_power_init(pet_power_t *p, int64_t now) {
  *p = (pet_power_t){.active_at = now, .brightness = PET_BRIGHT_ACTIVE};
}
bool pet_power_tick(pet_power_t *p, int running, unsigned unread, unsigned event, bool key, int64_t now) {
  unsigned old = p->brightness;
  bool message = unread > 0 || event != p->event;
  if (running > 0 || message || key) p->active_at = now;
  p->event = event;
  int64_t idle = now - p->active_at;
  p->brightness = message ? PET_BRIGHT_ACTIVE : running > 0 ? PET_BRIGHT_RUNNING :
      idle >= PET_SCREEN_IDLE_US ? 0 : idle >= PET_SCREEN_DIM_US ? PET_BRIGHT_IDLE : PET_BRIGHT_ACTIVE;
  p->off = p->brightness == 0;
  return old != p->brightness;
}
