#include "companion_ble_wire.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void){
    companion_ble_frame_t s={0};uint8_t p[20]={1,0,28,0,0,0};memset(p+6,7,14);
    assert(companion_ble_fragment(&s,p,20)==0);p[4]=15;assert(companion_ble_fragment(&s,p,20)==-1);
    p[4]=14;assert(companion_ble_fragment(&s,p,20)==1);for(int i=0;i<28;i++)assert(s.bytes[i]==7);
    assert(companion_ble_fragment(&s,p,20)==-1);p[4]=0;p[2]=0xff;p[3]=0xff;assert(companion_ble_fragment(&s,p,20)==-1);
    p[2]=28;p[3]=0;p[0]=2;assert(companion_ble_fragment(&s,p,20)==0);p[0]=1;p[4]=14;assert(companion_ble_fragment(&s,p,20)==-1);
    char out[8];uint8_t rle[]={1,0,5,5,'x'};assert(companion_ble_unpack(rle,sizeof(rle),out,sizeof(out))==5);assert(!strcmp(out,"xxxxx"));
    rle[3]=6;assert(companion_ble_unpack(rle,sizeof(rle),out,sizeof(out))==-1);rle[3]=0;assert(companion_ble_unpack(rle,sizeof(rle),out,sizeof(out))==-1);
    assert(companion_ble_unpack((uint8_t *)"\0abc",4,out,sizeof(out))==3);assert(!strcmp(out,"abc"));
    puts("companion BLE fragments: PASS");
}
