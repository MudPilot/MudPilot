"""You take over a fight by hand: MudPilot keeps its hands off that monster until you're done.

Dan, 2026-10-29: 'dtch sc' to drain HP back while poisoned — the game drops combat after the cast, MudPilot saw
*Combat Off* with the scorpion still there and sent 'fork scorpion', Dan cast dtch again, MudPilot sent fork again…

An attack or a targeted spell you type at a monster in the room arms the override. While it's on, the bot sends no
attacks, re-engages or spell switches (running away, hanging up, heals and cures still happen). It ends when:
  • the monster dies, leaves, or you leave the room — the bot fights whatever's next as usual;
  • combat is off and two rounds pass without another attack/targeted spell from you (one missed round from a
    mistimed bless is normal) — the bot takes that same monster over;
  • four rounds since your last attack/targeted spell, whatever else is going on — same.
Anything you type that isn't an attack or a targeted spell (bless, st, eq…) doesn't keep it going."""
import re
import time

from .gamestate import EXP_RE

ATTACK_WORDS = {"a", "at", "att", "atta", "attac", "attack", "aa", "bs", "backstab", "bash", "smash", "sm", "kill",
                "k", "sn", "snea"}
# words that take a target but aren't attacks (a spell short can't be one of these)
NOT_ATTACKS = {"l", "lo", "look", "ex", "exa", "exam", "examine", "get", "g", "drop", "dr", "give", "gi", "say",
               "tell", "te", "pe", "pea", "peak", "buy", "sell", "use", "eq", "rem", "remove", "inv", "i", "go",
               "open", "op", "close", "pick", "bre", "break", "search", "sea", "hide", "sneak", "ask", "touch",
               "read", "join", "invite", "inv", "track", "steal", "wear", "wield", "arm", "list", "deposit",
               "withdraw", "train", "rub", "push", "pull", "dig", "light", "extinguish"}
DEATH_WORDS_RE = re.compile(r"\b(?:dies|is dead|collapses|falls dead|falls to the ground|crumbles|disintegrates|"
                            r"vanishes|is destroyed|dying breath|death)\b", re.I)


def _matches(name: str, word: str) -> bool:
    """MajorMUD's targeting: 'sc' hits 'large giant scorpion' (any word of the name starts with it)."""
    n, w = name.lower(), word.lower().strip()
    return bool(w) and (n.startswith(w) or any(p.startswith(w) for p in n.split()))


