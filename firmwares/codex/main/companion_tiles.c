#include "companion_tiles.h"
#include <stdlib.h>
#include <string.h>
struct companion_blob { uint16_t size; uint8_t codec,refs; uint8_t data[]; };
/* Small LZSS blocks: 8-token control byte; match stores 12-bit distance and 4-bit length. */
static size_t lz_pack(const uint8_t *p,uint8_t *out) {
    size_t pos=0,used=0;
    while(pos<COMPANION_TILE_BYTES) {
        size_t control=used++;uint8_t flags=0;
        for(unsigned bit=0;bit<8 && pos<COMPANION_TILE_BYTES;bit++) {
            size_t best=0,distance=0,limit=pos<1024?pos:1024;
            for(size_t d=1;d<=limit;d++) {
                if(p[pos-d]!=p[pos])continue;
                size_t n=1;while(n<18 && pos+n<COMPANION_TILE_BYTES && p[pos+n-d]==p[pos+n])n++;
                if(n>best){best=n;distance=d;if(n==18)break;}
            }
            if(best>=3){uint16_t token=(uint16_t)(((distance-1)<<4)|(best-3));flags|=1u<<bit;
                if(out){out[used]=token>>8;out[used+1]=token;}used+=2;pos+=best;
            }else{if(out)out[used]=p[pos];used++;pos++;}
        }
        if(out)out[control]=flags;
    }return used;
}
static companion_blob_t *pack(const uint8_t *p) {
    size_t encoded=0;
    for(size_t i=0;i<COMPANION_TILE_BYTES;) {
        size_t n=1;while(i+n<COMPANION_TILE_BYTES && n<255 && p[i+n]==p[i])n++;
        encoded+=2;i+=n;
    }
    uint8_t codec=encoded<COMPANION_TILE_BYTES?1:0;size_t size=codec?encoded:COMPANION_TILE_BYTES;
    size_t lz=encoded<64?COMPANION_TILE_BYTES:lz_pack(p,NULL);if(lz<size){codec=2;size=lz;}
    companion_blob_t *b=malloc(sizeof(*b)+size);if(!b)return NULL;
    b->size=size;b->codec=codec;b->refs=1;
    if(codec==0)memcpy(b->data,p,size);
    else if(codec==2)lz_pack(p,b->data);
    else for(size_t i=0,j=0;i<COMPANION_TILE_BYTES;) {
        size_t n=1;while(i+n<COMPANION_TILE_BYTES && n<255 && p[i+n]==p[i])n++;
        b->data[j++]=(uint8_t)n;b->data[j++]=p[i];i+=n;
    }
    return b;
}
static void release(companion_blob_t *b){if(b && --b->refs==0)free(b);}
void companion_tiles_cancel(companion_tiles_t *s) {
    for(int i=0;i<=COMPANION_TASKS_MAX;i++){release(s->pending[i]);s->pending[i]=NULL;}
    s->mask=0;s->seq=0;
}
bool companion_tiles_stage(companion_tiles_t *s,const companion_tile_t *t) {
    if(!s||!t||t->index<0||t->index>COMPANION_TASKS_MAX||!t->seq)return false;
    if(s->seq!=t->seq){companion_tiles_cancel(s);s->seq=t->seq;}
    companion_blob_t *b=pack(t->pixels);if(!b)return false;
    companion_blob_t *front=s->front[t->index];
    if(front && front->codec==b->codec && front->size==b->size && !memcmp(front->data,b->data,b->size)) {
        release(b);b=front;b->refs++;
    }
    release(s->pending[t->index]);s->pending[t->index]=b;s->pending_ids[t->index]=t->id;
    s->mask|=1u<<t->index;return true;
}
bool companion_tiles_commit(companion_tiles_t *s,uint32_t seq,int count) {
    if(!s||count<0||count>COMPANION_TASKS_MAX)return false;
    uint32_t required=((1u<<count)-1u)|(1u<<COMPANION_ALERT_TILE);
    if(seq!=s->seq || (s->mask&required)!=required)return false;
    for(int i=0;i<=COMPANION_TASKS_MAX;i++) {
        release(s->front[i]);s->front[i]=NULL;s->ids[i]=0;
        if(i<count||i==COMPANION_ALERT_TILE){s->front[i]=s->pending[i];s->pending[i]=NULL;s->ids[i]=s->pending_ids[i];}
    }
    s->count=count;companion_tiles_cancel(s);return true;
}
void companion_tiles_read(const companion_tiles_t *s,int index,uint8_t out[COMPANION_TILE_BYTES]) {
    const companion_blob_t *b=index>=0&&index<=COMPANION_TASKS_MAX?s->front[index]:NULL;
    if(!b){memset(out,0,COMPANION_TILE_BYTES);return;}
    if(b->codec==0){memcpy(out,b->data,COMPANION_TILE_BYTES);return;}
    if(b->codec==2){
        size_t i=0,pos=0;while(i<b->size){uint8_t flags=b->data[i++];for(unsigned bit=0;bit<8 && pos<COMPANION_TILE_BYTES;bit++){
            if(flags&(1u<<bit)){uint16_t token=(uint16_t)b->data[i]<<8|b->data[i+1];i+=2;size_t distance=(token>>4)+1,n=(token&15)+3;for(size_t k=0;k<n;k++){out[pos]=out[pos-distance];pos++;}}
            else out[pos++]=b->data[i++];
        }}return;
    }
    size_t pos=0;
    for(size_t i=0;i<b->size;i+=2){memset(out+pos,b->data[i+1],b->data[i]);pos+=b->data[i];}
}
void companion_tiles_free(companion_tiles_t *s) {
    companion_tiles_cancel(s);for(int i=0;i<=COMPANION_TASKS_MAX;i++){release(s->front[i]);s->front[i]=NULL;}
}
size_t companion_tiles_bytes(const companion_tiles_t *s) {
    size_t n=0;for(int i=0;i<=COMPANION_TASKS_MAX;i++) {
        if(s->front[i])n+=sizeof(companion_blob_t)+s->front[i]->size;
        if(s->pending[i] && s->pending[i]!=s->front[i])n+=sizeof(companion_blob_t)+s->pending[i]->size;
    }return n;
}
