#include "companion_tiles.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    companion_tiles_t s={0};companion_tile_t t={.seq=1,.id=10,.index=0};uint8_t out[COMPANION_TILE_BYTES];
    memset(t.pixels,0,sizeof(t.pixels));assert(companion_tiles_stage(&s,&t));
    assert(!companion_tiles_commit(&s,1,1));t.index=16;assert(companion_tiles_stage(&s,&t));
    assert(companion_tiles_commit(&s,1,1));assert(companion_tiles_bytes(&s)<100);
    size_t before=companion_tiles_bytes(&s);t.seq=2;t.index=0;assert(companion_tiles_stage(&s,&t));
    assert(companion_tiles_bytes(&s)==before);companion_tiles_cancel(&s);assert(companion_tiles_bytes(&s)==before);
    t.seq=2;t.index=0;for(unsigned i=0;i<sizeof(t.pixels);i++)t.pixels[i]=(uint8_t)i;
    assert(companion_tiles_stage(&s,&t));companion_tiles_read(&s,0,out);for(unsigned i=0;i<sizeof(out);i++)assert(out[i]==0);
    assert(!companion_tiles_commit(&s,2,1));t.index=16;assert(companion_tiles_stage(&s,&t));
    assert(companion_tiles_commit(&s,2,1));companion_tiles_read(&s,0,out);assert(!memcmp(out,t.pixels,sizeof(out)));
    t.seq=3;t.index=0;memset(t.pixels,7,sizeof(t.pixels));assert(companion_tiles_stage(&s,&t));
    companion_tiles_cancel(&s);companion_tiles_read(&s,0,out);assert(out[0]==0&&out[1]==1);
    companion_tiles_free(&s);assert(companion_tiles_bytes(&s)==0);
    uint32_t random=7;
    for(unsigned round=0;round<128;round++) {
        t.seq=100+round;t.index=0;
        for(unsigned i=0;i<sizeof(t.pixels);i++){random=random*1664525u+1013904223u;t.pixels[i]=round%2?(uint8_t)(random>>24):(uint8_t)((i/17+round)%7);}
        assert(companion_tiles_stage(&s,&t));t.index=16;assert(companion_tiles_stage(&s,&t));assert(companion_tiles_commit(&s,t.seq,1));
        companion_tiles_read(&s,0,out);assert(!memcmp(out,t.pixels,sizeof(out)));
    }
    companion_tiles_free(&s);assert(companion_tiles_bytes(&s)==0);puts("companion tiles: PASS");
}
