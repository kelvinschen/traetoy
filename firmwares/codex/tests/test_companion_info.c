#include "companion_info.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
int main(void) {
    companion_info_t info={0};
    const char *packet="CDXI|12|3|60|0|1|1|UTC+08:00|2|local|1|devbox|0|Full reset|available|2026/08/22 08:00|2026/09/21 08:00|A free reset.|codexRateLimits|END";
    assert(companion_parse_info(packet,&info));
    assert(info.seq==12 && info.available==3 && info.count==1 && info.healthy[0] && !info.healthy[1]);
    assert(!strcmp(info.cards[0].expires,"2026/09/21 08:00"));
    companion_info_t before=info;
    for(size_t n=0;n<strlen(packet);n++) {
        char truncated[512];memcpy(truncated,packet,n);truncated[n]=0;
        assert(!companion_parse_info(truncated,&info));
        assert(!memcmp(&info,&before,sizeof(info)));
    }
    char maximum[2304]="CDXI|20|999|0|0|1|6|UTC+08:00|4|local|1|devbox|1|host2|0|host3|0|";
    for(int i=0;i<6;i++)strcat(maximum,"Full reset|available|2026/08/22 08:00|2026/09/21 08:00|This is the full description of a reset card returned by the service. It is displayed on the scrollable detail page without adding another framebuffer.|codexRateLimits|");
    strcat(maximum,"END");assert(companion_parse_info(maximum,&info) && info.count==6);
    info=before;
    assert(!companion_parse_info("CDXI|1|1|0|0|0|1|UTC|0|END",&info));
    assert(!memcmp(&info,&before,sizeof(info)));
    assert(!companion_parse_info("CDXI|1|1|0|0|1|7|UTC|0|END",&info));
    assert(!companion_parse_info("CDXI|1|1|0|0|1|0|UTC|5|END",&info));
    assert(!companion_parse_info("CDXI|1|-2|0|0|1|0|UTC|0|END",&info));
    assert(!companion_parse_info("CDXI|1|0|0|0|1|0|UTC|0|END|junk",&info));
    assert(companion_parse_info("CDXI|1|-1|-1|0|0|0|UTC|0|END",&info));
    companion_nav_t nav={0};
    assert(companion_info_navigate(&nav,COMPANION_DOWN,3) && nav.page==COMPANION_CARDS);
    assert(companion_info_navigate(&nav,COMPANION_DOWN,3) && nav.page==COMPANION_CONNECTION);
    assert(companion_info_navigate(&nav,COMPANION_DOWN,3) && nav.page==COMPANION_HOME);
    assert(!companion_info_navigate(&nav,COMPANION_OK,3));
    companion_info_navigate(&nav,COMPANION_DOWN,3);companion_info_navigate(&nav,COMPANION_OK,3);
    assert(nav.page==COMPANION_CARD_LIST);
    companion_info_navigate(&nav,COMPANION_DOWN,3);assert(nav.card_selected==1);
    companion_info_navigate(&nav,COMPANION_OK,3);assert(nav.page==COMPANION_CARD_DETAIL);
    companion_notify(&nav);assert(nav.return_page==COMPANION_CARD_DETAIL);
    companion_navigate(&nav,COMPANION_OK,0,1);assert(nav.page==COMPANION_CARD_DETAIL);
    companion_info_navigate(&nav,COMPANION_DOWN,3);assert(nav.info_scroll==1);
    assert(!companion_info_navigate(&nav,COMPANION_BACK,3));
    companion_navigate(&nav,COMPANION_BACK,0,0);assert(nav.page==COMPANION_HOME);
    puts("companion info: PASS");
}
