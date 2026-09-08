#include "bsp_i2c.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "bsp_audio.h"
#include "bsp_battery.h"
#include "companion_protocol.h"
#include "companion_alerts.h"
#include "companion_tiles.h"
#include "companion_ble.h"
#include "companion_refresh.h"
#include "companion_info_ui.h"
LV_FONT_DECLARE(companion_info_font);
#include "lvgl.h"
LV_FONT_DECLARE(companion_battery_font);
LV_FONT_DECLARE(companion_small_font);
LV_FONT_DECLARE(companion_value_bold_font);
#include "src/misc/cache/instance/lv_image_cache.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

#define PAPER 0xF4F0E7
#define INK 0x242421
#define ORANGE 0xEB631F
#define SAND 0xEDE4D5
#define MUTED 0x777369
extern const lv_image_dsc_t codex_logo;
typedef struct { int type; uint32_t session,counter; union { companion_state_t state; companion_tile_t tile; companion_metadata_t metadata; companion_info_t info; }; } message_t;
_Static_assert(sizeof(companion_info_t)<=sizeof(companion_tile_t),"auxiliary payload must fit existing message storage");
static QueueHandle_t updates, tones, keys;
static TaskHandle_t app_task;
static uint32_t render_count;
static unsigned backlight=75;
static companion_screen_t screen;
static companion_state_t state;
static companion_metadata_t metadata;
static int64_t metadata_at,info_at;
static companion_info_t info={.available=-1,.quota_age=-1};
static lv_obj_t *info_page,*info_heading;
static companion_nav_t info_view_nav;
static int info_device_age,info_snapshot_age;
static bool info_usb,info_ble;
static bool alert_has_title;
static companion_alerts_t alerts;
static companion_alert_clock_t alert_clock;
static uint32_t drawn_alert_seq;
static int alert_elapsed=-1;
static char alert_text[49];
static companion_nav_t nav;
static int64_t last_packet, battery_at;
static bool audio_ok, battery_ok;
static int soc=-1, shown_alert, task_count, quota_index;
static companion_tiles_t title_store;
static uint32_t task_ids[COMPANION_TASKS_MAX];
static uint8_t tile_scratch[COMPANION_TILE_BYTES];
static int link_source, lease_source=-1;
static bool usb_present,ble_present;
static uint32_t lease_session;
static int64_t lease_at;
/* Keep title storage compact; mutually exclusive pages share two alpha canvases.
 * A8 draws directly, avoiding an indexed decoder allocation larger than LVGL's pool. */
static uint8_t display_pixels[2][COMPANION_TILE_W*COMPANION_TILE_H];
static lv_image_dsc_t images[3], completion_project_image;
static int raster_source[3]={-2,-2,-2};
static companion_page_t raster_page=(companion_page_t)-1;
static lv_obj_t *battery, *home, *tasks, *complete, *number, *reset_label, *second_quota;
static lv_obj_t *quota_gauge, *running_label, *usb_icon, *ble_icon, *home_quota, *home_band;
static lv_obj_t *task_total, *rows[2], *row_images[2], *row_fallback[2], *page_label, *empty_label;
static lv_obj_t *complete_project, *complete_host, *complete_title, *complete_fallback, *complete_status, *check;
static int visible_windows;
static lv_obj_t *reset_card_value, *reset_value;
static int visible_reset_cards=-1;
static lv_obj_t *battery_white, *battery_fill, *token_group;
static lv_obj_t *row_duration[2], *complete_duration, *alert_badge;
static lv_obj_t *token_chart, *chart_empty;
static int16_t chart_values[7];
static bool chart_valid;
static unsigned chart_count, daily_count;

/* Direct arc rendering uses the existing LVGL draw buffer and no animation. */
static int gauge_span;
static void draw_quota_gauge(lv_event_t *event) {
    lv_obj_t *obj=lv_event_get_target_obj(event);lv_layer_t *layer=lv_event_get_layer(event);
    lv_area_t area;lv_obj_get_coords(obj,&area);
    lv_draw_arc_dsc_t arc;lv_draw_arc_dsc_init(&arc);
    arc.center=(lv_point_t){area.x1+62,area.y1+52};arc.radius=50;arc.width=7;arc.rounded=1;
    arc.start_angle=135;arc.end_angle=45;arc.color=lv_color_hex(SAND);
    lv_draw_arc(layer,&arc);
    if(gauge_span>0) {
        arc.end_angle=(135+gauge_span)%360;arc.color=lv_color_hex(ORANGE);
        lv_draw_arc(layer,&arc);
    }
}
static void update_meter(int remaining,bool fresh) {
    gauge_span=companion_gauge_span(remaining,fresh);
    lv_obj_invalidate(quota_gauge);
    if(fresh)lv_label_set_text_fmt(number,"%d%%",remaining);
    else lv_label_set_text(number,"--");
}

