/* Codex Pet: one transport/protocol owner, one bounded 60 Hz display owner. */
#include "bsp_audio.h"
#include "pet_sound_pcm.h"
#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "bsp_i2c.h"
#include "companion_alerts.h"
#include "companion_ble.h"
#include "companion_info.h"
#include "companion_protocol.h"
#include "companion_tiles.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_timer.h"
#include "firmware_identity.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "pet_behavior.h"
#include "pet_codec.h"
#include "pet_ui.h"
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern const uint8_t bloub_start[] asm("_binary_bloub_bin_start");
extern const uint8_t bloub_end[] asm("_binary_bloub_bin_end");
typedef struct {
  int type;
  uint32_t session, counter;
  union {
    companion_state_t state;
    companion_tile_t tile;
    companion_metadata_t meta;
    companion_info_t info;
    int command;
  };
} message_t;
static QueueHandle_t messages, keys, tones;
static SemaphoreHandle_t view_lock, dma_done;
static TaskHandle_t display_task;
static companion_state_t state = {.remaining = {-1, -1}};
static companion_metadata_t metadata;
static companion_info_t info;
static companion_tiles_t titles;
static companion_alerts_t alerts;
static pet_view_t view;
static int page, selected, preview = -1;
static int64_t last_packet, last_info, last_metadata, last_tone;
static pet_message_clock_t message_clock;
static pet_power_t power;
static int battery = -1;
static int lease = -1;
static uint32_t lease_session;
static int64_t lease_at;
static unsigned event_no, ack_no, version, shot_requested;
static int latest_event_kind;
static bool audio_ok;
static struct {
  uint32_t fps10, frames, skipped, decode_us, flush_us, max_us;
  unsigned clip, frame, stack, tones, brightness;
  bool display_off;
  uint32_t motion_frames, motion_avg_us, motion_max_us;
} stats;
static uint8_t tile_scratch[COMPANION_TILE_BYTES];

