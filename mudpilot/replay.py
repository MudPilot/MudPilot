"""Run a recorded session back through MudPilot, offline (pMUD's replay harness).

    python -m mudpilot.replay data/traces/Paradigm-Miserable-20261026-161000.ndjson
    python -m mudpilot.replay <trace> --rechunk lines      # same bytes, one line at a time
    python -m mudpilot.replay <trace> --rechunk blob       # …or all at once (packet-boundary bugs)
    python -m mudpilot.replay <trace> --from 120 --secs 60 # just a minute of it, 2 min in
    python -m mudpilot.replay <trace> --cut 120 180 tests/fixtures/double_cast.json --expect-not "esto,esto"

The board's output is fed in at the times it really came (on a virtual clock, so a two-hour session
replays in seconds); what you typed is typed again. Then what MudPilot sends this time is compared with
what it sent in the recording — the first differences are printed with the lines that led up to them.
A fixture (--cut) is a slice of a recording plus what should (or shouldn't) be sent; tests/
test_fixtures_replay.py replays every fixture on every test run, so a bug fixed from a log stays fixed.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import time as _time


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def now(self):
        return self.t


def load(path) -> list:
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    return out


def _chunks(data, mode):
    if mode == "lines":
        parts = data.splitlines(keepends=True)
        return parts or [data]
    return [data]


def run(recs, rechunk=None, start=0.0, secs=None, quiet=False, settings_over=None):
    """Replay records. Returns {"sent": [(t, cmd)], "recorded": [(t, cmd)], "session": s, "lines": [...]}."""
    import time as tmod
    head = next((r for r in recs if r.get("k") == "head"), {"d": {}, "t": recs[0]["t"] if recs else 0})
    t0 = float(head.get("t") or (recs[0]["t"] if recs else 0))
    body = [r for r in recs if r.get("k") in ("rx", "tx", "evt")]
    if start:
        body = [r for r in body if r["t"] - t0 >= start]
    if secs:
        body = [r for r in body if r["t"] - t0 < (start or 0) + secs]
    clock = Clock(body[0]["t"] - 0.5 if body else t0)
    real_time = tmod.time
    tmod.time = clock.now                           # every module's time.time() is the trace's clock
    try:
        from . import config
        from .session import Session
        st = config.Settings()
        for k, v in ((head.get("d") or {}).get("settings") or {}).items():
            if hasattr(st, k) and v != "(removed)" and k not in ("profile",):
                try:
                    setattr(st, k, v)
                except Exception:
                    pass
        for k, v in (settings_over or {}).items():
            setattr(st, k, v)
        st.save = lambda *a, **k: None
        st.auto_reconnect = False
        world = (head.get("d") or {}).get("world") or None
        if world and not os.path.exists(world):
            world = None
        s = Session(st, world_path=world) if world else Session(st)
        s._no_log_file = True
        sent = []
        typing = [False]

        class Tel:
            connected = True
            events = queue.Queue()

            def send_line(self, x):
                sent.append((clock.now(), x, typing[0]))

            def close(self):
                self.connected = False

        s.telnet = Tel()
        s._connected_at = clock.now()
        if hasattr(s, "recorder"):
            s.recorder.q = queue.Queue()             # never record a replay
            s.settings.record_sessions = False
        recorded, lines = [], []
        for r in body:
            # let the bot run in between, ~10 times a (virtual) second, skipping long quiet spells faster
            while clock.t < r["t"]:
                gap = r["t"] - clock.t
                clock.t += 0.1 if gap < 10 else 1.0
                s.poll()
            clock.t = r["t"]
            if r["k"] == "rx":
                for c in _chunks(r["d"], rechunk):
                    s.telnet.events.put(("data", c))
                    s.poll()
                lines.extend((r["t"], x) for x in str(r["d"]).splitlines() if x.strip())
            elif r["k"] == "tx":
                if r.get("bot"):
                    recorded.append((r["t"], r["d"]))
                elif r["d"] != "(hidden)":
                    typing[0] = True
                    try:
                        s.send(r["d"])               # what you typed, typed again
                    finally:
                        typing[0] = False
        for _ in range(30):
            clock.t += 0.1
            s.poll()
        bot_sent = [(t, c) for t, c, by_you in sent if not by_you]
        return {"sent": bot_sent, "recorded": recorded, "session": s, "lines": lines}
    finally:
        tmod.time = real_time


def diff(res, show=10) -> list:
    """Where the replay's sends part from the recording's (bot sends only), with the lines before each."""
    a = [c for _t, c in res["recorded"]]
    b = [c for _t, c in res["sent"]]
    import difflib
    out = []
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        t = (res["recorded"][i1][0] if i1 < len(res["recorded"]) else
             res["sent"][j1][0] if j1 < len(res["sent"]) else 0)
        before = [ln for lt, ln in res["lines"] if t - 6 <= lt <= t][-6:]
        out.append({"op": op, "recorded": a[i1:i2], "replay": b[j1:j2], "t": t, "before": before})
        if len(out) >= show:
            break
    return out


def cut(recs, start, end, out_path, expect=None, expect_not=None, note=""):
    head = next((r for r in recs if r.get("k") == "head"), None)
    t0 = float(head["t"]) if head else recs[0]["t"]
    keep = [r for r in recs if r.get("k") in ("rx", "tx", "evt") and start <= r["t"] - t0 < end]
    fx = {"note": note, "head": head, "records": keep,
          "expect": [e for e in (expect or []) if e], "expect_not": [e for e in (expect_not or []) if e]}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fx, f, indent=1)
    return out_path


def check_fixture(path) -> tuple[bool, str]:
    """Replay a fixture; every 'expect' command must be sent, no 'expect_not' sequence may appear."""
    with open(path, encoding="utf-8") as f:
        fx = json.load(f)
    recs = ([fx["head"]] if fx.get("head") else []) + fx["records"]
    res = run(recs, quiet=True, settings_over=fx.get("settings"))
    sent = [c for _t, c in res["sent"]]
    joined = "\n".join(sent)
    words = [c.split()[0].lower() if c.split() else "" for c in sent]
    for e in fx.get("expect", []):
        if e not in sent and e.lower() not in words:
            return False, f"expected '{e}' to be sent; sent: {sent[-15:]}"
    for e, most in (fx.get("expect_max") or {}).items():
        n = sum(1 for wd in words if wd == e.lower())
        if n > int(most):
            return False, f"'{e}' sent {n} times (at most {most}); sent: {sent[-15:]}"
    for e in fx.get("expect_not", []):
        seq = [x.strip() for x in e.split(",")]
        for i in range(len(sent) - len(seq) + 1):
            if [x.strip() for x in sent[i:i + len(seq)]] == seq:
                return False, f"'{e}' was sent (at {i}); sent: {sent[max(0, i - 3):i + len(seq) + 3]}"
    room = fx.get("room")
    if room and tuple(room) != res["session"].state.room:
        return False, f"ended in {res['session'].state.room}, expected {tuple(room)}"
    return True, f"{len(sent)} commands"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mudpilot.replay", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--rechunk", choices=("lines", "blob"))
    ap.add_argument("--from", dest="start", type=float, default=0.0, help="seconds into the recording")
    ap.add_argument("--secs", type=float, default=None)
    ap.add_argument("--cut", nargs=3, metavar=("START", "END", "OUT"))
    ap.add_argument("--expect", default="", help="commas: commands that must be sent (for --cut)")
    ap.add_argument("--expect-not", default="", help="a command sequence that must not be sent, e.g. 'esto,esto'")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    recs = load(a.trace)
    if not recs:
        print("Nothing in that file.")
        return 1
    if a.cut:
        p = cut(recs, float(a.cut[0]), float(a.cut[1]), a.cut[2], a.expect.split(",") if a.expect else [],
                [a.expect_not] if a.expect_not else [], a.note)
        print(f"Fixture written: {p}")
        return 0
    t = _time.time()
    res = run(recs, rechunk=a.rechunk, start=a.start, secs=a.secs)
    d = diff(res)
    print(f"Replayed {len(res['lines'])} lines in {_time.time() - t:.1f} s · recorded {len(res['recorded'])} "
          f"bot commands, replay sent {len(res['sent'])}")
    if not d:
        print("Same commands as the recording.")
    for x in d:
        print(f"\n@{x['t'] - (recs[0]['t']):.1f}s  {x['op']}: recorded {x['recorded']} → replay {x['replay']}")
        for ln in x["before"]:
            print(f"    | {ln}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
