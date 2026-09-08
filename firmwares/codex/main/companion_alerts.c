#include "companion_alerts.h"
#include <string.h>

bool companion_alert_push(companion_alerts_t *s, uint32_t seq, int kind, int elapsed,
                          const char *title, const char *host, const uint8_t *pixels) {
    if(!s || !seq || !title || !host || !pixels || (kind!=1 && kind!=2))return false;
    for(unsigned i=0;i<COMPANION_ALERT_SEEN;i++)if(s->seen[i]==seq)return false;
    for(unsigned i=0;i<s->count;i++)if(s->items[i].seq==seq)return false;
    s->seen[s->seen_next++ % COMPANION_ALERT_SEEN]=seq;
    if(s->count==COMPANION_ALERT_CAPACITY) {
        memmove(s->items,s->items+1,sizeof(s->items[0])*(COMPANION_ALERT_CAPACITY-1));
        s->count--;s->dropped++;
    }
    companion_alert_t *a=&s->items[s->count++];
    a->seq=seq;a->remaining_us=30000000;a->kind=kind;a->elapsed=elapsed;
    strncpy(a->title,title,sizeof(a->title)-1);a->title[sizeof(a->title)-1]=0;
    strncpy(a->host,host,sizeof(a->host)-1);a->host[sizeof(a->host)-1]=0;
    memcpy(a->pixels,pixels,COMPANION_TILE_BYTES);
    return true;
}
const companion_alert_t *companion_alert_top(const companion_alerts_t *s) {
    return s && s->count?&s->items[s->count-1]:NULL;
}
void companion_alert_pop(companion_alerts_t *s) {
    if(s && s->count)s->count--;
}

void companion_alert_account(companion_alerts_t *s,const companion_nav_t *nav,
                             companion_alert_clock_t *clock,int64_t now_us) {
    companion_alert_t *a=nav->page==COMPANION_COMPLETE && s->count?&s->items[s->count-1]:NULL;
    if(a && clock->seq==a->seq && now_us>=clock->at) {
        uint64_t elapsed=(uint64_t)(now_us-clock->at);
        a->remaining_us=elapsed>=a->remaining_us?0:a->remaining_us-(uint32_t)elapsed;
    }
    clock->seq=a?a->seq:0;clock->at=now_us;
}
bool companion_alert_expire(companion_alerts_t *s,companion_nav_t *nav) {
    bool expired=false;
    while(nav->page==COMPANION_COMPLETE && s->count && !s->items[s->count-1].remaining_us) {
        if(s->count==1)nav->page=nav->return_page;
        companion_alert_pop(s);expired=true;
    }
    return expired;
}