static void on_key(bsp_btn_t btn,bsp_btn_ev_t ev,void *arg) {
    (void)arg;
    int k=-1;
    if(btn==BSP_BTN_OK && ev==BSP_BTN_LONG)k=COMPANION_BACK;
    else if(ev==BSP_BTN_CLICK)k=btn==BSP_BTN_UP?COMPANION_UP:btn==BSP_BTN_DOWN?COMPANION_DOWN:COMPANION_OK;
    if(ev==BSP_BTN_PRESS)k=COMPANION_SCREEN_PRESS; /* Wake brightness immediately; suppress the wake gesture in the main loop. */
    if(k>=0 && xQueueSend(keys,&k,0)==pdTRUE)xTaskNotifyGive(app_task);
}
static void play_tone(void *arg) {
    (void)arg; int event; int16_t pcm[256];
    for (;;) {
        if (!xQueueReceive(tones,&event,portMAX_DELAY)) continue;
        if (!audio_ok) continue;
        for (int note=0;note<2;note++) {
            float hz=event==2?440.0f:(note?1046.5f:784.0f);
            for (int block=0;block<8;block++) {
                for (int i=0;i<256;i++) {
                    int sample=block*256+i;
                    float envelope=fminf(1.0f,fminf(sample/160.0f,(2048-sample)/320.0f));
                    pcm[i]=(int16_t)(2200.0f*envelope*sinf(6.2831853f*hz*sample/16000.0f));
                }
                if (bsp_audio_write(pcm,sizeof(pcm)) != ESP_OK) break;
            }
            memset(pcm,0,sizeof(pcm));bsp_audio_write(pcm,sizeof(pcm));
            vTaskDelay(pdMS_TO_TICKS(60));
        }
        printf("CDX_AUDIO_DONE\n");
    }
}

