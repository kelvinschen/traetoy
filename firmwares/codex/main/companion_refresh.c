#include "companion_refresh.h"
#include <string.h>
static int minute(int seconds){return seconds<0?-1:seconds/60;}
bool companion_state_visible_equal(const companion_state_t *a,const companion_state_t *b) {
    return a->remaining[0]==b->remaining[0] && a->remaining[1]==b->remaining[1] &&
        a->minutes[0]==b->minutes[0] && a->minutes[1]==b->minutes[1] &&
        a->running==b->running && a->completed==b->completed && a->alert==b->alert && a->fresh==b->fresh &&
        !strcmp(a->title,b->title) && !strcmp(a->reset[0],b->reset[0]) && !strcmp(a->reset[1],b->reset[1]);
}
bool companion_metadata_visible_equal(const companion_metadata_t *a,const companion_metadata_t *b) {
    if(a->reset_cards!=b->reset_cards || a->count!=b->count || minute(a->alert_seconds)!=minute(b->alert_seconds) ||
        strcmp(a->day,b->day) || strcmp(a->week,b->week) || strcmp(a->asof,b->asof) ||
        memcmp(a->daily,b->daily,sizeof(a->daily)) || memcmp(a->dates,b->dates,sizeof(a->dates)) ||
        strcmp(a->ceiling,b->ceiling) || a->weekday!=b->weekday || memcmp(a->chart,b->chart,sizeof(a->chart)))return false;
    for(int i=0;i<a->count;i++)if(a->ids[i]!=b->ids[i] || minute(a->elapsed[i])!=minute(b->elapsed[i]))return false;
    return true;
}
unsigned companion_backlight(int64_t now_us,int64_t interaction_us) {
    return now_us-interaction_us>=60000000?35:75;
}

int companion_chart_y(int value,int height) {
    if(value<0 || value>1000 || height<1 || height>320)return -1;
    return (height-1)*(1000-value)/1000;
}


int companion_gauge_span(int remaining,bool fresh) {
    if(!fresh || remaining<0 || remaining>100)return 0;
    return (270*remaining+50)/100;
}

void companion_screen_tick(companion_screen_t *screen,int64_t now_us) {
    if(now_us-screen->wake_at>=3600000000LL)screen->off=true;
}
void companion_screen_alert(companion_screen_t *screen,int64_t now_us) {
    screen->off=false;screen->wake_at=now_us;
}
bool companion_screen_key(companion_screen_t *screen,int key,int64_t now_us) {
    if(key==COMPANION_SCREEN_PRESS) {
        screen->suppress_gesture=screen->off;
        if(screen->off)companion_screen_alert(screen,now_us);
        return true;
    }
    if(screen->suppress_gesture) {
        screen->suppress_gesture=false;
        return true;
    }
    return screen->off;
}
