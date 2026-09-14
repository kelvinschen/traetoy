#include "pet_ui.h"

#include <stdio.h>
#include <string.h>
#include "pet_font.h"
#include "pet_icons.h"
#include "firmware_identity.h"
#define PAPER 236
#define INK 24
uint16_t pet_rgb(unsigned r, unsigned g, unsigned b) {
  uint16_t v = (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
  return (uint16_t)((v << 8) | (v >> 8));
}
void pet_layout_init(pet_layout_t *l, int64_t now) {
  *l = (pet_layout_t){.from = 154 * 256, .position = 154 * 256,
                     .target = 154 * 256, .at = now};
}
int pet_layout_tick(pet_layout_t *l, bool expanded, int64_t now) {
  int64_t elapsed = now > l->at ? now - l->at : 0;
  int64_t u = elapsed >= 380000 ? 256 : elapsed * 256 / 380000;
  int64_t e = u * u * (768 - 2 * u) / 65536;
  l->position = l->from + (int)((l->target - l->from) * e / 256);
  int target = (expanded ? 99 : 154) * 256;
  if (l->target != target) {
    l->from = l->position;
    l->target = target;
    l->at = now;
  }
  return (l->position + 128) / 256;
}
static unsigned palette(unsigned n, bool dim) {
  unsigned c = INK + ((PAPER - INK) * n + 7) / 14;
  return dim ? PAPER - (PAPER - c) / 2 : c;
}
static uint16_t color(unsigned n, bool dim) {
  if (n == 15)
    return pet_rgb(244, 120, 42);
  unsigned c = palette(n, dim);
  return pet_rgb(c, c, c);
}
static unsigned pixel(const uint8_t *p, unsigned x, unsigned y) {
  unsigned i = y * PET_W + x;
  return (p[i >> 1] >> ((i & 1) ? 0 : 4)) & 15;
}
static void dot(pet_rect_t a, uint16_t *out, int x, int y, uint16_t c) {
  if (x >= a.x && x < a.x + a.w && y >= a.y && y < a.y + a.h)
    out[(y - a.y) * a.w + x - a.x] = c;
}
static void text(pet_rect_t a, uint16_t *out, int x, int y, const char *s,
                 int scale, uint16_t c) {
  unsigned face = scale == 0 ? 380 : (unsigned)(scale - 1) * 95;
  // Blend the actual outline coverage, never enlarge a small pixel grid.
  uint16_t colors[16];
  unsigned rgb = (c << 8) | (c >> 8);
  unsigned r = ((rgb >> 11) & 31) * 255 / 31,
           g = ((rgb >> 5) & 63) * 255 / 63, b = (rgb & 31) * 255 / 31;
  for (unsigned n = 0; n < 16; n++)
    colors[n] = pet_rgb((r*n+PAPER*(15-n))/15,
                        (g*n+PAPER*(15-n))/15, (b*n+PAPER*(15-n))/15);
  for (; *s; s++) {
    unsigned ch = (unsigned char)*s;
    const pet_glyph_t *glyph = &pet_glyphs[face + (ch >= 32 && ch <= 126 ? ch-32 : '?'-32)];
    static const int top[] = {2,3,4,7,12};
    int dx = x + glyph->left, dy = y + glyph->top - top[scale];
    int x0 = a.x > dx ? a.x-dx : 0, y0 = a.y > dy ? a.y-dy : 0;
    int x1 = a.x+a.w < dx+glyph->width ? a.x+a.w-dx : glyph->width;
    int y1 = a.y+a.h < dy+glyph->height ? a.y+a.h-dy : glyph->height;
    for (int row = y0; row < y1; row++)
      for (int col = x0; col < x1; col++) {
        unsigned i = row * glyph->width + col;
        unsigned alpha = (pet_font_pixels[glyph->offset+i/2] >> ((i&1)?0:4)) & 15;
        if (alpha) out[(dy+row-a.y)*a.w+dx+col-a.x] = colors[alpha];
      }
    x += glyph->advance;
    if (x >= a.x+a.w) break;
  }
}
static int text_width(const char *s, int scale) {
  unsigned face = scale == 0 ? 380 : (unsigned)(scale - 1) * 95;
  int w = 0;
  for (; *s; s++) {
    unsigned c = (unsigned char)*s;
    w += pet_glyphs[face + (c >= 32 && c <= 126 ? c-32 : '?'-32)].advance;
  }
  return w;
}
static void right(pet_rect_t a, uint16_t *out, int x, int y, const char *s,
                   int face, uint16_t color) {
  text(a,out,x-text_width(s,face),y,s,face,color);
}
static void fit(pet_rect_t a, uint16_t *out, int x, int y, int w, const char *s,
                 int face, uint16_t color) {
  char label[80];
  snprintf(label,sizeof(label),"%s",s);
  if (text_width(label,face)>w) {
    size_t n = strlen(label);
    while (n && text_width(label,face)+text_width("...",face)>w) label[--n]=0;
    snprintf(label+n,sizeof(label)-n,"...");
  }
  text(a,out,x,y,label,face,color);
}
static void status_icon(pet_rect_t a, uint16_t *out, int icon) {
  if (a.x>=34 || a.x+a.w<=18 || a.y>=310 || a.y+a.h<=294) return;
  // Same quiet gray as the quota footer; each pixel has 16 coverage levels.
  for (int y=0;y<16;y++) for (int x=0;x<16;x++) {
    if (18+x<a.x || 18+x>=a.x+a.w || 294+y<a.y || 294+y>=a.y+a.h) continue;
    unsigned i=y*16+x, alpha=(pet_status_icons[icon][i/2]>>((i&1)?0:4))&15;
    unsigned c=(105*alpha+PAPER*(15-alpha))/15;
    dot(a,out,18+x,294+y,pet_rgb(c,c,c));
  }
}
int pet_quota_window(const companion_state_t *s) {
  int k = -1;
  for (int i = 0; i < 2; i++)
    if (s->minutes[i] > 0 && (k < 0 || s->minutes[i] < s->minutes[k]))
      k = i;
  return k;
}
pet_rect_t pet_content_bounds(const uint8_t *pixels) {
  int x0 = PET_W, x1 = -1, y0 = PET_W, y1 = -1;
  for (int y = 0; y < PET_W; y++)
    for (int x = 0; x < PET_W; x += 8) {
      uint32_t word;
      memcpy(&word, pixels + (y * PET_W + x) / 2, sizeof(word));
      if (word == 0xeeeeeeee) continue;
      if (x < x0) x0 = x;
      if (x + 7 > x1) x1 = x + 7;
      if (y < y0) y0 = y;
      y1 = y;
    }
  return x1 < 0 ? (pet_rect_t){0} : (pet_rect_t){x0,y0,x1-x0+1,y1-y0+1};
}
static void packed_bitmap(pet_rect_t a, uint16_t *out, const uint8_t *p,
                          unsigned offset, int sw, int sh, int dx, int dy,
                          int stride, unsigned opacity) {
  int x0 = a.x > dx ? a.x - dx : 0, y0 = a.y > dy ? a.y - dy : 0;
  int x1 = a.x + a.w < dx + sw ? a.x + a.w - dx : sw;
  int y1 = a.y + a.h < dy + sh ? a.y + a.h - dy : sh;
  uint16_t colors[4];
  for (unsigned v = 0; v < 4; v++) {
    unsigned c = PAPER - (PAPER - INK) * v * opacity / (3 * 256);
    colors[v] = pet_rgb(c,c,c);
  }
  for (int y = y0; y < y1; y++)
    for (int x = x0; x < x1; x++) {
      unsigned i = offset + y * stride + x;
      out[(dy+y-a.y)*a.w+dx+x-a.x] = colors[(p[i/4]>>(6-2*(i%4)))&3];
    }
}
static void bitmap(pet_rect_t a, uint16_t *out, const uint8_t *p, int sx,
                   int sy, int sw, int sh, int dx, int dy, int stride) {
  packed_bitmap(a,out,p,(unsigned)(sy*stride+sx),sw,sh,dx,dy,stride,256);
}
static void info_page(const pet_paint_t *p, pet_rect_t a, uint16_t *out) {
  const pet_view_t *v=p->view;
  uint16_t ink=pet_rgb(INK,INK,INK), gray=pet_rgb(105,105,105), orange=pet_rgb(196,86,20);
  char s[80];
  const char *heading=v->page==PET_QUOTA?"QUOTA & RESET":v->page==PET_USAGE?"TOKEN USAGE":"CONNECTION";
  text(a,out,18,22,heading,1,gray);
  snprintf(s,sizeof(s),"%d / 3",v->page);
  right(a,out,222,22,s,0,gray);
  if (v->page==PET_QUOTA) {
    int k=pet_primary_window(&v->state);
    bool known=k>=0 && p->quota_fresh && v->state.remaining[k]>=0;
    if (known) snprintf(s,sizeof(s),"%d%%",v->state.remaining[k]);
    else snprintf(s,sizeof(s),"--");
    text(a,out,18,64,s,4,ink);
    snprintf(s,sizeof(s),"RESET IN  %s",known?v->state.reset[k]:"--");
    text(a,out,18,137,s,1,gray);
    if (k>=0 && v->state.minutes[1-k]>0) {
      int j=1-k, m=v->state.minutes[j];
      if (p->quota_fresh && v->state.remaining[j]>=0)
        snprintf(s,sizeof(s),"%dH  %d%%   %s",m/60,v->state.remaining[j],v->state.reset[j]);
      else snprintf(s,sizeof(s),"%dH  --",m/60);
      fit(a,out,18,168,204,s,1,gray);
    }
    bool fresh=p->linked && v->info_age>=0 && v->info_age<900;
    if (fresh && v->cards>=0) snprintf(s,sizeof(s),"RESET CREDITS  %d",v->cards);
    else snprintf(s,sizeof(s),"RESET CREDITS  --");
    text(a,out,18,199,s,1,ink);
    text(a,out,18,224,"EXPIRES",0,gray);
    right(a,out,222,224,"STATUS",0,gray);
    if (!fresh || !v->cards_known) text(a,out,18,245,"Details unavailable",1,gray);
    else if (!v->card_count) text(a,out,18,245,"No reset credits",1,gray);
    else for (int i=0;i<v->card_count;i++) {
      const char *date=v->expires[i];
      text(a,out,18,243+i*12,strlen(date)==16?date+5:date,0,gray);
      right(a,out,222,243+i*12,v->card_status[i],0,gray);
    }
  } else if (v->page==PET_USAGE) {
    bool fresh=p->linked && v->usage_fresh;
    pet_token_label(fresh?v->usage.week:"--",s,sizeof(s));
    fit(a,out,18,63,169,s,3,ink);
    right(a,out,222,83,"/ 7d",1,gray);
    for (int i=0;i<7;i++) {
      int cx=31+i*29;
      pet_token_label(fresh?v->usage.daily[i]:"--",s,sizeof(s));
      size_t len=strlen(s);
      char unit[2]={0};
      if (len && (s[len-1]=='B'||s[len-1]=='M')) {unit[0]=s[len-1];s[len-1]=0;}
      // Labels occupy their own fixed two-line band, separate from the bars.
      if (text_width(s,0)>25) snprintf(s,sizeof(s),"...");
      text(a,out,cx-text_width(s,0)/2,124,s,0,ink);
      text(a,out,cx-text_width(unit,0)/2,138,unit,0,gray);
      int point=fresh?v->usage.chart[i]:-1;
      int height=point>0?(point*83+999)/1000:0;
      if (height>83) height=83;
      for (int y=246-height;y<246;y++) for (int x=cx-8;x<cx+9;x++)
        dot(a,out,x,y,i==6?orange:pet_rgb(63,63,63));
      // Distinguish a known zero from an absent calendar bucket.
      if (!point) for (int x=cx-5;x<=cx+5;x++) dot(a,out,x,245,gray);
      const char *date=v->usage.dates[i];
      if (!fresh || !*date) date="--";
      else if (strlen(date)==5) date+=3;
      text(a,out,cx-text_width(date,0)/2,259,date,0,gray);
    }
    snprintf(s,sizeof(s),"AS OF %s",fresh&&*v->usage.asof?v->usage.asof:"--");
    text(a,out,18,287,s,0,gray);
    if (fresh && !strcmp(v->usage.asof,"Today")) right(a,out,222,303,"Partial day",0,gray);
    else if (fresh) right(a,out,222,303,"Daily totals",0,gray);
  } else {
    text(a,out,18,62,!p->linked?"OFFLINE":v->transport==1?"BLE":"USB",3,ink);
    if (v->link_age>=0) snprintf(s,sizeof(s),"LAST UPDATE  %ds",v->link_age);
    else snprintf(s,sizeof(s),"LAST UPDATE  --");
    text(a,out,18,108,s,1,gray);
    if (!v->source_count) text(a,out,18,139,"Sources unavailable",1,gray);
    for (int i=0;i<v->source_count;i++) {
      fit(a,out,18,138+i*19,135,v->sources[i],1,ink);
      right(a,out,222,138+i*19,!p->linked||v->info_age<0?"--":v->sources_healthy[i]?"OK":"ERROR",0,gray);
    }
    if (v->battery>=0) snprintf(s,sizeof(s),"BATTERY  %d%%",v->battery);
    else snprintf(s,sizeof(s),"BATTERY  --");
    text(a,out,18,224,s,1,gray);
    snprintf(s,sizeof(s),"%u%%",v->brightness);
    right(a,out,222,246,s,1,ink);
    text(a,out,18,246,"BRIGHTNESS",1,gray);
    text(a,out,18,268,"FIRMWARE",1,gray);
    right(a,out,222,268,FIRMWARE_VERSION,1,ink);
    companion_format_duration((int)v->uptime,s,sizeof(s));
    text(a,out,18,294,s,1,gray);
    snprintf(s,sizeof(s),"%u.%u FPS",v->fps10/10,v->fps10%10);
    right(a,out,222,294,s,1,gray);
  }
}
void pet_paint(const pet_paint_t *p, pet_rect_t a, uint16_t *out) {
  const pet_view_t *v = p->view;
  uint16_t paper = pet_rgb(PAPER, PAPER, PAPER), ink = pet_rgb(INK, INK, INK),
           gray = pet_rgb(105, 105, 105);
  char s[80];
  int ay = p->avatar_y;
  for (int i = 0; i < a.w * a.h; i++)
    out[i] = paper;
  if (v->page>=PET_QUOTA && v->page<=PET_SYSTEM) {info_page(p,a,out);return;}
  if (v->page == PET_HOME || v->page == PET_GALLERY) {
    bool dim = !p->linked && v->page != PET_GALLERY;
    uint16_t lut[256];
    bool blending = p->previous && p->blend < 256;
    for (unsigned n = 0; n < 16; n++) {
      if (!blending) {
        lut[n] = color(n, dim);
        continue;
      }
      for (unsigned old = 0; old < 16; old++) {
        unsigned t = p->blend;
        unsigned r1 = n == 15 ? 244 : palette(n, dim), g1 = n == 15 ? 120 : r1,
                 b1 = n == 15 ? 42 : r1;
        unsigned r0 = old == 15 ? 244 : palette(old, dim),
                 g0 = old == 15 ? 120 : r0, b0 = old == 15 ? 42 : r0;
        lut[n * 16 + old] = pet_rgb((r1 * t + r0 * (256 - t)) >> 8,
                                    (g1 * t + g0 * (256 - t)) >> 8,
                                    (b1 * t + b0 * (256 - t)) >> 8);
      }
    }
    int y0 = a.y > ay ? a.y : ay,
        y1 = a.y + a.h < ay + PET_W ? a.y + a.h : ay + PET_W;
    int x0 = a.x > 24 ? a.x : 24,
        x1 = a.x + a.w < 24 + PET_W ? a.x + a.w : 24 + PET_W;
    if (x0 >= x1) y1 = y0;
    if (!blending) {
      /* Expand one packed byte into two native RGB565 pixels. The lookup is
       * immutable after initialization; only the display owner calls paint. */
      static uint16_t pairs[2][256][2];
      static bool ready;
      if (!ready) {
        for (unsigned d = 0; d < 2; d++)
          for (unsigned n = 0; n < 256; n++) {
            pairs[d][n][0] = color(n >> 4, d);
            pairs[d][n][1] = color(n & 15, d);
          }
        ready = true;
      }
      for (int y = y0; y < y1; y++) {
        int x = x0;
        uint16_t *dst = out + (y - a.y) * a.w + x - a.x;
        if (x & 1) {
          *dst++ = lut[pixel(p->pixels, x - 24, y - ay)];
          x++;
        }
        const uint8_t *src = p->pixels + ((y - ay) * PET_W + x - 24) / 2;
        for (; x + 1 < x1; x += 2, dst += 2)
          memcpy(dst, pairs[dim][*src++], 4);
        if (x < x1)
          *dst = lut[pixel(p->pixels, x - 24, y - ay)];
      }
    } else {
      for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) {
          unsigned n = pixel(p->pixels, x - 24, y - ay);
          unsigned old = pixel(p->previous, x - 24, y - ay);
          out[(y - a.y) * a.w + x - a.x] = lut[n * 16 + old];
        }
    }
    if ((!p->linked || v->input.source_bad) && v->page == PET_HOME)
      text(a, out, 18, 18, !p->linked ? "OFFLINE" : "SOURCE ERROR", 1, gray);
    if (v->page == PET_GALLERY) {
      text(a, out, 12, 14, pet_clips[p->clip].name, 2, ink);
      snprintf(s, sizeof(s), "%d/%d  %u.%u FPS", p->clip + 1, PET_CLIP_COUNT,
               v->fps10 / 10, v->fps10 % 10);
      text(a, out, 24, 281, s, 1, gray);
      return;
    }
    if (v->input.unread && p->reveal) {
      int dy = (int)((256 - p->reveal) * 10 / 256);
      const char *label = v->alert_kind == 1 ? "DONE" : v->alert_kind == 3 ? "WAITING" : "STOPPED";
      if (v->input.unread>1) snprintf(s,sizeof(s),"%s (%u UNREAD)",label,v->input.unread);
      else snprintf(s,sizeof(s),"%s",label);
      unsigned t=p->reveal;
      text(a,out,18,174+dy,s,1,pet_rgb((196*t+PAPER*(256-t))/256,
           (86*t+PAPER*(256-t))/256,(20*t+PAPER*(256-t))/256));
      // Reuse the immutable Chinese-capable wide title and workspace snapshot.
      packed_bitmap(a, out, v->tile, 0, 168, 60, 36, 188 + dy, 168, p->reveal);
      companion_format_duration(v->elapsed, s, sizeof(s));
      int room=204-text_width(s,1)-12;
      if (room>170) room=170;
      // Left-align the existing workspace bitmap; crop only at the reserved
      // duration boundary, so long names never collide with elapsed time.
      int left=170,last=-1;
      for (int y=0;y<16;y++) for (int x=0;x<170;x++) {
        unsigned i=168*60+y*170+x;
        if ((v->tile[i/4]>>(6-2*(i%4)))&3) {if(x<left)left=x;if(x>last)last=x;}
      }
      if (last>=left) {
        int width=last-left+1;
        bool cropped=width>room;
        if (cropped) width=room-14;
        packed_bitmap(a,out,v->tile,168*60+left,width,16,18,253+dy,170,p->reveal);
        if (cropped) text(a,out,18+width,253+dy,"...",0,gray);
      }
      right(a,out,222,253+dy,s,1,gray);
    }
    bool count_known=p->linked && !v->input.source_bad;
    if (!count_known || v->input.running>0)
      status_icon(a,out,!count_known?2:0);
    if (count_known && v->input.running>0) {
      snprintf(s,sizeof(s),"%d",v->input.running);
      text(a,out,40,297,s,1,gray);
    }
    int k=pet_primary_window(&v->state);
    if (k>=0 && p->quota_fresh && v->state.remaining[k]>=0) {
      snprintf(s,sizeof(s),"%d%%",v->state.remaining[k]);
      int room=142-text_width(s,2)-8;
      int width=text_width(v->state.reset[k],1);
      if (width>room) width=room;
      int reset_x=222-width;
      // Emphasize the percentage; align the 18 px and 13 px digit baselines.
      right(a,out,reset_x-8,293,s,2,ink);
      fit(a,out,reset_x,297,room,v->state.reset[k],1,gray);
    }
    return;
  }
  if (v->page == PET_TASKS) {
    snprintf(s, sizeof(s), "RUNNING %d/%d", v->count ? v->selected + 1 : 0,
             v->count);
    text(a, out, 20, 30, s, 2, gray);
    if (v->count) {
      bitmap(a, out, v->tile, 0, 0, 200, 64, 20, 104, 200);
      companion_format_duration(v->elapsed, s, sizeof(s));
      text(a, out, 20, 200, s, 2, ink);
    } else
      text(a, out, 20, 130, "NO ACTIVE TASK", 2, ink);
  }
  if (v->page == PET_ALERT) {
    text(a, out, 20, 30, v->alert_kind == 1 ? "TURN COMPLETE" : v->alert_kind == 3 ? "NEEDS YOUR INPUT" : "TASK STOPPED",
         2, gray);
    bitmap(a, out, v->tile, 0, 0, 168, 60, 36, 96,
           168); /* Wide protocol packs title then a 170x16 workspace. */
    for (int y = 0; y < 16; y++)
      for (int x = 0; x < 170; x++) {
        unsigned i = 168 * 60 + y * 170 + x,
                 q = (v->tile[i / 4] >> (6 - 2 * (i % 4))) & 3,
                 c = PAPER - (PAPER - INK) * q / 3;
        dot(a, out, 35 + x, 186 + y, pet_rgb(c, c, c));
      }
    text(a, out, 20, 224, v->host, 1, gray);
    companion_format_duration(v->elapsed, s, sizeof(s));
    text(a, out, 20, 244, s, 2, ink);
    snprintf(s, sizeof(s), "OK READ  %u LEFT", v->input.unread);
    text(a, out, 20, 290, s, 1, gray);
  }
}
