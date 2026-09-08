#include "companion_info.h"
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
/* Read one bounded ASCII field without duplicating the large input frame. */
static bool field(const char **p,char *out,size_t size) {
    const char *end=strchr(*p,'|');if(!end || (size_t)(end-*p)>=size)return false;
    for(const char *c=*p;c<end;c++)if((unsigned char)*c<32 || (unsigned char)*c>126)return false;
    memcpy(out,*p,(size_t)(end-*p));out[end-*p]=0;*p=end+1;return true;
}
static bool integer(const char **p,int min,int max,int *out) {
    char buf[16],*end;if(!field(p,buf,sizeof(buf)) || !*buf)return false;
    errno=0;long value=strtol(buf,&end,10);
    if(errno || *end || value<min || value>max)return false;
    *out=(int)value;return true;
}
bool companion_parse_info(const char *line,companion_info_t *out) {
    if(!line || !out || strncmp(line,"CDXI|",5) || strlen(line)>=2304)return false;
    companion_info_t info={0};const char *p=line+5;int seq;
    if(!integer(&p,1,INT_MAX,&seq) || !integer(&p,-1,INT_MAX,&info.available) ||
       !integer(&p,-1,INT_MAX,&info.quota_age) || !field(&p,info.generation,sizeof(info.generation)) || !integer(&p,0,1,&info.known) ||
       !integer(&p,0,COMPANION_CARDS_MAX,&info.count) ||
       !field(&p,info.timezone,sizeof(info.timezone)) ||
       !integer(&p,0,COMPANION_SOURCES_MAX,&info.source_count))return false;
    if(!info.known && info.count)return false;
    info.seq=(uint32_t)seq;
    for(int i=0;i<info.source_count;i++) {
        int healthy;
        if(!field(&p,info.sources[i],sizeof(info.sources[i])) ||
           !integer(&p,0,1,&healthy))return false;
        info.healthy[i]=healthy;
    }
    for(int i=0;i<info.count;i++) {
        companion_card_t *c=&info.cards[i];
        if(!field(&p,c->title,sizeof(c->title)) || !field(&p,c->status,sizeof(c->status)) ||
           !field(&p,c->granted,sizeof(c->granted)) || !field(&p,c->expires,sizeof(c->expires)) ||
           !field(&p,c->description,sizeof(c->description)) || !field(&p,c->reset_type,sizeof(c->reset_type)))return false;
    }
    if(strcmp(p,"END"))return false;
    *out=info;return true;
}
bool companion_info_navigate(companion_nav_t *nav,companion_key_t key,int count) {
    if(key==COMPANION_BACK || nav->page==COMPANION_TASKS || nav->page==COMPANION_COMPLETE)return false;
    if(nav->page==COMPANION_HOME || nav->page==COMPANION_CARDS || nav->page==COMPANION_CONNECTION) {
        if(key==COMPANION_UP || key==COMPANION_DOWN) {
            int index=nav->page==COMPANION_HOME?0:nav->page==COMPANION_CARDS?1:2;
            static const companion_page_t pages[]={COMPANION_HOME,COMPANION_CARDS,COMPANION_CONNECTION};
            nav->page=pages[(index+(key==COMPANION_DOWN?1:2))%3];return true;
        }
        if(nav->page==COMPANION_HOME)return false;
        if(key==COMPANION_OK && nav->page==COMPANION_CARDS) {
            nav->page=COMPANION_CARD_LIST;nav->card_selected=0;nav->info_scroll=0;
        }
        return true;
    }
    if(nav->page==COMPANION_CARD_LIST) {
        if(count<=0){nav->card_selected=0;return true;}
        if(nav->card_selected>=count)nav->card_selected=count-1;
        if(key==COMPANION_UP)nav->card_selected=(nav->card_selected+count-1)%count;
        if(key==COMPANION_DOWN)nav->card_selected=(nav->card_selected+1)%count;
        if(key==COMPANION_OK){nav->page=COMPANION_CARD_DETAIL;nav->info_scroll=0;}
        return true;
    }
    if(nav->page==COMPANION_CARD_DETAIL) {
        if(key==COMPANION_UP && nav->info_scroll>0)nav->info_scroll--;
        if(key==COMPANION_DOWN && nav->info_scroll<3)nav->info_scroll++;
        if(key==COMPANION_OK)nav->page=COMPANION_CARD_LIST;
        return true;
    }
    return false;
}