static void respond(const message_t *m, const char *line) {
  if (m->session)
    companion_ble_reply(m->session, m->counter, line);
  else
    printf("%s\n", line);
}
static bool parse(const char *line, message_t *m) {
  bool commit = false;
  m->type = 0;
  if (!strcmp(line, "PASSPORT?|END"))
    m->type = 7;
  else if (!strcmp(line, "CDXB|RELEASE|END"))
    m->type = 5;
  else if (companion_parse(line, &m->state))
    m->type = 1;
  else if (companion_parse_tile(line, &m->tile, &commit))
    m->type = commit ? 3 : 2;
  else if (companion_parse_metadata(line, &m->meta))
    m->type = 4;
  else if (companion_parse_info(line, &m->info))
    m->type = 6;
  /* Diagnostics are USB-only and cannot be invoked through unauthenticated
   * radio. */
  else if (!m->session) {
    if (!strcmp(line, "PET|STATS|END"))
      m->type = 8;
    else if (!strcmp(line, "PET|SHOT|END"))
      m->type = 9;
    else {
      int n, used = 0;
      if (sscanf(line, "PET|CLIP|%d|END%n", &n, &used) == 1 && used > 0 &&
          !line[used] && n >= -1 && n < PET_CLIP_COUNT) {
        m->type = 10;
        m->command = n;
      } else {
        used = 0;
        if (sscanf(line, "PET|IDLE|%d|END%n", &n, &used) == 1 && used > 0 &&
            !line[used] && n >= 0 && n <= 3600) {
          m->type = 12;
          m->command = n;
          return true;
        }
        used = 0;
        if (sscanf(line, "PET|KEY|%d|END%n", &n, &used) == 1 && used > 0 &&
            !line[used] && n >= 0 && n <= 4) {
          m->type = 11;
          m->command = n;
        }
      }
    }
  }
  return m->type != 0;
}
static bool ble_receive(const char *line, uint32_t session, uint32_t counter) {
  message_t m = {.session = session, .counter = counter};
  return parse(line, &m) && xQueueSend(messages, &m, 0) == pdTRUE;
}
static void reader(void *arg) {
  (void)arg;
  char line[7168];
  uint8_t bytes[128];
  size_t used = 0;
  bool overflow = false;
  message_t m;
  for (;;) {
    int n = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), pdMS_TO_TICKS(50));
    for (int i = 0; i < n; i++) {
      char ch = (char)bytes[i];
      if (ch == '\r')
        continue;
      if (ch == '\n') {
        line[used] = 0;
        m.session = m.counter = 0;
        if (!overflow && used == 78 && !strncmp(line, "CDXB|PAIR|", 10) &&
            !strcmp(line + 74, "|END")) {
          char id[13];
          line[74] = 0;
          if (companion_ble_provision(line + 10, id))
            printf("CDX_BLE_PAIRED %s\n", id);
          else
            printf("CDX_ERR provisioning\n");
        } else if (!overflow && parse(line, &m))
          xQueueSend(messages, &m, portMAX_DELAY);
        else if (used)
          printf("CDX_ERR invalid_frame\n");
        used = 0;
        overflow = false;
      } else if (used < sizeof(line) - 1)
        line[used++] = ch;
      else
        overflow = true;
    }
  }
}
static void on_key(bsp_btn_t b, bsp_btn_ev_t ev, void *arg) {
  (void)arg;
  int k = -1;
  if (ev == BSP_BTN_CLICK)
    k = (int)b;
  else if (ev == BSP_BTN_LONG && b == BSP_BTN_OK)
    k = 3;
  else if (ev == BSP_BTN_LONG && b == BSP_BTN_UP)
    k = 4;
  if (k >= 0)
    xQueueSend(keys, &k, 0);
}
static void audio(void *arg) {
  (void)arg;
  int kind;
  int16_t pcm[256];
  for (;;) {
    if (!xQueueReceive(tones, &kind, portMAX_DELAY) || !audio_ok)
      continue;
    const pet_sound_t *sound = pet_sound_get(kind);
    if (!sound) continue;
    for (unsigned offset = 0; offset < sound->count; offset += 256) {
      for (unsigned i = 0; i < 256; i++)
        pcm[i] = offset + i < sound->count ? sound->samples[offset + i] : 0;
      if (bsp_audio_write(pcm, sizeof(pcm)) != ESP_OK) break;
    }
    memset(pcm, 0, sizeof(pcm));
    bsp_audio_write(pcm, sizeof(pcm));
    xSemaphoreTake(view_lock, portMAX_DELAY);
    stats.tones++;
    xSemaphoreGive(view_lock);
    printf("PET_AUDIO_DONE kind=%d samples=%u rate=%u\n", kind, sound->count, PET_SOUND_RATE);
  }
}
static void publish(int64_t now) {
  xSemaphoreTake(view_lock, portMAX_DELAY);
  view.screen_off = power.off;
  view.brightness = power.brightness;
  view.input =
      (pet_input_t){.linked = last_packet && now - last_packet < 20000000,
                    .running = state.running,
                    .unread = alerts.count,
                    .event = event_no,
                    .ack = ack_no,
                    .event_kind = latest_event_kind,
                    .preview = preview};
  if (last_info)
    for (int i = 0; i < info.source_count; i++)
      view.input.source_bad |= !info.healthy[i];
  view.state = state;
  view.usage = metadata;
  view.usage_fresh = last_metadata && now-last_metadata<900000000;
  view.cards = last_info ? info.available : -1;
  view.cards_known = last_info && info.known;
  view.card_count = info.count;
  for (int i=0;i<info.count;i++) {
    strcpy(view.expires[i],info.cards[i].expires);
    strcpy(view.card_status[i],info.cards[i].status);
  }
  view.source_count=info.source_count;
  for (int i=0;i<info.source_count;i++) {
    strcpy(view.sources[i],info.sources[i]);
    view.sources_healthy[i]=info.healthy[i] && now-last_info<30000000;
  }
  view.info_age=last_info && info.quota_age>=0 ? info.quota_age+(int)((now-last_info)/1000000) : -1;
  view.link_age=last_packet?(int)((now-last_packet)/1000000):-1;
  view.uptime=(unsigned)(now/1000000);
  view.battery=battery;
  view.transport=lease;
  view.page = page;
  view.selected = selected;
  view.count = titles.count;
  view.version = ++version;
  view.dropped = alerts.dropped;
  view.elapsed = -1;
  view.host[0] = 0;
  if (page == PET_TASKS && titles.count) {
    if (selected >= titles.count)
      selected = titles.count - 1;
    view.selected = selected;
    companion_tiles_read(&titles, selected, view.tile);
    for (int i = 0; i < metadata.count; i++)
      if (metadata.ids[i] == titles.ids[selected])
        view.elapsed = metadata.elapsed[i];
  }
  if (page == PET_ALERT || page == PET_HOME) {
    const companion_alert_t *a = companion_alert_top(&alerts);
    if (a) {
      memcpy(view.tile, a->pixels, sizeof(view.tile));
      view.elapsed = a->elapsed;
      view.alert_kind = a->kind;
      view.input.event_kind = a->kind;
      strcpy(view.host, a->host);
    }
  }
  xSemaphoreGive(view_lock);
}
static void key(int k, int64_t now) {
  bool waking = power.off;
  pet_power_tick(&power, state.running, alerts.count, event_no, true, now);
  if (waking) return;
  if (k == 3) {
    page = PET_HOME;
    preview = -1;
    return;
  }
  if (k == 4) {
    page = PET_GALLERY;
    preview = 0;
    return;
  }
  if (page == PET_GALLERY) {
    if (k == BSP_BTN_OK) {
      page = PET_HOME;
      preview = -1;
    } else
      preview = (preview + (k == BSP_BTN_UP ? 1 : PET_CLIP_COUNT - 1)) %
                PET_CLIP_COUNT;
    return;
  }
  if (k == BSP_BTN_OK && page == PET_HOME) {
    companion_alert_pop(&alerts);
    ack_no++;
  }
  page=pet_page_key(page,k);
}
static bool dma_finished(esp_lcd_panel_io_handle_t io,
                         esp_lcd_panel_io_event_data_t *edata, void *arg) {
  (void)io;
  (void)edata;
  (void)arg;
  BaseType_t wake = pdFALSE;
  xSemaphoreGiveFromISR(dma_done, &wake);
  return wake == pdTRUE;
}
static void wake_frame(void *arg) {
  (void)arg;
  xTaskNotifyGive(display_task);
}
#define STRIPE 16
static uint16_t *dma[2];
static void flush_regions(const pet_paint_t *paint, const pet_rect_t *regions,
                          unsigned count, int dx, int dy) {
  bool pending = false;
  unsigned bank = 0;
  for (unsigned i = 0; i < count; i++) {
    pet_rect_t r = regions[i];
    r.x += dx;
    r.y += dy;
    if (r.w <= 0 || r.h <= 0)
      continue;
    for (int y = r.y; y < r.y + r.h; y += STRIPE) {
      int h = r.y + r.h - y;
      if (h > STRIPE)
        h = STRIPE;
      pet_rect_t a = {r.x, y, r.w, h};
      pet_paint(paint, a, dma[bank]);
      if (pending)
        xSemaphoreTake(dma_done, portMAX_DELAY);
      ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
          bsp_display_panel(), a.x, a.y, a.x + a.w, a.y + a.h, dma[bank]));
      pending = true;
      bank ^= 1;
    }
  }
  if (pending)
    xSemaphoreTake(dma_done, portMAX_DELAY);
}
static void flush(const pet_paint_t *paint, pet_rect_t r) {
  flush_regions(paint, &r, 1, 0, 0);
}
static pet_rect_t unite(pet_rect_t a, pet_rect_t b) {
  if (!a.w || !a.h)
    return b;
  if (!b.w || !b.h)
    return a;
  int x = a.x < b.x ? a.x : b.x, y = a.y < b.y ? a.y : b.y,
      ex = a.x + a.w > b.x + b.w ? a.x + a.w : b.x + b.w,
      ey = a.y + a.h > b.y + b.h ? a.y + a.h : b.y + b.h;
  return (pet_rect_t){x, y, ex - x, ey - y};
}
static void screenshot(const pet_paint_t *p) {
  printf("PET_SHOT_BEGIN 240 320 RGB565BE\n");
  char line[240 * 4 + 1];
  static const char hex[] = "0123456789abcdef";
  for (int y = 0; y < 320; y++) {
    pet_paint(p, (pet_rect_t){0, y, 240, 1}, dma[0]);
    const uint8_t *bytes = (const uint8_t *)dma[0];
    for (int i = 0; i < 480; i++) {
      line[i * 2] = hex[bytes[i] >> 4];
      line[i * 2 + 1] = hex[bytes[i] & 15];
    }
    line[960] = '\n';
    // The VFS stdout path may short-write under USB backpressure. A screenshot
    // is diagnostic and may block; retain every byte until the host drains it.
    size_t sent = 0;
    while (sent < sizeof(line)) {
      int n = usb_serial_jtag_write_bytes(line + sent, sizeof(line) - sent,
                                          portMAX_DELAY);
      if (n > 0) sent += (size_t)n;
    }
  }
  printf("PET_SHOT_END\n");
}
static void display(void *arg) {
  (void)arg;
  display_task = xTaskGetCurrentTaskHandle();
  pet_decoder_t *decoder = calloc(1, sizeof(*decoder));
  uint8_t *previous = malloc(PET_PACKED);
  configASSERT(decoder && previous);
  pet_decoder_init(decoder, bloub_start, (size_t)(bloub_end - bloub_start));
  memset(previous, 0xee, PET_PACKED);
  for (int i = 0; i < 2; i++) {
    dma[i] = heap_caps_malloc(240 * STRIPE * 2,
                              MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    configASSERT(dma[i]);
  }
  esp_lcd_panel_io_callbacks_t cb = {.on_color_trans_done = dma_finished};
  ESP_ERROR_CHECK(
      esp_lcd_panel_io_register_event_callbacks(bsp_display_io(), &cb, NULL));
  esp_timer_handle_t timer;
  esp_timer_create_args_t ta = {.callback = wake_frame, .name = "pet_frame"};
  ESP_ERROR_CHECK(esp_timer_create(&ta, &timer));
  int64_t now = esp_timer_get_time(), next = now, epoch = now, fade_at = now;
  pet_behavior_t behavior;
  pet_behavior_init(&behavior, now);
  pet_view_t local = {0};
  pet_layout_t layout;
  pet_layout_init(&layout, now);
  int old_y = 58, old_page = -1;
  pet_rect_t old_content = {0}, fade_content = {0};
  companion_state_t old_state = {0};
  unsigned old_reveal = 0;
  unsigned old_unread = 0, last_shot = 0;
  bool old_link = false, old_fresh = false, old_bad = false,
       was_blending = false;
  unsigned old_version = 0;
  uint32_t frames = 0, skipped = 0, max_us = 0;
  uint64_t decode_total = 0, flush_total = 0, motion_total = 0;
  uint32_t motion_frames = 0, motion_max = 0;
  int last_clip = -1, last_frame = -1;
  bool screen_off = false;
  unsigned brightness = PET_BRIGHT_ACTIVE;
  for (;;) {
    now = esp_timer_get_time();
    xSemaphoreTake(view_lock, portMAX_DELAY);
    if (last_clip >= 0) { stats.clip = (unsigned)last_clip; stats.frame = (unsigned)last_frame; }
    local = view;
    local.fps10 = stats.fps10;
    unsigned shot = shot_requested;
    xSemaphoreGive(view_lock);
    if (local.screen_off) {
      if (!screen_off) {
        bsp_display_backlight(0);
        xSemaphoreTake(view_lock, portMAX_DELAY);
        stats.display_off = true;
        stats.brightness = brightness = 0;
        stats.fps10 = 0;
        xSemaphoreGive(view_lock);
      }
      screen_off = true;
      old_page = -1; // Force a complete refresh before lighting the panel again.
      next = epoch = now;
      frames = skipped = max_us = 0;
      decode_total = flush_total = 0;
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }
    int avatar_y = local.page == PET_HOME ? pet_layout_tick(&layout, local.input.unread > 0, now) - 96 : 48;
    unsigned progress = local.page == PET_HOME ? (unsigned)((58 - avatar_y) * 256 / 55) : 0;
    unsigned reveal = progress > 192 ? (progress - 192) * 4 : 0;
    bool change = pet_behavior_tick(&behavior, &local.input, now);
    if (change) {
      memcpy(previous, decoder->pixels, PET_PACKED);
      fade_content = pet_content_bounds(previous);
      fade_at = now;
    }
    unsigned frame = pet_behavior_frame(&behavior, now);
    if (behavior.clip == last_clip && frame > (unsigned)(last_frame + 1))
      skipped += frame - last_frame - 1;
    pet_rect_t dirty = {0};
    int64_t begin = esp_timer_get_time();
    bool ok = pet_decode(decoder, (unsigned)behavior.clip, frame, &dirty);
    configASSERT(ok);
    decode_total += (uint64_t)(esp_timer_get_time() - begin);
    if (dirty.w) {
      dirty.x += 24;
      dirty.y += avatar_y;
    }
    unsigned mix = (unsigned)((now - fade_at) * 256 / 140000);
    if (mix > 256)
      mix = 256;
    pet_paint_t paint = {.view = &local,
                         .pixels = decoder->pixels,
                         .previous = previous,
                         .blend = mix,
                         .clip = behavior.clip,
                         .avatar_y = avatar_y,
                         .reveal = reveal,
                         .linked = local.input.linked,
                         .quota_fresh =
                             local.input.linked && local.state.fresh};
    pet_rect_t content = pet_content_bounds(decoder->pixels);
    if (mix < 256) content = unite(content, fade_content);
    if (content.w) { content.x += 24; content.y += avatar_y; }
    bool moved = old_y != avatar_y;
    bool repaint_avatar = moved || mix < 256 || was_blending ||
                          old_link != paint.linked ||
                          old_bad != local.input.source_bad;
    if (repaint_avatar)
      dirty = unite(content, old_content);
    begin = esp_timer_get_time();
    if (old_page != local.page ||
        ((local.page != PET_HOME && local.page != PET_GALLERY) &&
         (old_version != local.version || brightness != local.brightness))) {
      flush(&paint, (pet_rect_t){0, 0, 240, 320});
    } else if (local.page == PET_HOME || local.page == PET_GALLERY) {
      if (repaint_avatar)
        flush(&paint, dirty);
      else {
        flush_regions(&paint, decoder->stripes, PET_W / 16, 24, avatar_y);
      }
      if (local.page == PET_GALLERY &&
          (change || (old_version != local.version || brightness != local.brightness))) {
        flush(&paint, (pet_rect_t){0, 0, 240, 36});
        flush(&paint, (pet_rect_t){0, 270, 240, 50});
      }
      if (old_link != paint.linked || old_bad != local.input.source_bad)
        flush(&paint, (pet_rect_t){0, 0, 240, 30});
      if (local.page == PET_HOME &&
          (old_reveal != reveal || old_unread != local.input.unread ||
           (local.input.unread && old_version != local.version)))
        flush(&paint, (pet_rect_t){18, 174, 204, 114});
      if (memcmp(&old_state, &local.state, sizeof(old_state)) || paint.quota_fresh != old_fresh ||
          old_link != paint.linked || old_bad != local.input.source_bad)
        flush(&paint, (pet_rect_t){0, 290, 240, 30});
    }
    flush_total += (uint64_t)(esp_timer_get_time() - begin);
    frames++;
    uint32_t frame_us = (uint32_t)(esp_timer_get_time() - now);
    if (moved) {
      motion_frames++;
      motion_total += frame_us;
      if (frame_us > motion_max) motion_max = frame_us;
    }
    if (frame_us > max_us)
      max_us = frame_us;
    if (brightness != local.brightness) {
      bsp_display_backlight(local.brightness);
      brightness = local.brightness;
      screen_off = false;
      xSemaphoreTake(view_lock, portMAX_DELAY);
      stats.display_off = false;
      stats.brightness = brightness;
      xSemaphoreGive(view_lock);
    }
    was_blending = mix < 256;
    old_page = local.page;
    old_version = local.version;
    old_unread = local.input.unread;
    old_link = paint.linked;
    old_fresh = paint.quota_fresh;
    old_bad = local.input.source_bad;
    old_state = local.state;
    old_y = avatar_y;
    old_content = content;
    old_reveal = reveal;
    last_clip = behavior.clip;
    last_frame = (int)frame;
    if (now - epoch >= 5000000) {
      xSemaphoreTake(view_lock, portMAX_DELAY);
      stats.fps10 = (uint32_t)((uint64_t)frames * 10000000 / (now - epoch));
      stats.frames += frames;
      stats.skipped += skipped;
      stats.decode_us = frames ? (uint32_t)(decode_total / frames) : 0;
      stats.flush_us = frames ? (uint32_t)(flush_total / frames) : 0;
      stats.max_us = max_us;
      stats.motion_frames = motion_frames;
      stats.motion_avg_us = motion_frames ? (uint32_t)(motion_total / motion_frames) : 0;
      stats.motion_max_us = motion_max;
      stats.clip = behavior.clip;
      stats.frame = frame;
      stats.stack = uxTaskGetStackHighWaterMark(NULL);
      xSemaphoreGive(view_lock);
      epoch = now;
      frames = skipped = max_us = 0;
      decode_total = flush_total = 0;
    }
    if (shot != last_shot) {
      screenshot(&paint);
      last_shot = shot;
      next = esp_timer_get_time();
      epoch = next;
      frames = skipped = 0;
      decode_total = flush_total = 0;
    }
    next += 1000000 / PET_FPS;
    int64_t remaining_us = next - esp_timer_get_time();
    if (remaining_us > 100) {
      ESP_ERROR_CHECK(esp_timer_start_once(timer, (uint64_t)remaining_us));
      ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    } else {
      next = esp_timer_get_time();
      vTaskDelay(1);
    }
  }
}
void app_main(void) {
  messages = xQueueCreate(2, sizeof(message_t));
  keys = xQueueCreate(8, sizeof(int));
  tones = xQueueCreate(1, sizeof(int));
  view_lock = xSemaphoreCreateMutex();
  dma_done = xSemaphoreCreateBinary();
  configASSERT(messages && keys && tones && view_lock && dma_done);
  ESP_ERROR_CHECK(bsp_i2c_init());
  ESP_ERROR_CHECK(bsp_display_init());
  bsp_display_backlight(PET_BRIGHT_ACTIVE);
  stats.brightness = PET_BRIGHT_ACTIVE;
  audio_ok = bsp_audio_init() == ESP_OK &&
             bsp_audio_set_format(16000, 16, 1) == ESP_OK;
  if (audio_ok)
    bsp_audio_set_volume(65);
  bool battery_ok=bsp_battery_init()==ESP_OK;
  if (battery_ok) battery=bsp_battery_soc();
  ESP_ERROR_CHECK(bsp_button_init(on_key, NULL));
  usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 2048,
                                         .rx_buffer_size = 8192};
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
  usb_serial_jtag_vfs_use_driver();
  setvbuf(stdout, NULL, _IOLBF, 0);
  pet_power_init(&power, esp_timer_get_time());
  publish(esp_timer_get_time());
  configASSERT(xTaskCreate(audio, "pet_audio", 3072, NULL, 2, NULL) == pdPASS);
  ESP_ERROR_CHECK(companion_ble_start(ble_receive));
  configASSERT(xTaskCreate(reader, "pet_usb", 14336, NULL, 3, NULL) == pdPASS);
  configASSERT(xTaskCreate(display, "pet_display", 10240, NULL, 4, NULL) ==
               pdPASS);
  printf("PET_READY v1 target_fps=60 audio=%d heap=%lu\n", audio_ok,
         (unsigned long)esp_get_free_heap_size());
  int64_t next_status=0, next_battery=0;
  for (;;) {
    message_t m;
    bool got = xQueueReceive(messages, &m, pdMS_TO_TICKS(50)) == pdTRUE;
    int64_t now = esp_timer_get_time();
    int keycode;
    bool changed = pet_messages_tick(&alerts,&message_clock,page,now);
    while (xQueueReceive(keys, &keycode, 0)) {
      key(keycode, now);
      changed = true;
    }
    if (now>=next_status) {
      next_status=now+1000000;
      changed = true;
    }
    if (battery_ok && now>=next_battery) {
      battery=bsp_battery_soc();
      next_battery=now+10000000;
      changed=true;
    }
    bool linked = last_packet && now - last_packet < 20000000;
    if (linked != view.input.linked)
      changed = true;
    companion_ble_tick();
    char ack[384] = {0};
    if (got) {
      if (m.type == 7) {
        respond(&m, "PASSPORT|" FIRMWARE_ID
                    "|" FIRMWARE_VERSION "|1|codex-v1,completion-wide-v1,info-v1,waiting-alert-v1|END");
        goto finish;
      }
      if (m.type == 5) {
        lease = -1;
        companion_tiles_cancel(&titles);
        respond(&m, "CDX_RELEASE_ACK");
        goto finish;
      }
      if (m.type == 8) {
        xSemaphoreTake(view_lock, portMAX_DELAY);
        snprintf(ack, sizeof(ack),
                 "PET_STATS fps=%u.%u frames=%lu skipped=%lu decode_us=%lu "
                 "flush_us=%lu max_us=%lu clip=%s frame=%u heap=%lu "
                 "min_heap=%lu stack=%u unread=%u page=%d audio=%d tones=%u "
                 "event=%u ack=%u screen_off=%d display_off=%d brightness=%u applied_brightness=%u idle_s=%lu motion_frames=%lu motion_avg_us=%lu motion_max_us=%lu",
                 (unsigned)(stats.fps10 / 10), (unsigned)(stats.fps10 % 10),
                 (unsigned long)stats.frames, (unsigned long)stats.skipped,
                 (unsigned long)stats.decode_us, (unsigned long)stats.flush_us,
                 (unsigned long)stats.max_us, pet_clips[stats.clip].name,
                 stats.frame, (unsigned long)esp_get_free_heap_size(),
                 (unsigned long)esp_get_minimum_free_heap_size(), stats.stack,
                 alerts.count, page, audio_ok, stats.tones, event_no, ack_no, power.off, stats.display_off, power.brightness, stats.brightness,
                 (unsigned long)((now-power.active_at)/1000000),
                 (unsigned long)stats.motion_frames, (unsigned long)stats.motion_avg_us,
                 (unsigned long)stats.motion_max_us);
        xSemaphoreGive(view_lock);
        respond(&m, ack);
        goto finish;
      }
      if (m.type == 9) {
        xSemaphoreTake(view_lock, portMAX_DELAY);
        shot_requested++;
        xSemaphoreGive(view_lock);
        goto finish;
      }
      if (m.type == 10) {
        preview = m.command;
        page = preview >= 0 ? PET_GALLERY : PET_HOME;
        changed = true;
        respond(&m, "PET_CLIP_ACK");
        goto finish;
      }
      if (m.type == 12) {
        power.active_at = now - (int64_t)m.command * 1000000;
        changed = true;
        respond(&m, "PET_IDLE_ACK");
        goto finish;
      }
      if (m.type == 11) {
        key(m.command, now);
        changed = true;
        respond(&m, "PET_KEY_ACK");
        goto finish;
      }
      int source = m.session ? 1 : 0;
      if (lease == 0 && source == 1 && usb_serial_jtag_is_connected() &&
          now - lease_at < 10000000) {
        respond(&m, "CDX_ERR transport_busy");
        goto finish;
      }
      if (source != lease || m.session != lease_session)
        companion_tiles_cancel(&titles);
      lease = source;
      lease_session = m.session;
      lease_at = now;
      if (m.type == 2) {
        bool ok = companion_tiles_stage(&titles, &m.tile);
        snprintf(ack, sizeof(ack), "CDX_TILE_%s %lu %d", ok ? "ACK" : "ERR",
                 (unsigned long)m.tile.seq, m.tile.index);
      }
      if (m.type == 3) {
        bool ok = companion_tiles_commit(&titles, m.tile.seq, m.tile.count);
        snprintf(ack, sizeof(ack), "CDX_LIST_%s %lu count=%d",
                 ok ? "ACK" : "ERR", (unsigned long)m.tile.seq, titles.count);
        changed |= ok;
      }
      if (m.type == 4) {
        metadata = m.meta;
        last_metadata = now;
        snprintf(ack, sizeof(ack), "CDX_META_ACK %lu",
                 (unsigned long)metadata.seq);
        changed = true;
      }
      if (m.type == 6) {
        info = m.info;
        last_info = now;
        snprintf(ack, sizeof(ack), "CDX_INFO_ACK %lu", (unsigned long)info.seq);
        changed = true;
      }
      if (m.type == 1) {
        state = m.state;
        last_packet = now;
        changed = true;
        if (state.alert) {
          companion_tiles_read(&titles, COMPANION_ALERT_TILE, tile_scratch);
          int elapsed = metadata.seq == state.seq ? metadata.alert_seconds : -1;
          if (companion_alert_push(
                  &alerts, state.seq, state.alert, elapsed, state.title,
                  metadata.seq == state.seq ? metadata.alert_host : "",
                  tile_scratch)) {
            event_no++;
            latest_event_kind = state.alert;
            if (!last_tone || now - last_tone > 2000000) {
              xQueueSend(tones, &state.alert, 0);
              last_tone = now;
            }
          }
        }
        snprintf(
            ack, sizeof(ack),
            "CDX_ACK %lu %d %d windows=%d page=%d tasks=%d unread=%u alert=%lu "
            "link=%s heap=%lu min_heap=%lu",
            (unsigned long)state.seq, state.remaining[0], state.remaining[1],
            (state.minutes[0] > 0) + (state.minutes[1] > 0), page, titles.count,
            alerts.count,
            (unsigned long)(companion_alert_top(&alerts)
                                ? companion_alert_top(&alerts)->seq
                                : 0),
            source ? "ble" : "usb", (unsigned long)esp_get_free_heap_size(),
            (unsigned long)esp_get_minimum_free_heap_size());
      }
      if (ack[0])
        respond(&m, ack);
    }
  finish:
    changed |= pet_power_tick(&power, state.running, alerts.count, event_no, false, now);
    changed |= pet_messages_tick(&alerts,&message_clock,page,now);
    if (changed)
      publish(now);
  }
}
