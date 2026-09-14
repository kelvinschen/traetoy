#!/usr/bin/env python3
"""USB-only pet checks. Stop Passport first. --verify sends synthetic alerts/sounds."""

import argparse, fcntl, json, sys, time
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from companion import Device, frame

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--audio-timing", action="store_true", help="Measure actual notification worker wall time against each selected clip duration")
p.add_argument("--expiry", action="store_true", help="Check 15-second expiry and information-page timer pause")
p.add_argument("--verify", action="store_true")
p.add_argument("--power", action="store_true", help="Check one-hour idle boundary with USB clock aging and wake/ACK semantics")
p.add_argument("--perf", action="store_true")
p.add_argument("--footer", action="store_true", help="Check home status icons, count clearing and quota typography")
p.add_argument("--live-pages", action="store_true", help="Capture the last real synchronized pages without synthetic state")
p.add_argument("--shot", type=Path)
p.add_argument("--clip", type=int)
p.add_argument("--seconds", type=float, default=10)
p.add_argument("--output", type=Path, default=ROOT / "reports/pet-device.json")
a = p.parse_args()
lock = (ROOT / "reports/bridge.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
dev = Device()
# Native USB/JTAG interprets sequential DTR/RTS changes as reset. Keep the
# synchronized state intact when taking over from the desktop's connection.
import serial
from serial.tools import list_ports
class PreserveSerial(serial.Serial):
    def _update_dtr_state(self):
        pass
    def _update_rts_state(self):
        pass
ports=[p.device for p in list_ports.comports() if p.vid==0x303A]
if len(ports)!=1:
    raise OSError("Connect one Espressif board")
dev.serial=PreserveSerial(ports[0],115200,timeout=.15,write_timeout=2)
seq = int(time.time())
results = []
windows = [(75, 300, "3h 07m"), (46, 10080, "2d 04h")]


def request(s, prefix, timeout=5):
    dev.serial.write((s + "\n").encode())
    dev.serial.flush()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        line = dev.serial.readline().decode(errors="replace").strip()
        if line.startswith(prefix):
            return line
        if "panic" in line.lower() or "assert failed" in line.lower():
            raise RuntimeError(line)
    raise TimeoutError(s)


def values(line):
    return dict(x.split("=", 1) for x in line.split() if "=" in x)


def stats():
    line = request("PET|STATS|END", "PET_STATS")
    print(line, flush=True)
    return values(line)


def heartbeat(running=2):
    return dev.send(
        frame(seq + 100, windows, running, 0, 0, True, "PET TEST heartbeat"), seq + 100
    )


def pump(seconds, running=2):
    end = time.monotonic() + seconds
    next_packet = 0
    while time.monotonic() < end:
        if time.monotonic() >= next_packet:
            heartbeat(running)
            next_packet = time.monotonic() + 2
        time.sleep(0.05)


def key(n):
    request(f"PET|KEY|{n}|END", "PET_KEY_ACK")
    time.sleep(0.15)


def shot(path):
    request("PET|SHOT|END", "PET_SHOT_BEGIN", timeout=5)
    rows = []
    end = time.monotonic() + 30
    pending = bytearray()
    done = False
    invalid = []
    # Serial timeout may split a 961-byte row; retain fragments until newline.
    while time.monotonic() < end and not done:
        pending.extend(dev.serial.read(dev.serial.in_waiting or 1))
        while b"\n" in pending:
            raw, _, tail = pending.partition(b"\n")
            pending = bytearray(tail)
            line = raw.decode(errors="replace").strip()
            if line == "PET_SHOT_END":
                done = True
                break
            if len(line) == 960:
                try:
                    rows.append(bytes.fromhex(line))
                    continue
                except ValueError:
                    pass
            invalid.append(line)
    if len(rows) != 320:
        (ROOT / "reports/pet-shot-invalid.json").write_text(json.dumps(invalid))
    assert len(rows) == 320, len(rows)
    rgb = bytearray()
    for row in rows:
        for i in range(0, len(row), 2):
            v = int.from_bytes(row[i : i + 2], "big")
            rgb.extend(
                (
                    ((v >> 11) & 31) * 255 // 31,
                    ((v >> 5) & 63) * 255 // 63,
                    (v & 31) * 255 // 31,
                )
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (240, 320), bytes(rgb)).save(path)
    print(f"Screenshot: {path}", flush=True)


try:
    identity = request("PASSPORT?|END", "PASSPORT|")
    assert "|codex-pet|" in identity, identity
    print(identity, flush=True)
    if a.audio_timing:
        assert int(stats()["unread"]) == 0, "Read existing alerts before testing"
        for kind, duration in [(1, 2.2465625), (2, 2.25), (3, .8098125)]:
            key(3)
            dev.send_titles(seq, [], "Audio timing", "pet-test / local")
            dev.send_metadata(seq, ("--", "--", "TEST"), [], 10, "local")
            started = time.monotonic()
            packet = frame(seq, windows, 0, 1, kind, True, "PET audio timing")
            dev.serial.write(packet)
            dev.serial.flush()
            seq += 1
            audio_line = ""
            while time.monotonic()-started < 8:
                line=dev.serial.readline().decode(errors="replace").strip()
                if line.startswith(f"PET_AUDIO_DONE kind={kind}"):
                    audio_line=line
                    break
            elapsed = time.monotonic()-started
            if kind == 3:
                before = stats()
                dev.send(packet, seq-1)
                pump(1, 0)
                after = stats()
                assert after["event"] == before["event"] and after["tones"] == before["tones"]
                assert int(after["unread"]) == 1
                shot(ROOT / "reports/pet-v60-waiting.png")
            key(2)
            results.append({"checks":"audio worker wall time", "kind":kind, "seconds":elapsed, "line":audio_line})
            a.output.write_text(json.dumps(results,indent=2)+"\n")
            print(f"AUDIO_TIMING seconds={elapsed:.3f} {audio_line}", flush=True)
            assert audio_line and duration - .20 < elapsed < duration + .35, f"{duration:.3f}s clip worker took {elapsed:.3f}s"
            pump(2.2, 0)  # Respect the notification sound cooldown.
    if a.expiry:
        assert int(stats()["unread"]) == 0, "Read existing alerts before testing"
        key(3)
        key(1)  # Keep timers paused while preparing two snapshots.
        for i in range(2):
            dev.send_titles(seq, [], f"15 second expiry {i+1}", "pet-test / local")
            dev.send_metadata(seq, ("--", "--", "TEST"), [], 10, "local")
            packet = frame(seq, windows, 0, i+1, 1, True, "PET expiry test")
            ack = dev.send(packet, seq)
            assert int(values(ack)["unread"]) == i+1
            seq += 1
        pump(16, 0)
        assert int(stats()["unread"]) == 2  # More than 15 seconds off home does not expire.
        key(3)
        started = time.monotonic()
        pump(13.5, 0)
        before = stats()
        assert int(before["unread"]) == 2
        dev.send(packet, seq-1)  # Duplicate near expiry must not reset the timer.
        pump(max(0, 16 - (time.monotonic()-started)), 0)
        after = stats()
        assert int(after["unread"]) == 1
        assert after["event"] == before["event"]
        key(2)
        assert int(stats()["unread"]) == 0
        tone_count = int(stats()["tones"])
        dev.send_titles(seq, [], "Gentle stop sound", "pet-test / local")
        dev.send_metadata(seq, ("--", "--", "TEST"), [], 10, "local")
        dev.send(frame(seq, windows, 0, 0, 2, True, "PET stop sound test"), seq)
        seq += 1
        pump(2.6, 0)
        assert int(stats()["tones"]) == tone_count + 1
        key(2)
        assert int(stats()["unread"]) == 0
        results.append({"checks":"15-second expiry, information-page timer pause, duplicate does not reset timer, previous snapshot revealed, OK dismissal, stop audio worker completed", "status":"PASS"})
        print("PASS: 15-second notification expiry and paused information-page timing", flush=True)
    if a.power:
        assert int(stats()["unread"]) == 0, "Read existing alerts before testing"
        heartbeat(0)
        key(3)
        def age(seconds):
            request(f"PET|IDLE|{seconds}|END", "PET_IDLE_ACK")
            time.sleep(.15)
        def off(expected):
            v=stats()
            assert int(v["screen_off"]) == expected, v
            assert int(v["display_off"]) == expected, v
            return v
        def level(expected):
            v=off(int(expected == 0))
            assert int(v["brightness"]) == expected, v
            assert int(v["applied_brightness"]) == expected, v
            return v
        level(85)
        age(59)
        level(85)
        pump(1.1,0)
        level(35)
        age(3599)
        level(35)
        pump(1.1,0)
        level(0)
        key(2)
        level(85)
        ack_before=int(stats()["ack"])
        age(3600)
        level(0)
        key(2)
        assert int(level(85)["ack"]) == ack_before
        heartbeat(2)
        age(3600)
        level(50)
        heartbeat(0)
        age(3600)
        level(0)
        heartbeat(1)
        time.sleep(.2)
        level(50)
        def result(kind):
            global seq
            dev.send_titles(seq, [], "背光验证", "pet-test / local")
            dev.send_metadata(seq, ("--","--","TEST"), [], 60, "local")
            packet=frame(seq,windows,1,1,kind,True,"PET power test")
            dev.send(packet,seq)
            seq+=1
            time.sleep(.2)
            return packet, seq-1
        for kind in (1,2,3):
            packet, packet_seq=result(kind)
            level(85)
            age(3600)
            level(85) # Unread messages win over running and injected idle age.
            key(2)
            level(50)
            heartbeat(0)
            age(60)
            level(35)
            # Keep current running=0: transport snapshots may update live work
            # independently of notification deduplication.
            duplicate=frame(packet_seq,windows,0,1,kind,True,"PET power test")
            dev.send(duplicate,packet_seq)
            time.sleep(.2)
            level(35) # Duplicate must not restore a dismissed message.
            assert int(stats()["unread"]) == 0
            age(3600)
            level(0)
        key(2)
        level(85)
        print("PASS: 85/50/35/0 backlight; 60/3600s clock-aged boundaries; unread priority, duplicate suppression, key/run/message wake",flush=True)
        results.append({"checks":"four applied backlight levels; 59/60 and 3599/3600s; all message kinds override running; dismissal; duplicates; wake", "status":"PASS", "real_hour_wait":False})
    if a.footer:
        assert int(stats()["unread"]) == 0, "Read existing alerts before testing"
        key(3)
        def source_health(healthy):
            fields=["CDXI",seq,0,0,int(time.time()),1,0,"UTC+08:00",1,"pet-test",int(healthy),"END"]
            request("|".join(map(str,fields)),"CDX_INFO_ACK")
        source_health(True)
        captures = {}
        for count in [1, 2, 16, 0]:
            heartbeat(count)
            time.sleep(.3)
            path=ROOT/f"reports/pet-footer-{count}.png"
            shot(path)
            captures[count]=Image.open(path).convert("RGB")
        # A quantity must disappear completely when the last task finishes.
        paper=captures[0].getpixel((239,319))
        def blank(im, box):
            return all(px==paper for px in im.crop(box).getdata())
        assert blank(captures[0],(18,291,90,314))
        assert not blank(captures[16],(38,291,90,314))
        heartbeat(2)
        source_health(False)
        time.sleep(.3)
        path=ROOT/"reports/pet-footer-source-error.png"
        shot(path)
        assert blank(Image.open(path).convert("RGB"),(38,291,90,314))
        source_health(True)
        heartbeat(0)
        # Lose the transport while already idle: no numeric placeholder remains.
        time.sleep(21)
        path=ROOT/"reports/pet-footer-offline.png"
        shot(path)
        offline=Image.open(path).convert("RGB")
        assert blank(offline,(38,291,90,314))
        assert offline.crop((18,294,34,310)).tobytes()!=captures[0].crop((18,294,34,310)).tobytes()
        assert blank(offline,(95,290,240,320))
        heartbeat(2)
        time.sleep(.3)
        shot(ROOT/"reports/pet-footer-reconnected.png")
        heartbeat(0)
        print("PASS: footer 1/2/16 counts, blank idle footer and offline icon without numbers, stale quota clearing and reconnection",flush=True)
        results.append({"checks":"home footer count changes, idle has no icon or quantity; offline has no quantity, disconnect hides stale quota, reconnection", "status":"PASS"})
    if a.live_pages:
        key(3)
        shot(ROOT / "reports/pet-live-home.png")
        for name in ["reset", "tokens", "system"]:
            key(1)
            shot(ROOT / f"reports/pet-live-{name}.png")
        key(3)
    if a.verify:
        assert int(stats()["unread"]) == 0, "Read existing alerts before testing"
        for count in [0, 1, 2, 16, 2, 0]:
            rows = [
                (f"pet-test-{i}", f"动画验证任务 {i + 1} 中文标题", "pet-test / local")
                for i in range(count)
            ]
            dev.send_titles(seq, rows, "", "")
            dev.send_metadata(
                seq,
                ("--", "--", "TEST"),
                [(r[0], 120 + i) for i, r in enumerate(rows)],
                -1,
                "local",
            )
            ack = dev.send(frame(seq, windows, count, 0, 0, True, "PET TEST"), seq)
            assert int(values(ack)["tasks"]) == count, ack
            seq += 1
        print("PASS: 0/1/2/16/replacement task transactions", flush=True)
        key(0)
        assert int(stats()["page"]) == 3
        shot(ROOT / "reports/pet-system.png")
        key(3)
        for i in range(2):
            dev.send_titles(
                seq, [], f"宠物测试结果 {i + 1}：这一轮已完成", "traetoy / pet-test"
            )
            dev.send_metadata(seq, ("--", "--", "TEST"), [], 180 + i * 60, "local")
            packet = frame(seq, windows, 0, i + 1, 1, True, "PET TEST complete")
            ack = dev.send(packet, seq)
            assert int(values(ack)["unread"]) == i + 1, ack
            seq += 1
            pump(2.2, 0)
        before = stats()
        dev.send(packet, seq - 1)
        pump(1, 0)
        after = stats()
        assert before["event"] == after["event"] and before["tones"] == after["tones"]
        print("PASS: duplicate delivery does not replay animation/sound", flush=True)
        shot(ROOT / "reports/pet-completion.png")
        pump(16, 0)
        assert int(stats()["unread"]) == 1
        print("PASS: newest message expires after 15 seconds and reveals the previous snapshot", flush=True)
        shot(ROOT / "reports/pet-one-unread.png")
        key(2)
        pump(0.5, 0)
        shot(ROOT / "reports/pet-acknowledged.png")
        assert int(stats()["unread"]) == 0
        key(1)
        assert int(stats()["page"]) == 1
        shot(ROOT / "reports/pet-quota.png")
        # Real protocol shapes for reset credits, source health and daily usage.
        cards = ["Reset", "available", "2026/09/01 08:00", "2026/09/30 18:00", "Reset credit", "codexRateLimits",
                 "Reset", "available", "2026/09/01 08:00", "2026/10/31 18:00", "Reset credit", "codexRateLimits"]
        info_fields = ["CDXI",seq,2,0,int(time.time()),1,2,"UTC+08:00",2,"local",1,"devbox",1,*cards,"END"]
        request("|".join(map(str,info_fields)),"CDX_INFO_ACK")
        def usage_fixture(known=True):
            daily="190M,241M,1B,48M,21M,184M,149M" if known else ",".join(["--"]*7)
            chart="173,219,921,44,19,168,136" if known else ",".join(["-1"]*7)
            return f"CDXM|{seq}|{'149M' if known else '--'}|{'1.8B' if known else '--'}|09/07|-1|0|-|1|{chart}|1.1B|{daily}|09/01,09/02,09/03,09/04,09/05,09/06,09/07|2|local|END"
        request(usage_fixture(),"CDX_META_ACK")
        shot(ROOT / "reports/pet-reset-credits.png")
        key(1)
        assert int(stats()["page"]) == 2
        shot(ROOT / "reports/pet-token-usage.png")
        request(usage_fixture(False),"CDX_META_ACK")
        shot(ROOT / "reports/pet-token-unknown.png")
        request(usage_fixture(),"CDX_META_ACK")
        key(1)
        assert int(stats()["page"]) == 3
        shot(ROOT / "reports/pet-system.png")
        key(1)
        assert int(stats()["page"]) == 0
        key(0)
        assert int(stats()["page"]) == 3
        key(2)
        assert int(stats()["page"]) == 0
        # Information pages keep their place during arrivals and pause visible time.
        key(1)
        for i in range(2):
            dev.send_titles(seq, [], f"信息页期间完成 {i+1}", "pet-test / local")
            dev.send_metadata(seq, ("--","--","TEST"), [], 120, "local")
            dev.send(frame(seq,windows,0,4+i,1,True,"PET TEST paused"),seq)
            seq += 1
        pump(32,0)
        paused=stats()
        assert int(paused["unread"])==2 and int(paused["page"])==1,paused
        key(2)
        assert int(stats()["unread"])==2
        pump(31,0)
        assert int(stats()["unread"])==1
        key(2)
        assert int(stats()["unread"])==0
        print("PASS: four-page navigation, information-page arrival isolation, paused timers, real metadata shapes and M/B labels",flush=True)
        key(3)
        # A completion keeps notify until its result leaves, even with other work.
        dev.send_titles(seq, [], "其他任务仍在运行：保留完成消息", "pet-test / local")
        dev.send_metadata(seq, ("--", "--", "TEST"), [], 240, "local")
        dev.send(frame(seq, windows, 2, 3, 1, True, "PET TEST concurrent"), seq)
        seq += 1
        pump(23, 2)
        concurrent = stats()
        assert concurrent["clip"] == "done" and int(concurrent["unread"]) == 1, concurrent
        shot(ROOT / "reports/pet-working-unread.png")
        key(2)
        # Clip/frame diagnostics are sampled in five-second display windows.
        # Allow the 3.6-second ACK plus a full statistics refresh.
        pump(9,2)
        assert stats()["clip"] == "work"
        # Stop remains a distinct reaction and heading.
        dev.send_titles(seq, [], "这一轮已停止，等待下一步操作", "pet-test / local")
        dev.send_metadata(seq, ("--", "--", "TEST"), [], 65, "local")
        dev.send(frame(seq, windows, 0, 3, 2, True, "PET TEST stopped"), seq)
        seq += 1
        pump(6, 0)
        stopped = stats()
        assert stopped["clip"] == "stop" and int(stopped["unread"]) == 1, stopped
        shot(ROOT / "reports/pet-stopped.png")
        key(2)
        pump(.5, 0)
        # Refresh the long window independently; stale percentages must disappear.
        changed_windows = [windows[0], (9, 10080, "2d 04h")]
        dev.send(frame(seq, changed_windows, 0, 3, 0, True, "PET TEST long quota"), seq)
        seq += 1
        time.sleep(.1)
        shot(ROOT / "reports/pet-long-quota.png")
        dev.send(frame(seq, changed_windows, 0, 3, 0, False, "PET TEST stale quota"), seq)
        seq += 1
        time.sleep(.1)
        shot(ROOT / "reports/pet-stale-quota.png")
        heartbeat(0)
        print("PASS: notify survives 20 seconds with background work; dismissal restores work; stop reaction, long quota and stale rendering", flush=True)
        # Malformed input is rejected, and the identity endpoint remains responsive.
        assert request("CDX1|broken|END", "CDX_ERR") == "CDX_ERR invalid_frame"
        assert "|codex-pet|" in request("PASSPORT?|END", "PASSPORT|")
        results.append(
            {
                "checks": "protocol, deduplication, 15-second LIFO expiry, information-page timer pause, four-page navigation, reset credits, daily token metadata, direct acknowledgement, concurrent work, stopped reaction, two quota windows, stale quota, malformed packet",
                "status": "PASS",
            }
        )
    if a.perf:
        manifest = json.loads(
            (ROOT / "firmwares/codex-pet/assets/bloub.json").read_text()
        )
        for name in ["idle", "work", "done", "ack", "stop", "offline"]:
            index = next(
                i for i, c in enumerate(manifest["clips"]) if c["name"] == name
            )
            request(f"PET|CLIP|{index}|END", "PET_CLIP_ACK")
            duration=max(a.seconds,manifest["clips"][index]["duration"]+.5)
            pump(duration)
            r = stats()
            r["requested_clip"] = name
            r["sample_seconds"] = duration
            results.append(r)
        request("PET|CLIP|-1|END", "PET_CLIP_ACK")
    if a.clip is not None:
        request(f"PET|CLIP|{a.clip}|END", "PET_CLIP_ACK")
        pump(a.seconds)
    if a.shot:
        shot(a.shot)
    if not (a.verify or a.perf):
        results.append(stats())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(results, indent=2) + "\n")
finally:
    try:
        request("PET|CLIP|-1|END", "PET_CLIP_ACK")
        request("CDXB|RELEASE|END", "CDX_RELEASE_ACK")
    finally:
        dev.close()
        lock.close()
