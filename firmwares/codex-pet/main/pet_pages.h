#pragma once
#include "companion_alerts.h"
#include "companion_info.h"
#include <stddef.h>

enum { PET_HOME, PET_QUOTA, PET_USAGE, PET_SYSTEM, PET_GALLERY, PET_TASKS, PET_ALERT };
typedef struct { uint32_t seq; int64_t at, remaining; bool visible; } pet_message_clock_t;
/* Only home consumes time. A newly exposed snapshot gets a fresh 15 seconds. */
bool pet_messages_tick(companion_alerts_t *alerts, pet_message_clock_t *clock,
                       int page, int64_t now);
/* UP/DOWN cycle the four main pages; OK elsewhere only returns home. */
int pet_page_key(int page, int key);
/* Protocol compact values become M below one billion, B with one decimal above. */
void pet_token_label(const char *value, char *out, size_t size);
int pet_primary_window(const companion_state_t *state);
