#include <CoreText/CoreText.h>
#include <CoreGraphics/CoreGraphics.h>
#include <stdint.h>
#include <string.h>

static CTLineRef line_for(const char *text, double size, int headline) {
    CFStringRef string = CFStringCreateWithCString(NULL, text, kCFStringEncodingUTF8);
    CTFontRef font = CTFontCreateWithName(headline ? CFSTR("PingFangSC-Semiheadline") : CFSTR("ArialUnicodeMS"), size, NULL);
    CGFloat components[] = {1, 1};
    CGColorSpaceRef space = CGColorSpaceCreateDeviceGray();
    CGColorRef color = CGColorCreate(space, components);
    const void *keys[] = {kCTFontAttributeName, kCTForegroundColorAttributeName};
    const void *values[] = {font, color};
    CFDictionaryRef attrs = CFDictionaryCreate(NULL, keys, values, 2,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFAttributedStringRef styled = CFAttributedStringCreate(NULL, string, attrs);
    CTLineRef line = CTLineCreateWithAttributedString(styled);
    CFRelease(styled); CFRelease(attrs); CFRelease(font); CFRelease(string);
    CGColorRelease(color); CGColorSpaceRelease(space);
    return line;
}

double passport_text_width(const char *text, double size, int headline) {
    CTLineRef line = line_for(text, size, headline);
    double width = CTLineGetTypographicBounds(line, NULL, NULL, NULL);
    CFRelease(line);
    return width;
}

void passport_text_draw(uint8_t *pixels, int width, int height, int top,
                        const char *text, double size, int headline) {
    CGColorSpaceRef space = CGColorSpaceCreateDeviceGray();
    CGContextRef context = CGBitmapContextCreate(pixels, width, height, 8, width,
                                                space, kCGImageAlphaNone);
    CGColorSpaceRelease(space);
    if (!context) return;
    CTLineRef line = line_for(text, size, headline);
    CGRect bounds = CTLineGetBoundsWithOptions(line, kCTLineBoundsUseGlyphPathBounds);
    CGContextSetShouldAntialias(context, true);
    CGContextSetShouldSmoothFonts(context, false);
    CGContextSetTextPosition(context, 0, height-top-bounds.origin.y-bounds.size.height);
    CTLineDraw(line, context);
    CFRelease(line); CGContextRelease(context);
}
