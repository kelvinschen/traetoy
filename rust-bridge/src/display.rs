use crate::state::{Completion, State};
use chrono::{Datelike, Duration as Days, Local, NaiveDate};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
#[derive(Clone, Debug)]
pub struct Window {
    pub left: i64,
    pub minutes: i64,
    pub reset: String,
}
#[derive(Clone)]
pub struct Account {
    pub windows: [Window; 2],
    pub usage: Usage,
    pub reset_cards: Option<i32>,
    pub cards: crate::info::Cards,
    pub quota_at: f64,
    pub usage_at: f64,
}
impl Default for Account {
    fn default() -> Self {
        Self {
            windows: [unknown(), unknown()],
            usage: Usage::default(),
            reset_cards: None,
            cards: crate::info::Cards::default(),
            quota_at: 0.,
            usage_at: 0.,
        }
    }
}
fn unknown() -> Window {
    Window {
        left: -1,
        minutes: 0,
        reset: "Not available".into(),
    }
}
pub fn quota(v: &Value) -> [Window; 2] {
    let b = if v["rateLimitsByLimitId"].is_object() {
        &v["rateLimitsByLimitId"]["codex"]
    } else {
        &v["rateLimits"]
    };
    let mut result = Vec::new();
    for key in ["primary", "secondary"] {
        let w = &b[key];
        if let (Some(used), Some(minutes)) =
            (w["usedPercent"].as_f64(), w["windowDurationMins"].as_i64())
        {
            if minutes <= 0 {
                continue;
            }
            let reset = w["resetsAt"]
                .as_i64()
                .map(|t| reset_countdown(t.saturating_sub(crate::now() as i64)))
                .unwrap_or("--".into());
            result.push(Window {
                left: (100. - used).round().clamp(0., 100.) as i64,
                minutes,
                reset,
            });
        }
    }
    while result.len() < 2 {
        result.push(unknown());
    }
    [result.remove(0), result.remove(0)]
}
pub fn reset_cards(v: &Value) -> Option<i32> {
    let n = v["rateLimitResetCredits"]["availableCount"].as_i64()?;
    i32::try_from(n).ok().filter(|n| *n >= 0)
}
fn reset_countdown(seconds: i64) -> String {
    let seconds = seconds.max(0);
    let minutes = (seconds / 60).max(i64::from(seconds > 0));
    if seconds >= 86400 {
        format!("{}d {:02}h", seconds / 86400, seconds % 86400 / 3600)
    } else if seconds >= 3600 {
        format!("{}h {:02}m", minutes / 60, minutes % 60)
    } else {
        format!("{minutes}m")
    }
}
pub fn compact(n: Option<u64>) -> String {
    compact128(n.map(u128::from))
}
fn compact128(n: Option<u128>) -> String {
    match n {
        None => "--".into(),
        Some(n) => {
            for (scale, suffix) in [
                (1_000_000_000_000_000_000, "E"),
                (1_000_000_000_000_000, "P"),
                (1_000_000_000_000, "T"),
                (1_000_000_000, "B"),
                (1_000_000, "M"),
                (1_000, "K"),
            ] {
                if n >= scale {
                    let value = n as f64 / scale as f64;
                    let s = if value >= 100. {
                        format!("{value:.0}")
                    } else {
                        format!("{value:.1}")
                    };
                    return format!(
                        "{}{suffix}",
                        if s.contains('.') {
                            s.trim_end_matches('0').trim_end_matches('.')
                        } else {
                            &s
                        }
                    );
                }
            }
            n.to_string()
        }
    }
}
// At most four characters, fitting a 31 px column with the 11 px font.
fn compact_daily(value: Option<u64>) -> String {
    let Some(n) = value else { return "--".into() };
    let mut v = n as f64;
    let units = ["", "K", "M", "B", "T", "P", "E"];
    let mut unit = 0;
    while v >= 999.5 && unit < units.len() - 1 {
        v /= 1000.;
        unit += 1;
    }
    if unit == 0 || v >= 9.95 {
        format!("{:.0}{}", v.round(), units[unit])
    } else {
        format!(
            "{}{}",
            format!("{v:.1}")
                .trim_end_matches('0')
                .trim_end_matches('.'),
            units[unit]
        )
    }
}
#[derive(Clone, Debug)]
pub struct Usage {
    pub summary: [String; 3],
    pub points: [i16; 7],
    pub ceiling: String,
    pub daily: [String; 7],
    pub dates: [String; 7],
    pub weekday: u8,
    pub collected_date: NaiveDate,
}
impl Default for Usage {
    fn default() -> Self {
        Self {
            summary: ["--".into(), "--".into(), "No data".into()],
            points: [-1; 7],
            ceiling: "--".into(),
            daily: std::array::from_fn(|_| "--".into()),
            dates: std::array::from_fn(|_| "--".into()),
            weekday: 0,
            collected_date: Local::now().date_naive(),
        }
    }
}
pub fn usage(v: &Value) -> Usage {
    usage_on(v, Local::now().date_naive())
}
fn usage_on(v: &Value, today: NaiveDate) -> Usage {
    let mut days = BTreeMap::new();
    if let Some(rows) = v["dailyUsageBuckets"].as_array() {
        for r in rows {
            if let (Some(date), Some(tokens)) = (r["startDate"].as_str(), r["tokens"].as_u64()) {
                if let Ok(date) = NaiveDate::parse_from_str(date, "%Y-%m-%d") {
                    days.insert(date, tokens);
                }
            }
        }
    }
    let latest = days
        .range(..=today)
        .next_back()
        .map(|(date, _)| *date)
        .unwrap_or(today);
    let start = latest - Days::days(6);
    let amounts: [Option<u64>; 7] =
        std::array::from_fn(|i| days.get(&(start + Days::days(i as i64))).copied());
    let peak = amounts.iter().flatten().copied().max().unwrap_or(0);
    let mut magnitude = 1u128;
    while magnitude * 10 <= peak as u128 {
        magnitude *= 10;
    }
    let step = (magnitude / 10).max(1);
    let ceiling = (peak as u128).div_ceil(step).max(1) * step;
    let ceiling_label = if amounts.iter().any(Option::is_some) {
        compact128(Some(ceiling))
    } else {
        "--".into()
    };
    let points = amounts.map(|n| match n {
        None => -1,
        Some(0) => 0,
        Some(n) => ((n as u128 * 1000 / ceiling).max(1)) as i16,
    });
    // Missing calendar buckets are unknown, never fabricated as zero activity.
    let total = amounts
        .iter()
        .try_fold(0u64, |sum, n| sum.checked_add((*n)?));
    Usage {
        summary: [
            compact(amounts[6]),
            compact(total),
            if latest == today {
                "Today".into()
            } else {
                latest.format("%m/%d").to_string()
            },
        ],
        points,
        ceiling: ceiling_label,
        daily: amounts.map(compact_daily),
        dates: std::array::from_fn(|i| (start + Days::days(i as i64)).format("%m/%d").to_string()),
        weekday: start.weekday().num_days_from_monday() as u8,
        collected_date: today,
    }
}
pub fn identity(id: &str) -> u32 {
    let digest = Sha256::digest(id.as_bytes());
    (u32::from_be_bytes(digest[..4].try_into().unwrap()) & 0x7fff_ffff).max(1)
}
fn ascii(s: &str) -> String {
    if !s.is_ascii() {
        return "Task notification".into();
    }
    s.chars()
        .map(|c| {
            if c.is_ascii_graphic() && c != '|' {
                c
            } else {
                ' '
            }
        })
        .take(48)
        .collect()
}
#[derive(Clone, Debug)]
pub struct Transaction {
    pub seq: i64,
    pub titles: Vec<(String, String, String)>,
    pub alert_title: String,
    pub alert_project: String,
    pub packet: String,
    pub metadata: String,
    pub info: String,
    pub is_alert: bool,
}
pub fn snapshot(
    state: &State,
    account: &Account,
    seq: i64,
    alert: Option<&Completion>,
    filter: Option<&str>,
) -> anyhow::Result<Transaction> {
    let now = crate::now();
    let mut tasks = Vec::new();
    for s in state.sources.values() {
        let stale = !s.healthy || now - s.observed > 30.;
        for t in &s.active {
            if filter.is_some_and(|f| f != t.thread) {
                continue;
            }
            let elapsed = t
                .started
                .map(|start| {
                    ((if stale { s.observed.min(now) } else { now }) - start).max(0.) as i64
                })
                .unwrap_or(-1);
            tasks.push((t, elapsed, stale));
        }
    }
    tasks.sort_by_key(|(t, _, _)| t.key());
    let count = tasks.len();
    tasks.truncate(16);
    let titles = tasks
        .iter()
        .map(|(t, _, stale)| {
            (
                t.key(),
                t.title.clone(),
                format!("{}{}", t.project, if *stale { " · ?" } else { "" }),
            )
        })
        .collect();
    let durations = if tasks.is_empty() {
        "-".into()
    } else {
        tasks
            .iter()
            .map(|(t, seconds, _)| {
                format!("{}:{}", identity(&t.key()), (*seconds).min(i32::MAX as i64))
            })
            .collect::<Vec<_>>()
            .join(",")
    };
    let (title, project, seconds, kind) = if let Some(a) = alert {
        (
            format!(
                "{}{}",
                if a.status == "failed" { "Failed: " } else { "" },
                a.task.title
            ),
            a.task.project.clone(),
            a.seconds,
            if a.status == "completed" { 1 } else { 2 },
        )
    } else {
        (String::new(), String::new(), -1, 0)
    };
    let a = &account.windows[0];
    let b = &account.windows[1];
    let fresh = account.quota_at > 0. && now - account.quota_at < 180.;
    let packet = format!(
        "CDX1|{seq}|{}|{}|{}|{}|{}|{}|{kind}|{}|{}|{}|{}|END\n",
        a.left,
        a.minutes,
        b.left,
        b.minutes,
        count.min(999),
        state.done_count()?.min(999999),
        fresh as u8,
        if alert.is_some() {
            ascii(&title)
        } else {
            "Watching tasks".into()
        },
        a.reset,
        b.reset
    );
    let u = if account.usage_at > 0.
        && now - account.usage_at < 900.
        && account.usage.collected_date == Local::now().date_naive()
    {
        account.usage.clone()
    } else {
        Usage::default()
    };
    let metadata = format!(
        "CDXM|{seq}|{}|{}|{}|{seconds}|{}|{durations}|{}|{}|{}|{}|{}|{}|{}|END\n",
        u.summary[0],
        u.summary[1],
        u.summary[2],
        tasks.len(),
        u.weekday,
        u.points
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join(","),
        u.ceiling,
        u.daily.join(","),
        u.dates.join(","),
        if fresh {
            account.reset_cards.unwrap_or(-1)
        } else {
            -1
        },
        ascii(project.rsplit_once(" · ").map_or("", |(_, host)| host))
    );
    Ok(Transaction {
        seq,
        titles,
        alert_title: title,
        alert_project: project,
        packet,
        metadata,
        info: crate::info::packet(state, account, now),
        is_alert: alert.is_some(),
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn reset_cards_are_distinct_from_paid_balance() {
        assert_eq!(
            reset_cards(&json!({"rateLimitResetCredits":{"availableCount":3}})),
            Some(3)
        );
        assert_eq!(
            reset_cards(&json!({"rateLimitResetCredits":{"availableCount":0}})),
            Some(0)
        );
        for value in [
            json!({}),
            json!({"credits":{"balance":"3"}}),
            json!({"rateLimitResetCredits":{"availableCount":-1}}),
            json!({"rateLimitResetCredits":{"availableCount":2147483648i64}}),
        ] {
            assert_eq!(reset_cards(&value), None);
        }
    }
    #[test]
    fn seven_column_values_and_calendar_rollover() {
        for (n, label) in [
            (0, "0"),
            (999, "999"),
            (1000, "1K"),
            (10_500_000, "11M"),
            (999_500_000, "1B"),
            (u64::MAX, "18E"),
        ] {
            assert_eq!(compact_daily(Some(n)), label);
        }
        assert_eq!(compact_daily(None), "--");
        let today = NaiveDate::from_ymd_opt(2024, 3, 2).unwrap();
        let u = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2024-03-02","tokens":184000000}]}),
            today,
        );
        assert_eq!(
            u.dates,
            ["02/25", "02/26", "02/27", "02/28", "02/29", "03/01", "03/02"]
        );
        assert_eq!(u.daily[0], "--");
        assert_eq!(u.daily[6], "184M");
        assert_eq!(u.points[0], -1);
    }
    #[test]
    fn quota_missing_and_real_window() {
        let v = json!({"rateLimitsByLimitId":{"codex":{"primary":{"usedPercent":61,"windowDurationMins":10080}}}});
        let q = quota(&v);
        assert_eq!(q[0].left, 39);
        assert_eq!(q[1].left, -1);
    }
    #[test]
    fn tokens_calendar_gaps_zero_and_overflow() {
        let today = NaiveDate::from_ymd_opt(2026, 9, 7).unwrap();
        let empty = usage_on(&json!({}), today);
        assert_eq!(empty.points, [-1; 7]);
        let partial = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2026-09-01","tokens":0},{"startDate":"2026-09-07","tokens":2000}]}),
            today,
        );
        assert_eq!(partial.points, [0, -1, -1, -1, -1, -1, 1000]);
        assert_eq!(partial.summary, ["2K", "--", "Today"]);
        assert_eq!(partial.weekday, 1);
        let rows: Vec<_> = (0..7)
            .map(|i| json!({"startDate":(today-Days::days(6-i)).to_string(),"tokens":i*1000}))
            .collect();
        let full = usage_on(&json!({"dailyUsageBuckets":rows}), today);
        assert_eq!(full.summary, ["6K", "21K", "Today"]);
        assert_eq!(full.points, [0, 166, 333, 500, 666, 833, 1000]);
        let huge = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2026-09-07","tokens":u64::MAX}]}),
            today,
        );
        assert!(huge.points[6] > 900 && huge.points[6] <= 1000);
        assert_eq!(huge.ceiling, "19E");
        assert_eq!(compact(Some(100_000_000)), "100M");
        assert_eq!(compact(Some(20_578_780)), "20.6M");
        let yesterday = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2026-09-06","tokens":2000}]}),
            today,
        );
        assert_eq!(yesterday.summary, ["2K", "--", "09/06"]);
        assert_eq!(yesterday.weekday, 0);
        assert_eq!(yesterday.points[6], 1000);
    }
    #[test]
    fn reset_time_boundaries_and_chart_upper_bound() {
        for (seconds, expected) in [
            (0, "0m"),
            (59, "1m"),
            (3599, "59m"),
            (3600, "1h 00m"),
            (11220, "3h 07m"),
            (86399, "23h 59m"),
            (86400, "1d 00h"),
        ] {
            assert_eq!(reset_countdown(seconds), expected);
        }
        let date = NaiveDate::from_ymd_opt(2026, 9, 7).unwrap();
        let value = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2026-09-07","tokens":1_013_222_974u64}]}),
            date,
        );
        assert_eq!(value.ceiling, "1.1B");
        assert_eq!(value.points[6], 921);
        let zero = usage_on(
            &json!({"dailyUsageBuckets":[{"startDate":"2026-09-07","tokens":0}]}),
            date,
        );
        assert_eq!(zero.ceiling, "1");
        assert_eq!(zero.points[6], 0);
    }
    #[test]
    fn identity_matches_python() {
        assert_eq!(identity("task-a"), 935050221);
    }
}
