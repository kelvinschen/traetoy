#pragma once
#include "companion_info.h"
#include "lvgl.h"
void companion_info_draw(lv_event_t *event,const companion_info_t *info,const companion_nav_t *nav,
                         int device_age,int info_age,bool usb,bool ble);
const char *companion_info_title(companion_page_t page);
