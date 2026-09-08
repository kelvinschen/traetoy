from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
image=Image.open(root/'firmwares/codex/assets/images/codex-official-light.png').convert('RGBA')
image=image.resize((32,32),Image.Resampling.LANCZOS)
# LVGL ARGB8888 byte order on ESP32-C3 is BGRA.
data=bytes(component for r,g,b,a in image.getdata() for component in (b,g,r,a))
out=root/'firmwares/codex/main/codex_logo.c'
lines=['#include "lvgl.h"','static const uint8_t logo_data[] = {']
lines += [','.join(f'0x{x:02x}' for x in data[i:i+24])+',' for i in range(0,len(data),24)]
lines+=['};','const lv_image_dsc_t codex_logo = {','.header = {.magic=LV_IMAGE_HEADER_MAGIC, .cf=LV_COLOR_FORMAT_ARGB8888, .w=32, .h=32, .stride=128},','.data_size=sizeof(logo_data), .data=logo_data','};']
out.write_text('\n'.join(lines)+'\n')
