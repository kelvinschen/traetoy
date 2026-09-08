#include "companion_ble_wire.h"
#include <string.h>
static uint16_t le16(const uint8_t *p){return (uint16_t)(p[0]|p[1]<<8);}
int companion_ble_fragment(companion_ble_frame_t *s,const uint8_t *p,size_t n) {
    if(!s||!p||n<=6)return -1;
    uint16_t id=le16(p),total=le16(p+2),offset=le16(p+4);size_t payload=n-6;
    if(!id||total<21||total>COMPANION_BLE_FRAME_MAX||offset>total||payload>(size_t)(total-offset))return -1;
    if(offset==0){s->id=id;s->total=total;s->used=0;}
    if(id!=s->id||total!=s->total||offset!=s->used)return -1;
    memcpy(s->bytes+offset,p+6,payload);s->used+=payload;
    return s->used==s->total?1:0;
}

int companion_ble_unpack(const uint8_t *p,size_t n,char *out,size_t capacity) {
    if(!p||!n||!out||!capacity)return -1;
    size_t size=0;
    if(p[0]==0){if(n<=1||n-1>=capacity)return -1;size=n-1;memcpy(out,p+1,size);}
    else if(p[0]==1){
        if(n<5||(n-3)%2)return -1;
        size=(size_t)p[1]<<8|p[2];if(!size||size>=capacity)return -1;
        size_t used=0;for(size_t i=3;i<n;i+=2){if(!p[i]||p[i]>size-used)return -1;memset(out+used,p[i+1],p[i]);used+=p[i];}
        if(used!=size)return -1;
    }else return -1;
    if(memchr(out,0,size))return -1;
    out[size]=0;return (int)size;
}
