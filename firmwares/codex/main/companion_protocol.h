#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    uint32_t seq;
    int remaining[2], minutes[2], running, completed, alert, fresh;
    char title[49];
    char reset[2][17];
} companion_state_t;
bool companion_parse(const char *line, companion_state_t *out);

#define COMPANION_TASKS_MAX 16
#define COMPANION_TILE_W 200
#define COMPANION_TILE_H 64
#define COMPANION_TILE_BYTES (COMPANION_TILE_W * COMPANION_TILE_H / 4)
#define COMPANION_ALERT_TILE COMPANION_TASKS_MAX
typedef struct {
    uint32_t seq, id;
    int index, count;
    uint8_t pixels[COMPANION_TILE_BYTES];
} companion_tile_t;
/* Parse CDXP project/title four-level grayscale tile or CDXL transaction commit. No partial updates on failure. */
bool companion_parse_tile(const char *line, companion_tile_t *out, bool *commit);
typedef enum { COMPANION_HOME, COMPANION_TASKS, COMPANION_COMPLETE, COMPANION_CARDS, COMPANION_CONNECTION, COMPANION_CARD_LIST, COMPANION_CARD_DETAIL } companion_page_t;
typedef enum { COMPANION_UP, COMPANION_DOWN, COMPANION_OK, COMPANION_BACK } companion_key_t;
typedef struct { companion_page_t page, return_page; int selected, card_selected, info_scroll; } companion_nav_t;
/* True means confirm/pop the current alert. pending is the count before confirmation. */
bool companion_navigate(companion_nav_t *nav, companion_key_t key, int count, unsigned pending);
void companion_notify(companion_nav_t *nav);

typedef struct {
    uint32_t seq, ids[COMPANION_TASKS_MAX];
    int count, elapsed[COMPANION_TASKS_MAX], alert_seconds;
    char alert_host[49]; /* ASCII host, owned by each completion snapshot */
    int reset_cards; /* -1 unavailable; zero is a known empty balance */
    char day[16], week[16], asof[16], ceiling[16];
    char daily[7][5], dates[7][6]; /* compact values and MM/DD labels (legacy DD accepted) */
    int16_t chart[7]; /* -1 unknown, 0..1000 normalized against chart upper bound */
    uint8_t weekday; /* first point: Monday=0 */
} companion_metadata_t;
bool companion_parse_metadata(const char *line, companion_metadata_t *out);

void companion_format_duration(int seconds, char *out, unsigned size);
