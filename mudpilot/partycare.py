"""Party cures (pMUD): your partner's poison, blindness, disease or being held.

How you find out:
* poison — the 'P' after a member's health in 'par' ("[H: 80%]P - Frontrank");
* the rest — the member says it in the room: '@blind', '@held', '@diseased', '@major diseased', '@darkness'
  (pMUD and MudPilot both say these; telepaths and gangpaths count too).

What happens: the one with the cure casts it on them ("cure poison Revolution"), once a round at most. A
'casts cure poison on Revolution' line from anyone, a clean 'par', or two minutes with no repeat clears it.
And the other way: when you go blind / get held / diseased in a party, MudPilot says it for your healer."""
from __future__ import annotations

import re
import time

REPORT_RE = re.compile(r"^([A-Z][A-Za-z'-]+) (?:says|telepaths|gangpaths|says to the party)[,:]?\s*(?:\([^)]*\)\s*)?"
                       r"[\"']?\.?(@(?:major[\s_-]diseased?|poisoned|blind|darkness|diseased|held|ok))\b", re.I)
CURE_RE = re.compile(r"^(?:You|[A-Z][A-Za-z'-]+) casts? (cure poison|cure blindness|cure disease|cure major disease|"
                     r"cure paralysis|freedom)\s+(?:on|upon)\s+([A-Za-z'-]+)", re.I)

COND_OF = {"@poisoned": "poison", "@blind": "blind", "@darkness": "blind", "@diseased": "disease",
           "@major diseased": "major disease", "@major disease": "major disease", "@held": "held"}
CURED_BY = {"cure poison": "poison", "cure blindness": "blind", "cure disease": "disease",
            "cure major disease": "major disease", "cure paralysis": "held", "freedom": "held"}
LABEL = {"poison": "Poisoned", "blind": "Blind", "disease": "Diseased", "major disease": "Major disease",
         "held": "Held"}
REPORT_OF = {"blind": "@blind", "disease": "@diseased", "held": "@held", "knocked": "@held"}
STALE = 120