static bool parse_message(const char *line,message_t *msg) {
    bool commit=false;msg->type=0;
    if(!strcmp(line,"PASSPORT?|END"))msg->type=7;
    else if(companion_parse(line,&msg->state))msg->type=1;
    else if(companion_parse_tile(line,&msg->tile,&commit))msg->type=commit?3:2;
    else if(companion_parse_metadata(line,&msg->metadata))msg->type=4;
    else if(companion_parse_info(line,&msg->info))msg->type=6;
    return msg->type!=0;
}
static bool enqueue_update(const message_t *msg,TickType_t wait) {
    if(xQueueSend(updates,msg,wait)!=pdTRUE)return false;
    xTaskNotifyGive(app_task);return true;
}
static bool ble_receive(const char *line,uint32_t session,uint32_t counter) {
    message_t msg={.session=session,.counter=counter};
    return parse_message(line,&msg) && enqueue_update(&msg,0);
}
static void respond(const message_t *msg,const char *line) {
    if(msg->session)companion_ble_reply(msg->session,msg->counter,line);
    printf("%s\n",line);
}
static void reader(void *arg) {
    (void)arg; char line[7168];size_t used=0;bool overflow=false;uint8_t buf[128];message_t msg;
    for (;;) {
        int n=usb_serial_jtag_read_bytes(buf,sizeof(buf),pdMS_TO_TICKS(100));
        if(n<=0){vTaskDelay(pdMS_TO_TICKS(10));continue;}
        for(int i=0;i<n;i++) {
            char ch=(char)buf[i];if(ch=='\r')continue;
            if(ch=='\n') {
                line[used]=0;msg.session=msg.counter=0;
                if(!overflow && !strcmp(line,"CDXB|RELEASE|END")){msg.type=5;enqueue_update(&msg,portMAX_DELAY);}
                else if(!overflow && used==78 && !strncmp(line,"CDXB|PAIR|",10) && !strcmp(line+74,"|END")) {
                    char identity[13];line[74]=0;
                    if(companion_ble_provision(line+10,identity))printf("CDX_BLE_PAIRED %s\n",identity);
                    else printf("CDX_ERR provisioning\n");
                }
                else if(!overflow && parse_message(line,&msg))enqueue_update(&msg,portMAX_DELAY);
                else if(used)printf("CDX_ERR invalid_frame\n");
                used=0;overflow=false;
            } else if(used<sizeof(line)-1)line[used++]=ch;else overflow=true;
        }
    }
}
static lv_obj_t *group(lv_obj_t *parent,int x,int y,int w,int h) {
    lv_obj_t *o=lv_obj_create(parent);lv_obj_remove_style_all(o);lv_obj_remove_flag(o,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_pos(o,x,y);lv_obj_set_size(o,w,h);return o;
}
static lv_obj_t *rect(lv_obj_t *parent,int x,int y,int w,int h,uint32_t color) {
    lv_obj_t *o=group(parent,x,y,w,h);lv_obj_set_style_bg_color(o,lv_color_hex(color),0);lv_obj_set_style_bg_opa(o,LV_OPA_COVER,0);return o;
}
static lv_obj_t *label(lv_obj_t *parent,int x,int y,const char *text,const lv_font_t *font,uint32_t color) {
    lv_obj_t *o=lv_label_create(parent);lv_label_set_text(o,text);lv_obj_set_pos(o,x,y);
    lv_obj_set_style_text_font(o,font,0);lv_obj_set_style_text_color(o,lv_color_hex(color),0);return o;
}
static void hide(lv_obj_t *o,bool hidden) {if(hidden)lv_obj_add_flag(o,LV_OBJ_FLAG_HIDDEN);else lv_obj_remove_flag(o,LV_OBJ_FLAG_HIDDEN);}
/* A single draw object; no chart canvas, frame buffer or animation task. */
static void draw_token_chart(lv_event_t *event) {
    lv_obj_t *obj=lv_event_get_target_obj(event);lv_layer_t *layer=lv_event_get_layer(event);
    lv_area_t area;lv_obj_get_coords(obj,&area);
    if(!chart_valid)return;
    for(int row=0;row<7;row++) {
        int i=6-row;
        int value=chart_values[i],y=area.y1+3+18*row;
        lv_draw_label_dsc_t text;lv_draw_label_dsc_init(&text);
        text.font=&companion_small_font;text.color=lv_color_hex(MUTED);
        text.text=metadata.dates[i];
        lv_area_t bounds={area.x1,y,area.x1+45,y+15};lv_draw_label(layer,&text,&bounds);
        if(value>0) {
            int width=(102*value+999)/1000;
            lv_draw_rect_dsc_t bar;lv_draw_rect_dsc_init(&bar);
            bar.bg_color=lv_color_hex(ORANGE);bar.bg_opa=LV_OPA_COVER;
            bounds=(lv_area_t){area.x1+52,y+5,area.x1+51+width,y+10};
            lv_draw_rect(layer,&bar,&bounds);
        }
        text.color=lv_color_hex(INK);text.align=LV_TEXT_ALIGN_RIGHT;text.text=metadata.daily[i];
        bounds=(lv_area_t){area.x1+162,y,area.x1+215,y+15};lv_draw_label(layer,&text,&bounds);
    }
}
static void draw_info_page(lv_event_t *event) {
    companion_info_draw(event,&info,&info_view_nav,info_device_age,info_snapshot_age,info_usb,info_ble);
}

static void make_ui(void) {
    lv_obj_t *screen=rect(NULL,0,0,240,320,PAPER);
    lv_obj_t *logo=lv_image_create(screen);lv_image_set_src(logo,&codex_logo);lv_obj_set_pos(logo,9,5);
    info_heading=label(screen,100,13,"",&companion_info_font,INK);
    alert_badge=label(screen,63,13,"",&lv_font_montserrat_14,ORANGE);
    usb_icon=label(screen,170,14,LV_SYMBOL_USB,&lv_font_montserrat_16,MUTED);
    ble_icon=label(screen,170,14,LV_SYMBOL_BLUETOOTH,&lv_font_montserrat_16,MUTED);
    lv_obj_t *battery_body=rect(screen,196,14,32,16,INK);
    lv_obj_set_style_radius(battery_body,3,0);
    rect(screen,228,18,2,8,INK);
    lv_obj_t *battery_inside=rect(battery_body,1,1,30,14,PAPER);
    lv_obj_set_style_radius(battery_inside,2,0);lv_obj_set_style_clip_corner(battery_inside,true,0);
    battery=label(battery_inside,0,2,"--",&companion_battery_font,INK);
    lv_obj_set_width(battery,30);lv_obj_set_style_text_align(battery,LV_TEXT_ALIGN_CENTER,0);
    battery_fill=rect(battery_inside,0,0,1,14,INK);
    lv_obj_set_style_radius(battery_fill,2,0);lv_obj_set_style_clip_corner(battery_fill,true,0);
    /* Two aligned labels are clipped by the fill, keeping digits readable at every charge. */
    battery_white=label(battery_fill,0,2,"--",&companion_battery_font,PAPER);
    lv_obj_set_width(battery_white,30);lv_obj_set_style_text_align(battery_white,LV_TEXT_ALIGN_CENTER,0);
    info_page=group(screen,0,46,240,274);
    lv_obj_add_event_cb(info_page,draw_info_page,LV_EVENT_DRAW_MAIN,NULL);
    home=group(screen,0,46,240,274);tasks=group(screen,0,46,240,274);complete=group(screen,0,46,240,274);
    home_quota=group(home,0,0,240,100);
    quota_gauge=group(home_quota,12,0,124,100);
    lv_obj_add_event_cb(quota_gauge,draw_quota_gauge,LV_EVENT_DRAW_MAIN,NULL);
    number=label(quota_gauge,0,0,"--",&lv_font_montserrat_28,INK);
    lv_obj_set_width(number,88);lv_obj_set_style_text_align(number,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_align(number,LV_ALIGN_CENTER,0,2);
    reset_label=label(home_quota,132,52,"Resets in",&lv_font_montserrat_14,MUTED);
    lv_obj_set_width(reset_label,96);lv_obj_set_style_text_align(reset_label,LV_TEXT_ALIGN_RIGHT,0);
    reset_value=label(home_quota,132,71,"--",&companion_value_bold_font,INK);
    lv_obj_set_width(reset_value,96);lv_obj_set_style_text_align(reset_value,LV_TEXT_ALIGN_RIGHT,0);
    lv_label_set_long_mode(reset_value,LV_LABEL_LONG_DOT);
    second_quota=label(home_quota,132,85,"",&companion_small_font,MUTED);
    lv_obj_set_width(second_quota,96);lv_label_set_long_mode(second_quota,LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_align(second_quota,LV_TEXT_ALIGN_RIGHT,0);
    lv_obj_t *cards_title=label(home_quota,132,4,"Reset cards",&lv_font_montserrat_14,MUTED);
    lv_obj_set_width(cards_title,96);lv_obj_set_style_text_align(cards_title,LV_TEXT_ALIGN_RIGHT,0);
    reset_card_value=label(home_quota,132,23,"--",&companion_value_bold_font,INK);
    lv_obj_set_width(reset_card_value,96);lv_obj_set_style_text_align(reset_card_value,LV_TEXT_ALIGN_RIGHT,0);
    token_group=group(home,0,101,240,132);
    token_chart=group(token_group,12,0,216,132);
    lv_obj_add_event_cb(token_chart,draw_token_chart,LV_EVENT_DRAW_MAIN,NULL);
    chart_empty=label(token_group,65,62,"No usage data",&lv_font_montserrat_14,MUTED);
    home_band=rect(home,0,236,240,38,SAND);
    lv_obj_t *dot=rect(home_band,13,14,10,10,ORANGE);lv_obj_set_style_radius(dot,LV_RADIUS_CIRCLE,0);
    running_label=label(home_band,33,7,"Connecting",&lv_font_montserrat_20,INK);
    label(tasks,12,9,"Running tasks",&lv_font_montserrat_20,INK);
    task_total=label(tasks,208,12,"0",&lv_font_montserrat_14,INK);
    rect(tasks,12,41,216,1,INK);
    for(int i=0;i<2;i++) {
        rows[i]=rect(tasks,12,47+i*102,216,100,PAPER);
        row_images[i]=lv_image_create(rows[i]);lv_obj_set_pos(row_images[i],10,4);
        lv_obj_set_style_image_recolor(row_images[i],lv_color_hex(INK),0);
        lv_obj_set_style_image_recolor_opa(row_images[i],LV_OPA_COVER,0);
        row_duration[i]=label(rows[i],10,78,"",&lv_font_montserrat_16,MUTED);
        row_fallback[i]=label(rows[i],10,18,"Syncing title...",&lv_font_montserrat_20,MUTED);
    }
    page_label=label(tasks,12,252,"",&lv_font_montserrat_14,MUTED);
    empty_label=label(tasks,12,86,"No running tasks",&lv_font_montserrat_20,INK);
    /* Title-first completion page; metadata shares the existing alert bitmap. */
    lv_obj_t *mark=rect(complete,12,24,20,20,ORANGE);
    lv_obj_set_style_radius(mark,LV_RADIUS_CIRCLE,0);
    check=label(mark,3,2,LV_SYMBOL_OK,&lv_font_montserrat_14,PAPER);
    complete_status=label(complete,42,25,"Task complete",&lv_font_montserrat_14,MUTED);
    complete_title=lv_image_create(complete);lv_obj_set_pos(complete_title,12,66);
    lv_obj_set_style_image_recolor(complete_title,lv_color_hex(INK),0);
    lv_obj_set_style_image_recolor_opa(complete_title,LV_OPA_COVER,0);
    rect(complete,12,177,216,1,0xCFC6B4);
    /* Small open folder, native LVGL lines: no icon bitmap or extra framebuffer. */
    lv_obj_t *folder=lv_obj_create(complete);lv_obj_remove_style_all(folder);
    lv_obj_set_pos(folder,12,199);lv_obj_set_size(folder,18,14);
    static const lv_point_precise_t folder_points[]={{1,13},{1,1},{7,1},{10,4},{17,4},{17,13},{1,13}};
    lv_obj_t *outline=lv_line_create(folder);lv_line_set_points(outline,folder_points,7);
    lv_obj_set_style_line_color(outline,lv_color_hex(ORANGE),0);
    lv_obj_set_style_line_width(outline,2,0);
    complete_project=lv_image_create(complete);lv_obj_set_pos(complete_project,38,198);
    lv_obj_set_style_image_recolor(complete_project,lv_color_hex(INK),0);
    lv_obj_set_style_image_recolor_opa(complete_project,LV_OPA_COVER,0);
    complete_host=label(complete,38,224,"",&lv_font_montserrat_16,MUTED);
    lv_obj_set_width(complete_host,94);lv_label_set_long_mode(complete_host,LV_LABEL_LONG_DOT);
    complete_duration=label(complete,140,220,"",&lv_font_montserrat_20,INK);
    lv_obj_set_width(complete_duration,88);lv_obj_set_style_text_align(complete_duration,LV_TEXT_ALIGN_RIGHT,0);
    complete_fallback=label(complete,12,66,"Task complete",&lv_font_montserrat_20,INK);
    lv_obj_set_width(complete_fallback,216);lv_label_set_long_mode(complete_fallback,LV_LABEL_LONG_WRAP);
    for(int i=0;i<3;i++) {
        images[i]=(lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_A8,
            .w=COMPANION_TILE_W,.h=COMPANION_TILE_H,.stride=COMPANION_TILE_W},
            .data_size=sizeof(display_pixels[0]),.data=display_pixels[i==2?0:i]};
    }
    /* Two descriptors share the immutable alert snapshot; no extra pixel buffers. */
    images[2].header.w=168;images[2].header.h=60;images[2].header.stride=168;
    images[2].data_size=168*60;
    completion_project_image=(lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_A8,
        .w=170,.h=16,.stride=170},.data_size=170*16,.data=display_pixels[0]+168*60};
    lv_image_set_src(complete_project,&completion_project_image);
    lv_screen_load(screen);
}
static void raster_title(lv_obj_t *widget,int display_index,int tile_index) {
    if(raster_source[display_index]!=tile_index) {
        lv_image_cache_drop(&images[display_index]);
        companion_tiles_read(&title_store,tile_index,tile_scratch);
        for(int i=0;i<COMPANION_TILE_W*COMPANION_TILE_H;i++)
            display_pixels[display_index][i]=((tile_scratch[i/4]>>(6-2*(i%4))) & 3u)*85u;
        raster_source[display_index]=tile_index;
        lv_image_set_src(widget,&images[display_index]);lv_obj_invalidate(widget);
    }
}
static void duration_label(lv_obj_t *label,int seconds) {
    char text[24];companion_format_duration(seconds,text,sizeof(text));
    lv_label_set_text(label,text);
}

static void render_alert_snapshot(void) {
    const companion_alert_t *a=companion_alert_top(&alerts);
    uint32_t seq=a?a->seq:0;
    if(seq==drawn_alert_seq)return;
    drawn_alert_seq=seq;alert_elapsed=a?a->elapsed:-1;shown_alert=a?a->kind:0;
    alert_has_title=false;alert_text[0]=0;
    if(!a)return;
    strcpy(alert_text,a->title);
    lv_label_set_text(complete_host,a->host);
    lv_image_cache_drop(&images[2]);lv_image_cache_drop(&completion_project_image);
    for(int i=0;i<COMPANION_TILE_W*COMPANION_TILE_H;i++) {
        uint8_t alpha=((a->pixels[i/4]>>(6-2*(i%4))) & 3u)*85u;
        display_pixels[0][i]=alpha;if(alpha)alert_has_title=true;
    }
    lv_image_set_src(complete_title,&images[2]);
    lv_obj_invalidate(complete_title);lv_obj_invalidate(complete_project);lv_obj_invalidate(complete_host);
}
static void render(void) {
    render_count++;
    /* Task and completion pages are mutually exclusive. Repaint on every ownership change. */
    if(raster_page!=nav.page){raster_page=nav.page;raster_source[0]=raster_source[1]=-2;drawn_alert_seq=UINT32_MAX;}
    render_alert_snapshot();
    hide(alert_badge,alerts.count==0);
    lv_label_set_text_fmt(alert_badge,LV_SYMBOL_OK " %u",alerts.count);
    bool linked=last_packet && esp_timer_get_time()-last_packet<20000000;
    hide(home,nav.page!=COMPANION_HOME);hide(tasks,nav.page!=COMPANION_TASKS);hide(complete,nav.page!=COMPANION_COMPLETE);
    bool auxiliary=nav.page>=COMPANION_CARDS;
    hide(info_page,!auxiliary);hide(info_heading,!auxiliary);
    if(auxiliary){
        int64_t now=esp_timer_get_time();info_view_nav=nav;
        info_device_age=last_packet?(int)((now-last_packet)/1000000):-1;
        info_snapshot_age=info_at?(int)((now-info_at)/1000000):0;
        info_usb=link_source==0;info_ble=link_source==1;
        lv_label_set_text(info_heading,companion_info_title(nav.page));lv_obj_invalidate(info_page);
    }
    char percent[8];if(soc>=0)snprintf(percent,sizeof(percent),"%d",soc>100?100:soc);else strcpy(percent,"--");
    lv_label_set_text(battery,percent);lv_label_set_text(battery_white,percent);
    int battery_width=soc>0?(30*(soc>100?100:soc)+50)/100:0;
    if(soc>0 && battery_width==0)battery_width=1;
    hide(battery_fill,soc<=0);
    lv_obj_set_width(battery_fill,battery_width>0?battery_width:1);
    visible_windows=0;quota_index=-1;
    for(int i=0;i<2;i++)if(state.minutes[i]>0 && state.remaining[i]>=0){visible_windows++;if(quota_index<0)quota_index=i;}
    hide(home_quota,!visible_windows);
    lv_obj_set_y(reset_label,visible_windows==2?46:52);
    lv_obj_set_y(reset_value,visible_windows==2?65:71);
    if(quota_index>=0) {
        int i=quota_index;bool fresh=linked && state.fresh;
        update_meter(state.remaining[i],fresh);
        if(!linked)lv_label_set_text(reset_value,"offline");
        else if(!state.fresh)lv_label_set_text(reset_value,"delayed");
        else lv_label_set_text(reset_value,state.reset[i]);
        hide(second_quota,visible_windows<2);
        if(visible_windows==2)lv_label_set_text_fmt(second_quota,"%d min: %d%% left",state.minutes[1],state.remaining[1]);

    } else {update_meter(0,false);}
    lv_obj_set_y(token_group,visible_windows?101:36);
    lv_obj_set_y(home_band,236);
    bool have_metadata=linked && metadata_at && esp_timer_get_time()-metadata_at<20000000;
    visible_reset_cards=have_metadata && state.fresh?metadata.reset_cards:-1;
    if(visible_reset_cards<0)lv_label_set_text(reset_card_value,"--");
    else if(visible_reset_cards>999)lv_label_set_text(reset_card_value,"999+");
    else lv_label_set_text_fmt(reset_card_value,"%d",visible_reset_cards);
    chart_valid=have_metadata && metadata.weekday<7 && (!strcmp(metadata.asof,"Today") || (strlen(metadata.asof)==5 && metadata.asof[2]=='/'));bool any=false;chart_count=0;daily_count=0;
    for(int i=0;i<7;i++) {
        chart_values[i]=chart_valid?metadata.chart[i]:-1;any|=chart_values[i]>=0;chart_count+=chart_values[i]>=0;
        if(chart_valid && chart_values[i]>=0 && strcmp(metadata.daily[i],"--") && strcmp(metadata.dates[i],"--"))daily_count++;
    }
    hide(chart_empty,any);lv_obj_invalidate(token_chart);
    if(linked)lv_label_set_text_fmt(running_label,"%d task%s running",state.running,state.running==1?"":"s");
    else lv_label_set_text(running_label,"Mac disconnected");
    hide(usb_icon,!linked || link_source!=0 || !usb_present);
    hide(ble_icon,!linked || link_source!=1 || !ble_present);
    lv_obj_set_style_text_color(usb_icon,lv_color_hex(linked && link_source==0?ORANGE:INK),0);
    lv_obj_set_style_text_color(ble_icon,lv_color_hex(linked && link_source==1?ORANGE:INK),0);
    int count=linked?task_count:0;
    if(nav.selected>=count)nav.selected=count>0?count-1:0;
    lv_label_set_text_fmt(task_total,"%d",count);
    hide(empty_label,count>0);lv_label_set_text(empty_label,linked?"No running tasks":"Mac disconnected");
    int first=(nav.selected/2)*2;
    for(int row=0;row<2;row++) {
        int i=first+row;hide(rows[row],i>=count);
        if(i>=count)continue;
        lv_obj_set_style_bg_color(rows[row],lv_color_hex(i==nav.selected?0xF8E3D1:PAPER),0);
        lv_obj_set_style_border_side(rows[row],LV_BORDER_SIDE_LEFT,0);
        lv_obj_set_style_border_width(rows[row],i==nav.selected?3:0,0);
        lv_obj_set_style_border_color(rows[row],lv_color_hex(ORANGE),0);
        hide(row_fallback[row],task_ids[i]!=0);hide(row_images[row],task_ids[i]==0);
        if(nav.page==COMPANION_TASKS)raster_title(row_images[row],row,i);
        int elapsed=-1;
        if(have_metadata)for(int j=0;j<metadata.count;j++)if(metadata.ids[j]==task_ids[i])elapsed=metadata.elapsed[j];
        duration_label(row_duration[row],elapsed);
    }
    if(count>0)lv_label_set_text_fmt(page_label,"%d / %d",nav.selected+1,count);else lv_label_set_text(page_label,"");
    lv_label_set_text(complete_status,shown_alert==2?"Task stopped":"Task complete");
    lv_label_set_text(check,shown_alert==2?LV_SYMBOL_CLOSE:LV_SYMBOL_OK);
    hide(complete_title,!alert_has_title);
    hide(complete_project,!alert_has_title);hide(complete_host,!alert_has_title);
    hide(complete_fallback,alert_has_title);
    lv_label_set_text(complete_fallback,alert_text);
    duration_label(complete_duration,alert_elapsed);
}
static bool commit_tiles(const companion_tile_t *t) {
    uint32_t selected_id=nav.selected<task_count?task_ids[nav.selected]:0;
    if(!companion_tiles_commit(&title_store,t->seq,t->count))return false;
    task_count=t->count;for(int i=0;i<2;i++)raster_source[i]=-2;
    for(int i=0;i<COMPANION_TASKS_MAX;i++)task_ids[i]=i<task_count?title_store.ids[i]:0;
    for(int i=0;i<task_count;i++)if(task_ids[i]==selected_id)nav.selected=i;
    return true;
}
void app_main(void) {
    app_task=xTaskGetCurrentTaskHandle();
    state.remaining[0]=state.remaining[1]=-1;
    updates=xQueueCreate(1,sizeof(message_t));tones=xQueueCreate(4,sizeof(int));keys=xQueueCreate(8,sizeof(int));
    if(!updates || !tones || !keys)return;
    ESP_ERROR_CHECK(bsp_i2c_init());ESP_ERROR_CHECK(bsp_display_init());if(!bsp_lvgl_init())return;
    bsp_display_backlight(75);battery_ok=bsp_battery_init()==ESP_OK;
    audio_ok=bsp_audio_init()==ESP_OK && bsp_audio_set_format(16000,16,1)==ESP_OK;
    if(audio_ok)bsp_audio_set_volume(100);
    ESP_ERROR_CHECK(bsp_button_init(on_key,NULL));
    if(bsp_lvgl_lock(1000)){make_ui();render();bsp_lvgl_unlock();}
    usb_serial_jtag_driver_config_t cfg={.tx_buffer_size=2048,.rx_buffer_size=8192};
    if(!usb_serial_jtag_is_driver_installed())ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));
    usb_serial_jtag_vfs_use_driver();
    if(xTaskCreate(play_tone,"cdx_audio",3072,NULL,2,NULL)!=pdPASS)return;
    esp_err_t ble_status=companion_ble_start(ble_receive);
    if(xTaskCreate(reader,"cdx_usb",14336,NULL,3,NULL)!=pdPASS)return;
    printf("CDX_BLE init=%s heap=%lu\n",esp_err_to_name(ble_status),(unsigned long)esp_get_free_heap_size());
    printf("CDX_READY v5 ble1 lifo8 audio=%d battery=%d volume=100 heap=%lu\n",audio_ok,battery_ok,(unsigned long)esp_get_free_heap_size());
    bool dirty=false,was_linked=false,had_metadata=false;
    int64_t interaction_at=esp_timer_get_time();
    screen.wake_at=interaction_at;
    for (;;) {
        /* Inputs and packets wake immediately; only housekeeping needs a one-second tick. */
        ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(1000));
        message_t msg;bool received=xQueueReceive(updates,&msg,0)==pdTRUE;
        int64_t now=esp_timer_get_time();
        {
            companion_nav_t visible_nav=nav;
            if(screen.off)visible_nav.page=COMPANION_HOME;
            companion_alert_account(&alerts,&visible_nav,&alert_clock,now);
        }
        companion_screen_tick(&screen,now);
        companion_ble_tick();
        if(received && msg.type==7){respond(&msg,"PASSPORT|codex-cream|0.5.0|1|codex-v1,completion-wide-v1,info-v1|END");continue;}
        if(received && msg.type==5){lease_source=-1;companion_tiles_cancel(&title_store);respond(&msg,"CDX_RELEASE_ACK");continue;}
        if(received) {
            int source=msg.session?1:0;
            if(lease_source==0 && source==1 && usb_serial_jtag_is_connected() && now-lease_at<10000000){respond(&msg,"CDX_ERR transport_busy");continue;}
            if(source!=lease_source||msg.session!=lease_session)companion_tiles_cancel(&title_store);
            lease_source=source;lease_session=msg.session;lease_at=now;
        }
        int k;while(xQueueReceive(keys,&k,0)) {
            interaction_at=now;
            if(companion_screen_key(&screen,k,now))continue;
            if(!companion_info_navigate(&nav,(companion_key_t)k,info.count) && companion_navigate(&nav,(companion_key_t)k,task_count,alerts.count))companion_alert_pop(&alerts);
            dirty=true;
            const companion_alert_t *top=companion_alert_top(&alerts);
            printf("CDX_VIEW page=%d selected=%d count=%d unread=%u alert=%lu\n",nav.page,nav.selected,task_count,alerts.count,(unsigned long)(top?top->seq:0));
        }
        char ack[320]={0};
        if(received && msg.type==6) {
            dirty|=nav.page>=COMPANION_CARDS;
            /* The LVGL draw callback reads this cache; serialize replacement. */
            if(!bsp_lvgl_lock(500))continue;
            info=msg.info;info_at=now;
            if(info.count && nav.card_selected>=info.count)nav.card_selected=info.count-1;
            bsp_lvgl_unlock();
            snprintf(ack,sizeof(ack),"CDX_INFO_ACK %lu",(unsigned long)info.seq);
        }
        if(received && msg.type==2){
            bool ok=companion_tiles_stage(&title_store,&msg.tile);
            snprintf(ack,sizeof(ack),"CDX_TILE_%s %lu %d",ok?"ACK":"ERR",(unsigned long)msg.tile.seq,msg.tile.index);
        }
        if(received && msg.type==3){
            bool ok=commit_tiles(&msg.tile);dirty|=ok;
            snprintf(ack,sizeof(ack),"CDX_LIST_%s %lu count=%d",ok?"ACK":"ERR",(unsigned long)msg.tile.seq,task_count);
        }
        if(received && msg.type==4){
            dirty|=!companion_metadata_visible_equal(&metadata,&msg.metadata);
            metadata=msg.metadata;metadata_at=now;
            snprintf(ack,sizeof(ack),"CDX_META_ACK %lu",(unsigned long)msg.metadata.seq);
        }
        if(received && msg.type==1) {
            int source=msg.session?1:0;
            dirty|=!companion_state_visible_equal(&state,&msg.state)||link_source!=source;
            state=msg.state;last_packet=now;link_source=source;
            if(state.alert) {
                companion_tiles_read(&title_store,COMPANION_ALERT_TILE,tile_scratch);
                int elapsed=metadata.seq==state.seq?metadata.alert_seconds:-1;
                if(companion_alert_push(&alerts,state.seq,state.alert,elapsed,state.title,metadata.seq==state.seq?metadata.alert_host:"",tile_scratch)) {
                    companion_notify(&nav);xQueueSend(tones,&state.alert,0);dirty=true;interaction_at=now;companion_screen_alert(&screen,now);
                }
            }
        }
        if(battery_ok && (!battery_at || now-battery_at>=30000000)) {
            int reading=bsp_battery_soc();
            if(reading!=soc){printf("CDX_BATTERY soc=%d\n",reading);dirty=true;}
            soc=reading;battery_at=now;
        }
        if(companion_alert_expire(&alerts,&nav)) {
            dirty=true;printf("CDX_EXPIRE page=%d unread=%u\n",nav.page,alerts.count);
        }
        {
            companion_nav_t visible_nav=nav;
            if(screen.off)visible_nav.page=COMPANION_HOME;
            companion_alert_account(&alerts,&visible_nav,&alert_clock,now);
        }
        bool usb=usb_serial_jtag_is_connected(),ble=companion_ble_connected();
        dirty|=usb_present!=usb || ble_present!=ble;usb_present=usb;ble_present=ble;
        bool linked=last_packet && now-last_packet<20000000;
        bool have_metadata=linked && metadata_at && now-metadata_at<20000000;
        dirty|=linked!=was_linked || have_metadata!=had_metadata;
        was_linked=linked;had_metadata=have_metadata;
        static int64_t info_bucket=-1;
        if(nav.page>=COMPANION_CARDS && now/5000000!=info_bucket){info_bucket=now/5000000;dirty=true;}
        unsigned light=screen.off?0:companion_backlight(now,interaction_at);
        if(light!=backlight){backlight=light;bsp_display_backlight(light);printf("CDX_LIGHT %u\n",light);}
        if(dirty && !screen.off) {
            if(!bsp_lvgl_lock(500))continue;
            render();bsp_lvgl_unlock();dirty=false;
        }
        if(received && msg.type==1)snprintf(ack,sizeof(ack),"CDX_ACK %lu %d %d windows=%d page=%d tasks=%d elapsed=%d unread=%u alert=%lu link=%s heap=%lu min_heap=%lu renders=%lu light=%u usb=%d ble=%d chart=%u daily=%u gauge=%d resets=%d cards=%d sources=%d",(unsigned long)state.seq,state.remaining[0],state.remaining[1],visible_windows,nav.page,task_count,alert_elapsed,alerts.count,(unsigned long)drawn_alert_seq,link_source?"ble":"usb",(unsigned long)esp_get_free_heap_size(),(unsigned long)esp_get_minimum_free_heap_size(),(unsigned long)render_count,backlight,usb_present,ble_present,chart_count,daily_count,gauge_span,visible_reset_cards,info.count,info.source_count);
        if(ack[0])respond(&msg,ack);
    }
}
