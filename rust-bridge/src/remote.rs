use crate::{
    rpc::Rpc,
    state::{Batch, Completion, SourceState, Task, Update},
};
use anyhow::{bail, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    path::Path,
    sync::{atomic::AtomicBool, mpsc::SyncSender, Arc},
    time::Duration,
};
trait SourceRpc {
    fn call(&mut self, method: &str, params: Value) -> Result<Value>;
    fn offset(&self) -> f64;
}
impl SourceRpc for Rpc {
    fn call(&mut self, method: &str, params: Value) -> Result<Value> {
        Rpc::call(self, method, params)
    }
    fn offset(&self) -> f64 {
        self.offset
    }
}
fn text<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn rows(v: &Value) -> Vec<Value> {
    v["data"].as_array().cloned().unwrap_or_default()
}
fn root(v: &Value) -> bool {
    v["ephemeral"] != true && v["source"].is_string()
}
pub struct Remote {
    alias: String,
    first: f64,
    checkpoint: f64,
    active: BTreeMap<String, Task>,
    first_poll: bool,
    next_discovery: f64,
    projects: BTreeMap<String, String>,
    next_projects: f64,
}
impl Remote {
    pub fn new(alias: String, s: SourceState) -> Self {
        Self {
            alias,
            first: s.first,
            checkpoint: s.checkpoint,
            active: s
                .active
                .into_iter()
                .map(|t| (t.thread.clone(), t))
                .collect(),
            first_poll: true,
            next_discovery: 0.,
            projects: BTreeMap::new(),
            next_projects: 0.,
        }
    }
    fn discover(&self, rpc: &mut impl SourceRpc, cutoff: f64) -> Result<BTreeMap<String, Value>> {
        let mut found = BTreeMap::new();
        for archived in [false, true] {
            let mut cursor = Value::Null;
            let mut seen = HashSet::new();
            for page in 0..500 {
                let limit = if cursor.is_null() && (self.active.is_empty() || archived) {
                    1
                } else {
                    25
                };
                let result=rpc.call("thread/list",json!({"limit":limit,"sortKey":"updated_at","sortDirection":"desc","archived":archived,"useStateDbOnly":true,"cursor":cursor}))?;
                let data = rows(&result);
                for v in &data {
                    if root(v) {
                        found.insert(text(v, "id").into(), v.clone());
                    }
                }
                let next = result["nextCursor"].clone();
                if next.is_null()
                    || data.iter().any(|v| {
                        v["updatedAt"]
                            .as_f64()
                            .unwrap_or(crate::now() + rpc.offset())
                            - rpc.offset()
                            < cutoff
                    })
                {
                    break;
                }
                if !seen.insert(next.to_string()) || page == 499 {
                    bail!("thread pagination cannot advance");
                }
                cursor = next;
            }
        }
        Ok(found)
    }
    fn turns(&self, rpc: &mut impl SourceRpc, id: &str, cutoff: f64) -> Result<Vec<Value>> {
        let mut all = Vec::new();
        let mut cursor = Value::Null;
        let mut seen = HashSet::new();
        for page in 0..500 {
            let response=rpc.call("thread/turns/list",json!({"threadId":id,"limit":10,"itemsView":"notLoaded","sortDirection":"desc","cursor":cursor}))?;
            let data = rows(&response);
            let old = data.iter().any(|v| {
                v["completedAt"]
                    .as_f64()
                    .is_some_and(|n| n - rpc.offset() < cutoff)
            });
            all.extend(data);
            let next = response["nextCursor"].clone();
            if old || next.is_null() {
                return Ok(all);
            }
            if !seen.insert(next.to_string()) || page == 499 {
                bail!("turn pagination cannot advance");
            }
            cursor = next;
        }
        Ok(all)
    }
    fn poll(&mut self, rpc: &mut impl SourceRpc) -> Result<Batch> {
        let observed = crate::now();
        let cutoff = self.first.max(self.checkpoint - 3.);
        let discover = self.first_poll || observed >= self.next_discovery;
        let mut candidates = if discover {
            self.discover(rpc, cutoff)?
        } else {
            BTreeMap::new()
        };
        let mut ids: HashSet<String> = self.active.keys().cloned().collect();
        if self.first_poll {
            let mut cursor = Value::Null;
            let mut cursors = HashSet::new();
            loop {
                let result =
                    rpc.call("thread/loaded/list", json!({"limit":100,"cursor":cursor}))?;
                for id in rows(&result) {
                    if let Some(id) = id.as_str() {
                        ids.insert(id.into());
                    }
                }
                cursor = result["nextCursor"].clone();
                if cursor.is_null() {
                    break;
                }
                if !cursors.insert(cursor.to_string()) {
                    bail!("loaded cursor repeats");
                }
            }
        }
        for id in ids {
            if let std::collections::btree_map::Entry::Vacant(entry) = candidates.entry(id) {
                let v = rpc.call(
                    "thread/read",
                    json!({"threadId":entry.key(),"includeTurns":false}),
                )?["thread"]
                    .clone();
                if root(&v) {
                    entry.insert(v);
                }
            }
        }
        if observed >= self.next_projects {
            if let Ok(v) = rpc.call("project/list", json!({"limit":100})) {
                self.projects = rows(&v)
                    .into_iter()
                    .map(|p| (text(&p, "id").into(), text(&p, "name").into()))
                    .collect();
            }
            self.next_projects = observed + 600.;
        }
        let source = format!("ssh:{}", self.alias);
        let mut active = self.active.clone();
        let mut completed = Vec::new();
        for (id, v) in candidates {
            let running = v["status"]["type"] == "active";
            let recent = v["updatedAt"].as_f64().unwrap_or(0.) - rpc.offset() >= cutoff;
            if !running && !recent && !active.contains_key(&id) {
                continue;
            }
            let title = if text(&v, "name").is_empty() {
                format!(
                    "Task {}",
                    id.chars()
                        .rev()
                        .take(8)
                        .collect::<String>()
                        .chars()
                        .rev()
                        .collect::<String>()
                )
            } else {
                text(&v, "name").into()
            };
            let project = self
                .projects
                .get(text(&v, "projectId"))
                .cloned()
                .unwrap_or_else(|| {
                    Path::new(text(&v, "cwd"))
                        .file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .into()
                });
            let project = format!(
                "{} · {}",
                if project.is_empty() {
                    "No workspace"
                } else {
                    &project
                },
                self.alias
            );
            let mut current = None;
            for turn in self.turns(rpc, &id, cutoff)? {
                let started = turn["startedAt"].as_f64().map(|n| n - rpc.offset());
                let task = Task {
                    source: source.clone(),
                    thread: id.clone(),
                    title: title.clone(),
                    project: project.clone(),
                    turn: text(&turn, "id").into(),
                    started,
                };
                let status = text(&turn, "status");
                if status == "inProgress" && current.is_none() {
                    current = Some(task.clone());
                }
                if ["completed", "interrupted", "failed"].contains(&status) {
                    if let Some(ended) = turn["completedAt"]
                        .as_f64()
                        .map(|n| n - rpc.offset())
                        .filter(|n| *n >= cutoff)
                    {
                        let seconds = turn["durationMs"]
                            .as_f64()
                            .filter(|n| *n >= 0.)
                            .map(|n| (n / 1000.) as i64)
                            .or_else(|| started.map(|s| (ended - s).max(0.) as i64))
                            .unwrap_or(-1);
                        completed.push(Completion {
                            task,
                            status: status.into(),
                            ended,
                            seconds,
                        });
                    }
                }
            }
            if running {
                active.insert(
                    id.clone(),
                    current.unwrap_or(Task {
                        source: source.clone(),
                        thread: id,
                        title,
                        project,
                        turn: String::new(),
                        started: None,
                    }),
                );
            } else {
                active.remove(&id);
            }
        }
        if discover {
            self.checkpoint = observed;
            self.next_discovery = observed + 10.;
        }
        self.active = active;
        self.first_poll = false;
        completed.sort_by(|a, b| a.ended.total_cmp(&b.ended));
        Ok(Batch {
            source,
            active: self.active.values().cloned().collect(),
            completed,
            checkpoint: self.checkpoint,
        })
    }
}
pub fn worker(
    mut remote: Remote,
    out: SyncSender<Update>,
    stop: Arc<AtomicBool>,
    identity: Option<String>,
) {
    let mut retry = 1;
    let mut quota_due = 0.;
    let mut usage_due = 0.;
    let mut metrics_due = 0.;
    while !crate::stopping(&stop) {
        let result = (|| -> Result<()> {
            let mut rpc = Rpc::remote(&remote.alias, stop.clone())?;
            remote.first_poll = true;
            let mut verified = false;
            let mut identity_due = 0.;
            crate::log(&format!(
                "native source {} connected (existing App Server)",
                remote.alias
            ));
            loop {
                if crate::stopping(&stop) {
                    return Ok(());
                }
                let batch = remote.poll(&mut rpc)?;
                let active = batch.active.len();
                if !crate::publish(&out, &stop, Update::Batch(batch)) {
                    return Ok(());
                }
                if let Some(expected) = &identity {
                    if crate::now() >= identity_due {
                        identity_due = crate::now() + 60.;
                        let account = rpc.call("account/read", json!({"refreshToken":false}))?
                            ["account"]
                            .clone();
                        let digest = hex::encode(Sha256::digest(serde_json::to_vec(&account)?));
                        verified = &digest == expected;
                        if !verified {
                            crate::log("account identity mismatch: account display disabled, task collection continues");
                        }
                    }
                    if verified && crate::now() >= quota_due {
                        quota_due = crate::now() + 60.;
                        match rpc.call("account/rateLimits/read", json!({})) {
                            Ok(v) => {
                                crate::publish(&out, &stop, Update::Quota(v));
                            }
                            Err(e) => crate::log(&format!("quota unavailable: {e}")),
                        };
                    }
                    if verified && crate::now() >= usage_due {
                        usage_due = crate::now() + 300.;
                        match rpc.call("account/usage/read", json!({})) {
                            Ok(v) => {
                                crate::publish(&out, &stop, Update::Usage(v));
                            }
                            Err(e) => crate::log(&format!("usage unavailable: {e}")),
                        };
                    }
                }
                if crate::now() >= metrics_due {
                    crate::log(&format!(
                        "source {} active={} rpc/rx/tx={:?}",
                        remote.alias,
                        active,
                        rpc.stats()
                    ));
                    metrics_due = crate::now() + 60.;
                }
                retry = 1;
                crate::pause(&stop, Duration::from_secs(if active > 0 { 3 } else { 10 }));
            }
        })();
        if crate::stopping(&stop) {
            break;
        }
        if let Err(e) = result {
            crate::log(&format!("source {} unavailable: {e}", remote.alias));
            crate::publish(
                &out,
                &stop,
                Update::Health(format!("ssh:{}", remote.alias), false),
            );
        }
        crate::pause(&stop, Duration::from_secs(retry));
        retry = (retry * 2).min(60);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    struct Fake {
        responses: VecDeque<(&'static str, Value)>,
        calls: Vec<(String, Value)>,
    }
    impl SourceRpc for Fake {
        fn offset(&self) -> f64 {
            5.
        }
        fn call(&mut self, m: &str, p: Value) -> Result<Value> {
            self.calls.push((m.into(), p));
            let (expected, v) = self.responses.pop_front().expect("unexpected request");
            assert_eq!(expected, m);
            Ok(v)
        }
    }
    fn source() -> Remote {
        Remote::new(
            "devbox".into(),
            SourceState {
                first: 10.,
                checkpoint: 100.,
                observed: 100.,
                healthy: true,
                active: vec![],
            },
        )
    }
    #[test]
    fn discovery_paginates_and_includes_archived_without_subagents() {
        let mut fake = Fake {
            calls: vec![],
            responses: VecDeque::from([
                (
                    "thread/list",
                    json!({"data":[{"id":"a","source":"cli","updatedAt":130}],"nextCursor":"next"}),
                ),
                (
                    "thread/list",
                    json!({"data":[{"id":"internal","source":{"subagent":{}},"updatedAt":129},{"id":"b","source":"cli","updatedAt":110}],"nextCursor":null}),
                ),
                (
                    "thread/list",
                    json!({"data":[{"id":"archived","source":"cli","updatedAt":109}],"nextCursor":null}),
                ),
            ]),
        };
        let got = source().discover(&mut fake, 100.).unwrap();
        assert_eq!(
            got.keys().map(String::as_str).collect::<Vec<_>>(),
            vec!["a", "archived", "b"]
        );
        assert_eq!(fake.calls[0].1["limit"], 1);
        assert_eq!(fake.calls[1].1["limit"], 25);
        assert_eq!(fake.calls[2].1["archived"], true);
    }
    #[test]
    fn turn_backfill_stops_after_older_page_and_requests_no_items() {
        let mut fake = Fake {
            calls: vec![],
            responses: VecDeque::from([
                (
                    "thread/turns/list",
                    json!({"data":[{"id":"a","completedAt":125}],"nextCursor":"next"}),
                ),
                (
                    "thread/turns/list",
                    json!({"data":[{"id":"b","completedAt":115},{"id":"old","completedAt":90}],"nextCursor":"unused"}),
                ),
            ]),
        };
        assert_eq!(source().turns(&mut fake, "task", 100.).unwrap().len(), 3);
        assert_eq!(fake.calls.len(), 2);
        for (_, p) in fake.calls {
            assert_eq!(p["itemsView"], "notLoaded");
        }
    }
    #[test]
    fn repeated_cursor_fails_without_advancing_source() {
        let mut fake = Fake {
            calls: vec![],
            responses: VecDeque::from([
                ("thread/turns/list", json!({"data":[],"nextCursor":"same"})),
                ("thread/turns/list", json!({"data":[],"nextCursor":"same"})),
            ]),
        };
        let remote = source();
        assert!(remote.turns(&mut fake, "task", 100.).is_err());
        assert_eq!(remote.checkpoint, 100.);
    }
}
