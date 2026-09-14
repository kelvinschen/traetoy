#!/usr/bin/env python3
"""Bake the repository's OFL Montserrat font into small 4-bit antialiased glyphs."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import hashlib

root = Path(__file__).resolve().parents[1]
source = root.parent / 'codex/assets/fonts/Montserrat-Medium.ttf'
records, data, faces = [], bytearray(), []
for size in (13, 18, 34, 60, 11):
    font = ImageFont.truetype(str(source), size)
    faces.append(len(records))
    for code in range(32, 127):
        ch = chr(code)
        left, top, right, bottom = font.getbbox(ch, anchor='lt')
        width, height = max(1, right-left), max(1, bottom-top)
        image = Image.new('L', (width, height))
        ImageDraw.Draw(image).text((-left, -top), ch, font=font, fill=255, anchor='lt')
        pixels = list(image.tobytes())
        offset = len(data)
        for i in range(0, len(pixels), 2):
            a = (pixels[i]*15+127)//255
            b = (pixels[i+1]*15+127)//255 if i+1<len(pixels) else 0
            data.append((a<<4)|b)
        # getbbox(..., anchor='lt') starts at visible ink; use baseline metrics
        # for consistent cap/x-height alignment across letters, digits and symbols.
        _, asc_top, _, _ = font.getbbox(ch, anchor='la')
        records.append((offset,width,height,left,asc_top,round(font.getlength(ch))))
header='''/* Generated from Montserrat-Medium.ttf (SIL OFL 1.1); see vendor/fonts/OFL.txt. */
#pragma once
#include <stdint.h>
typedef struct { uint32_t offset; uint8_t width,height; int8_t left,top; uint8_t advance; } pet_glyph_t;
extern const pet_glyph_t pet_glyphs[475];
extern const uint8_t pet_font_pixels[];
'''
(root/'main/pet_font.h').write_text(header)
(root/'main/pet_font.c').write_text('#include "pet_font.h"\n/* Source SHA-256: '+hashlib.sha256(source.read_bytes()).hexdigest()+' */\nconst uint8_t pet_font_pixels[]={\n'+',\n'.join(','.join(str(v) for v in data[i:i+24]) for i in range(0,len(data),24))+'\n};\nconst pet_glyph_t pet_glyphs[]={\n'+',\n'.join('{'+','.join(map(str,r))+'}' for r in records)+'\n};\n')
(root/'vendor/fonts').mkdir(exist_ok=True)
(root/'vendor/fonts/OFL.txt').write_bytes((source.parent/'Montserrat-OFL.txt').read_bytes())
print(f'Font: {len(data)} bytes + {len(records)} glyph records; sizes 11/13/18/34/60px, 16 alpha levels')
