#pragma once
#include <stdint.h>
#define PET_SOUND_RATE 16000u
typedef struct { const int16_t *samples; unsigned count; } pet_sound_t;
/* Wire kinds: 1 success, 2 stopped/failed, 3 waiting for user. Unknown is silent. */
const pet_sound_t *pet_sound_get(int kind);
