#include "companion_info_ui.h"
#include <stdio.h>
#include <string.h>
LV_FONT_DECLARE(companion_info_font);
LV_FONT_DECLARE(companion_value_bold_font);
#define INK 0x242421
#define MUTED 0x777369
#define ORANGE 0xEB631F
#define SAND 0xEDE4D5
static void text(lv_layer_t *layer,const lv_area_t *origin,int x,int y,int w,int h,
                 const char *s,const lv_font_t *font,unsigned color,bool right) {
    lv_draw_label_dsc_t d;lv_draw_label_dsc_init(&d);
    d.text=s;d.text_local=1;d.font=font;d.color=lv_color_hex(color);d.align=right?LV_TEXT_ALIGN_RIGHT:LV_TEXT_ALIGN_LEFT;
    lv_area_t a={origin->x1+x,origin->y1+y,origin->x1+x+w-1,origin->y1+y+h-1};
    lv_draw_label(layer,&d,&a);
}
static void box(lv_layer_t *layer,const lv_area_t *origin,int x,int y,int w,int h,unsigned color,int border) {
    lv_draw_rect_dsc_t d;lv_draw_rect_dsc_init(&d);
    d.bg_color=lv_color_hex(color);d.bg_opa=border?LV_OPA_TRANSP:LV_OPA_COVER;
    d.border_color=lv_color_hex(color);d.border_width=border;
    lv_area_t a={origin->x1+x,origin->y1+y,origin->x1+x+w-1,origin->y1+y+h-1};lv_draw_rect(layer,&d,&a);
}
const char *companion_info_title(companion_page_t page) {
    return page==COMPANION_CONNECTION?"连接":"重置卡";
}
void companion_info_draw(lv_event_t *event,const companion_info_t *info,const companion_nav_t *nav,
                         int device_age,int info_age,bool usb,bool ble) {
    lv_layer_t *layer=lv_event_get_layer(event);lv_area_t origin;
    lv_obj_get_coords(lv_event_get_target_obj(event),&origin);
    const lv_font_t *cn=&companion_info_font,*normal=&lv_font_montserrat_16,*bold=&companion_value_bold_font;
    bool linked=device_age>=0 && device_age<20;
    int64_t quota_age=info->quota_age<0?-1:(int64_t)info->quota_age+info_age;
    bool fresh=linked && quota_age>=0 && quota_age<180;
    char value[64];
    if(nav->page==COMPANION_CONNECTION) {
        text(layer,&origin,12,20,216,28,linked?(usb?"USB 已连接":ble?"BLE 已连接":"已连接"):"设备已断开",cn,linked?INK:MUTED,false);
        text(layer,&origin,12,67,120,20,"设备同步",cn,MUTED,false);
        if(device_age<0)strcpy(value,"--");else if(device_age<10)strcpy(value,"刚刚");else snprintf(value,sizeof(value),"%d 秒前",device_age);
        text(layer,&origin,125,67,103,20,value,cn,INK,true);
        box(layer,&origin,12,101,216,1,0xCFC6B4,0);
        for(int i=0;i<info->source_count;i++) {
            int y=120+i*27;bool ok=linked && info->healthy[i];
            box(layer,&origin,12,y+5,7,7,ok?ORANGE:MUTED,0);
            text(layer,&origin,28,y,139,21,!strcmp(info->sources[i],"local")?"本机":info->sources[i],cn,INK,false);
            text(layer,&origin,168,y,60,21,ok?"正常":linked?"断开":"缓存",cn,ok?INK:MUTED,true);
        }
        if(!info->source_count)text(layer,&origin,12,120,216,24,"数据源暂无信息",cn,MUTED,false);
        text(layer,&origin,12,238,112,22,"账号同步",cn,MUTED,false);
        if(quota_age<0)strcpy(value,"--");else if(quota_age<60)strcpy(value,"刚刚");else snprintf(value,sizeof(value),"%lld 分钟前",(long long)(quota_age/60));
        text(layer,&origin,124,238,104,22,value,cn,fresh?INK:MUTED,true);
        return;
    }
    if(nav->page==COMPANION_CARD_DETAIL && info->count && fresh) {
        int index=nav->card_selected<info->count?nav->card_selected:info->count-1;
        const companion_card_t *c=&info->cards[index];int offset=nav->info_scroll*48;
        text(layer,&origin,12,12-offset,216,42,c->title,normal,INK,false);
        text(layer,&origin,12,60-offset,216,22,c->status,normal,ORANGE,false);
        text(layer,&origin,12,94-offset,216,22,"过期时间",cn,MUTED,false);
        text(layer,&origin,12,118-offset,216,22,c->expires,bold,INK,false);
        text(layer,&origin,12,150-offset,216,22,"发放时间",cn,MUTED,false);
        text(layer,&origin,12,174-offset,216,22,c->granted,normal,INK,false);
        text(layer,&origin,12,208-offset,216,20,info->timezone,&lv_font_montserrat_14,MUTED,false);
        text(layer,&origin,12,238-offset,216,20,c->reset_type,&lv_font_montserrat_14,MUTED,false);
        text(layer,&origin,12,270-offset,216,160,c->description,&lv_font_montserrat_14,INK,false);
        return;
    }
    if(fresh && info->available>=0){if(info->available>999)strcpy(value,"999+");else snprintf(value,sizeof(value),"%d",info->available);}else strcpy(value,"--");
    text(layer,&origin,12,16,100,40,value,&lv_font_montserrat_28,INK,false);
    text(layer,&origin,90,25,138,24,"张可用",cn,MUTED,false);
    box(layer,&origin,0,77,240,64,SAND,0);
    text(layer,&origin,12,86,216,22,"最近到期",cn,MUTED,false);
    const char *nearest="--";
    if(fresh && info->count && strcmp(info->cards[0].expires,"--"))nearest=info->cards[0].expires+5;
    text(layer,&origin,12,111,216,22,nearest,bold,INK,false);
    if(!fresh || !info->known || !info->count) {
        text(layer,&origin,12,174,216,42,!fresh?"正在同步":!info->known?"暂无详情":"暂无可用卡",cn,MUTED,false);
        return;
    }
    int first=nav->page==COMPANION_CARD_LIST?(nav->card_selected/3)*3:0;
    for(int row=0;row<3 && first+row<info->count;row++) {
        int i=first+row,y=152+row*33;
        if(nav->page==COMPANION_CARD_LIST && i==nav->card_selected) {
            box(layer,&origin,0,y-3,240,31,SAND,0);box(layer,&origin,0,y-3,3,31,ORANGE,0);
        }
        box(layer,&origin,12,y+4,16,12,ORANGE,1);box(layer,&origin,12,y+7,16,1,ORANGE,0);
        text(layer,&origin,37,y,118,24,info->cards[i].title,&lv_font_montserrat_14,INK,false);
        const char *date=info->cards[i].expires;
        if(strlen(date)>=10)snprintf(value,sizeof(value),"%.5s",date+5);else strcpy(value,"--");
        text(layer,&origin,164,y,64,24,value,normal,INK,true);
    }
    if(info->available>info->count)snprintf(value,sizeof(value),"%d / %d",info->count,info->available);
    else if(nav->page==COMPANION_CARD_LIST)snprintf(value,sizeof(value),"%d / %d",nav->card_selected+1,info->count);
    else value[0]=0;
    text(layer,&origin,160,253,68,20,value,&lv_font_montserrat_14,MUTED,true);
}
