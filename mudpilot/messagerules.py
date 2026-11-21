"""Message rules: MegaMUD's Messages file, working in MudPilot.

MegaMUD keeps game messages in a "Messages" file. Each entry is
    Name:MASK:MODE:Response
    start message            ({target}, {dmg} … are wildcards)
    end message (optional)   (the "ends with" / wear-off line)
MASK (hex) says what the message means for you; MODE says what to do about it; Response is
commands to send (^M = Enter). pMUD worked out the bits; we use the same meaning:
    0001 blind · 0002 confused · 0004 poisoned · 0008 losing HP · 0010 can't move · 0020 can't attack
    0040 diseased · 0080 HP regen · 0100 find in conversations · 0200 mana regen · 0400 find anywhere
    in the line · 1000 ends combat · 2000 last action failed · 4000 use while chasing · 8000 disabled
    MODE 1 check the room · 2 wait for it to wear off · 3 rest to full HP · 4 rest to full mana ·
         5 don't rest — keep going · 6 hang up
MudPilot ships with the Messages data pMUD imported (841 entries, 255 that do something). You can
import your own MegaMUD Messages file, and add or edit rules in Game Data → Messages.

Conditions (blind, confused, poisoned, held…) feed the cures and holds MudPilot already has: held =
no walking until it wears off; blind/confused = no walking or starting fights (Health tab settings).

Also learns: a death line it has never seen just before "You gain N experience" goes to Game Data →
Messages → Needs review, with the monster it was fighting, so new lines can be taught.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import config

BITS = {0x0001: "blind", 0x0002: "confused", 0x0004: "poisoned", 0x0008: "losing_hp", 0x0010: "held",
        0x0020: "no_attack", 0x0040: "diseased", 0x0080: "hp_regen", 0x0200: "mana_regen"}
F_CONVO, F_ANYWHERE, F_ENDS_COMBAT, F_FAILED, F_DISABLED = 0x0100, 0x0400, 0x1000, 0x2000, 0x8000
MODES = {0: "nothing", 1: "check the room", 2: "wait for it to wear off", 3: "rest to full HP",
         4: "rest to full mana", 5: "don't rest — keep going", 6: "hang up"}
# MudPilot's own ailment names (extras.STATUS_RES / cures)
AILMENT = {"blind": "blind", "confused": "confused", "poisoned": "poison", "diseased": "disease", "held": "held"}
HEADER_RE = re.compile(r"^(?P<name>[^:\n]+):(?P<mask>[0-9A-Fa-f]{4}):(?P<mode>\d+):(?P<resp>.*)$")
WILD_RE = re.compile(r"\{(\w+)\}")
DEATH_WORDS = re.compile(r"\b(?:dead|dies|died|slain|collapses|crumbles|dissolves|dissipates|vanishes|shatters|"
                         r"falls|slumps|keels over|breathes its last|turns to (?:stone|dust|ash)|is ended|is still|"
                         r"no more|heap|bursts|explodes|disintegrates|fades)\b", re.I)
KNOWN_DEATH = re.compile(r"(?:falls to the ground|is dead|has been slain|dies|collapses|breathes its last|"
                         r"turns to dust|dies in a heap)", re.I)
COOLDOWN = 8.0
CONDITION_SECS = 120          # a condition with no end line clears itself after this


def parse(text: str) -> list:
    """MegaMUD Messages text → [rule dicts]."""
    rules, cur = [], None
    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        m = HEADER_RE.match(line)
        if m:
            cur = {"name": m.group("name").strip(), "mask": int(m.group("mask"), 16), "mode": int(m.group("mode")),
                   "resp": m.group("resp"), "start": "", "end": ""}
            rules.append(cur)
            continue
        if cur is None:
            continue
        if not line.strip():
            cur = None
            continue
        if not cur["start"]:
            cur["start"] = line.strip()
        elif not cur["end"]:
            cur["end"] = line.strip()
    return [r for r in rules if r["start"]]


def dump(rules: list) -> str:
    out = []
    for r in rules:
        out.append(f"{r['name']}:{r['mask']:04X}:{r['mode']}:{r.get('resp', '')}")
        out.append(r["start"])
        if r.get("end"):
            out.append(r["end"])
        out.append("")
    return "\n".join(out)


def to_regex(template: str, anywhere: bool) -> re.Pattern:
    """'Acid sears {target} for {dmg} damage!' → a regex; ending punctuation is optional."""
    t = template.strip().rstrip(".!?")
    parts = WILD_RE.split(t)
    rx = ""
    for i, p in enumerate(parts):
        if i % 2:
            rx += r"(\d[\d,]*)" if p.lower() in ("dmg", "damage", "amount", "heal", "num", "n") else r"(.+?)"
        else:
            rx += re.escape(p)
    body = rx + r"[.!?]*"
    return re.compile(body if anywhere else r"^\s*" + body + r"\s*$", re.I)


def does_something(r) -> bool:
    if r["mask"] & F_DISABLED:
        return False
    return bool(r["mask"] & ~(F_CONVO | F_ANYWHERE)) or r["mode"] or (r.get("resp") or "").strip()


class MessageRules:
    def __init__(self, session):
        self.s = session
        self.rules: list = []
        self.active: list = []        # [(rule, start_rx, end_rx)]
        self.conditions: dict = {}    # condition → {"since", "rule"}
        self.review: list = []        # [{"line", "monster", "n", "t"}]
        self._fired: dict = {}
        self._recent: list = []       # last few screen lines (for the death-line capture)
        self._waiting = None          # rule name we wait to wear off (mode 2)
        self.load()

    # ------------------------------------------------------------ storage
    @property
    def file(self):
        return os.path.join(config.DATA_DIR, "messages.md")

    @property
    def review_file(self):
        return os.path.join(config.DATA_DIR, "messages_review.json")

    def load(self):
        own = os.path.exists(self.file)
        src = self.file if own else os.path.join(os.path.dirname(__file__), "bundled", "megamud_messages.md")
        try:
            with open(src, encoding="utf-8", errors="replace") as f:
                self.rules = parse(f.read())
        except OSError:
            self.rules = []
        if not own:
            for r in self.rules:
                r["bundled"] = True       # someone else's file: no hang-ups or replies until you make it yours
        try:
            with open(self.review_file, encoding="utf-8") as f:
                self.review = json.load(f)
        except (OSError, ValueError):
            self.review = []
        self.compile()

    def save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(dump(self.rules))
        os.replace(tmp, self.file)

    def save_review(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(self.review_file, "w", encoding="utf-8") as f:
            json.dump(self.review[-200:], f, indent=1)

    def import_file(self, path, replace=False) -> int:
        with open(path, encoding="utf-8", errors="replace") as f:
            new = parse(f.read())
        if replace:
            self.rules = new
        else:
            have = {(r["name"].lower(), r["start"].lower()) for r in self.rules}
            self.rules += [r for r in new if (r["name"].lower(), r["start"].lower()) not in have]
        self.save()
        self.compile()
        self.s.log(f"Messages: imported {len(new)} entries from {os.path.basename(path)}")
        return len(new)

    def compile(self):
        out = []
        for r in self.rules:
            if not does_something(r):
                continue
            try:
                out.append((r, to_regex(r["start"], bool(r["mask"] & F_ANYWHERE)),
                            to_regex(r["end"], True) if r.get("end") else None))
            except re.error:
                continue
        self.active = out

    # ------------------------------------------------------------ live
    def feed_line(self, text: str, chat=False):
        t = (text or "").strip()
        if not t or not self.s.settings.message_rules_on:
            return
        chat = chat or bool(re.match(r"^\w+ (?:telepaths|gossips|says|gangpaths|auctions):?|^Broadcast from", t))
        self._recent = (self._recent + [t])[-6:]
        now = time.time()
        if "held" in self.conditions:
            self.confirm_held(t)
        for cond, c in list(self.conditions.items()):
            if c.get("end_rx") and c["end_rx"].search(t):
                self._clear(cond, "wore off")
            elif now - c["since"] > CONDITION_SECS:
                self._clear(cond, "timed out")
        for r, srx, _erx in self.active:
            if chat and not r["mask"] & F_CONVO:
                continue
            if not srx.search(t):
                continue
            self._fire(r, _erx, now, t)
        if re.match(r"^You gain [\d,]+ experience", t):
            self._capture_death()

    # pMUD: only a line that says it happened to you sets a condition — the cast announcement ('casts poison
    # bolt upon you') comes before the roll, and a resisted spell doesn't poison you
    NOT_ABOUT_YOU_RE = re.compile(r"\bcasts?\b.*\b(?:on|upon|at)\s+you\b|^a cool wind blows around you", re.I)

    def _fire(self, r, end_rx, now, line=""):
        s, b = self.s, self.s.bot
        about_you = not (line and self.NOT_ABOUT_YOU_RE.search(line))
        name = r["name"]
        low = name.lower()
        if low.endswith(" end"):
            base = low[:-4].strip()
            bits = 0
            for rr in self.rules:
                if rr["name"].lower() == base:
                    bits |= rr["mask"]
            ends = {c for b_, c in BITS.items() if bits & b_}
            for cond, c in list(self.conditions.items()):
                if cond in ends or c["rule"].lower().startswith(base):
                    self._clear(cond, "wore off")
            if self._waiting and self._waiting.lower().startswith(base):
                self._waiting = None
        for bit, cond in BITS.items():
            if r["mask"] & bit and about_you:
                # the shipped file calls 'weakness' and the like "can't move" — but you can. Only your own rules,
                # or the game refusing a move ("You are held!"), stop the walk
                tentative = cond == "held" and r.get("bundled") and not self.REAL_HOLD_RE.search(
                    f"{name} {r.get('start', '')} {line}")
                if cond not in self.conditions:
                    s.log(f"Messages: {cond.replace('_', ' ')} ({name})" + (
                        " — walking on (it only stops if a move fails, e.g. too heavy to move)" if tentative else ""))
                self.conditions[cond] = {"since": now, "rule": name, "end_rx": end_rx, "tentative": tentative,
                                         "rule_own": None if r.get("bundled") else True}
                ail = AILMENT.get(cond)
                if ail and not tentative:
                    b.x.ailments.setdefault(ail, now)
        if r["mask"] & F_ENDS_COMBAT:
            s.state.in_combat = False
            s.state.need_refresh = True
        if r["mask"] & F_FAILED:
            for i, e in enumerate(s.state.pending):
                if e[0] == "move":
                    del s.state.pending[i]
                    s.state.move_failed += 1
                    break
        if now - self._fired.get(name, 0) < COOLDOWN:
            return
        self._fired[name] = now
        mode = r["mode"]
        if r.get("bundled") and mode in (2, 3, 4, 6):
            mode = 0                      # the shipped file's waits / hang-ups / rests are someone's own choices
            # (its 'weakness — wait for it to wear off' stood the party still ~45 s a time in the glades)
        if mode == 1:
            s.state.need_refresh = True
        elif mode == 2:
            self._waiting = name
            s.log(f"Messages: {name} — waiting for it to wear off before moving on")
        elif mode in (3, 4):
            b._msg_rest_full = time.time()
            s.log(f"Messages: {name} — resting to full {'HP' if mode == 3 else 'mana'} next")
        elif mode == 5:
            b._no_rest_until = now + 30
        elif mode == 6:
            s.safety.hangup(f"message: {name}")
            return
        resp = "" if r.get("bundled") else (r.get("resp") or "")
        if resp.strip():
            for c in resp.split("^M"):
                if c.strip() or resp.strip() == "^M":
                    s.send(c.strip(), from_bot=True)
                    if resp.strip() == "^M":
                        break

    REAL_HOLD_RE = re.compile(r"entangl|\bheld\b|\bhold\b|paraly|\bweb|frozen|freez|immobil|can'?t move|cannot move|"
                              r"rooted|stuck|petrif|stone|bola|net\b|snare|bound|pinned|knocked", re.I)
    HELD_CONFIRM_RE = re.compile(r"^you (?:are|'re) (?:held|paralyzed|unable to move|frozen|stuck)|^you can'?t move|"
                                 r"^you cannot move|^you struggle,? but can'?t move|"
                                 # weakness only stops you when it leaves you over-encumbered (Dan)
                                 r"too (?:heavy|much|encumbered|weak) to (?:move|walk|go)|"
                                 r"(?:carrying|holding) too much|overloaded|overburdened", re.I)

    def confirm_held(self, line):
        """The game refused a move: a 'held' the shipped file guessed at is real after all."""
        c = self.conditions.get("held")
        if c and c.get("tentative") and self.HELD_CONFIRM_RE.search(line.strip()):
            c["tentative"] = False
            c["confirmed"] = time.time()
            self.s.bot.x.ailments.setdefault("held", time.time())
            self.s.log(f"Messages: really can't move ({c['rule']}) — waiting")

    def _clear(self, cond, why):
        c = self.conditions.pop(cond, None)
        if c:
            self.cleared_at = {**getattr(self, "cleared_at", {}), cond: time.time()}   # (bot._knocked_down_now)
        ail = AILMENT.get(cond)
        if ail:
            self.s.bot.x.ailments.pop(ail, None)
        if c:
            self.s.log(f"Messages: {cond.replace('_', ' ')} gone ({why})")

    def holding_walk(self) -> str | None:
        """Can't walk right now: held (can't move), or waiting for something to wear off (mode 2)."""
        if not self.s.settings.message_rules_on:
            return None
        c = self.conditions.get("held")
        if c and not c.get("tentative"):
            if c.get("rule_own") is None and time.time() - c.get("confirmed", time.time()) > 60:
                # paused a minute on a shipped rule (weakness): try a step again — refused again, wait another
                # round; it carries on by itself even if the wear-off line was missed (Dan: wait, don't stop)
                c["tentative"] = True
                self.s.bot.x.ailments.pop("held", None)
                return None
            return f"can't move ({c['rule']})"
        if self._waiting:
            if time.time() - self._fired.get(self._waiting, 0) > 90:
                self._waiting = None
                return None
            return f"waiting for {self._waiting} to wear off"
        return None

    # ------------------------------------------------------------ learning death lines
    def _capture_death(self):
        mon = getattr(self.s.bot, "_cast_target", None) or ""
        for line in reversed(self._recent[:-1][-4:]):
            low = line.lower()
            if re.search(r"for \d+ damage|^you (?:swing|kick|critically|cast|attempt)|^\[hp=|drop to the ground|"
                         r"^you notice|^also here|^obvious exits", low):
                continue
            if not DEATH_WORDS.search(line) or KNOWN_DEATH.search(line):
                continue
            for rv in self.review:
                if rv["line"] == line:
                    rv["n"] += 1
                    rv["t"] = time.time()
                    break
            else:
                self.review.append({"line": line, "monster": mon, "n": 1, "t": time.time()})
                self.s.log(f"Messages: new death line for review — \"{line}\"")
            self.save_review()
            return
