#include "companion_refresh.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    companion_state_t a={0},b={0};a.seq=1;b.seq=99;
    assert(companion_state_visible_equal(&a,&b));
    b.remaining[0]=1;assert(!companion_state_visible_equal(&a,&b));b=a;
    b.fresh=1;assert(!companion_state_visible_equal(&a,&b));
    companion_metadata_t m={.count=1,.ids={3},.elapsed={1},.alert_seconds=-1},n=m;
    n.seq=100;n.elapsed[0]=59;assert(companion_metadata_visible_equal(&m,&n));
    n.elapsed[0]=60;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.elapsed[0]=-1;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.ids[0]=4;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.alert_seconds=0;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.chart[3]=1000;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.weekday=1;assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.ceiling[0]='1';assert(!companion_metadata_visible_equal(&m,&n));
    n=m;strcpy(n.daily[2],"1M");assert(!companion_metadata_visible_equal(&m,&n));
    n=m;strcpy(n.dates[2],"01");assert(!companion_metadata_visible_equal(&m,&n));
    n=m;n.reset_cards=3;assert(!companion_metadata_visible_equal(&m,&n));
    assert(companion_chart_y(-1,63)==-1);
    assert(companion_chart_y(0,63)==62);
    assert(companion_chart_y(1000,63)==0);
    assert(companion_chart_y(500,63)==31);
    assert(companion_chart_y(1001,63)==-1);
    assert(companion_chart_y(0,0)==-1);
    assert(companion_gauge_span(0,true)==0);
    assert(companion_gauge_span(1,true)==3);
    assert(companion_gauge_span(50,true)==135);
    assert(companion_gauge_span(96,true)==259);
    assert(companion_gauge_span(100,true)==270);
    assert(companion_gauge_span(96,false)==0);
    assert(companion_gauge_span(-1,true)==0);
    assert(companion_gauge_span(101,true)==0);
    assert(companion_backlight(59999999,0)==75);
    assert(companion_backlight(60000000,0)==35);
    assert(companion_backlight(60000000,60000000)==75);
    companion_screen_t screen={0};
    companion_screen_tick(&screen,3599999999LL);
    assert(!screen.off);
    /* Active navigation and ordinary ticks do not extend the notification timer. */
    assert(companion_screen_key(&screen,COMPANION_SCREEN_PRESS,3599999999LL));
    assert(!companion_screen_key(&screen,COMPANION_OK,3599999999LL));
    companion_screen_tick(&screen,3600000000LL);
    assert(screen.off);
    assert(companion_screen_key(&screen,COMPANION_SCREEN_PRESS,3600000001LL));
    assert(!screen.off && screen.wake_at==3600000001LL);
    assert(companion_screen_key(&screen,COMPANION_OK,3600000002LL));
    assert(companion_screen_key(&screen,COMPANION_SCREEN_PRESS,3600000003LL));
    assert(!companion_screen_key(&screen,COMPANION_OK,3600000004LL));
    companion_screen_tick(&screen,7200000000LL);assert(!screen.off);
    companion_screen_tick(&screen,7200000001LL);assert(screen.off);
    companion_screen_alert(&screen,7300000000LL);assert(!screen.off);
    companion_screen_tick(&screen,10899999999LL);assert(!screen.off);
    companion_screen_tick(&screen,10900000000LL);assert(screen.off);
    puts("companion refresh: PASS");
}
