/*******************************************************************************
 * Size: 8 px
 * Bpp: 4
 * Opts: --no-compress --no-prefilter --bpp 4 --size 8 --font ai-passport/assets/fonts/Montserrat-Medium.ttf --symbols KMBTPE --format lvgl --lv-include lvgl.h --lv-font-name companion_unit_font -o ai-passport/assets/fonts/montserrat_medium_8_units.c
 ******************************************************************************/

#ifdef LV_LVGL_H_INCLUDE_SIMPLE
#include "lvgl.h"
#else
#include "lvgl.h"
#endif

#ifndef COMPANION_UNIT_FONT
#define COMPANION_UNIT_FONT 1
#endif

#if COMPANION_UNIT_FONT

/*-----------------
 *    BITMAPS
 *----------------*/

/*Store the image of the glyphs*/
static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {
    /* U+0042 "B" */
    0x2d, 0x99, 0xb1, 0x2a, 0x0, 0x84, 0x2d, 0x9a,
    0xd1, 0x2a, 0x0, 0x39, 0x2d, 0x99, 0xb4,

    /* U+0045 "E" */
    0x2e, 0xaa, 0x82, 0xa0, 0x0, 0x2d, 0xaa, 0x42,
    0xa0, 0x0, 0x2e, 0xaa, 0x90,

    /* U+004B "K" */
    0x2a, 0x1, 0xa2, 0x2a, 0x1b, 0x20, 0x2c, 0xc7,
    0x0, 0x2d, 0x19, 0x50, 0x2a, 0x0, 0xa4,

    /* U+004D "M" */
    0x2c, 0x0, 0x3, 0xc2, 0xd7, 0x0, 0xbc, 0x29,
    0x92, 0x84, 0xc2, 0x91, 0xb9, 0xc, 0x29, 0x3,
    0x0, 0xc0,

    /* U+0050 "P" */
    0x2e, 0xaa, 0x90, 0x2a, 0x0, 0x84, 0x2a, 0x0,
    0xa3, 0x2e, 0xaa, 0x60, 0x2a, 0x0, 0x0,

    /* U+0054 "T" */
    0xaa, 0xea, 0x60, 0xc, 0x0, 0x0, 0xc0, 0x0,
    0xc, 0x0, 0x0, 0xc0, 0x0
};


/*---------------------
 *  GLYPH DESCRIPTION
 *--------------------*/

static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0} /* id = 0 reserved */,
    {.bitmap_index = 0, .adv_w = 97, .box_w = 6, .box_h = 5, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 15, .adv_w = 86, .box_w = 5, .box_h = 5, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 28, .adv_w = 92, .box_w = 6, .box_h = 5, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 43, .adv_w = 122, .box_w = 7, .box_h = 5, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 61, .adv_w = 92, .box_w = 6, .box_h = 5, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 76, .adv_w = 75, .box_w = 5, .box_h = 5, .ofs_x = 0, .ofs_y = 0}
};

/*---------------------
 *  CHARACTER MAPPING
 *--------------------*/

static const uint16_t unicode_list_0[] = {
    0x0, 0x3, 0x9, 0xb, 0xe, 0x12
};

/*Collect the unicode lists and glyph_id offsets*/
static const lv_font_fmt_txt_cmap_t cmaps[] =
{
    {
        .range_start = 66, .range_length = 19, .glyph_id_start = 1,
        .unicode_list = unicode_list_0, .glyph_id_ofs_list = NULL, .list_length = 6, .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY
    }
};

/*-----------------
 *    KERNING
 *----------------*/


/*Map glyph_ids to kern left classes*/
static const uint8_t kern_left_class_mapping[] =
{
    0, 1, 0, 2, 0, 3, 4
};

/*Map glyph_ids to kern right classes*/
static const uint8_t kern_right_class_mapping[] =
{
    0, 1, 1, 1, 1, 1, 2
};

/*Kern values between classes*/
static const int8_t kern_class_values[] =
{
    0, -1, 0, -6, -1, -4, 0, 1
};


/*Collect the kern class' data in one place*/
static const lv_font_fmt_txt_kern_classes_t kern_classes =
{
    .class_pair_values   = kern_class_values,
    .left_class_mapping  = kern_left_class_mapping,
    .right_class_mapping = kern_right_class_mapping,
    .left_class_cnt      = 4,
    .right_class_cnt     = 2,
};

/*--------------------
 *  ALL CUSTOM DATA
 *--------------------*/

#if LVGL_VERSION_MAJOR == 8
/*Store all the custom data of the font*/
static  lv_font_fmt_txt_glyph_cache_t cache;
#endif

#if LVGL_VERSION_MAJOR >= 8
static const lv_font_fmt_txt_dsc_t font_dsc = {
#else
static lv_font_fmt_txt_dsc_t font_dsc = {
#endif
    .glyph_bitmap = glyph_bitmap,
    .glyph_dsc = glyph_dsc,
    .cmaps = cmaps,
    .kern_dsc = &kern_classes,
    .kern_scale = 16,
    .cmap_num = 1,
    .bpp = 4,
    .kern_classes = 1,
    .bitmap_format = 0,
#if LVGL_VERSION_MAJOR == 8
    .cache = &cache
#endif
};



/*-----------------
 *  PUBLIC FONT
 *----------------*/

/*Initialize a public general font descriptor*/
#if LVGL_VERSION_MAJOR >= 8
const lv_font_t companion_unit_font = {
#else
lv_font_t companion_unit_font = {
#endif
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,    /*Function pointer to get glyph's data*/
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,    /*Function pointer to get glyph's bitmap*/
    .line_height = 5,          /*The maximum line height required by the font*/
    .base_line = 0,             /*Baseline measured from the bottom of the line*/
#if !(LVGL_VERSION_MAJOR == 6 && LVGL_VERSION_MINOR == 0)
    .subpx = LV_FONT_SUBPX_NONE,
#endif
#if LV_VERSION_CHECK(7, 4, 0) || LVGL_VERSION_MAJOR >= 8
    .underline_position = -1,
    .underline_thickness = 0,
#endif
    .dsc = &font_dsc,          /*The custom font data. Will be accessed by `get_glyph_bitmap/dsc` */
#if LV_VERSION_CHECK(8, 2, 0) || LVGL_VERSION_MAJOR >= 9
    .fallback = NULL,
#endif
    .user_data = NULL,
};



#endif /*#if COMPANION_UNIT_FONT*/
