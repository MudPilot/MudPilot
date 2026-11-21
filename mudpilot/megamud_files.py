"""Read/write MegaMUD path (.mp) and room (Rooms.md) files, and resolve path steps
to exact MME map/room numbers.

.mp layout (as written by MegaMUD / MME):
    [Path or Loop Name][Author]
    [CODE:Group:From Room Name]
    [CODE:Group:To Room Name]            (omitted for loops)
    STARTHASH:ENDHASH:nSteps:-1:0:Needed Item::
    ROOMHASH:FLAGS:DIR[pre-cmd,pre-cmd]  (one line per step; hash = room the step starts in)

Rooms.md line:  HASH8:FLAGS:0:0:0:CODE:Group:Room Name
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .worlddb import DIRS, WorldDB, norm_dir

STEPF = {
    "DARK": 0x1, "REST": 0x2, "DONTREST": 0x4, "NOLIGHT": 0x8, "STASH": 0x10,
    "NOATTACK": 0x40, "RELEARN": 0x80, "SUSPECT": 0x100, "DISARM": 0x200,
    "CANPICK": 0x400, "CYCLED": 0x8000,
}
ANY_ROOM = "FFFFFFFF"     # MegaMUD's hash for a step done wherever you are (a RELEARN command step)


@dataclass
class Step:
    hash: str             # MegaMUD hash of the room the step starts in
    flags: int
    move: str             # "N" / "SW" … or a raw command (text exits like "go path")
    pre: list = field(default_factory=list)   # commands to send before moving
    room: tuple | None = None                 # resolved MME room where the step starts
    dest: tuple | None = None                 # resolved MME room after the step

    @property
    def dir(self) -> str | None:
        return self.move if self.move in DIRS else None

    def flag(self, name: str) -> bool:
        return bool(self.flags & STEPF[name])

    def to_line(self) -> str:
        pre = ("[" + ",".join(self.pre) + "]") if self.pre else ""
        return f"{self.hash}:{self.flags:04X}:{self.move}{pre}"


def step_exit(world, stp):
    """The MME exit a path step takes, or None. (0.8.201, walk check: a room-command step holds the command —
    'dig grave' — and the exit is stored under '@dig grave', so looking it up by stp.dir found nothing: the shovel
    it needs, its toll, trap or quest flag were never seen, and Go to walked there and spammed 'dig grave'.)"""
    r = world.room(stp.room) if getattr(stp, "room", None) else None
    if r is None:
        return None
    if stp.dir:
        return r.exits.get(stp.dir)
    mv = (stp.move or "").strip()
    if not mv:
        return None
    hits = [e for e in r.exits.values() if e.accepts(mv)]
    if len(hits) > 1 and stp.dest:
        hits = [e for e in hits if tuple(e.to) == tuple(stp.dest)] or hits
    return hits[0] if hits else None


@dataclass
class MPath:
    name: str
    author: str
    start_hash: str
    end_hash: str
    start_label: str = ""
    end_label: str = ""
    start_code: str = ""
    end_code: str = ""
    needed_item: str = ""
    start_group: str = ""      # MegaMUD area folder ("Terra Fuego")
    end_group: str = ""
    steps: list = field(default_factory=list)
    filename: str = ""
    resolved: bool = False
    resolve_note: str = ""

    @property
    def is_loop(self) -> bool:
        return self.start_hash == self.end_hash

    @property
    def title(self) -> str:
        if self.name:
            return self.name
        if self.is_loop:
            return f"Loop @ {self.start_label}"
        return f"{self.start_label} → {self.end_label}"

    def rooms(self) -> list:
        return [s.room for s in self.steps if s.room]


def _parse_step(line: str) -> Step | None:
    parts = line.strip().split(":", 2)
    if len(parts) < 3 or not re.fullmatch(r"[0-9A-Fa-f]{8}", parts[0]):
        return None
    try:
        flags = int(parts[1], 16)
    except ValueError:
        flags = 0
    body = parts[2].strip()
    pre = []
    m = re.match(r"^([^\[]*)\[(.*)\]\s*$", body)
    if m:
        body = m.group(1).strip()
        pre = [c.strip() for c in m.group(2).split(",") if c.strip()]
    d = norm_dir(body)
    return Step(parts[0].upper(), flags, d if d else body, pre)


def read_mp(path: str) -> MPath:
    with open(path, "r", encoding="latin-1", errors="replace") as f:
        lines = [l.rstrip("\r\n") for l in f if l.strip()]
    if not lines:
        raise ValueError("empty path file")
    head = re.findall(r"\[([^\]]*)\]", lines[0])
    name = head[0] if head else ""
    author = head[1] if len(head) > 1 else ""
    labels, idx = [], 1
    while idx < len(lines) and lines[idx].startswith("["):
        labels.append(lines[idx].strip()[1:-1])
        idx += 1
    if idx >= len(lines):
        raise ValueError("missing path header line")
    hdr = lines[idx].split(":")
    idx += 1
    mp = MPath(name, author, hdr[0].upper(), (hdr[1] if len(hdr) > 1 else hdr[0]).upper(),
               needed_item=hdr[5] if len(hdr) > 5 else "", filename=path)

    def label(l):
        p = l.split(":", 2)                     # [CODE:Area:Room name]
        return (p[0], p[1] if len(p) > 2 else "", p[2] if len(p) > 2 else l)

    if labels:
        mp.start_code, mp.start_group, mp.start_label = label(labels[0])
    if len(labels) > 1:
        mp.end_code, mp.end_group, mp.end_label = label(labels[1])
    elif mp.is_loop:
        mp.end_code, mp.end_group, mp.end_label = mp.start_code, mp.start_group, mp.start_label
    for l in lines[idx:]:
        s = _parse_step(l)
        if s:
            mp.steps.append(s)
    if not mp.steps:
        raise ValueError("no steps found")
    return mp


def write_mp(mp: MPath, path: str):
    out = [f"[{mp.name if mp.is_loop else ''}][{mp.author or 'MudPilot'}]"]
    out.append(f"[{mp.start_code or 'FFFF'}:{mp.start_group or 'MudPilot'}:{mp.start_label}]")
    if not mp.is_loop:
        out.append(f"[{mp.end_code or 'FFFE'}:{mp.end_group or 'MudPilot'}:{mp.end_label}]")
    out.append(f"{mp.start_hash}:{mp.end_hash}:{len(mp.steps)}:-1:0:{mp.needed_item}::")
    out += [s.to_line() for s in mp.steps]
    with open(path, "w", encoding="latin-1", newline="\r\n") as f:
        f.write("\n".join(out) + "\n")


def read_rooms_md(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="latin-1", errors="replace") as f:
        for line in f:
            p = line.rstrip("\r\n").split(":")
            if len(p) >= 8 and re.fullmatch(r"[0-9A-Fa-f]{8}", p[0]):
                rows.append({"hash": p[0].upper(), "code": p[5], "group": p[6], "name": ":".join(p[7:])})
    return rows


def find_mp_files(folder: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(folder):
        out += [os.path.join(root, f) for f in files if f.lower().endswith(".mp")]
    return sorted(out)


# ---------------------------------------------------------------- resolving
def _advance(world: WorldDB, room, step: Step):
    if step.dir:
        return world.neighbor(room, step.dir)
    # raw command: find a text/action exit whose command matches
    r = world.room(room)
    if not r:
        return None
    cmd = step.move.lower()
    for ex in r.exits.values():
        if ex.accepts(cmd):
            return ex.to
        if cmd and cmd in ex.etype.lower():
            return ex.to
    return None


def resolve_path(world: WorldDB, mp: MPath, hint=None) -> bool:
    """Walk the path through the MME exit graph from every room whose hash matches the
    start; keep the start that stays consistent with every step's hash. Fills step.room
    / step.dest with exact map/room numbers."""
    starts = list(world.by_hash.get(mp.steps[0].hash, []))
    if not starts and mp.steps[0].hash.upper() == ANY_ROOM:
        starts = list(world.by_hash.get(mp.start_hash, []))
    if hint and hint in starts:
        starts.remove(hint)
        starts.insert(0, hint)
    best, best_score, best_bridges = None, -1, []
    for st in starts:
        cur, rooms, score, bridges = st, [], 0, []
        for i, s in enumerate(mp.steps):
            if cur is None:
                break
            h = world.room(cur).mega_hash if world.room(cur) else None
            # (0.8.201, walk check: MegaMUD writes 'FFFFFFFF' for a step done wherever you are — 'hide 500 gold' in
            #  the Lower Bristlewood and Dark-elf Royal Guards loops. Compared as a real hash it broke the whole path)
            any_room = s.hash.upper() == ANY_ROOM
            if h == s.hash or any_room:
                score += 1
            elif not s.flag("DARK"):
                # tolerate hidden-exit differences: name part must still match
                if not h or h[:3] != s.hash[:3]:
                    break
            nxt = _advance(world, cur, s)
            if nxt is None and any_room and not s.dir:
                nxt = cur                                # a command, not a move: still here (no bridge spent)
            if nxt is None and len(bridges) < 6:
                # MME has no exit for this move ('enter pyramid', a portal MME forgot) — the path knows
                # better: bridge to the room the next step starts in (or the path's end)
                nxt = _bridge(world, cur, mp, i)
                if nxt is not None:
                    bridges.append((cur, s.move, nxt))
            rooms.append((cur, nxt))
            cur = nxt
        if len(rooms) == len(mp.steps) and (score, -len(bridges)) > (best_score, -len(best_bridges)):
            best, best_score, best_bridges = rooms, score, bridges
            if score == len(mp.steps) and not bridges:
                break
    if not best:
        mp.resolved = False
        mp.resolve_note = f"start hash {mp.steps[0].hash} not found in MME data" if not starts \
            else "steps don't line up with MME exits"
        return False
    for s, (r, d) in zip(mp.steps, best):
        s.room, s.dest = r, d
    mp.resolved = True
    mp.bridges = best_bridges
    for src, move, dst in best_bridges:
        if src[0] != dst[0] or _room_action(world, src, move):
            # (0.8.201, walk check: a guess onto another map, or an action that opens one of the room's own exits —
            #  3/817 'raise idol' was learned as a teleport into 13/3812's swamp. Fine for walking this path, never
            #  saved as an exit for routes)
            continue
        world.add_learned(src, move, dst)          # now routes can use it too
    mp.resolve_note = f"{best_score}/{len(mp.steps)} steps exact" + (
        f", {len(best_bridges)} move(s) MME doesn't have" if best_bridges else "")
    return True


def _room_action(world: WorldDB, room, move) -> bool:
    """`move` is the action of one of this room's exits ('raise idol' opens 3/817's hidden north)."""
    r = world.room(room)
    m = (move or "").strip().lower()
    if not r or not m:
        return False
    for ex in r.exits.values():
        try:
            if m in [c.lower() for c in ex.action_cmds()] or any(
                    m == (c or "").strip().lower() for a in ex.actions for c in (a.get("cmds") or [])):
                return True
        except Exception:
            continue
    return False


def _bridge(world: WorldDB, cur, mp: MPath, i):
    """The room after step i when MME has no exit for it: one that has the next step's hash (or the end's),
    on the same map, whose own next move lines up with the path; the nearest room number if several do."""
    want = mp.steps[i + 1].hash if i + 1 < len(mp.steps) else mp.end_hash
    cands = list(world.by_hash.get(want, []))
    if not cands:
        return None
    same = [c for c in cands if c[0] == cur[0]] or cands
    if i + 2 <= len(mp.steps) - 1 and len(same) > 1:
        nxt_step = mp.steps[i + 1]
        after = mp.steps[i + 2].hash
        fit = []
        for c in same:
            n2 = _advance(world, c, nxt_step)
            if n2 and world.room(n2) and world.room(n2).mega_hash[:3] == after[:3]:
                fit.append(c)
        same = fit or same
    if len(same) > 12:
        return None                                  # far too ambiguous to guess
    return min(same, key=lambda c: abs(c[1] - cur[1]))


def path_from_route(world: WorldDB, start, exits: list, name: str = "", author: str = "MudPilot") -> MPath:
    """Build a MegaMUD-compatible path from a BFS route (list of Exit)."""
    steps, cur, rush = [], start, []
    for ex in exits:
        at = world.action_at(ex) if hasattr(world, "action_at") else None
        if at and at != cur and at in world.rooms:
            # the exit is opened from other rooms ('push block' in 12/1808 opens 12/1811's north wall; the mummy's
            # gate 1/1056 N needs the levers in 1/1038 and 1/1044): walk to each, do it, come back, go through
            tour = _lever_tour(world, cur, ex)
            if tour:
                sub, gate_pre, first = tour
                begin = len(steps)
                steps.extend(sub)
                steps.append(Step(world.room(cur).mega_hash, 0, ex.dir, gate_pre, cur, ex.to))
                for s in steps[begin + first:]:
                    s.flags |= STEPF["NOATTACK"]      # (Dan: the gate's on a timer — run, don't fight)
                rush.append({"begin": begin, "first": begin + first, "gate": len(steps) - 1, "room": cur,
                             "dir": ex.dir})
                cur = ex.to
                continue
        pre, move, flags = [], ex.dir, 0
        if ex.kind == "hidden" and "search" in ex.etype.lower():
            pre = [f"search {ex.dir.lower()}"]
        elif ex.kind in ("hidden", "door") and ex.action_cmds() and not (at and at != cur):
            pre = ex.action_cmds()                 # e.g. 'pull lever' opens it
        elif ex.kind == "text" and ex.text_command:
            move = ex.text_command
        elif ex.kind == "trap":
            flags |= STEPF["DISARM"]
        if getattr(world, "segments", None):
            from .board_fixes import pre_for
            pre = pre_for(world, cur, ex) + list(pre)
        steps.append(Step(world.room(cur).mega_hash, flags, move, pre, cur, ex.to))
        if getattr(ex, "scatter", None):
            steps[-1]._scatter = ex.scatter          # a random drop (the asylum): it may land elsewhere in range
        cur = ex.to
    s_room, e_room = world.room(start), world.room(cur)
    mp = MPath(name, author, s_room.mega_hash, e_room.mega_hash,
               start_label=s_room.name, end_label=e_room.name, steps=steps, resolved=True,
               resolve_note="built from MME")
    mp.rush = rush                                   # lever gates on this path (Bot._rush_retry)
    return mp


def _lever_tour(world, gate, ex):
    """The walk round an exit's levers: (steps, the gate step's own commands, index of the first lever step) or
    None. Each action is done in its room ('at', else the gate room), in order, then back to the gate."""
    acts = ex.steps_needed() if hasattr(ex, "steps_needed") else (getattr(ex, "actions", None) or [])
    if not acts:
        return None
    steps, pos, pending, first = [], gate, [], None
    for a in acts + [None]:
        to = gate if a is None else (tuple(a["at"]) if a.get("at") else gate)
        if to != pos:
            # (never through the gate itself on the way to its levers — 0.8.213: the Darkened Tunnels' 15/477 N, whose
            #  lever at 15/604 is closest through 15/478, gave no tour at all)
            leg = world.route(pos, to, max_nodes=20000, avoid={ex.to} if to != ex.to else None)
            if leg is None or any(world.action_at(x) for x in leg):
                return None
            sub = path_from_route(world, pos, leg).steps
            if not sub:
                return None
            if pending:
                sub[0].pre = pending + list(sub[0].pre or [])
                if first is None:
                    first = len(steps)
                pending = []
            steps.extend(sub)
            pos = to
        if a is not None:
            pending.append((a.get("cmds") or ["pull lever"])[0])
    if not steps or first is None:
        return None
    return steps, pending, first


def anchor_path(world: WorldDB, mp: MPath, j: int, room) -> bool:
    """Re-resolve the path assuming step j starts in `room` (your real position).
    Walks forward (wrapping for loops) checking each step's hash. Returns success."""
    n = len(mp.steps)
    order = list(range(j, n)) + (list(range(0, j)) if mp.is_loop else [])
    cur, assigned = room, []
    for i in order:
        s = mp.steps[i]
        r = world.room(cur) if cur else None
        if not r or (r.mega_hash != s.hash and r.mega_hash[:3] != s.hash[:3] and not s.flag("DARK")):
            return False
        nxt = _advance(world, cur, s)
        assigned.append((i, cur, nxt))
        cur = nxt
    for i, a, b in assigned:
        mp.steps[i].room, mp.steps[i].dest = a, b
    mp.resolved = True
    return True
