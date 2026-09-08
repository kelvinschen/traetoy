#pragma once
#include "companion_protocol.h"
#define COMPANION_CARDS_MAX 6
#define COMPANION_SOURCES_MAX 4
typedef struct {
    char title[40],status[16],granted[17],expires[17],description[160],reset_type[24];
} companion_card_t;
typedef struct {
    uint32_t seq;
    int available,quota_age,known,count,source_count;
    char generation[24],timezone[16],sources[COMPANION_SOURCES_MAX][24];
    bool healthy[COMPANION_SOURCES_MAX];
    companion_card_t cards[COMPANION_CARDS_MAX];
} companion_info_t;
bool companion_parse_info(const char *line,companion_info_t *out);
/* Handles auxiliary pages and root navigation, leaves existing task/alert keys alone. */
bool companion_info_navigate(companion_nav_t *nav,companion_key_t key,int cards);
