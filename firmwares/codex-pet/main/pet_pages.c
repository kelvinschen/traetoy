#include "pet_pages.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool pet_messages_tick(companion_alerts_t *alerts, pet_message_clock_t *c,
                       int page, int64_t now) {
  const companion_alert_t *top = companion_alert_top(alerts);
  uint32_t seq = top ? top->seq : 0;
  bool expired = false;
  if (seq != c->seq) c->remaining = 15000000;
  else if (seq && c->visible && now >= c->at) {
    int64_t elapsed = now - c->at;
    c->remaining = elapsed >= c->remaining ? 0 : c->remaining - elapsed;
    if (!c->remaining) {
      companion_alert_pop(alerts);
      top = companion_alert_top(alerts);
      seq = top ? top->seq : 0;
      c->remaining = 15000000;
      expired = true;
    }
  }
  c->seq = seq;
  c->at = now;
  c->visible = page == PET_HOME && seq;
  return expired;
}
int pet_page_key(int page, int key) {
  if (key == 2 || key == 3) return PET_HOME;
  if (page < PET_HOME || page > PET_SYSTEM) page = PET_HOME;
  return (page + (key == 0 ? 3 : 1)) % 4;
}
int pet_primary_window(const companion_state_t *s) {
  int k = -1;
  for (int i = 0; i < 2; i++)
    if (s->minutes[i] > 0 && (k < 0 || s->minutes[i] > s->minutes[k])) k = i;
  return k;
}
void pet_token_label(const char *value, char *out, size_t size) {
  char *end;
  double n = strtod(value, &end);
  if (end == value || n < 0 || !isfinite(n)) { snprintf(out,size,"--"); return; }
  const char *units = "KMBTPE", *unit = *end ? strchr(units,*end) : NULL;
  if (*end && (!unit || end[1])) { snprintf(out,size,"--"); return; }
  if (unit) for (int i = 0; i <= unit - units; i++) n *= 1000;
  if (n >= 1e9) snprintf(out,size,"%.1fB",n/1e9);
  else if (n == 0) snprintf(out,size,"0M");
  else if (n < 100000) snprintf(out,size,"<0.1M");
  else if (n < 1e7) snprintf(out,size,"%.1fM",n/1e6);
  else snprintf(out,size,"%.0fM",fmin(999, n/1e6));
}