class ManualFight:
    def __init__(self, bot):
        self.b = bot
        self.mob = None              # the monster's name as the room shows it, while the override's on
        self.cands = []              # names your abbreviation could mean (the game's reply picks one)
        self.room = None
        self.armed_at = 0.0
        self.last_attack = 0.0
        self.resolve_until = 0.0
        self.cmd = ""
        self.takeover = None         # (name, when): the monster MudPilot takes back over after a timeout

    # ------------------------------------------------------------ settings
    def _round(self) -> float:
        c = getattr(self.b.s, "clock", None)
        if c is not None and c.learned:
            return float(c.period)               # the rounds as timed (Dan: it determines that for itself)
        return float(getattr(self.b.cfg, "manual_round_secs", 5) or 5)

    def idle_secs(self) -> float:
        return self._round() * int(getattr(self.b.cfg, "manual_idle_rounds", 2) or 2)

    def max_secs(self) -> float:
        return self._round() * int(getattr(self.b.cfg, "manual_max_rounds", 4) or 4)

    @property
    def active(self) -> bool:
        return bool(self.mob)

    # ------------------------------------------------------------ you typed something
    def is_attack(self, cmd: str):
        """(command word, target word) when 'cmd' is an attack or a spell at something, else None."""
        parts = (cmd or "").strip().split()
        if len(parts) < 2 or (cmd or "").lstrip().startswith(("@", "/", ".", "#", "'", '"')):
            return None
        w0 = parts[0].lower()
        first = (getattr(self.b.cfg, "attack_cmd", "") or "a").split()[0].lower()
        if w0 in ATTACK_WORDS or w0 == first:
            return w0, parts[-1]
        if w0 in NOT_ATTACKS:
            return None
        try:
            sp = self.b.s.spellbook.resolve(w0)
        except Exception:
            sp = None
        return (w0, parts[-1]) if sp else None

    def note_cmd(self, cmd: str):
        if not getattr(self.b.cfg, "manual_override", True):
            return
        hit = self.is_attack(cmd)
        if not hit:
            return
        st = self.b.st
        names = [sh for sh, _r in (st.view.monsters if st.view else [])]
        cands = [n for n in names if _matches(n, hit[1])]
        if not cands:
            return                       # at a player, or nothing here by that name
        now = time.time()
        if self.mob and self.mob in cands and self.room == st.room:
            self.last_attack = now       # the same fight: timers start again
            self.resolve_until = now + 4
            self.cmd = cmd.strip()
            return
        was = self.mob
        self.mob = cands[0]
        self.cands = cands
        self.room = st.room
        self.armed_at = self.last_attack = now
        self.resolve_until = now + 4
        self.cmd = cmd.strip()
        self.takeover = None
        if not was:
            self.b.log(f"Manual fight: you've got the {self.mob} ('{self.cmd}') — MudPilot won't attack it until "
                       f"you stop for {int(self.idle_secs())} s with combat off (or {int(self.max_secs())} s)")

    # ------------------------------------------------------------ the game says
    def note_line(self, text: str):
        if not self.mob:
            return
        t = text.strip()
        low = t.lower()
        now = time.time()
        if now < self.resolve_until:
            # "You reach out and touch large giant scorpion!" — which one 'sc' meant
            names = [sh for sh, _r in (self.b.st.view.monsters if self.b.st.view else [])] or self.cands
            for n in sorted(set(names) | set(self.cands), key=len, reverse=True):
                if n.lower() in low and (n in self.cands or _matches(n, self.cmd.split()[-1])):
                    if n != self.mob:
                        self.b.log(f"Manual fight: '{self.cmd}' is the {n}")
                    self.mob = n
                    self.resolve_until = 0
                    break
        if EXP_RE.search(t):
            return self.end("it died")
        last = self.mob.split()[-1].lower()
        if DEATH_WORDS_RE.search(t) and (self.mob.lower() in low or re.search(rf"\b{re.escape(last)}\b", low)):
            return self.end("it died")

    # ------------------------------------------------------------ each tick
    def tick(self) -> bool:
        """True while the override holds (the bot then does nothing offensive)."""
        if not self.mob:
            return False
        st = self.b.st
        now = time.time()
        if st.room != self.room:
            return self.end("you left the room") and False
        v = st.view
        if v and v.t > self.armed_at + 0.5 and self.mob not in [sh for sh, _r in v.monsters]:
            return self.end("it's gone") and False
        since = now - self.last_attack
        if since >= self.max_secs():
            return self.end(f"{int(since)} s since your last attack", takeover=True) and False
        if not st.in_combat and since >= self.idle_secs():
            return self.end(f"combat off and no attack from you for {int(since)} s", takeover=True) and False
        return True

    def left(self) -> int:
        """Seconds until MudPilot takes over (the sooner of the two limits)."""
        if not self.mob:
            return 0
        since = time.time() - self.last_attack
        lim = self.max_secs() if self.b.st.in_combat else min(self.idle_secs(), self.max_secs())
        return max(0, int(round(lim - since)))

    def label(self) -> str:
        return f"MANUAL: {self.mob} ({self.left()} s)" if self.mob else ""

    def end(self, why: str, takeover: bool = False):
        mob, self.mob, self.cands = self.mob, None, []
        self.resolve_until = 0
        if takeover:
            self.takeover = (mob, time.time())
            self.b.log(f"Manual fight over ({why}) — MudPilot takes the {mob} back over")
        else:
            self.takeover = None
            self.b.log(f"Manual fight over ({why}) — back to normal")
        self.b._cool["cast"] = self.b._cool["attack"] = 0
        return True

    def prefer(self, mobs):
        """After a timeout, the monster you were fighting goes first."""
        tk = self.takeover
        if not tk or time.time() - tk[1] > 30 or not mobs:
            return mobs
        hit = [m for m in mobs if m[0] == tk[0]]
        if not hit:
            self.takeover = None
            return mobs
        return hit[:1] + [m for m in mobs if m is not hit[0]]
