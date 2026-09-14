#define _POSIX_C_SOURCE 200809L
#include "companion_protocol.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
static bool number(const char *s, long low, long high, long *out) {
    if (!*s) return false;
    char *end; errno = 0; long n = strtol(s, &end, 10);
    if (errno || *end || n < low || n > high) return false;
    *out = n; return true;
}
bool companion_parse(const char *line, companion_state_t *out) {
    if (!line || !out || strlen(line) >= 256) return false;
    char buf[256]; strcpy(buf, line);
    char *f[14]; f[0] = buf; int count = 1;
    for (char *p = buf; *p; p++) {
        if (*p == '|') { if (count == 14) return false; *p = 0; f[count++] = p + 1; }
        else if ((unsigned char)*p < 32 || (unsigned char)*p > 126) return false;
    }
    if (count != 14 || strcmp(f[0], "CDX1")) return false;
    long v[10];
    const long lo[] = {1,-1,0,-1,0,0,0,0,0};
    const long hi[] = {INT_MAX,100,1000000,100,1000000,999,999999,COMPANION_ALERT_KIND_MAX,1};
    for (int i=0;i<9;i++) if (!number(f[i+1],lo[i],hi[i],&v[i])) return false;
    if (strlen(f[10]) > 48 || strlen(f[11]) > 16 || strlen(f[12]) > 16 || strcmp(f[13],"END")) return false;
    companion_state_t s = {.seq=(uint32_t)v[0], .remaining={(int)v[1],(int)v[3]},
        .minutes={(int)v[2],(int)v[4]}, .running=(int)v[5], .completed=(int)v[6],
        .alert=(int)v[7], .fresh=(int)v[8]};
    strcpy(s.title,f[10]);strcpy(s.reset[0],f[11]);strcpy(s.reset[1],f[12]);
    *out=s;return true;
}

static int hexval(char c) {
    if(c>='0' && c<='9')return c-'0';
    if(c>='a' && c<='f')return c-'a'+10;
    if(c>='A' && c<='F')return c-'A'+10;
    return -1;
}
bool companion_parse_tile(const char *line, companion_tile_t *out, bool *commit) {
    if(!line || !out || !commit || strlen(line)>=7168)return false;
    /* Fixed numeric prefixes, followed by exact-size hex data; reject trailing bytes. */
    char prefix[80];const char *body=strchr(line,'|');
    if(!body)return false;
    bool end=!strncmp(line,"CDXL|",5);
    if(!end && strncmp(line,"CDXP|",5))return false;
    const char *p=line;int pipes=0,needed=end?3:4;
    while(*p && pipes<needed)if(*p++=='|')pipes++;
    if(pipes!=needed || (size_t)(p-line)>=sizeof(prefix))return false;
    memcpy(prefix,line,(size_t)(p-line));prefix[p-line-1]=0;
    char *f[4];int n=0;char *save=NULL;
    for(char *t=strtok_r(prefix,"|",&save);t && n<4;t=strtok_r(NULL,"|",&save))f[n++]=t;
    if(n!=(end?3:4))return false;
    long seq,index,id=0;
    if(!number(f[1],1,INT_MAX,&seq) || !number(f[2],0,COMPANION_TASKS_MAX,&index))return false;
    if(end) {if(strcmp(p,"END"))return false;}
    else {
        if(!number(f[3],1,INT_MAX,&id) || strlen(p)!=COMPANION_TILE_BYTES*2+4 || strcmp(p+COMPANION_TILE_BYTES*2,"|END"))return false;
        for(int i=0;i<COMPANION_TILE_BYTES*2;i++)if(hexval(p[i])<0)return false;
    }
    out->seq=(uint32_t)seq;out->id=(uint32_t)id;out->index=(int)index;out->count=end?(int)index:0;
    if(!end)for(int i=0;i<COMPANION_TILE_BYTES;i++)out->pixels[i]=(uint8_t)((hexval(p[i*2])<<4)|hexval(p[i*2+1]));
    *commit=end;return true;
}
bool companion_navigate(companion_nav_t *nav, companion_key_t key, int count, unsigned pending) {
    if(key==COMPANION_BACK) {nav->page=COMPANION_HOME;return false;}
    if(nav->page==COMPANION_COMPLETE) {
        if(key==COMPANION_OK) {
            if(pending<=1)nav->page=nav->return_page;
            return pending>0;
        }
        return false;
    }
    if(nav->page==COMPANION_HOME) {
        if(key==COMPANION_OK) {
            if(pending){nav->return_page=COMPANION_HOME;nav->page=COMPANION_COMPLETE;}
            else {nav->page=COMPANION_TASKS;nav->selected=0;}
        }
        return false;
    }
    if(count<=0){nav->selected=0;return false;}
    if(nav->selected>=count)nav->selected=count-1;
    if(key==COMPANION_UP)nav->selected=(nav->selected+count-1)%count;
    if(key==COMPANION_DOWN)nav->selected=(nav->selected+1)%count;
    return false;
}
void companion_notify(companion_nav_t *nav) {
    if(nav->page!=COMPANION_COMPLETE)nav->return_page=nav->page;
    nav->page=COMPANION_COMPLETE;
}

