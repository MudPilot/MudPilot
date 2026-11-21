"""Spell efficiency: start every monster on the hardest-hitting spell, then dial back when it's overkill.

Watches each fight: how long the kill took, how much mana was spent, and who did the damage.
When one caster is doing nearly all the work (the others hardly land a hit because things die to
the nuke) it tries that caster on the next weaker spell for a few kills. Kills nearly as fast for
less mana → keep it (and maybe try weaker still). Noticeably slower → back to the stronger one,
and that weaker spell is left alone for 30 min.

Two (or more) MudPilots in one party tune TOGETHER, so they don't both keep changing spells and
never settle: one of them — the party leader if it runs MudPilot, else the first by name — is the
coordinator. Only it decides, and it changes one caster at a time, judging the whole party's
kill time and the whole party's mana per kill. The others cast what it tells them and report their
mana use. Wire format (hidden, party MudPilots only, see partysync.py):
    @mpsync lv <k>|<monster>                       coordinator → caster: use step k on this monster
    @mpsync sk <kills>|<mana>|<steps>|<k>|<monster>  caster → coordinator: running totals for it

Always the hardest spell when: the fight looks dangerous, a boss, or the party changes (who's in it
decides how much help you get) — then it learns again from the top.
"""
from __future__ import annotations

import re
import time

WINDOW = 6            # kills per judgement
SHARE_HIGH = 0.75     # one caster did ≥75% of the damage → room to dial back
SLOWER_OK = 1.15      # weaker spell may kill up to 15% slower (+SLACK s) …
SLACK = 0.3           # (was 1 s: kills of 1.3 s let a spell taking 2.5 s through — slower kills are lost exp)
MANA_SAVE = 0.90      # … if it saves at least 10% of the party's mana per kill
LOCK_SECS = 6 * 3600  # a weaker spell that lost its trial isn't tried again for 6 hours (was 30 min — each retry cost)
EARLY_KILLS = 2       # a trial clearly slower after this many kills is called off then, not after the whole WINDOW
#                       (2026-11-01: Revolution's trial on blood skeletons ran 28 minutes for 6 kills at 3.5 s vs 1.3 s)
MAX_STEPS = 2         # never more than this many spells below the strongest (Revolution, 2026-10-30: one step at a
#                       time from soul rip down to godstrike on purple worms — each 'barely slower' than the last)
REPORT_EVERY = 3      # caster → coordinator report every N kills of a monster (the coordinator judges per 6)
PEER_FRESH = 180

DMG_RE = re.compile(r"\bfor (\d+) (?:points of )?damage", re.I)
# "You make a complex circling gesture!" / "Revolution makes a sweeping gesture!" — the damage line that
# follows ("A withering blast of dragonfire sears drooling geist for 343 damage!") doesn't say whose it is
CAST_VERBS = (r"(?:makes?|raises?|chants?|utters?|weaves?|traces?|waves?|claps?|points?|gestures?|draws?|summons?|"
              r"calls?|invokes?|casts?|throws?|flings?|hurls?|intones?|thrusts?|lifts?|extends?|spreads?|focus(?:es)?|"
              r"concentrates?|stretch(?:es)?|clench(?:es)?|sings?|whispers?|shouts?|speaks?|motions?|channels?)")
ACTOR_ME_RE = re.compile(rf"^You {CAST_VERBS}\b", re.I)
ACTOR_RE = re.compile(rf"^([A-Z][a-z]+) {CAST_VERBS}\b")
ACTOR_SECS = 2.0
# size / mood words in front of a monster's name: tune "large drooling geist" and "nasty drooling geist" together
VARIANT_WORDS = {"large", "small", "big", "little", "nasty", "tall", "short", "fat", "thin", "young", "old", "giant",
                 "huge", "tiny", "greater", "lesser", "elder", "ancient", "adult", "baby", "fierce", "angry", "wild",
                 "mean", "vicious", "savage", "rabid", "scrawny", "burly", "hulking", "massive", "wounded", "sickly",
                 "starving", "hungry", "mangy", "plump", "skinny", "grizzled", "massive", "monstrous", "enormous",
                 "juvenile", "mature", "dire", "feral", "crazed", "frenzied", "putrid", "rotting", "decrepit"}


