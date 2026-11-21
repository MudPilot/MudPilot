"""Send a path / loop to another MudPilot over telepath (Dan, 2026-11-01: "if I wanted Evolution to lead on the path I
just made, can we send it to him, complete with start room and steps?").

The game is the only link between the MudPilots (they run on different PCs), so it goes as a few telepaths:
    @mpsync path <id> <i>/<n> <piece>
The pieces together are "name=<name>|start=<map>/<room>|loop=1|" and then the steps, ';' between them: a move ("n",
"se", "~go path" for a typed exit), "#<flags>" after it if the step has any, and "!<command>" for a command sent before
the next move (search, dig, a lever). The other side walks the steps over its own map from the start room, builds the
file and saves it (folder 'Shared'), then says "{got loop 'name' — 42 steps}". Only from someone in your party or
allowed to move you (Talk tab)."""
from __future__ import annotations

import random
import re
import time

from .megamud_files import DIRS, MPath, Step

LINE = 76                   # the game wraps a telepath at ~80 characters — a wrapped piece would be cut in two
#                             (Revolution's '@mpsync me …' broke after 'ma=369'), so each one fits on a line
GAP = 1.2                   # seconds between pieces (the receiver's flood limit is 12 in 10 s)


def encode(mp) -> str:
    st = mp.steps[0].room if mp.steps else None
    if not st:
        return ""
    head = f"name={mp.title.replace('|', '/').replace(';', ',')}|start={st[0]}/{st[1]}|loop={1 if mp.is_loop else 0}|"
    toks = []
    for s in mp.steps:
        toks += ["!" + c.replace(";", ",") for c in (s.pre or [])]
        mv = s.move.lower() if s.move in DIRS else "~" + s.move.replace(";", ",")
        toks.append(mv + (f"#{s.flags:X}" if s.flags else ""))
    return head + ";".join(toks)


def decode(world, payload: str):
    """(MPath, "") or (None, why)."""
    head, _, body = payload.partition("|start=")
    name = head.replace("name=", "", 1)
    m = re.match(r"(\d+)/(\d+)\|loop=(\d)\|(.*)$", body, re.S)
    if not m:
        return None, "garbled"
    start, loop, toks = (int(m.group(1)), int(m.group(2))), m.group(3) == "1", [t for t in m.group(4).split(";") if t]
    if not world.room(start):
        return None, f"room {start[0]}/{start[1]} isn't on my map"
    cur, steps, pend = start, [], []
    for t in toks:
        if t.startswith("!"):
            pend.append(t[1:])
            continue
        mv, _, fl = t.partition("#")
        r = world.room(cur)
        if mv.startswith("~"):
            move = mv[1:]
            ex = next((e for e in r.exits.values() if hasattr(e, "accepts") and e.accepts(move)), None) if r else None
        else:
            move = mv.upper()
            ex = r.exits.get(move) if r else None
        dest = ex.to if ex is not None else None
        if dest is None:
            return None, f"my map has no '{move}' from {cur[0]}/{cur[1]} (step {len(steps) + 1})"
        steps.append(Step(r.mega_hash or "", int(fl, 16) if fl else 0, move, pend, cur, dest))
        pend, cur = [], dest
    if not steps and not pend:
        return None, "no steps"
    if pend:
        if steps and loop:
            steps[0].pre = pend + list(steps[0].pre or [])
        else:
            r = world.room(cur)
            steps.append(Step(r.mega_hash or "", 0, "", pend, cur, cur))
    a, b = world.room(start), world.room(cur)
    if loop and cur != start:
        return None, f"it's meant to be a loop but ends at {cur[0]}/{cur[1]}, not {start[0]}/{start[1]}"
    mp = MPath(name or "Shared loop", "MudPilot", a.mega_hash, (a if loop else b).mega_hash,
               start_label=a.name, end_label=(a if loop else b).name, start_group="Shared", end_group="Shared",
               steps=steps, resolved=True, resolve_note="sent by another MudPilot")
    return mp, ""


class PathShare:
    def __init__(self, session):
        self.s = session
        self.out: list = []          # (send at, command) queued pieces
        self.inbox: dict = {}        # (sender, id) -> {"n", "parts", "t"}

    # ------------------------------------------------------------ sending
    def send(self, mp, to: str) -> str:
        data = encode(mp)
        if not data:
            return "that path has no start room"
        pid = "%04x" % random.randrange(16 ** 4)
        me = self.s.settings.my_name or "Somebody"
        room = LINE - len(f"{me} telepaths: @mpsync path {pid} 99/99 ")
        room = max(16, room)
        parts = [data[i:i + room] for i in range(0, len(data), room)]
        now = time.time()
        for i, p in enumerate(parts):
            self.out.append((now + i * GAP, f"/{to} @mpsync path {pid} {i + 1}/{len(parts)} {p}"))
        self.s.log(f"Sending '{mp.title}' ({len(mp.steps)} steps) to {to} — {len(parts)} telepath"
                   f"{'s' if len(parts) != 1 else ''}")
        return ""

    def tick(self):
        now = time.time()
        while self.out and self.out[0][0] <= now:
            _t, cmd = self.out.pop(0)
            self.s.send(cmd, from_bot=True)

    # ------------------------------------------------------------ receiving
    def receive(self, sender: str, args: str):
        m = re.match(r"(\w+)\s+(\d+)/(\d+)\s(.*)$", args or "", re.S)
        if not m:
            return None
        pid, i, n, piece = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        key = (sender.lower(), pid)
        rec = self.inbox.setdefault(key, {"n": n, "parts": {}, "t": time.time()})
        rec["parts"][i] = piece
        self.inbox = {k: v for k, v in self.inbox.items() if time.time() - v["t"] < 120}
        if len(rec["parts"]) < rec["n"]:
            return None
        self.inbox.pop(key, None)
        r = self.s.remote
        if not (sender in (self.s.state.party or {}) or r.allowed(sender, "move")):
            self.s.log(f"{sender} sent a path — not taken (not in your party, nor allowed to move you)")
            return "not taking paths from you"
        mp, why = decode(self.s.world, "".join(rec["parts"][k] for k in sorted(rec["parts"])))
        if not mp:
            self.s.log(f"{sender} sent a path I couldn't use: {why}")
            return f"couldn't use that path: {why}"
        safe = re.sub(r"[^\w\- ]", "", mp.title).strip().replace(" ", "_")[:40] or "shared"
        self.s.save_path(mp, safe + ".mp")
        try:
            self.s.on_paths_changed()
        except Exception:
            pass
        kind = "loop" if mp.is_loop else "path"
        self.s.log(f"{sender} sent the {kind} '{mp.title}' ({len(mp.steps)} steps, from "
                   f"{mp.steps[0].room[0]}/{mp.steps[0].room[1]}) — saved in the Shared folder")
        return f"got {kind} '{mp.title}' - {len(mp.steps)} steps"
