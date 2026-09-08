#pragma once
#include "companion_protocol.h"
#include <stddef.h>
typedef struct companion_blob companion_blob_t;
typedef struct {
    companion_blob_t *front[COMPANION_TASKS_MAX+1], *pending[COMPANION_TASKS_MAX+1];
    uint32_t ids[COMPANION_TASKS_MAX+1], pending_ids[COMPANION_TASKS_MAX+1], seq, mask;
    int count;
} companion_tiles_t;
/* Single UI-task owner. A failed stage/commit leaves the visible bank intact. */
bool companion_tiles_stage(companion_tiles_t *s,const companion_tile_t *tile);
bool companion_tiles_commit(companion_tiles_t *s,uint32_t seq,int count);
void companion_tiles_read(const companion_tiles_t *s,int index,uint8_t out[COMPANION_TILE_BYTES]);
void companion_tiles_cancel(companion_tiles_t *s);
void companion_tiles_free(companion_tiles_t *s);
size_t companion_tiles_bytes(const companion_tiles_t *s);