class PartyCare:
    def __init__(self, extras):
        self.x = extras
        self.cond: dict = {}            # name -> {condition: since}
        self._tried: dict = {}          # (name, cond) -> last cure sent
        self._tries: dict = {}          # (name, cond) -> casts since the last report / par
        self._reported: set = set()     # my conditions I've already told the party about
        self._seq = None

    def _sync(self):
        st = self.st
        if getattr(st, "_party_reading", False):
            return
        if getattr(st, "party_seq", 0) != self._seq:
            self._seq = getattr(st, "party_seq", 0)
            self.on_par()

    @property
    def st(self):
        return self.x.st

    @property
    def cfg(self):
        return self.x.cfg

    def _member(self, name):
        for n in self.st.party or {}:
            if n.lower() == (name or "").lower():
                return n
        return None

    def feed_line(self, t: str):
        m = REPORT_RE.match(t.strip())
        if m:
            who = self._member(m.group(1))
            if not who or who.lower() == (self.x.me() or ""):
                return
            word = re.sub(r"[\s_-]+", " ", m.group(2).lower())
            if word == "@ok":
                if self.cond.get(who, {}).pop("held", None):
                    self.x.b._member_down_until = 0
                    self.x.b.release("member down")
                return
            c = COND_OF.get(word) or COND_OF.get(word.rstrip("d"))
            if c:
                self.cond.setdefault(who, {})[c] = time.time()
                self._tries.pop((who, c), None)
                if c == "held":
                    # held / knocked flat can't walk: the party waits for them (until their @ok, 30 s at most)
                    # — even in the timed pyramid, where nothing else is waited for
                    self.x.b.hold("member down", f"{who} is held")
                    self.x.b._member_down_until = time.time() + 30
                    # knocked down = hit too: check their HP soon, so the heal isn't left waiting (0.8.208)
                    b = self.x.b
                    b._cool["par"] = min(b._cool.get("par", 0), time.time() - float(b.cfg.party_check_secs or 5) + 1)
                    b._par_soon_until = time.time() + 20
                self.x.b.log(f"{who} says they're {LABEL.get(c, c).lower()}")
            return
        m = CURE_RE.match(t.strip())
        if m:
            c = CURED_BY.get(m.group(1).lower())
            who = self._member(m.group(2))
            if c and who:
                self.cond.get(who, {}).pop(c, None)

    def on_par(self):
        """A fresh 'par': poison comes and goes with the P flag."""
        now = time.time()
        self._tries = {k: v for k, v in self._tries.items() if k[1] != "poison"}
        for name, info in (self.st.party or {}).items():
            if name.lower() == (self.x.me() or ""):
                continue
            flags = (info.get("flags") or "").upper()
            c = self.cond.setdefault(name, {})
            if "P" in flags:
                c.setdefault("poison", now)
            else:
                c.pop("poison", None)
        for name in list(self.cond):
            if not self._member(name):
                self.cond.pop(name, None)

    def conditions(self, name) -> list:
        """What's wrong with a member right now (for the Party window)."""
        self._sync()
        now = time.time()
        c = self.cond.get(name) or {}
        for k in [k for k, t in c.items() if now - t > STALE and k != "poison"]:
            c.pop(k, None)
        out = [LABEL.get(k, k) for k in c]
        info = (self.st.party or {}).get(name) or {}
        fl = (info.get("flags") or "").upper()
        if "M" in fl:
            out.append("Meditating")
        elif "R" in fl:
            out.append("Resting")
        return out

    def _cmd_for(self, c):
        cfg = self.cfg
        return {"poison": cfg.cure_poison_cmd, "blind": cfg.cure_blind_cmd, "disease": cfg.cure_disease_cmd,
                "major disease": getattr(cfg, "cure_major_disease_cmd", "") or cfg.cure_disease_cmd,
                "held": cfg.freedom_cmd}.get(c) or ""

    def healing_first(self) -> bool:
        """Freedom / cure paralysis waits while the party still needs healing or rest (Dan, 2026-11-16: no reason to
        free someone knocked off their feet if we're going to sit and heal for 3-4 rounds anyway — heal first; if
        they're still down once the party's healed up and ready to move, that's the time to free them)."""
        st, cfg = self.st, self.cfg
        if st.resting or getattr(st, "meditating", False):
            return True
        try:
            mine = st.hp_pct() if st.max_hp else 100
        except Exception:
            mine = 100
        if mine < max(int(cfg.heal_pct or 0), int(cfg.rest_below_hp or 0)):
            return True
        try:
            ma = st.ma * 100 / st.max_ma if st.max_ma else 100
        except Exception:
            ma = 100
        if int(cfg.rest_below_ma or 0) and ma < int(cfg.rest_below_ma):
            return True         # we're about to sit for mana anyway (0.8.208: Revolution at 67%, rest line 70%)
        if getattr(cfg, "party_heal", False):
            fresh = max(30.0, 4 * float(cfg.party_check_secs or 5))
            me = (cfg.my_name or "").lower()
            now = time.time()
            for name, info in (st.party or {}).items():
                if name.lower() != me and now - info.get("t", 0) <= fresh and \
                        info.get("hp", 100) < int(cfg.party_heal_pct or 0):
                    return True
            # 0.8.208 (Dan, 2026-11-19): knocked down = hit too, and the last 'par' is from before the hit
            # (Miserable read 97%, got freedom first, then needed the heals). Wait for a 'par' after the report
            # (it goes out within a couple of seconds), 10 s at most
            for name, conds in self.cond.items():
                since = conds.get("held")
                if not since or now - since > 10:
                    continue
                info = next((v for n, v in (st.party or {}).items() if n.lower() == name.lower()), None) or {}
                if info.get("t", 0) < since:
                    return True
        return False

    def tick(self) -> bool:
        """Cure a party member who needs it. True = sent something."""
        cfg = self.cfg
        if not getattr(cfg, "party_cures", True) or not self.st.party:
            return False
        self._sync()
        now = time.time()
        for name, conds in list(self.cond.items()):
            if not self._member(name):
                continue
            for c, since in list(conds.items()):
                if c != "poison" and now - since > STALE:
                    conds.pop(c, None)
                    continue
                cmd = self._cmd_for(c).strip()
                if not cmd or not self.x._is_spell(cmd):
                    continue                        # a potion / item can't be used on someone else
                if c == "held" and self.healing_first():
                    continue                        # heals / rest first, freedom after
                v = self.st.view
                if not v or not any(p.split()[0].strip(".,*").lower() == name.lower() for p in (v.players or []) if p):
                    continue                        # not here: the cure can't reach them
                if now - self._tried.get((name, c), 0) < 6:
                    continue
                if self._tries.get((name, c), 0) >= 3:
                    continue                        # 3 casts didn't take — wait for a fresh report / par
                if not self.x.b.slot_free():
                    return False                    # (not a try: nothing was cast)
                self._tries[(name, c)] = self._tries.get((name, c), 0) + 1
                self._tried[(name, c)] = now
                self.x.b.status = f"Curing {name} ({LABEL.get(c, c).lower()})"
                self.x.b.log(self.x.b.status)
                self.x.b.why("party_cure", who=name, cond=c, cmd=cmd)
                self.x.send(f"{cmd} {name}")
                return True
        return False

    def report_mine(self, name, on: bool):
        """Tell the party I'm blind / held / diseased (pMUD's room reports), once per bout."""
        cfg = self.cfg
        word = REPORT_OF.get(name)
        if not word:
            return
        if not on:
            was = name in self._reported
            self._reported.discard(name)
            if was and word == "@held" and self.st.party and not (self._reported & {"held", "knocked"}):
                self.x.send("@ok")                    # back on my feet / free: the party can go on
                self.x.b.log("Told the party: @ok")
            return
        if name in self._reported or not self.st.party or not getattr(cfg, "report_conditions", True):
            return
        mine = self._cmd_for(name).strip() if name != "knocked" else ""
        if mine:
            return                                    # I can cure it myself
        self._reported.add(name)
        self.x.send(word)
        self.x.b.log(f"Told the party: {word}")
