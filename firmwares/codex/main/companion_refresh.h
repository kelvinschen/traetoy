#pragma once
#include "companion_protocol.h"
/* Compare displayed values; transport sequence and sub-minute timing are not pixels. */
bool companion_state_visible_equal(const companion_state_t *a,const companion_state_t *b);
bool companion_metadata_visible_equal(const companion_metadata_t *a,const companion_metadata_t *b);
/* No animation: keep a readable idle screen and wake on input or a new alert. */
unsigned companion_backlight(int64_t now_us,int64_t interaction_us);

/* Zero-baseline normalized chart coordinate; -1 means missing/out of range. */
int companion_chart_y(int value,int height);


/* 270-degree open ring, empty when quota is stale or unavailable. */
int companion_gauge_span(int remaining,bool fresh);

/* One hour without a new alert (or manual wake) turns off the screen. */
#define COMPANION_SCREEN_PRESS 4
typedef struct { bool off, suppress_gesture; int64_t wake_at; } companion_screen_t;
bool companion_screen_key(companion_screen_t *screen,int key,int64_t now_us);
void companion_screen_tick(companion_screen_t *screen,int64_t now_us);
void companion_screen_alert(companion_screen_t *screen,int64_t now_us);