def family(name: str) -> str:
    """'large drooling geist' → 'drooling geist'; 'tall nightshade' → 'nightshade'."""
    words = (name or "").lower().split()
    while len(words) > 1 and words[0] in VARIANT_WORDS:
        words.pop(0)
    return " ".join(words)


class SpellTune:
    def __init__(self, session):
        self.s = session
        self.mons: dict = {}          # monster -> {"lv": {caster: k}, "trial", "base", "recs", "locked", "n": {caster: n}}
        self.told: dict = {}          # (as follower) monster -> k the coordinator set
        self.peer_tot: dict = {}      # (as coordinator) monster -> {peer: (kills, mana, steps, k, t)}
        self.my_tot: dict = {}        # monster -> [kills, mana] this session (what we report)
        self._party_key = None
        self._fight = None            # {"mon", "t0", "dmg": {name: n}, "mana", "spell"}
        self._last_ma = None
        self._role_said = None
        session.state.on_exp.append(self._on_kill)

    # ------------------------------------------------------------ who decides
    def me(self) -> str:
        return (self.s.settings.my_name or "me").lower()

    def mudpilot_peers(self) -> list:
        """Party members running a MudPilot that tunes with us (fresh party-sync news)."""
        ps = getattr(self.s, "partysync", None)
        if not ps or not self.s.settings.party_sync:
            return []
        party = {n.lower(): n for n in self.s.state.party}
        now = time.time()
        return sorted(party[n.lower()] for n, p in ps.peers.items()
                      if n.lower() in party and p.get("tune") and now - p.get("t", 0) < PEER_FRESH)

    def coordinator(self) -> str | None:
        """None = tuning alone. Else the (lower-case) name of who decides for the party's MudPilots."""
        peers = [p.lower() for p in self.mudpilot_peers()]
        if not peers:
            return None
        pilots = set(peers) | {self.me()}
        try:
            ld = self.s.bot.x.leader()
            leader = (ld or "").lower() if ld else (self.me() if self.s.state.party else "")
        except Exception:
            leader = ""
        return leader if leader in pilots else min(pilots)

    def role(self) -> str:
        c = self.coordinator()
        r = "solo" if c is None else ("coord" if c == self.me() else "follow")
        if r != self._role_said:
            self._role_said = r
            if r == "coord":
                self.s.log(f"Spell efficiency: tuning together with {', '.join(self.mudpilot_peers())} "
                           "— I decide, one caster at a time")
            elif r == "follow":
                self.s.log(f"Spell efficiency: tuning together — {c.capitalize()} decides, I cast what it says")
        return r

    # ------------------------------------------------------------ what to cast
    def level(self, mon_name: str) -> int:
        """How many steps down from the hardest spell to go for this monster (0 = hardest)."""
        if not self.s.settings.spell_efficiency or not mon_name:
            return 0
        self._check_party()
        mon = family(mon_name)
        if self.role() == "follow":
            return self.told.get(mon, 0)
        return self.mons.get(mon, {}).get("lv", {}).get(self.me(), 0)

    def note_ladder(self, mon_name, n_usable):
        """The fight code tells us how many usable spells there are for this monster."""
        mon = family(mon_name)
        self._n_mine = getattr(self, "_n_mine", {})
        self._n_mine[mon] = n_usable
        m = self.mons.get(mon)
        if m is not None:
            m["n"][self.me()] = n_usable

    # ------------------------------------------------------------ party sync messages
    def on_message(self, sender, a) -> bool:
        a = a.strip()
        if a.startswith("lv "):
            k, _, mon = a[3:].partition("|")
            if k.strip().isdigit() and mon.strip():
                mon = family(mon.strip())
                k = int(k)
                if self.told.get(mon, 0) != k:
                    self.s.log(f"Spell efficiency: {sender} says step {k} on {mon}"
                               + (" (hardest spell)" if k == 0 else " (a weaker spell)"))
                self.told[mon] = k
            return True
        if a.startswith("sk "):
            parts = a[3:].split("|", 4)
            if len(parts) == 5 and all(p.strip().lstrip("-").isdigit() for p in parts[:4]):
                kills, mana, steps, k = (int(p) for p in parts[:4])
                mon = family(parts[4].strip())
                self.peer_tot.setdefault(mon, {})[sender.lower()] = (kills, mana, steps, k, time.time())
                m = self.mons.get(mon)
                if m is not None:
                    m["n"][sender.lower()] = steps
                    want = m["lv"].get(sender.lower(), 0)
                    if want != k and self.role() == "coord":
                        self._tell(sender.lower(), mon, want)        # they missed one: say it again
            return True
        return False

    def _tell(self, peer, mon, k):
        name = next((n for n in self.s.state.party if n.lower() == peer), peer.capitalize())
        self.s.send(f"/{name} @mpsync lv {k}|{mon}", from_bot=True)

    def _report(self, mon):
        c = self.coordinator()
        if not c or c == self.me():
            return
        kills, mana = self.my_tot.get(mon, [0, 0])
        steps = getattr(self, "_n_mine", {}).get(mon, 0)
        name = next((n for n in self.s.state.party if n.lower() == c), c.capitalize())
        self.s.send(f"/{name} @mpsync sk {kills}|{round(mana)}|{steps}|{self.told.get(mon, 0)}|{mon}", from_bot=True)

    # ------------------------------------------------------------ watching fights
    def _check_party(self):
        st = self.s.state
        key = tuple(sorted(n.lower() for n in st.party if n.lower() != self.me()))
        if key != self._party_key:
            if self._party_key is not None and (any(any(m["lv"].values()) for m in self.mons.values())
                                                or any(self.told.values())):
                self.s.log("Party changed — back to the hardest-hitting spells (spell efficiency re-learns)")
            self._party_key = key
            self.mons, self.told, self.peer_tot = {}, {}, {}

    def whose(self, t: str):
        """Whose damage is this line? 'me', a party member's name (lower case), or None.
        Lines like 'A withering blast of dragonfire sears … for 343 damage!' belong to whoever
        just gestured/cast ('You make a complex circling gesture!')."""
        now = time.time()
        if ACTOR_ME_RE.match(t):
            self._actor = ("me", now)
            return None
        ma = ACTOR_RE.match(t)
        if ma and ma.group(1) in self.s.state.party:
            self._actor = (ma.group(1).lower(), now)
            return None
        if not DMG_RE.search(t):
            return None
        low = t.lower()
        if " you for " in low or low.endswith(" you!") or " hits you" in low or " claws you" in low:
            return None                                # a monster hitting you
        if low.startswith("your ") or low.startswith("you "):
            return "me"
        who = re.sub(r"'s?$", "", t.split()[0])
        if who in self.s.state.party:
            return who.lower()
        rest = set(re.findall(r"[a-z]+", low.split(" ", 1)[1] if " " in low else ""))
        if rest & {n.lower() for n in self.s.state.party}:
            return None                                # aimed at a party member: a monster's
        act = getattr(self, "_actor", None)
        if act and now - act[1] <= ACTOR_SECS:
            return act[0]
        return None

    def feed_line(self, text: str):
        t = text.strip()
        st = self.s.state
        who = self.whose(t) if t else None
        if who == "me":
            self.s.bot._last_hit_at = time.time()     # our spell is landing (don't re-send it)
        if not self.s.settings.spell_efficiency:
            return
        if st.max_ma and st.ma is not None:
            if self._last_ma is not None and st.ma < self._last_ma and self._fight:
                self._fight["mana"] += self._last_ma - st.ma
            self._last_ma = st.ma
        if not who:
            return
        n = int(DMG_RE.search(t).group(1))
        mon = family(getattr(self.s.bot, "_cast_target", None) or "")
        if not self._fight or (mon and self._fight["mon"] != mon):
            self._fight = {"mon": mon, "t0": time.time(), "dmg": {}, "mana": 0,
                           "spell": self.s.bot._last_spell}
        key = self.me() if who == "me" else who
        self._fight["dmg"][key] = self._fight["dmg"].get(key, 0) + n

    def status(self) -> list:
        """For diagnostics / the log: where each monster's tuning stands."""
        out = []
        for mon, m in self.mons.items():
            lv = {("you" if c == self.me() else c): k for c, k in m["lv"].items() if k}
            tr = m["trial"]
            out.append(f"{mon}: steps down {lv or 'none (hardest)'} · {len(m['recs'])}/{WINDOW} kills this round"
                       + (f" · trying {tr['caster']} one weaker" if tr else ""))
        return out

    def _on_kill(self, _exp):
        f, self._fight = self._fight, None
        if not f or not f["mon"] or not self.s.settings.spell_efficiency:
            return
        tot = sum(f["dmg"].values())
        if tot <= 0:
            return
        if f["dmg"].get(self.me()) and f["spell"] != self.s.bot._last_spell:
            return                                     # our spell changed mid-fight: not a clean sample
        mt = self.my_tot.setdefault(f["mon"], [0, 0])
        mt[0] += 1
        mt[1] += f["mana"]
        role = self.role()
        if role == "follow":
            if mt[0] % REPORT_EVERY == 0:
                self._report(f["mon"])
            return
        if role == "solo" and (not f["dmg"].get(self.me()) or f["spell"] is None):
            return                                     # meleeing alone: nothing to tune
        secs = max(0.5, time.time() - f["t0"])
        shares = {k: v / tot for k, v in f["dmg"].items()}
        self.record(f["mon"], secs, shares, f["mana"])

    # ------------------------------------------------------------ deciding
    def _casters(self, m) -> list:
        out = [self.me()] if m["n"].get(self.me(), 99) > 0 else []
        if self.role() == "coord":
            out += [p.lower() for p in self.mudpilot_peers()]
        return out

    def _peer_rate(self, mon, peer, since):
        """Mana per kill for a peer between a snapshot and now (from their running totals)."""
        cur = self.peer_tot.get(mon, {}).get(peer)
        if not cur:
            return 0.0
        k0, m0 = since.get(peer, (0, 0))
        dk = cur[0] - k0
        if dk <= 0:
            return cur[1] / cur[0] if cur[0] else 0.0
        return max(0.0, (cur[1] - m0) / dk)

    def _snapshot(self, mon):
        return {p: (v[0], v[1]) for p, v in self.peer_tot.get(mon, {}).items()}

    def record(self, mon, secs, shares, mana):
        """One kill of `mon` with the party's current spells. `shares`: {caster: share of the damage}
        (a plain float = this MudPilot's share, for tuning alone)."""
        self._check_party()
        mon = family(mon)
        if not isinstance(shares, dict):
            shares = {self.me(): shares}
        m = self.mons.setdefault(mon, {"lv": {}, "trial": None, "base": None, "recs": [], "locked": {},
                                       "n": {}, "snap": self._snapshot(mon)})
        mine_n = getattr(self, "_n_mine", {}).get(mon)
        if mine_n is not None:
            m["n"][self.me()] = mine_n
        m["recs"].append((secs, shares, mana))
        if m["trial"] is not None and m["base"] and EARLY_KILLS <= len(m["recs"]) < WINDOW:
            early = sum(r[0] for r in m["recs"]) / len(m["recs"])
            if early > m["base"][0] * SLOWER_OK + SLACK + 0.5:
                c, frm = m["trial"]["caster"], m["trial"]["from"]
                m["locked"][(c, m["lv"].get(c, 0))] = time.time() + LOCK_SECS
                self._set(m, mon, c, frm)
                m["trial"] = None
                self._new_window(m, mon)
                self.s.log(f"Spell efficiency ({mon}): {'you' if c == self.me() else c.capitalize()} on the weaker "
                           f"spell is clearly slower ({early:.1f}s vs {m['base'][0]:.1f}s after {EARLY_KILLS} kills) — "
                           "back to the stronger one now")
                return
        if len(m["recs"]) < WINDOW:
            return
        recs = m["recs"]
        avg_t = sum(r[0] for r in recs) / len(recs)
        my_mana = sum(r[2] for r in recs) / len(recs)
        peers = [p.lower() for p in self.mudpilot_peers()] if self.role() == "coord" else []
        party_mana = my_mana + sum(self._peer_rate(mon, p, m["snap"]) for p in peers)
        avg_share = {}
        for _t, sh, _m in recs:
            for c, v in sh.items():
                avg_share[c] = avg_share.get(c, 0) + v / len(recs)
        self._new_window(m, mon)
        now = time.time()
        log = self.s.log
        who = (lambda c: "you" if c == self.me() else c.capitalize())
        if m["trial"] is not None:
            c, frm = m["trial"]["caster"], m["trial"]["from"]
            bt, bm = m["base"]
            tt = (m.get("top") or (bt, bm))[0]
            # within 15% of the last step AND of the strongest spell's kills: small slowdowns don't add up
            if avg_t <= bt * SLOWER_OK + SLACK and avg_t <= tt * SLOWER_OK + SLACK and party_mana <= bm * MANA_SAVE:
                log(f"Spell efficiency ({mon}): {who(c)} on the weaker spell — kills in {avg_t:.1f}s vs {bt:.1f}s "
                    f"for {party_mana:.0f} party mana vs {bm:.0f} — keeping it")
                m["trial"], m["base"] = None, (avg_t, party_mana)
            else:
                m["locked"][(c, m["lv"].get(c, 0))] = now + LOCK_SECS
                self._set(m, mon, c, frm)
                m["trial"] = None
                log(f"Spell efficiency ({mon}): {who(c)} on the weaker spell was slower ({avg_t:.1f}s vs {bt:.1f}s) "
                    f"or no cheaper — back to the stronger one")
            return
        if m["base"] and avg_t > m["base"][0] * 1.3 + 1:
            down = [c for c, k in m["lv"].items() if k > 0]
            if down:
                c = max(down, key=lambda x: m["lv"][x])     # it got harder: give the most-dialed-back caster a step up
                self._set(m, mon, c, m["lv"][c] - 1)
                m["base"] = None
                log(f"Spell efficiency ({mon}): kills slowed to {avg_t:.1f}s — {who(c)} back to a stronger spell")
                return
        # try ONE caster a step down: the one doing the most damage, if it's carrying the fight
        for c in sorted(self._casters(m), key=lambda x: -avg_share.get(x, 0)):
            share = avg_share.get(c, 0)
            if share < SHARE_HIGH - 1e-6 and not (peers and share >= 0.45 and avg_t <= self._quick()):
                break
            k = m["lv"].get(c, 0)
            if k + 1 >= m["n"].get(c, 99) or k + 1 > MAX_STEPS or m["locked"].get((c, k + 1), 0) > now:
                continue
            if not any(m["lv"].values()):
                m["top"] = (avg_t, party_mana)       # how the strongest spells do: every step is judged against it
            m["trial"], m["base"] = {"caster": c, "from": k}, (avg_t, party_mana)
            self._set(m, mon, c, k + 1)
            log(f"Spell efficiency ({mon}): {'you are' if c == self.me() else c.capitalize() + ' is'} doing "
                f"{share:.0%} of the damage — trying "
                f"{'you' if c == self.me() else c.capitalize()} on a weaker, cheaper spell for {WINDOW} kills"
                + (" (the others keep theirs)" if peers else ""))
            return

    def _quick(self):
        """A kill this fast (≈1½ rounds) with two casters nuking is overkill too."""
        return 1.5 * (getattr(self.s.clock, "period", 5.0) or 5.0)

    def _new_window(self, m, mon):
        m["recs"] = []
        m["snap"] = self._snapshot(mon)

    def _set(self, m, mon, caster, k):
        m["lv"][caster] = max(0, k)
        if caster != self.me():
            self._tell(caster, mon, m["lv"][caster])

    def summary(self) -> list:
        return [(n, dict(m["lv"]), m["trial"] is not None) for n, m in self.mons.items() if any(m["lv"].values())]
