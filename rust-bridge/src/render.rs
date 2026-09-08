use std::ffi::CString;
unsafe extern "C" {
    fn passport_text_width(text: *const std::ffi::c_char, size: f64, headline: i32) -> f64;
    fn passport_text_draw(
        p: *mut u8,
        w: i32,
        h: i32,
        y: i32,
        text: *const std::ffi::c_char,
        size: f64,
        headline: i32,
    );
}
fn clean(s: &str) -> String {
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .replace('\0', "")
}
fn width(s: &str, size: f64, headline: bool) -> f64 {
    let c = CString::new(s).unwrap();
    unsafe { passport_text_width(c.as_ptr(), size, headline as i32) }
}
fn ellipsis(mut s: String, w: f64, size: f64, headline: bool) -> String {
    while !s.is_empty() && width(&(s.clone() + "…"), size, headline) > w {
        s.pop();
    }
    s + "…"
}
fn lines(s: &str, w: f64, count: usize, headline: bool) -> Vec<String> {
    let mut result = Vec::new();
    let mut line = String::new();
    for c in clean(s).chars() {
        let next = format!("{line}{c}");
        if !line.is_empty() && width(&next, 20., headline) > w {
            if let Some(i) = line.rfind(' ').filter(|&i| i > 0) {
                result.push(line[..i].to_owned());
                line = format!("{}{c}", &line[i + 1..]);
            } else {
                result.push(line);
                line = c.to_string();
            }
            if result.len() == count {
                let last = result.pop().unwrap();
                result.push(ellipsis(last, w, 20., headline));
                line.clear();
                break;
            }
        } else {
            line = next;
        }
    }
    if !line.is_empty() {
        result.push(line);
    }
    result
}
fn draw(p: &mut [u8], w: usize, h: usize, y: usize, s: &str, size: f64, headline: bool) {
    let text = CString::new(s).unwrap();
    unsafe {
        passport_text_draw(
            p.as_mut_ptr(),
            w as i32,
            h as i32,
            y as i32,
            text.as_ptr(),
            size,
            headline as i32,
        )
    }
}
pub fn raster(title: &str, project: &str, alert: bool) -> Vec<u8> {
    let mut pixels = if alert {
        // Same 3200-byte tile: title 168x60 + workspace 170x16.
        // Host is snapshot metadata rendered by the device on the following row.
        let mut title_pixels = vec![0u8; 168 * 60];
        for (i, line) in lines(title, 168., 3, true).iter().enumerate() {
            draw(&mut title_pixels, 168, 60, i * 20, line, 20., true);
        }
        let project = clean(project);
        let (name, _) = project.rsplit_once(" · ").unwrap_or((&project, ""));
        let mut metadata = vec![0u8; 170 * 16];
        let text = if width(name, 16., false) > 170. {
            ellipsis(name.to_owned(), 170., 16., false)
        } else {
            name.to_owned()
        };
        draw(&mut metadata, 170, 16, 0, &text, 16., false);
        title_pixels.extend(metadata);
        title_pixels
    } else {
        let mut pixels = vec![0u8; 200 * 64];
        for (i, line) in lines(title, 200., 2, false).iter().enumerate() {
            draw(&mut pixels, 200, 64, 20 + i * 22, line, 20., false);
        }
        let mut project = clean(project);
        if width(&project, 16., false) > 200. {
            project = ellipsis(project, 200., 16., false);
        }
        draw(&mut pixels, 200, 64, 0, &project, 16., false);
        pixels
    };
    pixels.resize(12800, 0);
    let mut packed = vec![0; 3200];
    for (i, &alpha) in pixels.iter().enumerate() {
        packed[i / 4] |= (((alpha as u16 * 3 + 127) / 255) as u8) << (6 - 2 * (i % 4));
    }
    packed
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn completion_workspace_uses_its_own_line() {
        let packed = raster("Task", "ToutiaoKMP · devbox", true);
        let mut expected = vec![0u8; 170 * 16];
        draw(&mut expected, 170, 16, 0, "ToutiaoKMP", 16., false);
        for (offset, alpha) in expected.into_iter().enumerate() {
            let i = 168 * 60 + offset;
            let actual = (packed[i / 4] >> (6 - 2 * (i % 4))) & 3;
            assert_eq!(actual, ((alpha as u16 * 3 + 127) / 255) as u8);
        }
    }
    #[test]
    fn chinese_has_four_levels_and_independent_regions() {
        for alert in [false, true] {
            let p = raster("连接设备并探索二次开发", "acpus · devbox", alert);
            assert_eq!(p.len(), 3200);
            let mut levels = [false; 4];
            for b in &p {
                for s in [0, 2, 4, 6] {
                    levels[((b >> s) & 3) as usize] = true;
                }
            }
            assert!(levels.iter().all(|v| *v));
        }
        let a = raster("中文任务", "one", true);
        let b = raster("中文任务", "two", true);
        assert_eq!(&a[..2520], &b[..2520]);
        assert_ne!(&a[2520..], &b[2520..]);
        let remote = raster("中文任务", "one · devbox", true);
        assert_eq!(a, remote); // host is carried separately in metadata
    }
}
