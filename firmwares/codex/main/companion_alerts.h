#pragma once
#include "companion_protocol.h"

#define COMPANION_ALERT_CAPACITY 8
#define COMPANION_ALERT_SEEN 32

typedef struct {
    uint32_t seq,remaining_us;
    int kind, elapsed;
    char title[49], host[49];
    uint8_t pixels[COMPANION_TILE_BYTES];
} companion_alert_t;
typedef struct {
    companion_alert_t items[COMPANION_ALERT_CAPACITY];
    unsigned count, seen_next, dropped;
    uint32_t seen[COMPANION_ALERT_SEEN];
} companion_alerts_t;
/* Packed snapshots are owned by the stack. Duplicates include recently dismissed alerts. */
bool companion_alert_push(companion_alerts_t *s, uint32_t seq, int kind, int elapsed,
                          const char *title, const char *host, const uint8_t *pixels);
const companion_alert_t *companion_alert_top(const companion_alerts_t *s);
void companion_alert_pop(companion_alerts_t *s);

/* Each alert owns 30 seconds of visible time; hidden/preempted alerts pause. */
typedef struct { uint32_t seq; int64_t at; } companion_alert_clock_t;
void companion_alert_account(companion_alerts_t *s,const companion_nav_t *nav,
                             companion_alert_clock_t *clock,int64_t now_us);
bool companion_alert_expire(companion_alerts_t *s,companion_nav_t *nav);
