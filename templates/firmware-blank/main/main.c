/* Independent starting point: no Codex pages, quota, task collection or alerts. */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/usb_serial_jtag.h"
#include "bsp_display.h"
#include "companion_ble.h"
#include "lvgl.h"
#include "firmware_identity.h"

static bool respond(const char *line,uint32_t session,uint32_t counter) {
    const char *answer=!strcmp(line,"PASSPORT?|END")
        ? "PASSPORT|" FIRMWARE_ID "|0.1.0|1|passport-core-v1|END"
        : !strcmp(line,"CDXB|RELEASE|END") ? "CDX_RELEASE_ACK" : "PASSPORT_ERR unsupported";
    if(session)companion_ble_reply(session,counter,answer);
    else printf("%s\n",answer);
    return true;
}
typedef struct { char line[512]; uint32_t session,counter; } request_t;
static QueueHandle_t requests;
static bool receive(const char *line,uint32_t session,uint32_t counter) {
    if(strlen(line)>=sizeof(((request_t *)0)->line))return false;
    request_t request={.session=session,.counter=counter};
    strcpy(request.line,line);
    return xQueueSend(requests,&request,0)==pdTRUE;
}
void app_main(void) {
    ESP_ERROR_CHECK(bsp_display_init());
    if(!bsp_lvgl_init())return;
    if(bsp_lvgl_lock(1000)) {
        lv_obj_t *label=lv_label_create(lv_screen_active());
        lv_label_set_text(label,FIRMWARE_ID "\nYour firmware starts here");
        lv_obj_center(label);bsp_lvgl_unlock();
    }
    bsp_display_backlight(35);
    usb_serial_jtag_driver_config_t config={.tx_buffer_size=1024,.rx_buffer_size=1024};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    requests=xQueueCreate(4,sizeof(request_t));
    configASSERT(requests);
    ESP_ERROR_CHECK(companion_ble_start(receive));
    char line[512];size_t used=0;bool overflow=false;
    for(;;) {
        unsigned char bytes[64];int n=usb_serial_jtag_read_bytes(bytes,sizeof(bytes),pdMS_TO_TICKS(100));
        for(int i=0;i<n;i++) {
            char c=(char)bytes[i];if(c=='\r')continue;
            if(c=='\n'){line[used]=0;if(!overflow)respond(line,0,0);used=0;overflow=false;}
            else if(used<sizeof(line)-1)line[used++]=c;else overflow=true;
        }
        request_t request;
        while(xQueueReceive(requests,&request,0)==pdTRUE)
            respond(request.line,request.session,request.counter);
        companion_ble_tick();
    }
}
