#include "pet_sound_pcm.h"
#include "companion_alerts.h"
#include "pet_behavior.h"
#include "pet_codec.h"
#include "pet_ui.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t crc(uint32_t c, const uint8_t *p, size_t n) {
  static uint32_t table[256];
  static int ready;
  if (!ready) {
    for (unsigned i = 0; i < 256; i++) {
      uint32_t v = i;
      for (int b = 0; b < 8; b++)
        v = (v >> 1) ^ ((v & 1) ? 0xedb88320 : 0);
      table[i] = v;
    }
    ready = 1;
  }
  c = ~c;
  while (n--)
    c = table[(c ^ *p++) & 255] ^ (c >> 8);
  return ~c;
}
static void logic(void) {
  char label[32];
  const char *tokens[][2]={{"1B","1.0B"},{"1.2B","1.2B"},{"10B","10.0B"},
    {"999M","999M"},{"150M","150M"},{"500K","0.5M"},{"0","0M"},
    {"1K","<0.1M"},{"--","--"},{"nan","--"},{"-1","--"}};
  for (unsigned i=0;i<sizeof(tokens)/sizeof(tokens[0]);i++) {
    pet_token_label(tokens[i][0],label,sizeof(label));
    assert(!strcmp(label,tokens[i][1]));
  }
  int page=PET_HOME;
  for (int i=1;i<=4;i++) {page=pet_page_key(page,1);assert(page==i%4);}
  assert(pet_page_key(PET_HOME,0)==PET_SYSTEM);
  for (int i=1;i<=3;i++) assert(pet_page_key(i,2)==PET_HOME);
  pet_behavior_t b;
  pet_behavior_init(&b, 0);
  pet_input_t in = {.linked = true, .running = 1, .preview = -1};
  assert(pet_behavior_tick(&b, &in, 1));
  assert(!strcmp(pet_clips[b.clip].name, "work"));
  assert(pet_behavior_frame(&b, 500001) == 30);
  in.event = 1;
  in.event_kind = 1;
  in.unread = 1;
  assert(pet_behavior_tick(&b, &in, 1000000));
  assert(!strcmp(pet_clips[b.clip].name, "done"));
  assert(!pet_behavior_tick(&b, &in, 1100000));
  assert(b.start == 1000000);
  in.event++;
  in.event_kind = 2;
  assert(pet_behavior_tick(&b, &in, 1200000));
  assert(!strcmp(pet_clips[b.clip].name, "stop"));
  in.ack++;
  assert(pet_behavior_tick(&b, &in, 1300000));
  assert(!strcmp(pet_clips[b.clip].name, "ack"));
  pet_behavior_init(&b, 0);
  in = (pet_input_t){.linked = true, .preview = -1, .running = 2};
  pet_behavior_tick(&b, &in, 0);
  in.linked = false;
  assert(pet_behavior_tick(&b, &in, 1000000));
  assert(!strcmp(pet_clips[b.clip].name, "offline"));
  assert(in.running == 2);
  pet_behavior_init(&b, 0);
  in = (pet_input_t){
      .linked = true, .source_bad = true, .running = 2, .preview = -1};
  pet_behavior_tick(&b, &in, 0);
  assert(!strcmp(pet_clips[b.clip].name, "offline"));
  pet_behavior_init(&b, 0);
  in = (pet_input_t){.linked = true, .preview = -1};
  for (int64_t t = 0; t <= 200000000; t += 1000000)
    pet_behavior_tick(&b, &in, t);
  assert(b.idle_since == 0);
  assert(!strcmp(pet_clips[b.clip].name, "idle"));
  assert(pet_behavior_frame(&b, 200000000) < pet_clips[b.clip].count);
  // Reversible movement starts exactly where the last movement left off.
  pet_layout_t layout;
  pet_layout_init(&layout, 0);
  assert(pet_layout_tick(&layout, true, 0) == 154);
  int mid = pet_layout_tick(&layout, true, 190000);
  assert(mid > 99 && mid < 154);
  assert(pet_layout_tick(&layout, false, 190000) == mid);
  assert(pet_layout_tick(&layout, false, 570000) == 154);
  pet_layout_tick(&layout, true, 570000);
  assert(pet_layout_tick(&layout, true, 950000) == 99);
  assert(pet_layout_tick(&layout, true, 1200000) == 99);
  // Unread completion owns a living notify tail, even with other running work.
  pet_behavior_init(&b, 0);
  in = (pet_input_t){.linked=true,.preview=-1,.event=1,.event_kind=1,.unread=1};
  pet_behavior_tick(&b,&in,0);
  assert(!pet_behavior_tick(&b,&in,12000000));
  assert(!strcmp(pet_clips[b.clip].name,"done"));
  assert(pet_behavior_frame(&b,12000000)>=pet_clips[b.clip].loop_start);
  in.running=1;
  assert(!pet_behavior_tick(&b,&in,12000001));
  assert(!strcmp(pet_clips[b.clip].name,"done"));
  in.linked=false;in.source_bad=true;
  assert(!pet_behavior_tick(&b,&in,20000000));
  assert(!strcmp(pet_clips[b.clip].name,"done"));
  // Revealing a stopped snapshot changes type without replaying its arrival.
  in.event_kind=2;
  assert(pet_behavior_tick(&b,&in,21000000));
  assert(!strcmp(pet_clips[b.clip].name,"stop"));
  assert(pet_behavior_frame(&b,21000000)>=pet_clips[b.clip].loop_start);
  in.event_kind=1;
  assert(pet_behavior_tick(&b,&in,22000000));
  assert(!strcmp(pet_clips[b.clip].name,"done"));
  assert(pet_behavior_frame(&b,22000000)>=pet_clips[b.clip].loop_start);
  in.ack++;
  assert(pet_behavior_tick(&b,&in,23000000));
  assert(!strcmp(pet_clips[b.clip].name,"ack"));
  assert(pet_behavior_tick(&b,&in,29000000));
  assert(!strcmp(pet_clips[b.clip].name,"done"));
  in.unread=0;in.linked=true;in.source_bad=false;
  assert(pet_behavior_tick(&b,&in,30000000));
  assert(!strcmp(pet_clips[b.clip].name,"work"));
  // New arrivals and repeated OK cannot interrupt or extend the six-second ACK.
  in.ack++; pet_behavior_tick(&b,&in,31000000);
  in.event++; in.event_kind=2; in.unread=1;
  assert(!pet_behavior_tick(&b,&in,32000000));
  in.ack++;
  assert(!pet_behavior_tick(&b,&in,35000000));
  assert(b.start==31000000);
  assert(pet_behavior_tick(&b,&in,37000000));
  assert(!strcmp(pet_clips[b.clip].name,"stop"));
  assert(pet_behavior_frame(&b,37000000)>=pet_clips[b.clip].loop_start);
  pet_power_t power;
  pet_power_init(&power,0);
  assert(power.brightness == 85);
  assert(!pet_power_tick(&power,0,0,0,false,PET_SCREEN_DIM_US-1));
  assert(pet_power_tick(&power,0,0,0,false,PET_SCREEN_DIM_US));
  assert(power.brightness == 35 && !power.off);
  assert(!pet_power_tick(&power,0,0,0,false,PET_SCREEN_IDLE_US-1));
  assert(pet_power_tick(&power,0,0,0,false,PET_SCREEN_IDLE_US));
  assert(power.off && power.brightness == 0);
  assert(!pet_power_tick(&power,0,0,0,false,PET_SCREEN_IDLE_US+1));
  assert(pet_power_tick(&power,0,0,0,true,PET_SCREEN_IDLE_US+2));
  assert(power.brightness == 85);
  assert(pet_power_tick(&power,1,0,0,false,2*PET_SCREEN_IDLE_US));
  assert(power.brightness == 50);
  assert(!pet_power_tick(&power,1,0,0,false,3*PET_SCREEN_IDLE_US));
  assert(pet_power_tick(&power,1,1,1,false,3*PET_SCREEN_IDLE_US+1));
  assert(power.brightness == 85);
  assert(!pet_power_tick(&power,0,1,1,false,4*PET_SCREEN_IDLE_US));
  assert(power.brightness == 85); // Paused/unread messages retain priority.
  assert(pet_power_tick(&power,1,0,1,false,4*PET_SCREEN_IDLE_US+1));
  assert(power.brightness == 50); // Dismissed message reveals running level.
  assert(pet_power_tick(&power,0,0,1,false,4*PET_SCREEN_IDLE_US+2));
  assert(power.brightness == 85);
  assert(pet_power_tick(&power,0,0,1,false,5*PET_SCREEN_IDLE_US+1));
  assert(power.off); // Same event/heartbeats do not reset inactivity.
  assert(pet_power_tick(&power,0,0,2,false,5*PET_SCREEN_IDLE_US+2));
  assert(power.brightness == 85); // New event wakes even without unread snapshot.
  companion_state_t s = {.remaining = {5, 90}, .minutes = {10080, 300}};
  assert(pet_quota_window(&s) == 1);
  s.minutes[1] = 0;
  assert(pet_quota_window(&s) == 0);
  s.minutes[0] = 0;
  assert(pet_quota_window(&s) == -1);
  companion_alerts_t *a = calloc(1, sizeof(*a));
  uint8_t pixels[COMPANION_TILE_BYTES] = {0};
  assert(companion_alert_push(a, 1, 1, 12, "A", "local", pixels));
  assert(!companion_alert_push(a, 1, 1, 12, "A", "local", pixels));
  assert(a->count == 1);
  pixels[0] = 255;
  assert(a->items[0].pixels[0] == 0);
  for (unsigned i = 2; i <= 10; i++)
    assert(companion_alert_push(a, i, 1, 12, "B", "host", pixels));
  assert(a->count == 8 && a->dropped == 2);
  assert(companion_alert_top(a)->seq == 10);
  companion_alert_pop(a);
  assert(!companion_alert_push(a, 10, 1, 12, "B", "host", pixels));
  memset(a,0,sizeof(*a));
  pet_message_clock_t clock={0};
  assert(companion_alert_push(a,20,1,3,"A","local",pixels));
  assert(!pet_messages_tick(a,&clock,PET_HOME,0));
  assert(!pet_messages_tick(a,&clock,PET_HOME,10000000));
  assert(clock.remaining==5000000);
  assert(companion_alert_push(a,21,1,4,"B","remote",pixels));
  assert(!pet_messages_tick(a,&clock,PET_HOME,10000000));
  assert(clock.remaining==15000000);
  // Opening an information page pauses. A new message stays on that page.
  assert(!pet_messages_tick(a,&clock,PET_USAGE,15000000));
  assert(clock.remaining==10000000);
  assert(!pet_messages_tick(a,&clock,PET_USAGE,75000000));
  assert(clock.remaining==10000000 && a->count==2);
  assert(!pet_messages_tick(a,&clock,PET_HOME,75000000));
  assert(!pet_messages_tick(a,&clock,PET_HOME,84999999));
  assert(pet_messages_tick(a,&clock,PET_HOME,85000000));
  assert(a->count==1 && companion_alert_top(a)->seq==20 && clock.remaining==15000000);
  assert(!pet_messages_tick(a,&clock,PET_HOME,99999999));
  assert(pet_messages_tick(a,&clock,PET_HOME,100000000));
  assert(a->count==0);
  assert(!companion_alert_push(a,21,1,4,"B","remote",pixels));
  free(a);
  for (unsigned i = 0; i < PET_CLIP_COUNT; i++)
    assert(pet_clip_find(pet_clips[i].name) == (int)i);
}
static void paint_test(void) {
  uint8_t *pixels = malloc(PET_PACKED), *previous = malloc(PET_PACKED);
  uint16_t *full = malloc(240 * 320 * 2), tile[17 * 13];
  for (int i = 0; i < PET_PACKED; i++) { pixels[i] = i % 256; previous[i] = 255 - pixels[i]; }
  pet_view_t v = {.input = {.unread = 1}, .state = {.remaining = {75, 40}, .minutes = {300, 10080}, .fresh = 1}};
  v.usage_fresh=true;v.cards=2;v.cards_known=true;v.card_count=6;v.source_count=4;
  v.battery=-1;
  strcpy(v.usage.week,"1.8B");strcpy(v.usage.asof,"09/07");
  for(int i=0;i<7;i++){strcpy(v.usage.daily[i],i==2?"1B":"184M");strcpy(v.usage.dates[i],"09/07");v.usage.chart[i]=i*166;}
  v.usage.chart[0]=-1;
  for(int i=0;i<6;i++){strcpy(v.expires[i],"2026/09/30 18:00");strcpy(v.card_status[i],"available");}
  for(int i=0;i<4;i++) strcpy(v.sources[i],"remote source");
  for (v.page=PET_HOME;v.page<=PET_SYSTEM;v.page++)
  for (int pos = 3; pos <= 58; pos += 11)
  for (int dim = 0; dim < 2; dim++) for (unsigned blend = 0; blend <= 256; blend += 128) {
    v.input.running=pos==3?0:pos==14?1:16;
    pet_paint_t p = {.view = &v, .pixels = pixels, .previous = previous,
                     .blend = blend, .clip = 0, .avatar_y = pos, .reveal = 256, .linked = !dim, .quota_fresh = true};
    pet_paint(&p, (pet_rect_t){0, 0, 240, 320}, full);
    for (int y = 0; y < 320; y += 13) for (int x = 0; x < 240; x += 17) {
      pet_rect_t a = {x, y, x + 17 > 240 ? 240 - x : 17, y + 13 > 320 ? 320 - y : 13};
      pet_paint(&p, a, tile);
      for (int row = 0; row < a.h; row++)
        assert(!memcmp(tile + row * a.w, full + (y + row) * 240 + x, a.w * 2));
    }
  }
  free(pixels); free(previous); free(full);
}
int main(int argc, char **argv) {
  const unsigned counts[] = {35945, 36000, 12957};
  assert(!pet_sound_get(0) && !pet_sound_get(4) && !pet_sound_get(-1));
  for (int kind = 1; kind <= 3; kind++) {
    const pet_sound_t *sound = pet_sound_get(kind);
    assert(sound && sound->count == counts[kind-1]);
    int peak = 0;
    for (unsigned n = 0; n < sound->count; n++) {
      int sample = abs(sound->samples[n]);
      assert(sample <= 3000);
      if (sample > peak) peak = sample;
    }
    assert(peak > 2900);
    assert(sound->samples[0] == 0 && sound->samples[sound->count-1] == 0);
  }
  companion_state_t waiting;
  assert(companion_parse("CDX1|100|50|300|50|10080|1|0|3|1|Waiting|--|--|END", &waiting));
  assert(waiting.alert == 3);
  assert(!companion_parse("CDX1|100|50|300|50|10080|1|0|4|1|Invalid|--|--|END", &waiting));
  companion_alerts_t *sound_alerts = calloc(1, sizeof(*sound_alerts));
  uint8_t sound_pixels[COMPANION_TILE_BYTES] = {0};
  assert(companion_alert_push(sound_alerts, 100, 3, 0, "Waiting", "local", sound_pixels));
  assert(companion_alert_top(sound_alerts)->kind == 3);
  assert(!companion_alert_push(sound_alerts, 100, 3, 0, "Waiting", "local", sound_pixels));
  free(sound_alerts);

  assert(argc >= 2);
  logic();
  paint_test();
  FILE *f = fopen(argv[1], "rb");
  assert(f);
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  rewind(f);
  uint8_t *blob = malloc((size_t)size);
  assert(fread(blob, 1, (size_t)size, f) == (size_t)size);
  fclose(f);
  pet_decoder_t *d = malloc(sizeof(*d));
  pet_decoder_init(d, blob, (size_t)size);
  pet_rect_t r;
  uint32_t checksum = 0;
  unsigned count = 0;
  for (unsigned c = 0; c < PET_CLIP_COUNT; c++)
    for (unsigned n = 0; n < pet_clips[c].count; n++) {
      assert(pet_decode(d, c, n, &r));
      assert(r.w >= 0 && r.w <= PET_W && r.h >= 0 && r.h <= PET_W);
      pet_rect_t content = pet_content_bounds(d->pixels);
      for (unsigned j = 0; j < PET_PACKED; j++) if (d->pixels[j] != 0xee) {
        int x = (int)(j % (PET_W / 2)) * 2, y = (int)(j / (PET_W / 2));
        assert(x >= content.x && x + 1 < content.x + content.w &&
               y >= content.y && y < content.y + content.h);
      }
      checksum = crc(checksum, d->pixels, PET_PACKED);
      count++;
    }
  uint8_t expected[PET_PACKED];
  assert(pet_decode(d, 4, 110, &r));
  memcpy(expected, d->pixels, sizeof(expected));
  assert(pet_decode(d, 5, 14, &r));
  assert(pet_decode(d, 4, 110, &r));
  assert(!memcmp(expected, d->pixels, sizeof(expected)));
  /* A dirty rectangle must include every byte changed by skipped playback,
   * including the transition through a key frame. Compare with a fresh seek. */
  pet_decoder_t *reference = malloc(sizeof(*reference));
  for (unsigned c = 0; c < PET_CLIP_COUNT; c++) {
    pet_decoder_init(d, blob, (size_t)size);
    for (unsigned n = 0; n < pet_clips[c].count; n += 7) {
      memcpy(expected, d->pixels, sizeof(expected));
      assert(pet_decode(d, c, n, &r));
      pet_decoder_init(reference, blob, (size_t)size);
      pet_rect_t unused;
      assert(pet_decode(reference, c, n, &unused));
      assert(!memcmp(reference->pixels, d->pixels, PET_PACKED));
      for (unsigned j = 0; j < PET_PACKED; j++) {
        if (expected[j] == d->pixels[j])
          continue;
        int x = (int)(j % (PET_W / 2)) * 2;
        int y = (int)(j / (PET_W / 2));
        assert(x >= r.x && x + 1 < r.x + r.w && y >= r.y && y < r.y + r.h);
        pet_rect_t stripe = d->stripes[y / 16];
        assert(x >= stripe.x && x + 1 < stripe.x + stripe.w &&
               y >= stripe.y && y < stripe.y + stripe.h);
      }
    }
  }
  free(reference);
  assert(!pet_decode(d, PET_CLIP_COUNT, 0, &r));
  assert(!pet_decode(d, 0, pet_clips[0].count, &r));
  pet_decoder_init(d, blob, 1);
  assert(!pet_decode(d, 0, 0, &r));
  printf("CRC %08x FRAMES %u LOGIC PASS\n", checksum, count);
  if (argc >= 3) {
    pet_decoder_init(d, blob, (size_t)size);
    unsigned c = argc >= 4 ? (unsigned)atoi(argv[3]) : 0;
    assert(pet_decode(d, c, 72, &r));
    pet_view_t v = {
        .input = {.linked = true, .preview = -1},
        .state = {.remaining = {75, 40}, .minutes = {300, 10080}, .fresh = 1}};
    if (argc >= 5) {
      FILE *tile_file = fopen(argv[4], "rb");
      assert(tile_file);
      assert(fread(v.tile, 1, sizeof(v.tile), tile_file) == sizeof(v.tile));
      fclose(tile_file);
      v.input.unread = 2;
      v.alert_kind = 1;
      v.elapsed = 240;
    }
    pet_paint_t p = {.view = &v,
                     .pixels = d->pixels,
                     .blend = 256,
                     .avatar_y = v.input.unread ? 3 : 58,
                     .reveal = v.input.unread ? 256 : 0,
                     .clip = (int)c,
                     .linked = true,
                     .quota_fresh = true};
    f = fopen(argv[2], "wb");
    assert(f);
    fprintf(f, "P6\n240 320\n255\n");
    uint16_t row[240];
    for (int y = 0; y < 320; y++) {
      pet_paint(&p, (pet_rect_t){0, y, 240, 1}, row);
      for (int x = 0; x < 240; x++) {
        uint16_t n = (uint16_t)((row[x] << 8) | (row[x] >> 8));
        uint8_t rgb[] = {((n >> 11) & 31) * 255 / 31,
                         ((n >> 5) & 63) * 255 / 63, (n & 31) * 255 / 31};
        fwrite(rgb, 1, 3, f);
      }
    }
    fclose(f);
  }
  free(d);
  free(blob);
  return 0;
}