bool companion_parse_metadata(const char *line, companion_metadata_t *out) {
    if(!line || !out || strlen(line)>=768)return false;
    char buf[768];strcpy(buf,line);char *f[16]={buf};int count=1;
    for(char *p=buf;*p;p++) {
        if(*p=='|'){if(count==16)return false;*p=0;f[count++]=p+1;}
        else if((unsigned char)*p<32 || (unsigned char)*p>126)return false;
    }
    if((count!=9 && count!=11 && count!=12 && count!=14 && count!=15 && count!=16) || strcmp(f[0],"CDXM") || strcmp(f[count-1],"END"))return false;
    companion_metadata_t m={0};long seq,alert,n;
    m.weekday=7;m.reset_cards=-1;
    if(count>=15){long cards;if(!number(f[13],-1,INT_MAX,&cards))return false;m.reset_cards=(int)cards;}
    if(count==16){if(strlen(f[14])>=sizeof(m.alert_host))return false;strcpy(m.alert_host,f[14]);}
    for(int i=0;i<7;i++)m.chart[i]=-1;
    strcpy(m.ceiling,"--");
    if(count>=12) {
        if(!*f[10] || strlen(f[10])>=sizeof(m.ceiling))return false;
        if(strcmp(f[10],"--") && strspn(f[10],"0123456789.KMBTPE")!=strlen(f[10]))return false;
        strcpy(m.ceiling,f[10]);
    }
    for(int i=0;i<7;i++){strcpy(m.daily[i],"--");strcpy(m.dates[i],"--");}
    if(count>=14) {
        for(int field=11;field<=12;field++) {
            char *part=f[field];
            for(int i=0;i<7;i++) {
                char *next=strchr(part,',');if(next)*next++=0;
                if(!*part || strlen(part)> (field==11?4u:5u))return false;
                if(field==11) {
                    if(strcmp(part,"--") && strspn(part,"0123456789.KMBTPE")!=strlen(part))return false;
                    strcpy(m.daily[i],part);
                } else {
                    long day,month;
                    if(strlen(part)==5) {
                        if(part[2]!='/' || strspn(part,"0123456789")!=2 || strspn(part+3,"0123456789")!=2)return false;
                        part[2]=0;
                        static const int max_days[]={31,29,31,30,31,30,31,31,30,31,30,31};
                        if(!number(part,1,12,&month) || !number(part+3,1,max_days[month-1],&day))return false;
                        part[2]='/';
                    } else if(strcmp(part,"--") && !number(part,1,31,&day))return false;
                    strcpy(m.dates[i],part);
                }
                if((i<6 && !next) || (i==6 && next))return false;
                part=next;
            }
        }
    }
    if(count>=11) {
        long weekday;
        if(!number(f[8],0,6,&weekday))return false;
        m.weekday=(uint8_t)weekday;
        char *point=f[9];
        for(int i=0;i<7;i++) {
            char *next=strchr(point,',');if(next)*next++=0;
            long value;if(!number(point,-1,1000,&value))return false;
            m.chart[i]=(int16_t)value;
            if((i<6 && !next) || (i==6 && next))return false;
            point=next;
        }
    }
    if(!number(f[1],1,INT_MAX,&seq) || !number(f[5],-1,INT_MAX,&alert) || !number(f[6],0,COMPANION_TASKS_MAX,&n))return false;
    for(int i=2;i<=4;i++)if(!*f[i] || strlen(f[i])>=16)return false;
    strcpy(m.day,f[2]);strcpy(m.week,f[3]);strcpy(m.asof,f[4]);
    m.seq=(uint32_t)seq;m.alert_seconds=(int)alert;m.count=(int)n;
    char *p=f[7];
    if(n==0 && strcmp(p,"-"))return false;
    for(int i=0;i<n;i++) {
        char *next=strchr(p,',');if(next)*next++=0;
        char *colon=strchr(p,':');if(!colon)return false;*colon++=0;
        long id,elapsed;
        if(!number(p,1,INT_MAX,&id) || !number(colon,-1,INT_MAX,&elapsed))return false;
        for(int j=0;j<i;j++)if(m.ids[j]==(uint32_t)id)return false;
        m.ids[i]=(uint32_t)id;m.elapsed[i]=(int)elapsed;
        if(i<n-1 && !next)return false;
        if(i==n-1 && next)return false;
        p=next;
    }
    *out=m;return true;
}

void companion_format_duration(int seconds, char *out, unsigned size) {
    if(!out || !size)return;
    if(seconds<0)snprintf(out,size,"%s","");
    else if(seconds<60)snprintf(out,size,"<1m");
    else if(seconds>=3600)snprintf(out,size,"%dh %02dm",seconds/3600,(seconds%3600)/60);
    else snprintf(out,size,"%dm",seconds/60);
}
