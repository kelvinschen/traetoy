#include "companion_alerts.h"
#include <assert.h>
#include <string.h>
static companion_alerts_t stack;
static uint8_t pixels[COMPANION_TILE_BYTES];
int main(void) {
    companion_nav_t nav={.page=COMPANION_TASKS,.selected=1};
    memset(pixels,0x55,sizeof(pixels));
    assert(companion_alert_push(&stack,10,1,60,"First","devbox",pixels));companion_notify(&nav);
    memset(pixels,0xaa,sizeof(pixels));
    assert(companion_alert_push(&stack,20,2,120,"Second","other-host",pixels));companion_notify(&nav);
    assert(stack.count==2 && companion_alert_top(&stack)->seq==20);
    assert(nav.return_page==COMPANION_TASKS);
    assert(!companion_alert_push(&stack,20,1,999,"Duplicate","devbox",pixels));
    assert(companion_navigate(&nav,COMPANION_OK,2,stack.count));companion_alert_pop(&stack);
    assert(nav.page==COMPANION_COMPLETE && stack.count==1);
    const companion_alert_t *top=companion_alert_top(&stack);
    assert(top->seq==10 && top->elapsed==60 && top->pixels[0]==0x55 && !strcmp(top->title,"First") && !strcmp(top->host,"devbox"));
    assert(companion_navigate(&nav,COMPANION_OK,2,stack.count));companion_alert_pop(&stack);
    assert(nav.page==COMPANION_TASKS && nav.selected==1 && !stack.count);
    assert(!companion_alert_push(&stack,20,1,999,"Already dismissed","devbox",pixels));
    assert(companion_alert_push(&stack,30,1,180,"Third","devbox",pixels));companion_notify(&nav);
    assert(!companion_navigate(&nav,COMPANION_BACK,2,stack.count));
    assert(nav.page==COMPANION_HOME && stack.count==1);
    assert(!companion_navigate(&nav,COMPANION_OK,2,stack.count));
    assert(nav.page==COMPANION_COMPLETE && nav.return_page==COMPANION_HOME);
    assert(!companion_navigate(&nav,COMPANION_BACK,2,stack.count));
    assert(companion_alert_push(&stack,40,1,240,"New while paused","devbox",pixels));companion_notify(&nav);
    assert(nav.page==COMPANION_COMPLETE && companion_alert_top(&stack)->seq==40);
    while(stack.count){assert(companion_navigate(&nav,COMPANION_OK,2,stack.count));companion_alert_pop(&stack);}
    assert(nav.page==COMPANION_HOME);
    assert(!companion_navigate(&nav,COMPANION_OK,2,0));assert(nav.page==COMPANION_TASKS);
    for(unsigned i=100;i<109;i++)assert(companion_alert_push(&stack,i,1,(int)i,"Capacity","devbox",pixels));
    assert(stack.count==8 && stack.dropped==1 && stack.items[0].seq==101);
    for(unsigned i=108;i>=101;i--){assert(companion_alert_top(&stack)->seq==i);companion_alert_pop(&stack);}
    assert(!companion_alert_top(&stack));companion_alert_pop(&stack);
    companion_alert_clock_t clock={0};
    nav=(companion_nav_t){.page=COMPANION_TASKS};
    assert(companion_alert_push(&stack,201,1,0,"Timer A","devbox",pixels));companion_notify(&nav);
    companion_alert_account(&stack,&nav,&clock,0);
    companion_alert_account(&stack,&nav,&clock,15000000);
    assert(stack.items[0].remaining_us==15000000);
    assert(companion_alert_push(&stack,202,1,0,"Timer B","devbox",pixels));companion_notify(&nav);
    companion_alert_account(&stack,&nav,&clock,15000000);
    companion_alert_account(&stack,&nav,&clock,44999999);assert(!companion_alert_expire(&stack,&nav));
    companion_alert_account(&stack,&nav,&clock,45000000);assert(companion_alert_expire(&stack,&nav));
    assert(stack.count==1 && companion_alert_top(&stack)->seq==201 && nav.page==COMPANION_COMPLETE);
    companion_alert_account(&stack,&nav,&clock,45000000);
    companion_alert_account(&stack,&nav,&clock,50000000);
    companion_navigate(&nav,COMPANION_BACK,0,stack.count);companion_alert_account(&stack,&nav,&clock,50000000);
    companion_alert_account(&stack,&nav,&clock,90000000);assert(!companion_alert_expire(&stack,&nav));
    companion_navigate(&nav,COMPANION_OK,0,stack.count);companion_alert_account(&stack,&nav,&clock,90000000);
    assert(stack.items[0].remaining_us==10000000);
    companion_alert_account(&stack,&nav,&clock,100000000);assert(companion_alert_expire(&stack,&nav));
    assert(!stack.count && nav.page==COMPANION_HOME);
    assert(!companion_alert_push(&stack,201,1,0,"Expired duplicate","devbox",pixels));
    return 0;
}
