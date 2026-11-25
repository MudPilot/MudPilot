"""The bot: decides what to send each tick. Priority order mirrors MegaMUD:
run > heal > fight > loot > rest > walk. Walking follows MegaMUD paths/loops that
have been resolved to exact MME rooms, and re-routes itself if it gets lost."""
from __future__ import annotations

import math
import os
import re
import threading
import time

from .gamestate import GameState, coin_kind, COIN_VALUE, FRIENDLY_VERBS
from .gamestate import wielded as wielded_
from .megamud_files import MPath, path_from_route, anchor_path, step_exit
from .worlddb import REVERSE, DIRS, DIR_WORDS, norm_dir
SEARCH_CMD_RE = re.compile(r"^\s*sea(?:r(?:c(?:h)?)?)?\s+\S", re.I)    # search / sear / sea <dir>


def cfg_auto_get(cfg) -> bool:
    return bool(getattr(cfg, "auto_get_items", True))


_ITEM_NUM_RE = re.compile(r"(?<=[A-Za-z'])\((\d{1,5})\)")


def path_text(cmd: str) -> str:
    """A path command as the game takes it: MegaMud loop files write key steps 'use chiseled key(1264) SW' — the item
    number in brackets is MegaMud's own note, not part of the name (m1617c K1b) → 'use chiseled key SW'."""
    return _ITEM_NUM_RE.sub("", cmd) if "(" in (cmd or "") else cmd


# a step down the spell ladder has to kill the monster for this much less mana, or the harder spell stays (Dan,
# 2026-11-03: Miserable PVE flipping magma blast / sphere of implosion / forked lightning — a 500 HP monster is 6 magma
# blasts, 30 mana, one round; 2 spheres, 50 mana, two rounds. A quick spell stops when the monster dies.)
STEP_DOWN_GAIN = 1.15

# first words of commands that fight rather than walk: their "Your command had no effect." isn't the path's
COMBAT_WORDS = {"a", "at", "att", "atta", "attack", "k", "ki", "kil", "kill", "bs", "backstab", "brea", "break",
                "bash", "pu", "punch", "kick", "ki", "jumpkick", "jk", "smash", "sm", "c", "cast"}


class Automation:
    def __init__(self, session):
        self.s = session
        self.path: MPath | None = None
        self.idx = 0
        self.laps = 0
        self.loop = False
        self.walking = False
        self.detour: list | None = None     # list[Exit] used to get back onto the path
        self.after_goto = None              # path to start once a goto finishes
        self.last_path: MPath | None = None # for @rego / @loop last
        self.last_loop = False
        self.status = "Idle"
        self._cool: dict[str, float] = {}
        self._party_engaged_at = 0.0  # a party member started a fight (attack last)
        self._mobs_since = 0.0
        self._pheal_at: dict = {}
        from .extras import Extras
        self.x = Extras(self)
        from .errands import Errands
        self.errands = Errands(self)
        from .peruse import Peruse
        self.peruse = Peruse(self)
        from .partyflags import PartyFlags
        self.partyflags = PartyFlags(self)
        from .stash import Stash
        self.stash = Stash(self)
        from .manualfight import ManualFight
        self.manual = ManualFight(self)
        from .redress import Redress
        self.redress = Redress(self)
        from .lights import AutoLight
        self.lights = AutoLight(self)        # carried torches / lanterns for dark rooms (0.8.200, lights.py)
        self._opening_dir = None
        self._locked_dir = None
        self._lock_tries: dict = {}
        self._lock_room = None
        self._run_left = 0
        self._run_from = None
        self._dim_at = 0.0
        self._search_n: dict = {}
        from .regenclock import RegenClock
        self.regen = RegenClock()
        self._swap = None            # "rest" / "med" while pre-rest gear is on (post commands still owed)
        self._swap_rested = False    # the game confirmed we were resting after the swap
        self._await_seq = None
        self._step_sent_at = 0.0
        self._last_room_seq = -1
        self._last_refresh = 0.0
        self._looted_seq = -1
        self._no_item: dict = {}            # (room, item) -> when a get of it didn't take (too heavy): not again for 5 min
        self._loot_tries = 0
        self._last_hp = None
        self._attacked_at = 0.0
        self._fled = False
        self._last_progress = time.time()
        self._detour_from = None
        self._detour_expect = None
        self._expect_seq = None
        self._expect_fail = 0
        self._resends = (None, 0)            # (room, move) sent again without the room changing, count
        self._last_spell = None
        self._melee_on = False
        self._pre_done = False
        self.hunt_target = None             # monster record an event is hunting
        self._hidden_seq = -1
        self._searched_room = None
        self._mode = "manual"
        self._unsure_since = 0.0
        self._locate_at = 0.0
        self._locate_seen = 0
        self._locate_failed = 0
        self._spells_asked = False
        self._spells_asked_at = 0.0
        self._buff_cast: dict = {}
        self._buff_off: dict = {}
        self._abil_checked_at = 0.0
        self._rule_checked: dict = {}
        self._rerolls: dict = {}
        from .smartrest import SmartRest
        self.smart = SmartRest(self)
        self.buff_note: dict = {}
        self.spell_info = ""
        self.paused = False
        from .pilot import Pilot
        self.pilot = Pilot(self)            # Go to: plans every step from where we really are (pilot.py)

    # ---------------------------------------------------------- helpers
    @property
    def st(self) -> GameState:
        return self.s.state

    @property
    def cfg(self):
        return self.s.settings

    def log(self, msg):
        self.s.log(msg)

    def ready(self, key, secs) -> bool:
        now = time.time()
        if now - self._cool.get(key, 0) >= secs:
            self._cool[key] = now
            return True
        return False

    INFO_CMDS = ("par", "i", "stat", "st", "exp", "abil")

    def _info_gate(self, cmd) -> bool:
        """pMUD's Gather settings: your rules for the bot's own info commands (par, i, stat, exp, abil) — a
        minimum gap, not in combat, not while walking. A blocked one waits and goes out once it's allowed
        (so whatever asked still gets its answer). True = send it now."""
        c = (cmd or "").strip().lower()
        base = c.split()[0] if c else ""
        rules = (getattr(self.cfg, "info_cmd_rules", None) or {}).get(base if base != "st" else "stat")
        stats = self.__dict__.setdefault("info_stats", {})
        rec = stats.setdefault(base, {"sent": 0, "deferred": 0, "last": 0.0})
        if base not in self.INFO_CMDS or not rules:
            rec["sent"] += 1
            rec["last"] = time.time()
            return True
        now = time.time()
        why = None
        if float(rules.get("gap") or 0) and now - rec["last"] < float(rules["gap"]):
            why = "gap"
        elif rules.get("no_combat") and self.st.in_combat:
            why = "combat"
        elif rules.get("no_walking") and self.walking and self._step_sent_at and now - self._step_sent_at < 3:
            why = "walking"
        if why:
            q = self.__dict__.setdefault("_info_q", {})
            if c not in q:
                rec["deferred"] += 1
            q[c] = now
            return False
        rec["sent"] += 1
        rec["last"] = now
        return True

    def _info_flush(self):
        q = getattr(self, "_info_q", None)
        if not q:
            return
        for c in list(q):
            if time.time() - q[c] > 120:
                q.pop(c, None)                     # nobody's waiting for it any more
            elif self._info_gate(c):
                q.pop(c, None)
                self.s.send(c, from_bot=True)

    def _late_round(self, cmd, sp_) -> bool:
        """A partial-round spell (sleep): it lasts only to the end of the round it's cast in, so cast early it wears
        off before the round goes and does nothing (Dan, 2026-10-30). Hold it for the last couple of seconds."""
        late = {x.strip().lower() for x in re.split(r"[,\s]+", self.cfg.late_round_spells or "") if x.strip()}
        w = (cmd or "").split()
        short = (w[0] if w[0].lower() not in ("cast", "c") or len(w) < 2 else w[1]).lower() if w else ""
        if not late or not (short in late or (sp_.get("Name") or "").lower() in late):
            return False
        clock = getattr(self.s, "clock", None)
        left = clock.left() if clock else None
        win = float(self.cfg.late_round_secs or 2.0)
        if not left or left[0] <= win:
            return False
        self._late_q = (cmd, time.time())
        self.status = f"{sp_.get('Name') or short}: casting in the last {win:g} s of the round ({left[0]:.1f} s to go)"
        return True

    def _late_flush(self):
        q = getattr(self, "_late_q", None)
        if not q:
            return
        clock = getattr(self.s, "clock", None)
        left = clock.left() if clock else None
        if time.time() - q[1] > 8 or not self.st.view:
            self._late_q = None                       # the moment's gone (moved on, fight over)
            return
        if not left or left[0] <= float(self.cfg.late_round_secs or 2.0):
            self._late_q = None
            self.send(q[0], late_ok=True)

    def send(self, cmd, late_ok=False):
        if not self._info_gate(cmd):
            return
        w = (cmd or "").split()
        sp_ = self._cmd_spell(cmd, w)
        if sp_ and not late_ok and self._late_round(cmd, sp_):
            return
        if sp_:
            self._last_spell_at = time.time()          # one spell per round — see may_cast()
            if hasattr(self.s, "combatlog"):
                self.s.combatlog.note_cast(sp_.get("Name") or "")
        if w:
            self._last_cmd = (cmd, bool(sp_) or w[0].lower() in COMBAT_WORDS)
        self.s.send(cmd, from_bot=True)

    def _cmd_spell(self, cmd, w):
        """The spell a command casts, or None. (0.8.201, realm walk: SpellBook.find falls back to any MME spell's
        short name, so the rooftops' 'jump north' was 'jump from shaft', 'dive moat' divine intervention and 'light
        torch' lightning — marked as casts, a failed chance jump then waited out the 10 s step timeout every time.)
        A path/room command is never a spell; a bare word only when it's one of this character's spells."""
        if not w:
            return None
        bk = self.s.spellbook
        if w[0].lower() in ("cast", "c") and len(w) >= 2:
            return bk.find(w[1])
        if w[0].startswith("#"):
            return bk.find(w[0])                      # an item spell ('#etc')
        if self._room_command(cmd):
            return None
        word = w[0].lower()
        mine = self._my_spell_shorts()
        if mine and word not in mine:
            return None                               # (nothing known about our spells yet: as before 0.8.201)
        return bk.find(word)

    def _room_command(self, cmd) -> bool:
        """`cmd` is a text exit / exit action of this room, or the move / pre-command of the step being walked."""
        c = (cmd or "").strip().lower()
        try:
            r = self.s.world.room(self.st.room) if self.st.room else None
            for ex in (r.exits.values() if r else ()):
                if ex.accepts(c) or c in [a.lower() for a in ex.action_cmds()]:
                    return True
            if self.walking and self.path:
                stp = self.path.steps[self.idx] if 0 <= getattr(self, "idx", -1) < len(self.path.steps) else None
                if stp is not None and (c == (stp.move or "").strip().lower()
                                        or c in [p.strip().lower() for p in (stp.pre or [])]):
                    return True
        except Exception:
            pass
        return False

    def _my_spell_shorts(self) -> set:
        """Short names this character casts: the game's spell list (or, until it's read, what the class can learn
        at this level) plus the spells in the settings."""
        cfg, out = self.cfg, set()
        out = {str(x).lower() for x in (getattr(self.st, "known_spells", None) or [])}   # the game's 'spells' list
        out.discard("")
        if not out:
            cls_name = (self.st.char_class or cfg.char_class or "").lower()
            lvl = self.st.level or cfg.char_level
            key = (cls_name, lvl)
            cache = getattr(self, "_class_shorts", None)
            if not cache or cache[0] != key:
                from .spells import class_spells
                w = self.s.world
                cls = next((k for k, v in w.classes.items() if (v.get("Name") or "").lower() == cls_name), 0) \
                    if cls_name else 0
                shorts = {(sp.get("Short") or "").lower() for sp in class_spells(w, cls, lvl)} if cls else set()
                self._class_shorts = cache = (key, shorts)
            out = set(cache[1])
        out |= {str(x).split()[0].lower() for x in (getattr(cfg, "attack_spells", None) or []) if str(x).strip()}
        for k in ("multi_spell", "pre_attack_spell", "danger_opener_spell", "drain_spell"):
            v = str(getattr(cfg, k, "") or "").strip()
            if v:
                out.add(v.split()[0].lower())
        return out

    def why(self, what, **info):
        """Record a decision once (not every tick while it holds): Copy diagnostics + the session recording."""
        key = (what, tuple(sorted((k, str(v)) for k, v in info.items() if k != "t")))
        if getattr(self, "_why_last", None) == key:
            return
        self._why_last = key
        try:
            self.s.decide(what, **info)
        except Exception:
            pass

    def just_after_round(self, secs=None) -> bool:
        """Room in this round for a bless or heal mid-fight: not in the last `late_cast_guard` seconds before the
        next round (pMUD's late-cast guard), so the attack is armed again in time and no round is lost.
        False when no round has been seen yet."""
        clock = getattr(self.s, "clock", None)
        left = clock.left() if clock else None
        if not left:
            return False
        return left[0] >= float(self.cfg.late_cast_guard or 1.6)

    def early_in_round(self) -> bool:
        """The first couple of seconds of a round (heal_window_secs): a heal then, and the attack re-sent with it,
        lands before the next round — later, and the round is lost (Dan, 2026-10-30: Revolution healing at the
        wrong time, missing rounds). False when no round has been seen yet."""
        clock = getattr(self.s, "clock", None)
        left = clock.left() if clock else None
        if not left:
            return False
        return left[0] >= float(getattr(clock, "period", 5.0) or 5.0) - float(self.cfg.heal_window_secs or 2.5)

    def slot_free(self) -> bool:
        """One spell a round for everything — heals, cures, party blesses, attacks: nothing goes out in a
        round that already had one, or while the game has just said 'already cast a spell this round'."""
        return self.may_cast() and time.time() >= getattr(self, "_cast_block_until", 0)

    def may_cast(self, gap: float | None = None) -> bool:
        """Never two spells in one round ("You have already cast a spell this round!"). pMUD: once the
        game's round has ticked over since the last spell, the next may go — not a fixed 4 s after it."""
        last = getattr(self, "_last_spell_at", 0)
        now = time.time()
        if gap is None:
            same = self.s.clock.same_round(last, now) if hasattr(self.s, "clock") else None
            if same is not None and now - last >= 0.6:
                return not same
        gap = float(self.cfg.spell_round_secs if gap is None else gap) * 0.9
        return now - last >= gap

    def send_macro(self, text: str):
        """Send MegaMUD-style text: '^M' separates commands ("eq sparkl^Mremove p")."""
        self._macro_at = time.time()                 # its 'Your command had no effect.' isn't the path's
        for part in (text or "").replace("^m", "^M").split("^M"):
            if part.strip():
                self.send(part.strip())

    # ---------------------------------------------------------- gear swaps around rest / meditate
    def _swap_cmds(self, kind):
        cfg = self.cfg
        if kind == "med":
            return (cfg.pre_med_cmd, cfg.post_med_cmd) if cfg.med_swap_on else ("", "")
        return (cfg.pre_rest_cmd, cfg.post_rest_cmd) if cfg.rest_swap_on else ("", "")

    def _regen_gear(self, kind):
        """Auto regen gear: (on, back) commands for the best HP / mana regen set in your pack for this rest."""
        cfg, st = self.cfg, self.st
        if not cfg.auto_regen_gear:
            return [], []
        if not st.carrying or getattr(self, "_inv_stale", False):
            if self.ready("regen_noinv", 300):
                self.log("Regen gear: inventory not read since the last gear change — resting in what's on this time")
            return [], []
        if kind == "med":
            w_hp, w_mana = 0.0, 1.0
        else:
            # a rest gets you up when HP is back (rest-until HP): HP regen is what you're waiting on, even with mana
            # at 9% — weighting by what's short left the faded shawl's −100 HP regen on for a 233 s rest. Mana only
            # breaks ties.
            w_hp, w_mana = 1.0, 0.1
        from . import gearswap
        try:
            on, back, notes = gearswap.plan(self.s.world, st.carrying, w_hp, w_mana, st.level or cfg.char_level)
        except Exception as ex:
            self.log(f"Regen gear: {ex}")
            return [], []
        if notes:
            self.log(f"Regen gear ({'meditate' if kind == 'med' else 'rest'}): " + "; ".join(notes))
        return on, back

    def _sick(self) -> bool:
        """Nauseous, confused, blind: commands getting eaten ('You retch uncontrollably!')."""
        st = self.st
        return bool(getattr(st, "sick", False)) or time.time() - (getattr(st, "confused_fail_at", 0) or 0) < 30

    def _begin_swap(self, kind):
        if self._swap == kind:
            return
        if self._swap and self._sick():
            return              # sick: one swap, then sit in it — not a swap per rest/meditate (Miserable PVE, the beholder)
        if self._swap:
            self.end_swap("switching rest type")
        pre, post = self._swap_cmds(kind)
        on, back = self._regen_gear(kind)
        if on:
            self._macro_at = time.time()
        for c in on:
            self.send(c)
        if pre.strip():
            self.send_macro(pre)
            self.log(f"Pre-{'meditate' if kind == 'med' else 'rest'}: {pre.replace('^M', '; ').strip('; ')}")
        self._swap_back = back                       # what goes back on is what we took off now
        self._swap = kind if (pre.strip() or post.strip() or on) else None
        self._swap_rested = False
        self._save_swap_owed(back)                   # survives a restart mid-rest (0.8.201, bug hunt)

    def _save_swap_owed(self, back):
        """Keep the owed 'put the fighting gear back' commands in the settings while the regen set is on, so a
        restart or relog mid-rest still puts them back (Redress sends them at the next login). 0.8.201, bug hunt."""
        cfg = self.cfg
        if list(getattr(cfg, "swap_owed", None) or []) == list(back or []):
            return
        cfg.swap_owed = list(back or [])
        cfg.save_quietly(self.s.log)

    def end_swap(self, why=""):
        """Put the normal gear back (post-rest / post-meditate) before moving or fighting."""
        if not self._swap:
            return False
        kind, self._swap = self._swap, None
        _pre, post = self._swap_cmds(kind)
        back, self._swap_back = getattr(self, "_swap_back", []), []
        self._save_swap_owed([])
        if back:
            self._macro_at = time.time()
        for c in back:
            self.send(c)
        if post.strip():
            self.send_macro(post)
            self.log(f"Post-{'meditate' if kind == 'med' else 'rest'}{f' ({why})' if why else ''}: "
                     f"{post.replace('^M', '; ').strip('; ')}")
        if back:
            if not post.strip():
                self.log(f"Fighting gear back on{f' ({why})' if why else ''}: " + ", ".join(
                    c[3:] for c in back if c.startswith("eq ")))
            self.send("i")                           # the next rest plans from what's really on now
        return True

    def _swap_tick(self, mobs, in_range):
        """Call each tick: owe the post commands once resting is over for any reason."""
        if not self._swap:
            return False
        st, cfg = self.st, self.cfg
        if st.resting:
            self._swap_rested = True
            if cfg.auto_combat and mobs and in_range:
                return self.end_swap("monsters")
            return False
        if st.in_combat:
            return self.end_swap("combat")
        if self._swap_rested and not self.walking and not mobs and \
                time.time() - (getattr(self, "_last_spell_at", 0) or 0) < 3:
            # 0.8.224 (Dan, logEVO C): our own spell (a self-mend mid-rest) stood us up — keep the regen gear on, we
            # sit straight back down (11 ring swaps in one 60 s rest, each 'remove' costing HP)
            return False
        if self._swap_rested and self._sick() and not self.walking:
            # retching broke the rest: stay in the regen gear and rest again — swapping it all off and back on with
            # every retch was a wall of eq lines (Miserable PVE, 2026-11-06, the rotting beholder's stench)
            return False
        if self._swap_rested:
            return self.end_swap()        # rest was broken (moved, attacked, stood up)
        return False

    # ---------------------------------------------------------- control
    # ---------------------------------------------------------- needed items (keys, rope and grapple…)
    def picked_items(self) -> set:
        """Items picked up since the last full inventory read. (0.8.221, bug hunt: these were kept for good, so a key
        that crumbled or an item stashed / sold still counted as carried and was never fetched again — the Stock
        walk stood at 16/287 without the king crab claw.) A fresh 'i' lists what's really carried."""
        if getattr(self, "_picked_seq", None) != self.st.inv_seq:
            return set()
        return set(getattr(self, "_picked_items", set()))

    def held_items(self) -> set | None:
        """MME item numbers you carry or have on your keyring; None = inventory not read yet."""
        st, w = self.st, self.s.world
        picked = self.picked_items()
        if not st.carrying and not st.keys:
            return picked or None
        text = f"{st.carrying or ''}, {st.keys or ''}".lower()
        names = set()
        for part in re.split(r",\s*", text):        # commas only: "rope and grapple" is one item
            n = re.sub(r"\s*\([^)]*\)\s*$", "", part.strip().rstrip("."))
            n = re.sub(r"^(?:\d+\s+|an?\s+|the\s+|some\s+)", "", n).strip()
            if n:
                names.add(n)
        return {num for num, it in w.items.items() if it.get("name") and it["name"].lower() in names} | picked

    def path_needs(self, mp: MPath) -> list:
        """[(item number, soft)] the exits on this path need, in order, no repeats."""
        w, out, seen = self.s.world, [], set()
        for stp in mp.steps:
            ex = step_exit(w, stp)                  # (0.8.201, walk check: room-command exits too — 'dig grave')
            need = w.exit_need(ex) if ex else None
            if need and ex.kind == "key":
                ok = self.door_doable(ex)
                if ok is None:                  # your picklocks / strength aren't known yet: the old rules
                    ok = need[1] or self.cfg.bash_key_doors or self.can_pick_doors()
                    # (a locked door: no key → pick/bash it; good picklocks: pick it — PVE guardian golem)
                need = (need[0], bool(ok))      # soft = you can pick or bash it yourself: no key run
            if not need and ex is not None:
                need = self._twin_need(ex, set(self.held_items() or ()))
            if need and need[0] not in seen:
                seen.add(need[0])
                out.append(need)
            for n in self._opener_items(ex):
                if n not in seen:                    # rub the bloodstone orb to open 8/398 S (Dark-Elf City)
                    seen.add(n)
                    out.append((n, False))
        if (mp.needed_item or "").strip().isdigit() and int(mp.needed_item) > 0 and int(mp.needed_item) not in seen:
            out.append((int(mp.needed_item), False))
        for n in getattr(mp, "out_items", None) or ():
            if n not in seen:                        # (0.8.223: the way back out needs it — a rope out of the Large Hole)
                seen.add(n)
                out.append((n, False))
        return out

    @staticmethod
    def _opener_items(ex) -> list:
        """Items a hidden exit's action or a room command uses (not keys): the bloodstone orb."""
        if ex is None:
            return []
        out = list(ex.action_items() or []) if ex.kind in ("hidden", "door") else []   # (+ the signet ring's gates)
        out += [i for i in ((getattr(ex, "req", None) or {}).get("items") or []) if i not in out]
        return out

    def _twin_need(self, ex, held):
        """0.8.224 (w1617 #2): the inside of a key door MME types as a plain locked door — its key, (num, soft), when
        you don't hold it; soft only if your picklocks / strength open it. Started in the Fiery Lair (16/2118)
        without the key, Go to planned out and stopped at 'the door east is locked'."""
        w = self.s.world
        if ex is None or ex.kind != "door":
            return None
        try:
            tw = w.key_twin(ex)
            tn = w.exit_need(tw) if tw is not None else None
        except Exception:
            return None
        if not tn or tn[0] in held:
            return None
        ok = w.door_beaten(ex, set(held) - {tn[0]})
        return (tn[0], ok is not False)

    def _route_items(self, here, route, have) -> set:
        """Items (not soft keys) a route's exits need that you don't carry."""
        w, out = self.s.world, set()
        for ex in route:
            need = w.exit_need(ex)
            hard = need and (not need[1] or (ex.kind == "key" and self.door_doable(ex) is False))
            if hard and need[0] not in have:
                out.add(need[0])
            tn = self._twin_need(ex, set(have)) if not need else None
            if tn and not tn[1]:
                out.add(tn[0])
            out |= {n for n in self._opener_items(ex) if n not in have}
        return out

    def _opener_route(self, here, target, lvl, avoid, have, scenic):
        """The short way crosses a prompt area (Negative Power Plane): is there a normal way in once you fetch
        an item that opens it (bloodstone orb → Dark-Elf City)? MegaMUD grabs the orb and walks in. The route
        (its items get fetched by the path's needed-items check) or None."""
        if not (self.cfg.auto_get_items and self.cfg.check_needed_items) or isinstance(target, (set, frozenset)):
            return None
        w = self.s.world
        every = set(self.plan_items(target))
        for _ in range(4):
            keyed = w.route(here, target, level=lvl, avoid=avoid, have=every)
            if keyed is None or (scenic is not None and len(keyed) >= len(scenic)):
                return None
            need = self._route_items(here, keyed, have)
            if not need:
                # only keys you can do without (the gate key: '[or 101 picklocks]'): the path's needed-items check
                # fetches it or the door gets picked — PVE stood in the Commander's Office with the orb, told "only
                # way is through Black Wasteland", one picklock door from Dark-Elf City
                if self.ready("opener_note", 60):
                    self.log("Go to: the normal way in only needs doors picked / keys fetched on the way — "
                             "going that way rather than through the avoided area")
                return keyed
            ck = (tuple(target), frozenset(need))
            cache = getattr(self, "_opener_ok", {})
            hit = cache.get(ck)
            if hit and time.time() - hit[0] < 600:
                missing = hit[1]
            else:
                missing = frozenset(n for n in need if not self.errands.source_for(n))
                self._opener_ok = {**cache, ck: (time.time(), missing)}
            if not missing:
                if self.ready("opener_note", 60):
                    self.log("Go to: the normal way in needs " + ", ".join(w.item_name(n) for n in sorted(need))
                             + " — fetching it rather than going through the avoided area")
                return keyed
            # 0.8.189 (realm walk sweep): an item nobody can get (MME has nowhere the amber talisman comes from) on
            # the way in isn't the end of it — the way without it (the Fungus Tunnel, with the orb). Solo, Silvermere
            # → Dark-Elf City said "the only way is through Black Wasteland" though there's a 250-room way round.
            every -= set(missing)
        return None

    PICK_GOOD = 100
    DOOR_NEED_RE = re.compile(r"\[(?:or\s+)?(any|\d+)\s+picklocks(/strength)?", re.I)

    def door_doable(self, ex):
        """Can you pick or bash this door yourself? '[or 91 picklocks/strength]' against your picklocks and
        strength (Dan: by the time you're big enough for the Crimson Fortress its door is bashable — no key run).
        None = MME doesn't say, or your stats aren't known yet."""
        m = self.DOOR_NEED_RE.search((ex.etype or "") if ex is not None else "")
        if not m:
            return None
        if m.group(1).lower() == "any":
            return True
        n, st = int(m.group(1)), self.st
        if not (st.picklocks or st.strength):
            return True if self.door_hands(ex) else None
        mine = (st.picklocks or 0) >= n or bool(m.group(2) and (st.strength or 0) >= n)
        return mine or bool(self.door_hands(ex))

    def door_hands(self, ex) -> list:
        """Party members (their MudPilots told us their strength / picklocks) who can bash or pick a door you
        can't (Dan, 2026-10-30: the chrome key door in the Ancient Ruin — the leader doesn't need the strength,
        just someone in the party)."""
        m = self.DOOR_NEED_RE.search((ex.etype or "") if ex is not None else "")
        if not m or not m.group(1).isdigit():
            return []
        n = int(m.group(1))
        try:
            info = self.s.partysync.info()
        except Exception:
            info = {}
        me = (self.cfg.my_name or "").lower()
        return [name for name, d in info.items() if name.lower() != me and
                ((m.group(2) and int(d.get("str") or 0) >= n) or int(d.get("pick") or 0) >= n)]

    def door_power(self, leading=False):
        """(best picklocks, best strength) for routing past locked doors: yours, and leading a party the members' whose
        MudPilots told us (party sync). None until your own are known (st) — then doors cost what they always did."""
        st = self.st
        if not (st.picklocks or st.strength):
            return None
        pick, strength = int(st.picklocks or 0), int(st.strength or 0)
        if leading:
            try:
                info = self.s.partysync.info()
            except Exception:
                info = {}
            me = (self.cfg.my_name or "").lower()
            for name, d in info.items():
                if name.lower() != me:
                    pick = max(pick, int(d.get("pick") or 0))
                    strength = max(strength, int(d.get("str") or 0))
        return pick, strength

    def party_carry(self) -> frozenset:
        """Items every follower is known to carry (of the ones each walker needs their own of: the golden idol, a mine
        pass): what their MudPilot told us (party sync 'kit=') or their answer to '@have'. A follower we know nothing
        about carries nothing, as far as routing goes."""
        me = (self.cfg.my_name or "").lower()
        members = [n for n in (self.st.party or {}) if n.lower() != me]
        try:
            info = {k.lower(): v for k, v in self.s.partysync.info().items()}
        except Exception:
            info = {}
        known = getattr(self.errands, "known_have", {}) or {}
        now, out = time.time(), None
        for m in members:
            kit = info.get(m.lower(), {}).get("kit")
            mine = set(kit) if isinstance(kit, (list, tuple, set, frozenset)) else set()
            mine |= {n for (who, n), (yes, t) in known.items() if who == m.lower() and yes and now - t < 12 * 3600}
            mine -= {n for (who, n), (yes, t) in known.items() if who == m.lower() and not yes and now - t < 12 * 3600
                     and not (isinstance(kit, (list, tuple)) and n in kit)}
            out = mine if out is None else (out & mine)
        return frozenset(out or ())

    def can_pick_doors(self) -> bool:
        """Picklocks on your stat sheet ('st') good enough to pick the locks a key opens."""
        return (self.st.picklocks or 0) >= self.PICK_GOOD

    def path_toll(self, mp: MPath) -> int:
        """All the tolls (copper) the gates on this path charge, each time it crosses one. 0.8.201, bug hunt: it was
        the biggest one — 450 copper passed two 300 gates, the first took 300 and the walk stopped at the second."""
        w, total = self.s.world, 0
        for stp in mp.steps:
            ex = step_exit(w, stp)                  # (0.8.201, walk check: room-command exits too)
            if ex and ex.kind == "toll":
                m = re.search(r"Toll:\s*(\d+)", ex.etype)
                total += int(m.group(1)) if m else 0
            elif ex is not None and (getattr(ex, "req", None) or {}).get("price"):
                total += int(ex.req["price"])        # a fare ('secure passage', a boat): paid the same way (0.8.222)
        return total

    def carry_sets(self, mp: MPath) -> list:
        """[frozenset] items each walker on this path must carry one of (a raft for the river, the golden idol)."""
        w, steps = self.s.world, []
        for stp in mp.steps:
            ex = step_exit(w, stp)                  # (0.8.201, walk check: room-command exits too)
            steps.append((stp.dest if ex is None else stp.room, ex))
        # already in the desert: the stretch walking out of it can't be helped by fetching a waterskin (that's more
        # desert too) — only desert the way goes back into later counts (Dan, 2026-11-04)
        spells = getattr(w, "room_spells", {}) or {}
        here = (mp.steps[0].room if mp.steps and mp.steps[0].room else None) or self.st.room
        mine, skip = spells.get(here) if here else None, 0
        if mine:
            for room, ex in steps:
                if spells.get(ex.to if ex else room) != mine:
                    break
                skip += 1
        try:
            return w.carry_needs(steps, skip_spell=skip)
        except Exception as ex:
            self.log(f"Needed items: couldn't read the room spells ({ex})")
            return []

    def carry_pick(self, items, own=True) -> int:
        """The one to get out of 'any of these': the cheapest a shop sells (a log raft over a canoe)."""
        w = self.s.world
        # our own, hidden at the loop, first (Dan, 2026-11-16: Miserable's log raft was stashed at the Stonecaps and
        # MudPilot set off to buy a wooden skiff — 'stash' isn't 'shop', so the raft was never in the running)
        st_ = getattr(self, "stash", None)
        mine = [n for n in items if own and st_ is not None and n in st_.stashed()]
        if mine:
            return min(mine)
        shop = [n for n in items if (self.errands.source_for(n) or {}).get("kind") == "shop"]
        return min(shop or items, key=lambda n: ((w.items.get(n) or {}).get("price") or 0, n))

    def missing_items(self, mp: MPath):
        """(missing hard needs, missing soft needs) or None if the inventory isn't known yet."""
        needs = self.path_needs(mp)
        carry = self.carry_sets(mp)
        if not needs and not carry:
            return [], []
        have = self.held_items()
        if have is None:
            return None
        hard = [n for n, soft in needs if not soft and n not in have]
        hard += [p for p in (self.carry_pick(s) for s in carry if not s & have) if p not in hard]
        return hard, [n for n, soft in needs if soft and n not in have]

    def _skip_past_target(self, mp: MPath, hard: list) -> list:
        """0.8.223 (fight3 #4): an item carried against the rooms on the way (a waterskin for the desert) whose
        nearest source is reached only by walking through the Go to's own target isn't fetched — the walk there crosses
        the same rooms anyway (12/1747 → 12/977: through 12/977 to Nekojin's store and 30 rooms back, 112 rooms for
        26). Exit needs (keys, a rope) are always fetched. The items still to fetch."""
        tgt = getattr(self, "_goto_target", None)
        here = self.st.room
        if not tgt or isinstance(tgt, (set, frozenset)) or not here:
            return hard
        tgt = tuple(tgt)
        exit_needs = {n for n, _soft in self.path_needs(mp)}
        carry = set().union(*self.carry_sets(mp)) if hard else set()
        w, out = self.s.world, []
        for n in hard:
            if n in exit_needs or n not in carry:
                out.append(n)
                continue
            src = self.errands.source_for(n, toward=tgt)
            room = tuple(src["room"]) if src and src.get("room") else None
            rt = w.route(tuple(here), room, level=self.route_level(), have=set(self.held_items() or ()),
                         avoid=self.avoid_set() or None) if room and room != tuple(here) else None
            if room == tgt or (rt and any(tuple(e.to) == tgt for e in rt)):
                self.log(f"Not fetching the {w.item_name(n)} first: the way to {src['what']} goes through "
                         f"{tgt[0]}/{tgt[1]} itself — going straight there")
                continue
            out.append(n)
        return out

    def _party_cant_buy(self, mp: MPath, loop) -> bool:
        """Leading, before an errand for your own items: what each walker needs that no shop sells (the golden idol)
        is asked of the party first — it did a whole king-crab run, then said nobody could get the idol (party3
        #4). Followers known to carry it (party sync, an earlier '@have') aren't asked. True = holding for answers."""
        if not self.st.party or not self.s.comeback.leading():
            return False
        carry = self.carry_sets(mp)
        if not carry:
            return False
        known, er = self.party_carry(), self.errands
        odd = [c for c in carry if not (frozenset(c) & known)
               and not any((er.source_for(i) or {}).get("kind") == "shop" for i in c)]
        if not odd or not er.party_check(mp, loop, odd):
            return False
        if er.asking:
            er.asking["recheck"] = True              # (everyone has it: plan the walk again — the errand comes next)
        return True

    NEVER_AUTO_ON = {"auto_nuke"}

    def switches_on(self, why):
        """A loop starting or a Go to arriving: Combat, Heal (and the rest of 'turn these on') back on, even if you
        switched them off to run there — never Nuke: off stays off (Dan, 2026-11-02: "Combat should be, nuke
        shouldnt... Combat and heal should auto turn on when your looping or arrive at a loop")."""
        cfg = self.cfg
        on = []
        if why == "Looping" and not cfg.auto_combat:
            # a loop always fights, whatever 'turn these on' says (Dan, 2026-11-20: "never does it make sense to
            # loop with combat off" — running TO the loop with it off is fine)
            on.append("auto_combat")
        if cfg.arrive_auto_on:
            on += [k for k in (cfg.arrive_turn_on or []) if k not in self.NEVER_AUTO_ON and hasattr(cfg, k)
                   and not getattr(cfg, k) and k not in on]
        for k in on:
            setattr(cfg, k, True)
        if on:
            self.log(f"{why} — turned on " + ", ".join(k.replace("auto_", "") for k in on))
            self.s.on_settings_changed()
        if why == "Looping" and "auto_combat" in on and self.st.party and not self.s.my_leader():
            # leading: a '.@auto-combat off' to run here switched the followers off too — they fight at the loop as well
            self.s.send("@auto-combat on", from_bot=True)

    def start_path(self, mp: MPath, loop: bool | None = None, checked: bool = False):
        self._expect_dest = None                     # (a step from the walk before isn't this one's — m1617c E1)
        self.no_route_msg = ""                       # (a walk is going: an old plan's reason isn't @status's answer — flags2 #8)
        self._opening_dir = None                     # (nor the last door opened, on another loop — loopsD D1)
        sn_ = getattr(self, "_stop_norest", 0)
        if sn_:
            # Stop's 'not resting for 2 minutes' was about the rest going on then, not this trip: rests before traps
            # and when hurt work again (0.8.223, m1315 R4 — a Go to a minute after Stop hung up on the lever traps)
            self._stop_norest = 0
            if getattr(self, "_no_rest_until", 0) == sn_:
                self._no_rest_until = 0
        if getattr(mp, "lair_camp", False):
            # (0.8.201, Dan) a stash / train / bank trip that left from Camp lairs comes back to camping — there's no
            # path to walk; camping picks its next lair from wherever the trip ended
            lc = getattr(self.s, "lair_camp", None)
            if lc is not None:
                lc.trip_over()
            return
        if self.dead_blocked(f"walking '{mp.title}'"):
            return
        # walking something now: whatever Rego / a reconnect would have carried on with is history (Evolution,
        # 2026-11-01: a Go to 8/493 left over from an earlier relog sat under the loop it was started on by hand, and
        # a restart's @rego sent the party off on a key errand through a dangerous lair instead of the loop)
        self.resume = None
        if getattr(self.s, "_drop_resume", None) is not None:
            self.s._drop_resume = None
        if self.st.party or getattr(self.s.comeback, "_last_members", None):
            self._cool["par"] = 0                     # a new trip: check who's with us first
        self._expect_seq, self._resends = None, (None, 0)
        self._drift = []
        if self.cfg.check_needed_items and not checked and mp.resolved:
            miss = self.missing_items(mp)
            if miss is None:
                self.log("Checking your inventory for the keys/items this path needs…")
                self._await_inv = (mp, loop, self.st.inv_seq, time.time())
                self.send("i")
                return
            hard, soft = miss
            ea = self.errands.active
            if ea:
                # the errand's own walk to get them: they're what it's going for, not a reason to start another
                # errand (Buddy, 2026-11-04: in the desert with no waterskin, 'Go to 6/1335 General Store' needed a
                # waterskin from 6/1335 and detoured there every 5 s without moving)
                fetching = {t_["num"] for t_ in ea.get("todo") or []}
                later = []
                if ea.get("todo") and self.errands._is_leg(ea, mp):
                    # 0.8.223 (m349 #6): on the errand's walk to one item, an item it gets LATER that this walk needs
                    # (the log raft for the Silver River on the way to the fang farm) is got first — not walked
                    # without. Each one moves up once at most (no ping-pong); recipe / farm steps keep their order
                    cur_ = ea["todo"][0]
                    rooms_ = {tuple(cur_["room"])} if cur_.get("room") else set()
                    rooms_ |= {tuple(r_) for r_ in cur_.get("rooms") or []}
                    now_ = {cur_["num"]} | {t_["num"] for t_ in ea["todo"]
                                            if t_.get("room") and tuple(t_["room"]) in rooms_}
                    later = [t_ for t_ in ea["todo"][1:] if t_["num"] in hard and t_["num"] not in now_
                             and not t_.get("moved_up") and t_.get("kind") in ("shop", "monster", "ask", "stash",
                                                                                "party")]
                if later:
                    ids_ = {id(t_) for t_ in later}
                    for t_ in later:
                        t_["moved_up"] = True
                    ea["todo"] = later + [t_ for t_ in ea["todo"] if id(t_) not in ids_]
                    ea["at"], ea["tries"] = None, 0
                    names_ = ", ".join(self.s.world.item_name(t_["num"]) for t_ in later)
                    self.log(f"'{mp.title}' needs the {names_} this errand gets later — getting "
                             f"{'it' if len(later) == 1 else 'them'} first")
                    self.walking = False
                    self.set_mode("auto")
                    self.status = f"Getting {names_} first"
                    return
                hard = [n for n in hard if n not in fetching]
                soft = [n for n in soft if n not in fetching]
            elif hard and mp.title.startswith("Go to "):
                hard = self._skip_past_target(mp, hard)
            w = self.s.world
            toll = self.path_toll(mp)
            cash = self.st.wealth
            if toll and cash is not None and cash < toll:
                nrm_ = self.no_route_msg
                if self.s.trips.withdraw_for(mp, loop, toll - cash):
                    self.no_route_msg = nrm_         # (its bank search's own "No route: …" isn't this walk's — regr3 #2)
                    return                           # off to the bank first, then this path
                msg_ = f"Not walking '{mp.title}': the tolls on it come to {toll:,} copper and you have {cash:,}"
                self.stop(msg_)
                self.no_route_msg = msg_             # (what @status / diagnose say — not an old plan's door)
                self.s.on_alert(f"Need {toll:,} copper for a toll")
                return
            if soft and cfg_auto_get(self.cfg):
                # "Key: 475 [or any picklocks]" — the way back is often key-only, so fetch it if we can
                # (not with good picklocks: PVE fetched the green metal and large iron keys at Picklocks 182 —
                # except a key that's right there for the asking or the touching: Dan, the gate key from the
                # statue at Dark-Elf City's gate is how it's done)
                srcs = {n: self.errands.source_for(n, extra=hard) for n in soft}
                picks = self.can_pick_doors() or bool(self.st.picklocks or self.st.strength)   # (soft = doable)
                # 'right there' = on the way or one step off it. Dan, 2026-11-11: the Crimson Fortress gate bashes at
                # ~90 strength; its dirty obsidian key is a witchunter's quest ('ask witchunter' in a town shop on
                # another map) — a Go to sent everyone off to ask for it, when nobody but a witchunter can get one
                on_way = {s.room for s in mp.steps if s.room} | {s.dest for s in mp.steps if getattr(s, "dest", None)}
                near = set(on_way)
                for rm in on_way:
                    r_ = w.room(rm)
                    near |= {tuple(e.to) for e in (r_.exits.values() if r_ else []) if getattr(e, "to", None)}
                fetchable = [n for n in soft if srcs[n] and (not picks or (
                    (srcs[n]["kind"] == "ask" or srcs[n].get("summon")) and tuple(srcs[n].get("room") or ()) in near))]
                hard, soft = hard + fetchable, [n for n in soft if n not in fetchable]
            if getattr(self.cfg, "hazard_counters", False) and not ea:
                # 0.8.201 (Dan): a cheap item that stops the rooms that hurt on the way (hazards.py; capped, off by default)
                from .hazards import extra_buys
                hard += [n for n in extra_buys(self, mp) if n not in hard]
            cb_ = getattr(self, "_counter_buy", None)
            if cb_ and not ea and time.time() - cb_["t"] < 3 * 3600 and mp.title.startswith("Go to ") and \
                    tuple(getattr(self, "_goto_target", None) or ()) == cb_["target"] and \
                    cb_["item"] not in (self.held_items() or set()) and cb_["item"] not in hard:
                hard.append(cb_["item"])             # (0.8.224: the counter you said yes to fetching — _ask_counter)
            if hard and time.time() - (getattr(self.st, "inv_at", 0) or 0) > 10:
                # look in your own pack before asking anyone (Dan, 2026-11-05: Buddy handed Evolution the glowing
                # red amulet, then Evolution asked the party for one and stopped — the pack list was from before)
                self.log("Checking your inventory again before getting " + ", ".join(w.item_name(n) for n in hard))
                self._await_inv = (mp, loop, self.st.inv_seq, time.time())
                self.send("i")
                return
            if soft:
                gk_ = w.ghost_keys()                 # (a door whose 'key' isn't a real item: no "No item #1" — partyA #6)
                real_ = [w.item_name(n) for n in soft if n not in gk_]
                self.log(("No " + ", ".join(real_) + " — will try" if real_ else "Will try") +
                         " picking/bashing " + ("those doors" if len(soft) > 1 else "that door"))
            if hard:
                names = ", ".join(w.item_name(n) for n in hard)
                if cfg_auto_get(self.cfg):
                    if not ea and self._party_cant_buy(mp, loop):
                        self.walking = False         # (the party's idol first, then your errand — party3 #4)
                        return
                    ok, why = self.errands.plan(mp, loop, hard)
                    if ok:
                        self.walking = False
                        self.set_mode("auto")
                        self.status = f"Getting {names} first"
                        return
                    doors = {n for n, sft in self.path_needs(mp) if sft}
                    if self.cfg.bash_key_doors and all(n in doors for n in hard):
                        self.log(f"Can't fetch {names} ({why}) — walking anyway; the door gets picked/bashed")
                        hard = []
                    else:
                        # a boss hunt / a Go to off a loop: back to the loop, not stood there (give_up)
                        self.give_up(f"Not walking '{mp.title}': you need {names} — {why}", mp, self.after_goto,
                                     getattr(self, "_goto_target", None) if mp.title.startswith("Go to ") else None)
                        return
                if hard and cfg_auto_get(self.cfg):
                    self.s.on_alert(f"Path needs {names}")
                    return
                elif hard:
                    self.stop(f"Not walking '{mp.title}': you need {names}")
                    self.s.on_alert(f"Path needs {names}")
                    return
            # leading a party: everyone needs their own raft / idol, or the party drowns behind you
            # (not on the errand's own walk to the shop for them: asking again there replaced the errand, and its
            # 'then on to' became the shop itself — Buddy stopped dead at the Village Store, 2026-11-04. Every other
            # errand leg asks too, keeping the errand — party3 #2: the leader's raft run walked raftless followers
            # down the Silver River)
            carry = self.carry_sets(mp)
            ea_ = self.errands.active
            shop_leg = bool(ea_ and (ea_.get("todo") or [{}])[0].get("for"))
            if carry and not shop_leg and self.errands.party_check(mp, loop, carry, leg=bool(ea_)):
                self.walking = False
                return
            # a quest flag decides the way (the pyramid's arches): is everyone's flag one that gets through?
            if self.partyflags.check(mp, loop):
                self.walking = False
                return
        self._await_inv = None
        self.path = mp
        self.loop = mp.is_loop if loop is None else loop
        self.walking = True
        if self.loop and not mp.title.startswith("Go to "):
            self.switches_on("Looping")
        self.paused = False
        self.detour = None
        self.idx = self._index_for_current() or 0
        self.pilot.start(mp)
        self._loop_reset_pending = None
        rotating = getattr(self, "_rotating_to", None) is mp
        if not mp.title.startswith("Go to "):
            self._rotating_to = None
        if not mp.title.startswith("Go to ") and getattr(self, "_lap_path", None) is not mp:
            self._lap_path, self.laps = mp, 0
            if self.loop and not rotating:      # a rotation keeps the night's exp/hr going
                # a new loop: exp/hr starts fresh — but only once we're actually on it, not
                # while walking there from the bank
                self._loop_reset_pending = mp
        if self.loop and not mp.title.startswith("Go to ") and not self._loop_reset_pending:
            self.s.loopstats.lap_start(mp)        # a (re)started lap is measured from here
        self._anchor()
        self._await_seq = None
        self._last_progress = time.time()
        if not mp.title.startswith("Go to "):
            self.last_path, self.last_loop = mp, self.loop
        # back on a loop after a Go to (an errand, a boss hunt) with a raft bought for it: stash it once we're on the
        # loop — not only on a brand-new loop (Evolution, 2026-11-06: rafts carried all day on Rotting Glade Full)
        self._stash_pending = mp if self.loop and not mp.title.startswith("Go to ") else None
        self.set_mode("auto")
        self.log(f"Walking {'loop' if self.loop else 'path'}: {mp.title} ({len(mp.steps)} steps)")

    def _begin_loop(self, mp):
        """Arrived on a new loop: reset our exp/hr, ask the party to reset theirs, start lap timing."""
        self._loop_reset_pending = None
        self.s.state.reset_stats()
        self.s.stats.reset()
        self.s.loopstats.lap_start(mp)
        sent = []
        if self.cfg.party_reset_on_loop:
            me = (self.cfg.my_name or "").lower()
            for name in list(self.st.party or []):
                first = str(name).split()[0]
                if first and first.lower() != me:
                    self.send(self.cfg.party_reset_cmd.format(name=first))
                    sent.append(first)
        self.log(f"On loop '{mp.title}' — exp/hr reset" + (f", @reset sent to {', '.join(sent)}" if sent else ""))
        self._stash_pending = mp                     # rafts are heavy: hidden here while the loop doesn't need them
        self._stash_tell = True                      # (a new loop: the party's told too, whatever we carry)

    # areas MudPilot prompts before routing through, for everyone by default (Dan: dangerous for lower levels —
    # Negative Power Plane has a level gate, Black Wasteland has the Lord of the Hunt). Each character can add
    # more in Settings → Other → Routing; avoid_mode "allow" turns the prompting off.
    DEFAULT_PROMPT_AREAS = ("negative power plane", "black wasteland",
                            "webbed mine")    # Dan: rooms of wraith spiders — too much for a couple of level 45s

    NPP_SAFE_LEVEL = 50

    def _npp_level_ok(self) -> bool:
        """0.8.225 (Dan): from level 50 (the party's lowest) the Negative Power Plane is much less dangerous — not
        avoided any more (the shipped avoid list names it, so yours can't be told from the default)."""
        try:
            return int(self.route_level() or 0) >= self.NPP_SAFE_LEVEL
        except Exception:
            return False

    def _npp_only_ok(self, area) -> bool:
        """0.8.225 (Dan): under level 50 the Negative Power Plane is avoided — unless it's the only way: then it goes."""
        return "negative power plane" in (area or "").lower()   # (the shipped avoid list names it too: Dan's rule)

    def avoid_set(self) -> frozenset:
        """Rooms to prompt before routing through: the built-in prompt areas, plus names on your avoid list
        (e.g. Negative Power Plane) and listed map/rooms."""
        cfg, w = self.cfg, self.s.world
        npp_ok = self._npp_level_ok()
        key = (id(w), tuple(cfg.avoid_names or []), tuple(cfg.avoid_rooms or []), npp_ok)
        if getattr(self, "_avoid_key", None) != key:
            names = [n for n in list(self.DEFAULT_PROMPT_AREAS) + [x.lower() for x in (cfg.avoid_names or []) if x.strip()]
                     if not (npp_ok and "negative power plane" in n)]   # (the shipped avoid list has NPP too)
            rooms = set()
            if names:
                rooms = {k for k, r in w.rooms.items() if any(n in r.name.lower() for n in names)}
            for t in cfg.avoid_rooms or []:
                m = re.match(r"^\s*(\d+)\s*/\s*(\d+)", str(t))
                if m:
                    rooms.add((int(m.group(1)), int(m.group(2))))
            self._avoid_key, self._avoid = key, frozenset(rooms)
        return self._avoid

    def avoid_for(self, target) -> frozenset:
        """avoid_set() for a Go to to `target`: a target inside an avoided area may be walked to through that area.
        (0.8.201, walk check: only the goal room itself was exempt — Go to 8/958 in the Negative Power Plane was
        refused "goes through Black Wasteland" though a 115-room way exists through the rest of the NPP; 8/1085 walked
        651 rooms instead of 116.) Drops the avoided rooms joined to the target, the rest of the list stays."""
        avoid = self.avoid_set()
        if not avoid or isinstance(target, (set, frozenset)) or not target or tuple(target) not in avoid:
            return avoid
        ck = (id(avoid), tuple(target))
        hit = getattr(self, "_avoid_for_cache", None)
        if hit and hit[0] == ck:
            return hit[1]
        w, adj = self.s.world, {}
        # only the target's own area: the Negative Power Plane touches Black Wasteland, which stays avoided
        tn = (w.room(target).name if w.room(target) else "").lower()
        names = [n for n in list(self.DEFAULT_PROMPT_AREAS) + [x.lower() for x in (self.cfg.avoid_names or []) if x.strip()]
                 if n in tn]
        area = {k for k in avoid if w.room(k) and (any(n in w.room(k).name.lower() for n in names) if names
                                                    else w.room(k).name.lower() == tn)}
        for k in area:
            r = w.room(k)
            for ex in (r.exits.values() if r else ()):
                if ex.to in area:
                    adj.setdefault(k, set()).add(ex.to)
                    adj.setdefault(ex.to, set()).add(k)
        comp, todo = {tuple(target)}, [tuple(target)]
        while todo:
            for n in adj.get(todo.pop(), ()):
                if n not in comp:
                    comp.add(n)
                    todo.append(n)
        out = frozenset(avoid - comp)
        self._avoid_for_cache = (ck, out)
        return out

    def route_level(self):
        """The level to route on: the party's lowest (a level-30 follower can't take the level-40 portal into the
        Negative Power Plane), else your own. Followers running MudPilot tell their level (partysync)."""
        mine = self.st.level or self.cfg.char_level or None
        try:
            lv = self.s.partysync.levels()
        except Exception:
            lv = {}
        low = min(lv.values()) if lv else None
        return min(mine, low) if (mine and low) else (mine or low)

    def route_top_level(self):
        """The party's highest level (yours alone, solo): a 'Level 0 to 5' gate has to let the highest through too
        (partyA #1: an L55 leader with an L3 follower walked to the Silver River's 'Level 0 to 3' gate)."""
        mine = self.st.level or self.cfg.char_level or None
        try:
            lv = self.s.partysync.levels()
        except Exception:
            lv = {}
        top = max(lv.values()) if lv else None
        return max(mine, top) if (mine and top) else (mine or top)

    def every_item(self) -> set:
        """'As if you had every item' for planning a fetch — minus ones that split a party (amber talisman)."""
        from .board_fixes import PARTY_SPLIT_ITEMS
        w = self.s.world
        me = (self.cfg.my_name or "").lower()
        # doors whose key isn't in the item list ('Key: 1 [or 31 picklocks/strength]' — the Town Gates archway,
        # 8/462) can only be picked or bashed: count them as open, the walk bashes them (Revolution, 2026-10-30)
        ghost = w.ghost_keys()
        if not any(n.lower() != me for n in (self.st.party or {})):
            return set(w.items) | ghost
        return {n for n in w.items if w.item_name(n).lower() not in PARTY_SPLIT_ITEMS} | ghost

    def plan_items(self, target=None) -> set:
        """every_item() for planning a walk: minus the item an errand is out getting when this walk is that errand's
        leg (fight3 #0: the leg to the chiseled key planned through that key's own door at 16/1994; m1617 #3 covered
        errands.source_for only)."""
        every = self.every_item()
        ea = getattr(getattr(self, "errands", None), "active", None)
        cur = (ea.get("todo") or [None])[0] if ea else None
        if cur and target is not None and not isinstance(target, (set, frozenset)) and cur.get("room") and \
                tuple(cur["room"]) == tuple(target):
            every = set(every) - {cur["num"]}
        return every

    def _door_have(self) -> set:
        """Keys that count as 'can be fetched' for a locked door: every item when MudPilot fetches keys, else what
        you carry."""
        held = self.held_items() or set()
        return (held | self.every_item()) if (self.cfg.auto_get_items or self.cfg.bash_key_doors) else held

    def hopeless_doors(self, here, route, have=None) -> list:
        """[(room, exit)] on this route: doors nobody in the party can pick or bash and no key for (worlddb)."""
        w, out, cur = self.s.world, [], here
        have = self._door_have() if have is None else have
        for ex in route or ():
            if w.door_hopeless(ex, have):
                out.append((cur, ex))
            cur = ex.to
        return out

    def _ask_doors(self, here, target, route, ask, again):
        """0.8.201 (Dan): a route through a door nobody in the party can open went ahead silently (priced 300, or 60
        for a 1000-picklock door, "when there's no other way"). Now: '<door> — nobody in the party can open it. Try
        anyway?' with No as the default. Yes = today's behaviour (remembered for 3 hours, so re-plans on the way
        don't ask again); No, nobody to ask, or no answer = a wall: plan round it, or no route naming the door.
        again(): the same plan once more (no questions)."""
        w, now = self.s.world, time.time()
        yes = self._door_yes = {k: t for k, t in (getattr(self, "_door_yes", None) or {}).items() if now - t < 3 * 3600}
        w.door_yes = yes                             # (the same yeses for dist_map: errand sources past the door — #19)
        for _ in range(6):
            bad = [(c, ex) for c, ex in self.hopeless_doors(here, route) if id(ex) not in yes]
            if not bad:
                return route
            c, ex = bad[0]
            r = w.room(c)
            name = (f"The {DIR_WORDS.get(ex.dir, ex.dir).lower()} door in {r.name if r else 'a room'} "
                    f"({c[0]}/{c[1]}, {(ex.etype or '').strip()})")
            ok = False
            if ask is not None:
                try:
                    ok = bool(ask(len(route), None, name, "door"))
                except TypeError:                    # an older ask(short, scenic, area)
                    ok = bool(ask(len(route), None, f"{name} (nobody in the party can open it)"))
            if ok:
                yes[id(ex)] = now
                self.log(f"Routing: trying {name} anyway (you said yes)")
                continue
            w.refuse_door(ex)
            self.log(f"Routing: {name} — nobody in the party can open it; going round it"
                     + ("" if ask is not None else " (nobody to ask)"))
            self._door_blocked = (name, tuple(target) if not isinstance(target, (set, frozenset)) else None)
            route = again()
            if route is None:
                self.no_route_msg = f"No route: {name} is in the way and nobody in the party can open it."
                return None
        return route

    def keyed_route(self, here, target, ask=None):
        """'As if you had every key' — and a door nobody can open is asked about first (0.8.201, _ask_doors)."""
        r = self._keyed_route(here, target, ask)
        r = self._ask_doors(here, target, r, ask, lambda: self._keyed_route(here, target, None))
        if r and not isinstance(target, (set, frozenset)):
            # 0.8.226: round the bosses too — this fallback walked Miserable PVE into the Crazed Inquisitor's room
            r = self._boss_free_route(here, target, r, have=set(self.plan_items(target)))
        return r

    def _needed_area(self, here, target, lvl, have, avoid, thru):
        """No way that keeps out of every avoided area: the one area the way really needs (m1315 R2: Webbed Hollow
        15/10025 was "only through Black Wasteland" — there's a 330-step way round it; it's the Webbed Mine that can't
        be avoided — and a Yes walked you through all three). (area name, route through only that one) or None."""
        w = self.s.world
        names = list(self.DEFAULT_PROMPT_AREAS) + [n.lower() for n in (self.cfg.avoid_names or []) if n.strip()]
        seen, best = [], None
        for ex in thru or ():
            r = w.room(ex.to)
            if ex.to not in avoid or not r:
                continue
            nm = next((n for n in names if n in r.name.lower()), r.name.lower())
            if nm in seen:
                continue
            seen.append(nm)
            rest = frozenset(k for k in avoid if not (w.room(k) and nm in w.room(k).name.lower()))
            alt = w.route(here, target, level=lvl, have=have, avoid=rest)
            if alt is not None and (best is None or len(alt) < len(best[1])):
                best = (r.name, alt)
        return best

    def _keyed_route(self, here, target, ask=None):
        """'As if you had every key' (the doors get picked / bashed, or the keys fetched) — still keeping out of the
        areas you avoid. Sweep, 2026-10-28: 14 Go tos (Crimson Fortress, Rhudaur, the Dark-elf Queen…) went
        straight through Black Wasteland this way. If the only way is through one: ask (unattended: don't go)."""
        w, cfg = self.s.world, self.cfg
        lvl, every = self.route_level(), self.plan_items(target)
        avoid = self.avoid_for(target)               # (0.8.201, walk check: a target inside an avoided area)
        if not avoid or here in avoid or (cfg.avoid_mode or "ask").lower() == "allow":
            return w.route(here, target, level=lvl, have=every)
        full = w.route(here, target, level=lvl, have=every, avoid=avoid)
        if full is not None:
            return self._cheapest_way(here, target, full)
        thru = w.route(here, target, level=lvl, have=every)
        if thru is None:
            return None
        area = next((w.room(ex.to).name for ex in thru if ex.to in avoid and w.room(ex.to)), "an avoided area")
        na = self._needed_area(here, target, lvl, every, avoid, thru)
        if na:
            area, thru = na
        now = time.time()
        allowed = getattr(self, "_trip_allow", {})
        if now - allowed.get(area.lower(), 0) < 3 * 3600:
            return thru
        if self._npp_only_ok(area):
            if self.ready("npp_only_said", 60):
                self.log(f"The only way there is through {area} — going (avoided only when there's another way)")
            return thru
        if (cfg.avoid_mode or "ask").lower() == "ask" and ask is not None and ask(len(thru), None, area):
            self._trip_allow = {**allowed, area.lower(): now}
            return thru
        self._trip_deny = {**getattr(self, "_trip_deny", {}), area.lower(): now}
        self._avoid_blocked = (area, tuple(target) if not isinstance(target, (set, frozenset)) else None)
        return None

    def _shortcut_route(self, here, target, lvl, avoid, have, route):
        """A much shorter way opens with an item you could fetch (Seher'Sahham: the king crab claw opens 16/2141 —
        133 rooms instead of 308): fetch it and take the short way, when that beats walking round, detour
        included. The route (the path's needed-items check fetches the item) or the one you had."""
        fetch_ok = self.cfg.auto_get_items and self.cfg.check_needed_items
        if route is None or isinstance(target, (set, frozenset)) or not (fetch_ok or self.cfg.bash_key_doors):
            return route
        no = self.__dict__.setdefault("_shortcut_no", {})
        now = time.time()
        if now - no.get(tuple(target), 0) < 600:
            return route
        w = self.s.world
        keyed = w.route(here, target, level=lvl, have=self.every_item(), avoid=avoid or None)
        if keyed is None or len(keyed) > len(route) - max(30, len(route) // 4):
            no[tuple(target)] = now
            return route
        need = self._route_items(here, keyed, have)
        if not need:
            # 0.8.223 (Dan, m12 #5): only key doors your picklocks / strength (or the party's) open on the short way —
            # take it when it saves 30+ rooms (Silvermere's sewer: 106 rooms round for 10 through 1/1098 W)
            held = set(self.held_items() or ())
            doors = [ex for ex in keyed if ex.kind == "key" and not (w.exit_need(ex) and w.exit_need(ex)[0] in held)]
            if doors and self.cfg.bash_key_doors and all(w.door_beaten(ex, held) is True for ex in doors):
                self.log(f"Go to: picking / bashing {len(doors)} key door{'s' if len(doors) > 1 else ''} on the way "
                         f"({len(keyed)} rooms) beats walking round ({len(route)} rooms)")
                return keyed
            no[tuple(target)] = now
            return route
        if not fetch_ok:
            no[tuple(target)] = now
            return route
        cost = 0
        for n in need:
            src = self.errands.source_for(n, tuple(target))
            if not src or self._risky_source(src):
                no[tuple(target)] = now
                return route
            cost = max(cost, src.get("dist") or 0)
        if cost + 10 >= len(route):
            no[tuple(target)] = now
            return route
        self.log(f"Go to: a shortcut opens with {', '.join(w.item_name(n) for n in sorted(need))} — fetching it "
                 f"(~{cost} rooms, detour included) beats walking round ({len(route)} rooms)")
        return keyed

    def _risky_source(self, src) -> bool:
        """An optional fetch (a shortcut) from a monster that's a boss or would hurt the party badly — walk round
        instead (Dan: fine to get the king crab claw, as long as the crab isn't a risky room to walk into)."""
        if src.get("kind") != "monster":
            return False
        w = self.s.world
        nm = re.sub(r"^drop:\s*|\s+[\d.]+%$", "", src.get("what") or "").strip().lower()
        rec = w.monster_names.get(nm)
        if not rec:
            return False
        st = self.st
        hp = st.max_hp or 0
        if hp:
            from .danger import fight_estimate
            try:
                est = fight_estimate(self.s.danger, [rec])
            except Exception:
                return False
            if est >= hp * 0.8:                     # could all but kill you (the crab, ~60%, is fine)
                self.log(f"Go to: skipping the shortcut — the {rec['name']} for it would do ~{est:.0f} damage")
                return True
        return False

    def _fight_too_strong(self, recs, here=True) -> float:
        """0.8.223 (Dan, m349 #5 / m149 N1): '~damage to you' when fighting these could all but kill you (80% of your
        max HP — _risky_source's line), else 0. here=True: monsters in this room (what you've taken here before
        counts, as in danger.fight_estimate); False: somewhere else (an item dropper an errand would go and kill)."""
        hp = self.st.max_hp or 0
        recs = [r for r in (recs or []) if r]
        if not hp or not recs:
            return 0.0
        try:
            if here:
                from .danger import fight_estimate
                est = fight_estimate(self.s.danger, recs)
            else:
                d = self.s.danger
                rounds = math.ceil(sum(int(m.get("hp") or 100) for m in recs) / max(d.my_dpr(recs[0]), 1))
                est = sum(d.mob_dpr(m) for m in recs) * rounds * 0.5 * d.party_factor()
        except Exception:
            return 0.0
        return float(est) if est >= hp * 0.8 else 0.0

    def _too_small(self, here, target):
        """No route on the party's level, but there is one on yours: the level gates in the way and who's too
        low. (message) or None."""
        mine = self.st.level or self.cfg.char_level or None
        low = self.route_level()
        if not mine or not low or low >= mine:
            return None
        if (self.cfg.auto_get_items or self.cfg.bash_key_doors) and self.keyed_route(here, target) is not None:
            # the party CAN get there on its level — through a door that wants a key or a bash (Revolution,
            # 2026-10-30: the Royal Prison, 8/493, through the Black Steel Gate — 'only way is the Negative Power
            # Plane, members aren't big enough' was never true)
            return None
        w = self.s.world
        rt = w.route(here, target, level=mine, have=self.held_items() or set())
        if rt is None:
            return None
        gates = []
        for ex in rt:
            req = getattr(ex, "req", None) or {}
            m = w.LEVEL_RE.search(ex.etype or "")
            need = req.get("level") or (int(m.group(1)) if m else 0)
            if need and need > low:
                rr = w.room(ex.to)
                gates.append((need, rr.name if rr else f"{ex.to[0]}/{ex.to[1]}"))
        if not gates:
            return None
        need, area = max(gates)
        lv = self.s.partysync.levels()
        small = ", ".join(f"{n} (level {v})" for n, v in sorted(lv.items(), key=lambda x: x[1]) if v < need)
        return (f"the only way is through {area}, which needs level {need}+ — members of the party aren't big "
                f"enough: {small}")

    def plan_route(self, here, target, ask=None):
        def once(ask_):
            r_ = self._boss_free_route(here, target, self._cheapest_way(here, target, self._fewer_jumps(
                here, target, self._dry_route(here, target, self._plan_route(here, target, ask_)))))
            return self._party_carry_way(here, target, r_)
        r = self._ask_doors(here, target, once(ask), ask, lambda: once(None))   # (0.8.201: doors nobody can open)
        if not isinstance(target, (set, frozenset)):
            self._danger_note(r, target)
        return r

    def _carry_short(self, route) -> list:
        """The items on this route every walker needs their own of that not every follower is known to carry."""
        w = self.s.world
        c = w.char or {}
        ph = c.get("party_have")
        if not route or not c.get("party") or ph is None:
            return []
        out = []
        for ex in route:
            items = getattr(ex, "item_cast", None)
            if items and not (set(items) & set(ph)):
                out += sorted(items)[:1]
            elif ex.kind == "item":
                need = w.exit_need(ex)
                if need and not need[1] and need[0] not in ph:
                    out.append(need[0])
        return out

    def _party_carry_way(self, here, target, route):
        """0.8.190 (Dan, idol for each follower): the way takes the idol teleport (or another exit each walker needs
        their own item for) and not every follower is known to carry one — another way when there is one, even one
        that needs keys fetched or doors picked (the Lost City has no other way in with what you carry). None found:
        the way you had (the party's '@have' round sorts it out)."""
        short = self._carry_short(route)
        if not short or isinstance(target, (set, frozenset)):
            return route
        w = self.s.world
        w.party_strict_only = True
        try:
            avoid = frozenset() if (self.cfg.avoid_mode or "ask").lower() == "allow" else frozenset(self.avoid_set())
            avoid = (avoid | self._dry_keep(target)) or None
            alt = w.route(here, target, level=self.route_level(), have=set(self.every_item()), avoid=avoid)
        finally:
            w.party_strict_only = False
        if alt is None or self._carry_short(alt):
            return route
        if self.ready("party_carry_note", 60):
            self.log(f"Go to: not everyone is known to carry {', '.join(w.item_name(n) for n in short)} — the way "
                     f"without it ({len(alt)} rooms, not {len(route)})")
        return alt

    def lair_danger(self, room):
        """(expected damage to you from this lair's full spawn, max, worst monster) — the worst monster it can spawn,
        as many as it holds, at your AC/DR and kill speed, your share once the party soaks some (danger.py). What's
        really happened there (lair clock) wins when known."""
        w, d = self.s.world, self.s.danger
        r = w.room(room)
        m = re.match(r"\(Max (\d+)\):\s*([\d,]+)", (r.lair if r else "") or "")
        if not m:
            return 0.0, 0, None
        recs = [w.monsters.get(int(x)) for x in m.group(2).split(",") if x.strip().isdigit()]
        recs = [x for x in recs if x and x.get("in_game", 1)]
        if not recs:
            return 0.0, 0, None
        n = int(m.group(1))
        try:
            obs = d.observed(room)
        except Exception:
            obs = None
        worst = max(recs, key=d.mob_dpr)
        if obs is not None:                          # what you took on a bad visit — a healer's heals go further
            return obs * 1.2 * d.healed(), n, worst
        dpr = d.mob_dpr(worst) * n
        hp = int(worst.get("hp") or 100) * n
        try:                                         # the party kills it together (party sync: their best spell)
            team = sum(int(i.get("dmg") or 0) for i in self.s.partysync.info().values())
        except Exception:
            team = 0
        rounds = math.ceil(hp / max(d.my_dpr(worst) + team, 1))
        return dpr * rounds * 0.5 * d.party_factor(), n, worst

    def danger_room(self, room) -> bool:
        """A lair that would maul you — kept out of routes when there's another way (worlddb.route)."""
        st = self.st
        now = time.time()
        kc = getattr(self, "_danger_key", None)
        if kc is None or now - kc[0] > 2:
            # the key (you, the party's weakest) once every 2 s, not per exit looked at: a Go to asks this
            # millions of times (Revolution, 2026-10-30: 8 million party look-ups, the window stuck for minutes)
            kc = self._danger_key = (now, (st.level, st.max_hp, st.ac, st.dr, len(st.party or {}), self._weakest_hp()))
            self.s.world.danger_key = kc[1]          # (remembered routes are per this, too)
        key = kc[1]
        c = getattr(self, "_danger_cache", None)
        if c is None or c[0] != key:
            c = self._danger_cache = (key, {})
        hit = c[1].get(room)
        if hit is None:
            # the damage is to you, so it's your HP it's measured on (Dan, 2026-11-03: Buddy's own 233 at the Dirt
            # Path against Evolution's 267 flagged a lair 'Revo eats up'); the party's in the damage already
            hp = st.max_hp or self._weakest_hp() or 0
            pct = int(getattr(self.cfg, "route_danger_pct", 60) or 0)
            known = st.known_spells or self.cfg.attack_spells or st.char_class or self.cfg.char_class
            if not hp or not pct or not known:
                hit = False                          # can't judge your side of the fight yet: don't block anything
            else:
                try:
                    est, _n, _w = self.lair_danger(room)
                except Exception:
                    est = 0.0
                hit = est >= hp * pct / 100
            c[1][room] = hit
        return hit

    def _weakest_hp(self, read_only=False) -> int:
        """The smallest max HP in the party — yours, or a member's MudPilot told us (party sync 'me'). read_only: yours
        only once 'st' gave the real one (before that it's the highest prompt HP seen — after a hurt login, 60 of 130,
        and the HP wall refused traps "your whole max HP (60)": m349 #4)."""
        hps = [self.st.max_hp or 0] if (not read_only or getattr(self.st, "max_hp_read", True)) else []
        try:
            hps += [int(i.get("hp") or 0) for i in self.s.partysync.info().values()]
        except Exception:
            pass
        hps = [h for h in hps if h > 0]
        return min(hps) if hps else 0

    def _weakest_name(self, read_only=False):
        """Whose max HP _weakest_hp is — a member's name, or None when it's yours (a refusal says "Buddy's whole max
        HP", not "your whole max HP", when it's his: partyA D4)."""
        low = self._weakest_hp(read_only)
        mine = (self.st.max_hp or 0) if (not read_only or getattr(self.st, "max_hp_read", True)) else 0
        if not low or (mine and mine <= low):
            return None
        me = (self.cfg.my_name or "").lower()
        try:
            info = self.s.partysync.info()
        except Exception:
            return None
        return next((n for n, i in info.items() if n.lower() != me and int(i.get("hp") or 0) == low), None)

    def _danger_note(self, route, target):
        """Say so when the only way still goes through a lair that would maul you."""
        if not route or not getattr(self.s.world, "danger_fn", None):
            return
        bad = [ex.to for ex in route if ex.to != tuple(target) and self.danger_room(ex.to)]
        if bad and self.ready("danger_note", 120):
            w = self.s.world
            est, n, worst = self.lair_danger(bad[0])
            self.log(f"Go to: careful — the only way goes through {len(bad)} dangerous lair(s), e.g. "
                     f"{w.room(bad[0]).name} {bad[0][0]}/{bad[0][1]} (up to {n} {worst['name'] if worst else '?'}, "
                     f"~{est:.0f} damage to you)")

    def _item_cost(self, n, target):
        """Rooms-equivalent of getting item #n on the way to target: the detour (source_for's dist: here → where
        it comes from → target), plus the extra kills a rare drop takes (~20 rooms a kill — a 10% black star key
        is ~10 cultists). None = can't be had."""
        src = self.errands.source_for(n, tuple(target))
        if not src:
            return None
        extra = 0.0
        if src["kind"] == "monster":
            m = re.search(r"([\d.]+)%", src.get("what") or "")
            pct = float(m.group(1)) if m else 100.0
            extra = (100.0 / max(pct, 1.0) - 1) * 20
        return float(src.get("dist") or 0) + extra

    def way_cost(self, here, route, target, have) -> float:
        """What a way really costs: its length, or what fetching its items takes if that's more, plus ~100 rooms
        a chance jump for a party."""
        if not route:
            return float("inf")
        cost = float(len(route))
        for n in self._route_items(here, route, have):
            c = self._item_cost(n, target)
            if c is None:
                return float("inf")
            cost = max(cost, c)
        if (self.s.world.char or {}).get("party"):
            cost += self.JUMP_COST * self._jumps(route, target)
        return cost

    def _cheapest_way(self, here, target, route):
        """The way that's cheapest once getting its items is counted (Dan, 2026-10-28: the flaming mammoths are
        reached through Khazarad's mines with a mine pass bought next door — not the Black House door, whose key
        is a 10% cultist drop). Ways tried: this one, 'as if you had every item', then the same without the
        dearest item each time. The choice holds for 10 minutes per target (the pilot re-plans every tick)."""
        w, cfg = self.s.world, self.cfg
        if not route or isinstance(target, (set, frozenset)) or not (cfg_auto_get(cfg) and cfg.check_needed_items):
            return route
        have = self.held_items() or set()
        if not self._route_items(here, route, have) and not ((w.char or {}).get("party") and self._jumps(route, target)):
            return route                            # needs nothing and no jumps: nothing to weigh
        tk = tuple(target)
        memo = self.__dict__.setdefault("_way_memo", {})
        hit = memo.get(tk)
        lvl, avoid = self.route_level(), (frozenset(self.avoid_set()) | self._dry_keep(target)) or None
        if hit and time.time() - hit[0] < 600:
            if hit[1] is None:
                return route
            alt = w.route(here, target, level=lvl, have=set(hit[1]) | have, avoid=avoid)
            return alt or route
        best, best_cost, best_have = route, self.way_cost(here, route, target, have), None
        pool = set(self.every_item())
        for _ in range(3):
            alt = w.route(here, target, level=lvl, have=pool, avoid=avoid)
            if not alt:
                break
            c = self.way_cost(here, alt, target, have)
            if c < best_cost * 0.98:
                best, best_cost, best_have = alt, c, frozenset(pool)
            need = self._route_items(here, alt, have)
            if not need:
                break
            costs = {n: (self._item_cost(n, target) or float("inf")) for n in need}
            pool.discard(max(costs, key=costs.get))   # the dearest item: what's the way without it?
        memo[tk] = (time.time(), best_have)
        if best is not route:
            need = self._route_items(here, best, have)
            self.log(f"Go to: the cheapest way counts what it needs — {len(best)} rooms"
                     + (f", getting {', '.join(w.item_name(n) for n in sorted(need))}" if need else "")
                     + f" (the other way: {len(route)} rooms"
                     + (f", needing {', '.join(w.item_name(n) for n in sorted(self._route_items(here, route, have)))}"
                        if self._route_items(here, route, have) else "") + ")")
        return best

    @staticmethod
    def _jumps(route, target) -> int:
        return sum(1 for ex in route or [] if "(Chance)" in (ex.etype or "") and ex.to != tuple(target))

    JUMP_COST = 100           # a chance jump counts as this many extra rooms for a party

    def _fewer_jumps(self, here, target, route):
        """A party and the way goes over chance jumps (the Building Rooftops: 'jump north' split Revolution off):
        weigh each jump as ~100 extra rooms against the ways a key opens (the Black House door), and take the
        cheapest — the key gets fetched (or the party asked for it). The Old Mine's own 'jump east' is on most
        ways in, so one jump isn't ruled out, four on the rooftops are."""
        w, cfg = self.s.world, self.cfg
        if not route or isinstance(target, (set, frozenset)) or not (w.char or {}).get("party") \
                or not cfg_auto_get(cfg) or not self._jumps(route, target):
            return route
        lvl, every = self.route_level(), self.every_item()
        avoid = (frozenset(self.avoid_set()) | self._dry_keep(target)) or None
        options = [route, w.route(here, target, level=lvl, have=every, avoid=avoid)]     # (jumps kept off)
        ch = w.char
        try:
            w.char = {**ch, "party": False}                                             # (jumps allowed)
            options.append(w.route(here, target, level=lvl, have=every, avoid=avoid))
        finally:
            w.char = ch
        best = min((r for r in options if r), key=lambda r: len(r) + self.JUMP_COST * self._jumps(r, target))
        if best is not route:
            if self.ready("chance_note", 60):
                self.log(f"Go to: the open way has {self._jumps(route, target)} chance jump(s) that can split the "
                         f"party — taking a way a key or item opens instead ({len(best)} rooms, "
                         f"{self._jumps(best, target)} jump(s)), fetching what it needs")
            return best
        return route
        keyed = w.route(here, target, level=self.route_level(), have=self.every_item(),
                        avoid=self.avoid_set() or None)
        if keyed and self._jumps(keyed, target) < self._jumps(route, target):
            if self.ready("chance_note", 60):
                self.log("Go to: the open way has chance jumps that split the party — taking the way a key opens "
                         "instead (fetching the key if nobody has one)")
            return keyed
        return route

    def _needy_rooms(self, start, route, have) -> set:
        """Rooms on this route you can't walk without an item you don't have (river/sea without a raft)."""
        w, out, prev = self.s.world, set(), start
        for ex in route:
            try:
                sets = w.carry_needs([(prev, ex)])
            except Exception:
                sets = []
            if any(not (st_ & have) for st_ in sets):
                out.add(ex.to)
            prev = ex.to
        return out

    def _boss_free_route(self, here, target, route, have=None):
        """0.8.183 (Dan, 2026-11-12): a Go to to Tidepool went through Captain Flintlock's room and stopped there
        ('stop before a boss room'). When there's another way about as short (up to a quarter longer), take it;
        the stop only happens when there isn't.
        0.8.226 (Dan: "wall it off"): a boss you'd stop before is a wall — any way round, however long (Miserable PVE's
        Go to the Great Pyramid went through the Crazed Inquisitor's Command Room, the Khazarad way being 160 rooms
        longer). Only when there's no way round at all does the walk go up to it and stop, as before. A boss you'd
        just fight (easy, unticked) keeps the 'about as short' rule. have: the items to plan with (the every-key
        fallback's)."""
        if not route or not (self.cfg.stop_before_boss or getattr(self.cfg, "boss_route_round", True)):
            return route
        goals = target if isinstance(target, (set, frozenset)) else {tuple(target)}
        bossy = {ex.to for ex in route if ex.to not in goals and self._boss_avoids(ex.to)}
        if not bossy:
            return route
        w = self.s.world
        lvl = self.route_level()
        have = set(have) if have is not None else (self.held_items() or set())
        area = self._boss_area(bossy, goals)
        if tuple(here) in area:
            # 0.8.227.3 (Dan: PvP Miserable, restarted outside Shadow Lord at 14/8389 Farnholme): the whole of
            # Farnholme walled off, there was no way out of it but through him. Already inside: only his room's a wall
            area = set(bossy)
        avoid = set(self.avoid_set()) | area | self._dry_keep(target)
        # never round a boss by water you'd need a raft for when this way is dry (Dan, 2026-11-16: Stonecaps →
        # Rodolfo is dry over the Dale Road; round Shadow Lord took the River Lorian and sent Miserable 202 rooms
        # for a wooden skiff). Same carry rule as the dry way: a party is planned as carrying none.
        me = (self.cfg.my_name or "").lower()
        carry = set() if any(n.lower() != me for n in (self.st.party or {})) else have
        if carry is not have:
            # 0.8.227.2 (Dan: PvP Miserable stopped before Shadow Lord on a Go to Kingsport): the way round him took
            # more river, and with everyone carrying none it was thrown out — the walk went up to his room and
            # stopped. Rafts you hold that every follower is known to carry too (party sync kit, '@have') count
            try:
                carry = set(have) & set(self.party_carry())
            except Exception:
                carry = set()
        wet0 = self._needy_rooms(here, route, carry) if self.cfg.check_needed_items else set()
        for _ in range(10):
            alt = w.route(here, target, level=lvl, have=have, avoid=frozenset(avoid))
            wall = any(self._boss_stops(k) for k in bossy)       # (a stop-for boss: any length goes)
            if alt is None or (not wall and len(alt) > len(route) + max(20, len(route) // 4)):
                # no way round that's about as short: stop before it, as before (the boss may be what you're
                # there for: the king crab's claw opens Seher'Sahham's shortcut — 226 rooms, not 324)
                return route
            if self.cfg.check_needed_items:
                wet = self._needy_rooms(here, alt, carry) - wet0
                if wet:
                    avoid |= wet
                    continue
            more = {ex.to for ex in alt if ex.to not in goals and self._boss_avoids(ex.to)}
            if not more:
                names = ", ".join(sorted({b["name"] for k in bossy for b in self._boss_avoids(k)}))
                if self.ready("boss_route_note", 30):
                    extra = len(alt) - len(route)
                    self.log(f"Going round {names}'s room (" + (f"{extra} more room{'s' if extra != 1 else ''}"
                             if extra > 0 else "no longer") + f", {len(alt)} steps)")
                return alt
            bossy |= more
            a2 = self._boss_area(more, goals)
            avoid |= set(more) if tuple(here) in a2 else a2
        return route

    def _boss_area(self, rooms, goals) -> set:
        """The boss rooms and the rest of their area (same name, same map), unless you're going there: round
        Flintlock means off the Pirate Galleon, not rowing out and walking round him on deck (Dan, 2026-11-12:
        "the south entrance into tidepool is the proper path")."""
        w = self.s.world
        out = set(rooms)
        goal_areas = {(g[0], (w.room(g).name if w.room(g) else "").split(",")[0]) for g in goals}
        for k in rooms:
            r = w.room(k)
            area = (k[0], (r.name if r else "").split(",")[0])
            if not area[1] or area in goal_areas:
                continue
            idx = self.__dict__.setdefault("_area_idx", {})
            if area not in idx:
                idx[area] = {kk for kk, rr in w.rooms.items() if kk[0] == area[0] and rr.name.split(",")[0] == area[1]}
            if len(idx[area]) <= 80:                # a ship or a lair, not a whole town that shares a name
                out |= idx[area]
        return out

    def _boss_avoids(self, dest) -> list:
        """0.8.185 (Dan, 2026-11-12): "No reason i should try to afk kill shadow master as i walk from bank to
        abandoned inn when it might be 1 room farther". Routes go round any boss you aren't hunting, not only the
        ones you'd stop before (a level-55 Mage rates Shadow Master easy — no stop — and walked into him)."""
        if getattr(self.cfg, "boss_route_round", True):
            return self._boss_stops(dest, easy_too=True)
        return self._boss_stops(dest)

    def _boss_stops(self, dest, easy_too=False) -> list:
        """The bosses in this room you'd stop before (the same rules as _boss_ahead, nothing said or held).
        easy_too: ones you'd fight without stopping too (anything not hunted, unticked or friendly)."""
        cfg = self.cfg
        if not (cfg.stop_before_boss or easy_too) or not dest or getattr(self, "_boss_ok", None) == dest:
            return []
        bosses = self.s.world.bosses_by_room().get(dest) or []
        if not bosses:
            return []
        skip = {n.strip().lower() for n in (cfg.boss_no_stop or [])}
        bosses = [b for b in bosses if b["name"].lower() not in skip and not self._is_hunted(b)
                  and b.get("exp", 0) > 0 and self.hostile(b) and not self._boss_dead(b)]
        if not bosses:
            return []
        pct = int(getattr(cfg, "boss_stop_pct", 40) or 0)
        if pct and self.st.max_hp and not easy_too:
            from .danger import fight_estimate
            try:
                est = fight_estimate(self.s.danger, bosses)
            except Exception:
                est = None
            if est is not None and est < self.st.max_hp * pct / 100:
                return []
        return bosses

    def _dry_route(self, here, target, route):
        """Dan, 2026-10-28: Go to Dragon's Teeth Hills (111 rooms, across a river) set off 220 rooms the other
        way to the only raft shop MME knows. If the way round the water isn't much longer, walk that instead."""
        self._dry_avoid = None
        if not route or not self.cfg.check_needed_items:
            return route
        # inventory not read yet (just back in, or re-checking before an errand): plan as carrying nothing. Dan,
        # 2026-11-16: Stonecaps → Rodolfo's Salvage Yard set off 202 rooms (down the river itself) to buy a
        # wooden skiff instead of walking round the water
        have = self.held_items() or set()
        me = (self.cfg.my_name or "").lower()
        party = any(n.lower() != me for n in (self.st.party or {}))
        # with a party, plan as if the others have no raft — they're heavy and usually nobody carries one (Dan,
        # 2026-10-30): a dry way even when you have one yourself
        carry = set() if party else have
        needy = self._needy_rooms(here, route, carry)
        if not needy:
            return route
        w, cfg = self.s.world, self.cfg
        lvl = self.route_level()
        avoid = set(self.avoid_set()) | needy
        # "even if it's longer it's usually shorter on this side than going to get a raft" (Dan, 2026-11-17): the
        # dry way is fine up to about double, or up to the trip by way of the raft shop, whichever is longer
        cap = max(len(route) + max(60, len(route)), self._raft_trip(here, target, route, carry))
        # 0.8.227.2 (Dan: PvP Miserable's Go to Kingsport wanted a raft while the party hauled cudgels — nobody could
        # carry one, so it stopped): no room for the raft — any dry way, however long; none: the raft after all
        short = self._no_room_on(here, route, carry)
        if short:
            cap = 10 ** 6
        for _ in range(8):
            alt = w.route(here, target, level=lvl, have=have, avoid=frozenset(avoid))
            if alt is None or len(alt) > cap:
                return route                         # no sensible dry way: the raft
            more = self._needy_rooms(here, alt, carry)
            if not more:
                if self.ready("dry_route_note", 30):
                    self.log(f"Going round the water ({len(alt)} rooms instead of {len(route)}) — no raft needed"
                             + (f" ({short})" if short else ""))
                # the later passes (round a boss, the cheapest way, fewer jumps) re-plan: they keep off this water
                # too — the boss pass swapped the 204-room dry way back for the 129-room river (2026-11-16)
                self._dry_avoid = (self._tkey(target), frozenset(avoid - set(self.avoid_set())))
                return alt
            avoid |= more
        return route

    NO_ROOM_SECS = 1800
    SNEAK_FAIL_TRIES, SNEAK_REST_SECS = 3, 300
    BOAT_RE = re.compile(r"\b(?:raft|skiff|canoe|punt)s?\b", re.I)

    def _sneak_hopeless(self) -> bool:
        """0.8.227.5 (Dan: "rafts are huge -stealth and pretty much make it impossible to sneak unless you're a sneaking
        class and have done the perfect stealth quest... MudPilot just attempts to sneak over and over and never moves
        anywhere"): Stealth at 0 or below on 'st' (Miserable with a log raft: -17), or 'sn' failed SNEAK_FAIL_TRIES
        times in a row — walk on without sneaking ("don't move unless sneaking" too); try again SNEAK_REST_SECS on."""
        st = self.st
        if getattr(st, "stealth_read", False):
            if (st.stealth or 0) <= 0:
                if self.ready("sneak_hopeless_say", 600):
                    self.log(f"Not sneaking: your Stealth is {st.stealth} (a raft or heavy gear) — it can't work; "
                             "walking on")
                return True
        elif self.BOAT_RE.search(st.carrying or ""):
            # 'st' not read yet, a raft in the pack: the same (a raft's a huge stealth penalty)
            if self.ready("sneak_hopeless_say", 600):
                self.log("Not sneaking: you're carrying a raft — it can't work with one; walking on")
            return True
        if (getattr(st, "sneak_fails", 0) >= self.SNEAK_FAIL_TRIES
                and time.time() - getattr(st, "sneak_fail_at", 0) < self.SNEAK_REST_SECS):
            if self.ready("sneak_fails_say", self.SNEAK_REST_SECS):
                self.log(f"Sneaking failed {st.sneak_fails} times in a row — walking on without it for "
                         f"{self.SNEAK_REST_SECS // 60} minutes")
            return True
        return False

    def note_no_room(self, item):
        """A raft (or the like) nobody could make room for — the party member it was given to, or us: plan dry ways
        for NO_ROOM_SECS (0.8.227.2)."""
        w = self.s.world
        num = item if isinstance(item, int) else (w.item_names.get(str(item or "").strip().lower()) or {}).get("num")
        if num:
            self._no_room = {**(getattr(self, "_no_room", None) or {}), num: time.time()}

    def _no_room_on(self, here, route, carry) -> str:
        """Why one of the items this route needs carried can't be: a member or we couldn't make room for it lately,
        or our own pack can't take it even after dropping copper/silver/gold ('' = it can)."""
        w, st, now = self.s.world, self.st, time.time()
        nr = {n: t for n, t in (getattr(self, "_no_room", None) or {}).items() if now - t < self.NO_ROOM_SECS}
        self._no_room = nr
        sets, prev = [], here
        try:
            for ex in route:
                sets += [s for s in w.carry_needs([(prev, ex)]) if not (s & carry)]
                prev = ex.to
        except Exception:
            return ""
        held = self.held_items() or set()
        for s in {frozenset(x) for x in sets}:
            if s & held:
                continue
            try:
                pick = self.carry_pick(s)               # the one MudPilot would get (a log raft over a canoe)
            except Exception:
                pick = min(s)
            name = w.item_name(pick)
            if pick in nr:
                return f"no room for a {name} in the party lately"
            enc = st.enc
            wt = int((w.items.get(pick) or {}).get("encum") or 0)
            if enc and wt:
                from .remote import RemoteControl as _RC
                coins = sum(int(st.coins.get(k, 0) or 0) for k in _RC.ROOM_COINS)
                room = max(0, enc[1] - enc[0]) + coins // _RC.COINS_PER_ENC
                if wt > room:
                    return f"a {name} weighs {wt}, you've room for {room}"
        return ""

    @staticmethod
    def _tkey(target):
        return frozenset(map(tuple, target)) if isinstance(target, (set, frozenset)) else tuple(target)

    def _dry_keep(self, target) -> frozenset:
        """The water rooms the dry way to this target keeps off (empty when it didn't take one)."""
        d = getattr(self, "_dry_avoid", None)
        return d[1] if d and d[0] == self._tkey(target) else frozenset()

    def _raft_trip(self, here, target, route, carry) -> int:
        """Rooms for the wet way once a raft has to be fetched first: here → the nearest shop selling one → there.
        0 when nothing needs fetching or no shop is known."""
        w = self.s.world
        if isinstance(target, (set, frozenset)):
            return 0
        try:
            sets, prev = [], here
            for ex in route:
                sets += [s for s in w.carry_needs([(prev, ex)]) if not (s & carry)]
                prev = ex.to
            if not sets:
                return 0
            lvl, best = self.route_level(), 0
            for c in {frozenset(s) for s in sets}:
                src = self.errands.source_for(self.carry_pick(c, own=False), toward=tuple(target))
                if not src or src.get("kind") != "shop":
                    return 0
                a = w.route(here, tuple(src["room"]), level=lvl, have=carry)
                b = w.route(tuple(src["room"]), target, level=lvl, have=carry | set(c))
                if a is None or b is None:
                    return 0
                best = max(best, len(a) + len(b))
            return best
        except Exception:
            return 0

    def _plan_route(self, here, target, ask=None):
        """Shortest route, staying out of avoided areas. If the short way goes through one:
        avoid mode takes the scenic route, allow mode goes through, ask mode calls ask(short, long, area)
        (True = go through) — unattended runs never ask and take the scenic route."""
        w, cfg = self.s.world, self.cfg
        lvl = self.route_level()
        have = self.held_items() or set()
        try:
            self.s.route_char()
        except Exception as ex:
            self.log(f"Routing: couldn't read your class/race ({ex})")
        direct = w.route(here, target, level=lvl, have=have)
        avoid = self.avoid_for(target)               # (0.8.201, walk check: a target inside an avoided area)
        if direct is None or not avoid or here in avoid or not any(ex.to in avoid for ex in direct[:-1]):
            # already inside it? then just walk out the short way
            return self._shortcut_route(here, target, lvl, avoid, have, direct)
        mode = (cfg.avoid_mode or "ask").lower()
        if mode == "allow":
            return direct
        scenic = w.route(here, target, level=lvl, avoid=avoid, have=have)
        area = next((w.room(ex.to).name for ex in direct if ex.to in avoid and w.room(ex.to)), "an avoided area")
        if scenic is None:
            na = self._needed_area(here, target, lvl, have, avoid, direct)
            if na:
                area, direct = na
        allowed = getattr(self, "_trip_allow", {})
        denied = getattr(self, "_trip_deny", {})
        now = time.time()
        tkey = tuple(target) if not isinstance(target, (set, frozenset)) else None
        if now - allowed.get(area.lower(), 0) < 3 * 3600:
            # you said yes to going through here on this trip: a re-plan (fetching the party, going round a
            # door) keeps to it instead of turning round for the long way
            return direct
        keyed = self._opener_route(here, target, lvl, avoid, have, scenic)
        if keyed is not None:
            return keyed
        if scenic is None and self._npp_only_ok(area):
            if self.ready("npp_only_said", 60):
                self.log(f"The only way there is through {area} — going (avoided only when there's another way)")
            return direct
        if mode == "ask" and ask is not None:
            # someone's here to answer (a fresh Go to) — ask, whatever was said before
            if ask(len(direct), len(scenic) if scenic is not None else None, area):
                self._trip_allow = {**allowed, area.lower(): now}
                return direct
            self._trip_deny = {**denied, area.lower(): now}
            if scenic is None:
                self._avoid_blocked = (area, tkey)
            return scenic
        # no one to ask (a re-plan on the way, or unattended): a remembered 'no' means don't pop the question
        # again — take the scenic route, or stop if there's none (Dan: the popup wouldn't stop)
        if scenic is None:
            if not (now - denied.get(area.lower(), 0) < 3 * 3600):
                self.log(f"Only way there is through {area} — avoided, so not going (Settings → Other → Routing)")
            self._avoid_blocked = (area, tkey)
        return scenic

    def replan(self, target, then=None, ask=None, retry=True, looked=False):
        """A Go to tried again by itself (after 'abil' / 'who'): worked out off the window's thread like one you
        start — on the window's it froze it for 25 s (Buddy, 2026-11-04)."""
        from . import bgplan
        bgplan.plan(self.s, lambda a: self.goto(target, then=then, ask=ask, _retry=retry, _looked=looked),
                    after=getattr(self.s, "tk_after", None))

    def goto_bg(self, target, then=None, done=None, retry=False):
        """A Go to the bot starts itself (back to the loop, an errand, a trip, Comeback…), worked out off the window's
        thread like one you start (HUNT_1123 #24: on the window's they froze it for 2-13 s). The walk waits for the
        route, fighting and healing carry on (bgplan / walk()). done(ok) runs on the window's thread when it's
        worked out — what the caller did with goto()'s answer — unless a Stop came meanwhile. Without the window
        (tests, headless) it's all right here, as before: returns goto()'s answer; on the worker: None."""
        try:
            import inspect
            fr = inspect.stack()[1:4]
            by = " ← ".join(f"{os.path.basename(f.filename)[:-3]}.{f.function}" for f in fr)
        except Exception:
            by = "?"
        kw = {}                                # (goto's own arguments, only those the caller gave)
        if then is not None:
            kw["then"] = then
        if retry:
            kw["_retry"] = True
        key = frozenset(target) if isinstance(target, (set, frozenset)) else tuple(target)
        after = getattr(self.s, "tk_after", None)
        if getattr(self, "_planning", False) and getattr(self, "_bg_goto", None) == key and \
                threading.current_thread() is threading.main_thread():
            self.status = "Calculating route — one moment please…"
            return None                        # this very Go to is being worked out already: it goes when it's done
        if after is None or getattr(self, "_planning", False):
            # (another route being worked out: goto() says so and returns False on the window's thread, as before)
            self._goto_by_next = by
            try:
                ok = self.goto(target, **kw)
            finally:
                self.__dict__.pop("_goto_by_next", None)
            if done:
                done(bool(ok))
            return ok
        from . import bgplan
        seq0 = getattr(self, "_stop_seq", 0)
        self._bg_goto = key

        def fin(res, err):
            self._bg_goto = None
            if err is not None:
                self.log(f"Go to: working out the route failed ({type(err).__name__}: {err})")
                res = False
            if done and getattr(self, "_stop_seq", 0) == seq0:
                done(bool(res))

        def work(_a):
            self._goto_by_next = by
            try:
                return self.goto(target, **kw)
            finally:
                self.__dict__.pop("_goto_by_next", None)
        bgplan.plan(self.s, work, fin, after=after)
        return None

    def _reread_flags(self, target) -> bool:
        """No way there: read 'abil' again first (once in 5 minutes per place) — a quest step done since the last
        read can open it. True = asked; the Go to tries again when the answer is in."""
        done = getattr(self, "_flags_reread", {})
        now = time.time()
        if now - done.get(tuple(target), 0) < 300:
            return False
        done[tuple(target)] = now
        self._flags_reread = done
        self.log("Go to: no way there with the quest flags MudPilot has — reading them again ('abil') before "
                 "giving up")
        self._abil_read = ("sent", now)              # (the answer updates the saved flags and says what's new)
        self.send("abil")
        return True

    def _why_words(self, why) -> str:
        """MME's exit note in words: '(Cast: pre-0, post-702)' → what the spell does to you."""
        w = self.s.world
        nums = [int(n) for n in re.findall(r"(?:pre|post)-(\d+)", why or "") if int(n)]
        if not nums or "Cast:" not in (why or ""):
            return why
        names = [((w.spells.get(n) or {}).get("Name") or f"spell {n}") for n in nums]
        return "it casts " + ", ".join(f"'{nm}'" for nm in names) + " on you, which takes you somewhere else"

    def _flags_text(self) -> str:
        held = {str(k): v for k, v in (self.cfg.known_abils or {}).items() if self.is_quest_flag(k)}
        out = []
        for k, v in sorted(held.items(), key=lambda kv: int(kv[0])):
            hint = self.s.world.quest_hint(int(k), None, v if isinstance(v, int) else None)
            out.append(self.flag_text(k, v) + (f" ({hint.split(' — needs')[0]})" if hint else ""))
        return ", ".join(out)

    def _ask_gate_abilities(self, here, target) -> bool:
        """The way is blocked by an ability gate (quest flags) whose value we've never seen: send 'abil N'
        for those (once a session each)."""
        w, st = self.s.world, self.st
        try:
            bl = w.why_no_route(here, target, level=self.route_level(),
                                have=self.held_items() or set(), avoid=self.avoid_set(), limit=12)
        except Exception:
            bl = []
        ids = set()
        for _r, _d, why in bl:
            m = w.ABIL_GATE_RE.search(why or "")
            if m:
                ids.add(int(m.group(1)))
            # (a room command's quest gate is worded — "'secure passage to talkiran' needs ability 211 ≥ 3" — m1315 R3)
            ids |= {int(x) for x in re.findall(r"\bability (\d+) [≥>=]", why or "", re.I)}
        asked = getattr(self, "_abil_asked", set())
        todo = [a for a in sorted(ids) if a > 0 and a not in asked and st.abil_value(a, "total") is None]
        if not todo:
            return False
        self._abil_asked = asked | set(todo)
        self.log("Go to: checking " + ", ".join(f"abil {a}" for a in todo) + " (exits need them)")
        for a in todo:
            self.send(f"abil {a}")
        return True

    def _align_is_the_block(self, here, target, ask=None) -> bool:
        """No route, and an alignment gate was on the way with yours unknown: would there be one with that gate open?
        Then 'who' is the answer — not keys, quest flags, a twin room (each another whole-map search)."""
        w = self.s.world
        w._align_any = True
        w.forget_routes()
        try:
            return self.plan_route(here, target, ask) is not None
        finally:
            w._align_any = False
            w.forget_routes()

    def _reachable_twin(self, here, target, ask=None):
        """MME has rooms nothing leads into (16/297 'Sandbar', where MegaMUD's 'King Crab' room resolves — no exits
        at all; the crab spawns in 16/287, also 'Sandbar'). The target can't be reached: the nearest room of the
        same name on that map that can. (key, route) or None."""
        w = self.s.world
        r = w.room(target)
        if not r:
            return None
        try:
            reach, via_mon = w.leads_in(here, target)
        except Exception:
            reach, via_mon = True, True
        if not reach:
            way_in, mon_way = None, None               # (nothing on the map leads there from here at all)
        with w._plan_lock:
            # every item, the cash for any toll and any class / race / alignment / quest-flag gate (0.8.221, bug hunt:
            # with 0 copper the 14/1792 Training Hall's toll read as "no way in", so it went to the 14/1791 one next
            # door — where it stood — and called it done; flag 126 at 51 did the same at the 14/10450 Castle
            # Courtyard before the quest-flag check below ever asked the game)
            if reach:
                saved = w.char
                w.char = dict(saved or {}, wealth=10 ** 12, gate_any=True)
                try:
                    way_in = w.route(here, target, level=self.route_level(), have=self.every_item())
                finally:
                    w.char = saved
        if way_in is None and via_mon:
            # 0.8.222 (Dan, 11-20 bug hunt): the only way in needs a particular monster there (MME 'req monster': 14/1290
            # 'go courtyard' into the 14/10450 Castle Courtyard) — say so; don't go to a look-alike and call it arrived
            with w._plan_lock:
                saved = w.char
                w.char = dict(saved or {}, wealth=10 ** 12, gate_any="monster")
                try:
                    mon_way = w.route(here, target, level=self.route_level(), have=self.every_item())
                finally:
                    w.char = saved
            prev = tuple(here)
            for ex in mon_way or ():
                q = getattr(ex, "req", None) or {}
                if q.get("monster"):
                    pr = w.room(prev)
                    return "needs", (f"Not going to {target[0]}/{target[1]} {r.name}: the way in ('{ex.text_command}' "
                                     f"in {pr.name if pr else 'a room'}, {prev[0]}/{prev[1]}) needs "
                                     f"{w.req_monster_names(q)} there")
                prev = tuple(ex.to)
        if way_in is not None:
            # there IS a way in — behind keys/doors the key run or a bash sorts out. Buddy, 2026-10-29: Goto
            # 'Guardian Golem' (1/1797, behind the green metal and large iron key doors) went to 1/662, another
            # 'Small Room' 1100 rooms away, and ran him through the sewers
            return None
        # a Rooms.md label that's a monster ("King Crab"): where that monster spawns, not just the nearest
        # same-name room (16/296 is a Sandbar too, but the crab is in 16/287)
        try:
            labels = [n for _g, n, k in self.s.known_rooms() if tuple(k) == tuple(target)]
        except Exception:
            labels = []
        for lab in labels:
            mon = w.monster_names.get(lab.strip().lower())
            spawns = [tuple(k) for k in (mon or {}).get("spawn_rooms") or [] if tuple(k) != tuple(target)]
            spawns.sort(key=lambda k: (k[0] != target[0], abs(k[1] - target[1])))
            for k in spawns[:6]:
                try:
                    if not w.leads_in(here, k)[0]:
                        continue                     # (0.8.225, walks: no full search where nothing leads from here)
                except Exception:
                    pass
                route = self.plan_route(here, k, ask)
                if route is not None:
                    self.log(f"Go to: {target[0]}/{target[1]} {r.name} has no way in on MME's map — going to "
                             f"{k[0]}/{k[1]}, where the {lab} spawns")
                    return k, route
        twins = sorted((k for k, x in w.rooms.items() if k != tuple(target) and k[0] == target[0]
                        and x.name == r.name and x.exits), key=lambda k: abs(k[1] - target[1]))
        for k in twins[:12]:
            try:
                if not w.leads_in(here, k)[0]:
                    continue                         # (0.8.225, walks: 15-50 s "no way in" Go tos → ~6 s)
            except Exception:
                pass
            route = self.plan_route(here, k, ask)
            if route is not None:
                self.log(f"Go to: {target[0]}/{target[1]} {r.name} has no way in on MME's map — "
                         f"going to {k[0]}/{k[1]}, another {r.name} on that map")
                return tuple(k), route
        return None

    def goto(self, target, then: MPath | None = None, ask=None, _retry=False, _looked=False):
        _by = self.__dict__.pop("_goto_by_next", None)     # (goto_bg: who started it — the worker can't tell)
        if self.dead_blocked(f"going to {target}"):
            self.no_route_msg = "died — nothing walks until you start it yourself"
            return False
        if getattr(self, "_planning", False) and threading.current_thread() is threading.main_thread():
            self.status = "Calculating route — one moment please…"
            return False                       # a Go to is being worked out already (bgplan): that one first
        er = getattr(self, "errands", None)
        if er is not None and er.asking:
            # a new walk: the '@have' round for the old one is over — its answers mustn't start that walk again
            # (Evolution, 2026-11-06: the crimson mist walk's raft check came back in the golem's room, 'lost')
            er.asking = None
        here = self.st.room
        self.no_route_msg = ""
        # rooms struck off in the route preview count for that Go to only (and its re-plans on the way)
        ta = getattr(self, "_trip_avoid", None)
        if ta and not isinstance(target, (set, frozenset)) and tuple(target) == ta[0]:
            self.s.world.user_avoid = ta[1]
        else:
            self.s.world.user_avoid = None
        seq0 = getattr(self, "_stop_seq", 0)
        try:
            if _by:
                by = _by                       # (goto_bg: who started it, worked out before the worker thread)
            else:
                import inspect
                fr = inspect.stack()[1:4]
                by = " ← ".join(f"{os.path.basename(f.filename)[:-3]}.{f.function}" for f in fr)
        except Exception:
            by = "?"
        if by.startswith(("app.", "gotodlg.")) and getattr(self, "_too_strong", None):
            # your own Go to: try again past what we ran from (fight3 #2 — "Go to again to try once more")
            self._too_strong = {}
        ts_ = self.too_strong_rooms()
        if ts_:
            # rooms we ran from the same monster twice in lately: gone round, like rooms struck off in the preview
            self.s.world.user_avoid = frozenset(self.s.world.user_avoid or ()) | ts_
            if not isinstance(target, (set, frozenset)) and tuple(target) in ts_:
                self.no_route_msg = f"not going back to {self.too_strong_note([tuple(target)])}"
                self.log(f"Not going to {target[0]}/{target[1]}: {self.no_route_msg}. Go to it yourself to try again.")
                self.status = "Idle"
                return False
        if not isinstance(target, (set, frozenset)):
            self.why("goto", target=target, then=getattr(then, "title", None), by=by)
            if not by.startswith(("app.", "gotodlg.")):
                if self.called_off(target):
                    return False
                self.log(f"Go to {target[0]}/{target[1]} — started by {by.split(' ← ')[0]}")
            else:
                self._user_goto_at = time.time()      # your own Go to: you're taking it from here (session._rejoin)
                self._goto_by_user = (tuple(target), time.time())   # (its 'no route' pops up; nobody else's does)
                self._called_off = None
                tr_ = getattr(self.s, "trips", None)
                if tr_ is not None and tr_.trip:
                    # (0.8.201, realm walk: a bank/shop trip left running finished a few seconds into your own Go to
                    #  and its walk back took over — 161 rooms to the bank instead of where you sent it)
                    tr_.reset("your Go to")
                    self.log("Trip: cancelled — your Go to takes over")
        if not here:
            if not _looked and not isinstance(target, (set, frozenset)):
                # look (and ask the board where it can), then go once the room's known — the way Rego does (Dan,
                # 2026-11-10: Rocky Trail → Iron House, 'press Enter to look first' and the Go to just didn't go)
                if self.walking:
                    # whatever's walking (a loop that lost its room) gives way, or the tick would drop this retry
                    # as 'a walk started meanwhile'
                    self.stop(f"Stopped: Go to {target[0]}/{target[1]} takes over")
                self._goto_retry = {"t": time.time(), "args": (target, then, ask)}
                self.log(f"Go to {target[0]}/{target[1]}: finding out which room this is first, then going")
                if not self.locate_now("Go to: room not known"):
                    self.send("")
                self.status = "Finding out which room this is — then going"
                return True
            self.no_route_msg = "MudPilot isn't sure which room you're in — press Enter (look) and try again."
            self.log("Can't route: current room unknown — looked and still can't tell. Press Enter, then Go to again.")
            return False
        self.s.world.align_unknown = False
        route = self.plan_route(here, target, ask)
        if route is None and getattr(self.s.world, "align_unknown", False) and \
                not getattr(self.st, "alignment", "") and not self.cfg.char_alignment and \
                not isinstance(target, (set, frozenset)) and self._align_is_the_block(here, target, ask) and \
                self.ready("align_who", 60):
            # an alignment gate on the way and MudPilot doesn't know yours: read it off 'who', then try again —
            # straight away, before the twin-room / every-key searches (Miserable PVE, 2026-11-06: 70 s of those
            # on the mini PC for the 87-room walk to Chancellor Annora, then 'who', then 1 s)
            self.s.world.align_unknown = False
            if self._stopped_since(seq0):
                return False
            self._goto_after_who = (tuple(target), time.time(), then)
            self.log("The way goes through an alignment gate and MudPilot doesn't know your alignment yet — "
                     "checking 'who', then trying again")
            self.status = "Checking my alignment (who)"
            self.send("who")
            return True
        ab = getattr(self, "_avoid_blocked", None)
        if route is None and ab and \
                ab[1] == (tuple(target) if not isinstance(target, (set, frozenset)) else None):
            # the only way there is through an area you're avoiding (you said no, or it's unattended): stop
            # cleanly instead of fetching keys / asking gates / re-prompting (Dan: the popup wouldn't stop)
            self._avoid_blocked = None
            rr = self.s.world.room(target) if not isinstance(target, (set, frozenset)) else None
            where = f"{target[0]}/{target[1]} {rr.name}" if rr else "there"
            self.no_route_msg = f"The only way to {where} goes through {ab[0]}, which you're avoiding."
            self.log(f"Not going to {where}: the only way is through {ab[0]} (avoided — Settings → Other → Routing)")
            self.s.on_alert(f"Can't reach {where} without going through {ab[0]}")
            return False
        if route is None and not isinstance(target, (set, frozenset)):
            twin = self._reachable_twin(here, target, ask)
            if twin and twin[0] == "needs":
                return self._no_go(target, twin[1])  # 0.8.222: a way in that needs a monster there — not a look-alike
            if twin:
                target, route = twin
        if route is None and not isinstance(target, (set, frozenset)):
            small = self._too_small(here, target)
            if small:
                # Dan: when a level-gated area (NPP is 40) is the only way and a follower is too low, say so —
                # don't ask "go this way?" or run off after keys
                rr = self.s.world.room(target)
                where = f"{target[0]}/{target[1]} {rr.name}" if rr else "there"
                self.no_route_msg = f"Can't take the party to {where}: {small}."
                self.log(f"Not going to {where}: {small}")
                self.status = "Party too low for the way there"
                self.s.on_alert(f"Can't reach {where}: members of the party aren't big enough")
                return False
        fe = getattr(self.s.world, "failed_edges", None)
        if route is None and not _retry and fe:
            # the only way there is an exit that failed earlier (a hidden exit whose push/search missed, a door
            # that was locked): those are a 'try another way first', not a wall — when there is no other way,
            # forget them and try again
            saved = dict(fe)
            fe.clear()
            route = self.plan_route(here, target, ask)
            if route is None:
                fe.update(saved)
            else:
                self.log("Go to: the only way there goes through "
                         + ", ".join(f"{DIR_WORDS.get(d, d)} from {r[0]}/{r[1]}" for r, d in saved)
                         + ", which failed earlier — trying it again")
        if route is None and not _retry and self.held_items() is None and self.s.telnet.connected:
            # don't know what you carry yet (keys!) — read the inventory, then plan again
            self._pending_goto = (target, then, ask, self.st.inv_seq, time.time())
            self.status = "Checking your keys before routing…"
            self.log("Go to: reading your inventory first (keys can open the way)")
            self.send("i")
            return True
        if route is None and self.s.telnet.connected and not isinstance(target, (set, frozenset)) \
                and self._ask_gate_abilities(here, target):
            # exits gated on an ability (quest flags: "Ability: 134 w/value 2 to 999") and we don't know yours yet:
            # ask the game ('abil 134'), then plan again
            self._pending_abil = (target, then, ask, time.time())
            self.status = "Checking your quest abilities before routing…"
            return True
        if route is None and (self.cfg.auto_get_items or self.cfg.bash_key_doors) \
                and not isinstance(target, (set, frozenset)):
            # behind doors you have no key for? route as if you had every key; the path's needed-items check
            # then fetches the key, or (no key to be had) picks/bashes the door when you get there
            w = self.s.world
            self._avoid_blocked = None               # (one left by another plan — a bank / shop trip's — isn't this one's:
            full = self.keyed_route(here, target, ask)   # flags2 #3, "only through Negative Power Plane" for a Go to it wasn't)
            ab_ = getattr(self, "_avoid_blocked", None)
            if full is None and ab_ and (ab_[1] is None or tuple(ab_[1]) == tuple(target)):
                ab = self._avoid_blocked
                self._avoid_blocked = None
                rr = w.room(target)
                where = f"{target[0]}/{target[1]} {rr.name}" if rr else "there"
                self.no_route_msg = f"The only way to {where} goes through {ab[0]}, which you're avoiding."
                self.log(f"Not going to {where}: the only way is through {ab[0]} (avoided — Settings → Other → Routing)")
                self.s.on_alert(f"Can't reach {where} without going through {ab[0]}")
                return False
            if full and (self.called_off(target) or self._stopped_since(seq0)):
                return False
            if full:
                full = self._hurt_choice(here, target, full, ask, have=set(self.plan_items(target)))
                if self.called_off(target) or self._stopped_since(seq0):
                    return False
                self._goto_alt = None
                chk = self._goto_check(here, target, full, then, ask)
                if chk is not None:
                    return chk
                full = self._goto_alt or full
                r = w.room(target)
                mp = path_from_route(w, here, full, name=f"Go to {target[0]}/{target[1]} {r.name}")
                mp.out_items = sorted(getattr(self, "_goto_out", None) or ())
                self.after_goto = then
                self._goto_target = tuple(target)
                t0_ = time.time()
                self.start_path(mp, loop=False)      # its needed-items check sends us after the keys
                return self._started_after(t0_, target)
        if route is None and self.s.telnet.connected and self._bank_way(here, target, then, ask):
            return not self.__dict__.pop("_bank_no", False)   # 0.8.222: off to the bank for a toll / fare first
        if route is None and self.s.telnet.connected and not isinstance(target, (set, frozenset)) \
                and self._reread_flags(target):
            # the quest flags we have may be old (Dan, 2026-11-04: DaoLordQuest was 9 in the game, MudPilot still
            # had 8 — the pyramid's arches throw you about at 8 — and it just didn't go): read them, plan again
            self._pending_abil = (target, then, ask, time.time())
            self.status = "Checking your quest flags before giving up…"
            return True
        if route is None:
            w = self.s.world
            msg = f"No walkable route from {here[0]}/{here[1]} to {target[0]}/{target[1]}"
            if not isinstance(target, (set, frozenset)):
                try:
                    bl = w.why_no_route(here, target, level=self.route_level(),
                                        have=self.held_items() or set(), avoid=self.avoid_set())
                except Exception:
                    bl = []
                if bl:
                    def yours(why):
                        m = w.ABIL_GATE_RE.search(why or "")
                        if not m:
                            return ""
                        v = self.st.abil_value(int(m.group(1)), "total")
                        return f" — yours: {v[0]}" if v else " — yours isn't known (the game didn't list it)"
                    msg += " — blocked by " + "; ".join(
                        (f"the {DIR_WORDS.get(d, d)} exit of {w.room(r).name} ({r[0]}/{r[1]}): " if d else "")
                        + f"{self._why_words(why)}{yours(why)}" for r, d, why in bl)
                    flags = self._flags_text()
                    if flags:
                        msg += f" (your quest flags: {flags})"
            if " — blocked by " not in msg and not isinstance(target, (set, frozenset)) and self._boxed_in(here):
                # (0.8.225, HUNT_1123 #21: aboard the Swiftwind, 14/744 — every Go to blamed the target)
                msg += (" — MME's map has no way out of where you are (only a handful of rooms lead on from here). "
                        "Walk out by hand, and MudPilot learns the way.")
            elif " — blocked by " not in msg and not isinstance(target, (set, frozenset)):
                msg += (" — MME's map has no way into that area at all (some entrances aren't in MME). Walk in "
                        "once by hand, or import a MegaMUD path that goes there, and MudPilot learns the way.")
            if self.called_off(target):
                return False
            self.log(msg)
            self.status = "No route — see the log"
            self.no_route_msg = msg
            self.s.on_alert(msg)
            gu = getattr(self, "_goto_by_user", None)
            if gu and not isinstance(target, (set, frozenset)) and gu[0] == tuple(target) and time.time() - gu[1] < 600:
                # the popup only for a Go to you started: a party member's @comeback, an errand or a re-plan just
                # logs it (Dan, 2026-11-11: flung out of the Dao Lord's room, a popup for a walk he never asked for)
                self.s.on_no_route(msg)
            return False
        if self._stopped_since(seq0):
            return False
        if not route:
            if then:
                self.start_path(then)
            return True
        if self.called_off(target):
            return False
        route = self._hurt_choice(here, target, route, ask)
        if self.called_off(target) or self._stopped_since(seq0):
            return False                             # (0.8.224.2, review: stopped while the route question was up)
        self._goto_alt = None
        chk = self._goto_check(here, target, route, then, ask)
        if chk is not None:
            return chk
        route = self._goto_alt or route
        r = self.s.world.room(target)
        mp = path_from_route(self.s.world, here, route, name=f"Go to {target[0]}/{target[1]} {r.name}")
        mp.out_items = sorted(getattr(self, "_goto_out", None) or ())
        self.after_goto = then
        self._goto_target = tuple(target) if not isinstance(target, (set, frozenset)) else None
        t0_ = time.time()
        self.start_path(mp, loop=False)
        return self._started_after(t0_, target)

    def _started_after(self, t0, target) -> bool:
        """0.8.225 (walks: about 30 a profile): start_path's needed-items check can refuse (give_up) — then the Go to
        didn't go, and says so like any refusal (the popup for your own Go to, @goto's reply)."""
        if getattr(self, "_gave_up_at", 0) >= t0 and not self.walking and self.no_route_msg:
            self._goto_refused_at = time.time()      # (regression sweep: callers don't give up a second time)
            gu = getattr(self, "_goto_by_user", None)
            if gu and not isinstance(target, (set, frozenset)) and gu[0] == tuple(target) and time.time() - gu[1] < 600:
                self.s.on_no_route(self.no_route_msg)
            return False
        return True

    HURT_PICK_PCT = 50       # a run of rooms that hurts for at least this % of your max HP (and past the hang-up line)
    HURT_PICK_EXTRA = 120    # …and a way round that's at most this many rooms more, and not over twice as long

    def _hurt_choice(self, here, target, route, ask, have=None):
        """0.8.224.2 (Dan: "if there's a much easier route and the route is considered dangerous maybe a prompt that lets
        them pick the route"). Nothing is ever refused for rooms that hurt. Only when the way has a run that could do
        more than half your max HP and past your hang-up line, and a way round that hurts at most a quarter as much and
        isn't a huge detour: 'Yes = the short way through them / No = the safe way round' — no answer, or nobody to ask
        (an errand, a member's @goto): the safe way round. Otherwise the way as planned."""
        if not route or isinstance(target, (set, frozenset)):
            return route
        w = self.s.world
        try:
            hp = int((w.char or {}).get("max_hp") or 0)
            if hp <= 0:
                return route
            st_ = w.hurt_stretches(route, have)
            worst = max((d for _r, d in st_), default=0)
            if worst < hp * self.HURT_PICK_PCT / 100 or worst < w.stretch_limit():
                return route
            dmg = sum(d for _r, d in st_)
            alt = w.safe_round(tuple(here), tuple(target), level=self.route_level(),
                               have=have if have is not None else (self.held_items() or set()),
                               avoid=self.avoid_set() or None)
            if alt:
                # (0.8.224.2, review: the safe way gets plan_route's own boss / party-carry checks too)
                alt = self._party_carry_way(here, target, self._boss_free_route(here, target, alt))
                if alt and set(self._carry_short(alt)) - set(self._carry_short(route)):
                    alt = None
                held_ = set(self.held_items() or ())    # (review: with every item, a key door read as open)
                if alt and any(getattr(ex, "kind", None) in ("door", "key") and w.door_beaten(ex, held_) is False
                               for ex in alt) and not any(getattr(ex, "kind", None) in ("door", "key")
                                                          and w.door_beaten(ex, held_) is False for ex in route):
                    alt = None                       # (0.8.225, walks: a door the party can't open → a 1% key farm)
            if not alt:
                return route
            adm = sum(d for _r, d in w.hurt_stretches(alt, have))
            if adm > dmg / 4 or len(alt) > 2 * len(route) or len(alt) - len(route) > self.HURT_PICK_EXTRA:
                return route
        except Exception as ex:
            self.log(f"Routing: rooms-that-hurt check skipped ({ex})")
            return route
        rooms = max(st_, key=lambda t: t[1])[0]
        text = f"{len(rooms)} rooms in a row that hurt (up to {worst} damage; {w._hp_whose()} max HP is {hp})"
        ok = False
        mem = self.__dict__.setdefault("_hurt_pick_ans", {})
        old = mem.get(tuple(target))
        if old and time.time() - old[1] < 3 * 3600:
            return route if old[0] else alt          # (0.8.225, #5: asked already — not again on every re-plan)
        if ask is not None:
            try:
                ok = bool(ask(len(route), len(alt), text, "hurtpick"))
            except TypeError:
                ok = bool(ask(len(route), len(alt), text))
            except Exception:
                ok = False
        if ask is not None:
            mem[tuple(target)] = (ok, time.time())
        if ok:
            self.log(f"Routing: the short way through {text} ({len(route)} steps) — you said yes")
            return route
        self.log(f"Routing: the safe way round {text} — {len(alt)} steps, {len(alt) - len(route)} more"
                 + (" (you said no or didn't answer)" if ask is not None else " (nobody to ask)"))
        return alt

    def _deadly_run(self, here, target, route, ask, have=None, then=None):
        """0.8.225 (HUNT_1123 #1, with Dan's "being the only option, it should just go"): a run of rooms that hurt for
        MORE than your whole max HP asks once — never refuses:
          - another way exists that keeps out of those rooms: 'Yes = through them / No = the other way'; no answer or
            nobody to ask takes the other way;
          - it's the only way: a shop item that stops them (swamp boots, a fur cape) is offered; then it goes.
        Under your max HP it just goes. Returns the route to walk, or goto's answer after a counter errand re-plan."""
        if not route or isinstance(target, (set, frozenset)):
            return route
        w = self.s.world
        try:
            hp = int((w.char or {}).get("max_hp") or 0)
            if hp <= 0 or w.stretch_allowed(target):
                return route
            st_ = w.hurt_stretches(route, have)
            bad = [(r, d) for r, d in st_ if d > hp]
            start_hurts = bool(w.room_damage(tuple(here), (w.char or {}).get("carried") or ()))
            if bad and start_hurts and bad[0][0] and bad[0][0][0] == tuple(route[0].to):
                bad = bad[1:]                        # (walking out of where you stand is the point)
            if not bad:
                return route
            sb = max(bad, key=lambda t: t[1])
            alt = w.route(tuple(here), tuple(target), level=self.route_level(),
                          have=have if have is not None else (self.held_items() or set()),
                          avoid=frozenset(set(self.avoid_set() or ()) |
                                          (set(r for rr, _d in bad for r in rr) - {tuple(target), tuple(here)})))
            if alt:
                alt = self._party_carry_way(here, target, self._boss_free_route(here, target, alt))
            if alt and any(d > hp for _r, d in w.hurt_stretches(alt, have)):
                alt = None
        except Exception as ex:
            self.log(f"Routing: rooms-that-hurt check skipped ({ex})")
            return route
        rooms, dmg = sb
        a, b = rooms[0], rooms[-1]
        what = (f"{len(rooms)} rooms in a row that hurt ({a[0]}/{a[1]} to {b[0]}/{b[1]}), up to {dmg} damage — more "
                f"than {w._hp_whose()} whole max HP ({hp})")
        mem = self.__dict__.setdefault("_hurt_pick_ans", {})
        old = mem.get(("deadly", tuple(target)))
        if alt:
            if old and time.time() - old[1] < 3 * 3600:
                return route if old[0] else alt
            ok = False
            if ask is not None:
                try:
                    ok = bool(ask(len(route), len(alt), what, "hurtpick"))
                except TypeError:
                    ok = bool(ask(len(route), len(alt), what))
                except Exception:
                    ok = False
                mem[("deadly", tuple(target))] = (ok, time.time())
            if ok:
                self.log(f"Routing: through {what} — you said yes")
                return route
            self.log(f"Routing: the other way round {what} — {len(alt)} steps, {len(alt) - len(route)} more"
                     + (" (you said no or didn't answer)" if ask is not None else " (nobody to ask)"))
            return alt
        cn = self._stretch_counter(sb)
        if cn is not None and not (old and time.time() - old[1] < 3 * 3600):
            if ask is not None:
                mem[("deadly", tuple(target))] = (False, time.time())
            if self._ask_counter(target, sb, cn, ask):
                return self.goto(target, then, ask, _retry=True, _looked=True)
        if self.ready("deadly_only_way", 60):
            self.log(f"Routing: the only way goes through {what} — going (Dan: the only way, it just goes)"
                     + (f"; {cn[2]} ({cn[1] // 100:,} gold in a shop) would stop them" if cn else ""))
        return route

    def _stretch_counter(self, sb):
        """0.8.224 (Dan): the cheapest shop-sold item that stops every room spell in the blocking run (swamp boots in
        the bog, a fur cape on the icy path) and that you don't carry — (item, price in copper, name) or None. Not
        when the limit is a follower's max HP: one bought by the leader doesn't help them."""
        w = self.s.world
        if (w.char or {}).get("max_hp_who"):
            return None
        from .hazards import counters, shop_price
        rs = getattr(w, "room_spells", None) or {}
        spells = {rs.get(tuple(r)) for r in (sb[0] if sb else ())} - {None}
        if not spells:
            return None
        held = self.held_items() or set()
        best = None
        common = None
        for sp in spells:
            cs = set(counters(w, sp))
            if cs & held:
                continue
            common = cs if common is None else (common & cs)
        for c in sorted(common or ()):
            p = shop_price(self, c)
            if p is not None and (best is None or p < best[1]):
                best = (c, p, w.item_name(c))
        return best

    def _ask_counter(self, target, sb, cn, ask) -> bool:
        """'… swamp boots (25 gold in a shop) stop those rooms — fetch one first and go?' Yes: the item counts as carried
        for this Go to, and the walk's needed-items check buys it on the way (3 hours)."""
        if ask is None:
            return False
        w = self.s.world
        rooms, dmg = sb
        c, p, nm = cn
        text = (f"The way to {target[0]}/{target[1]} goes through {len(rooms)} rooms that hurt (up to {dmg} damage, more "
                f"than your whole max HP). {nm} ({p // 100:,} gold in a shop) would stop them — fetch one first")
        try:
            ok = bool(ask(len(rooms), None, text, "hurt"))
        except TypeError:
            ok = bool(ask(len(rooms), None, text + "?"))
        except Exception:
            ok = False
        if not ok:
            return False
        w.stretch_counter = {**(getattr(w, "stretch_counter", None) or {}), tuple(target): c}
        self._counter_buy = {"item": c, "target": tuple(target), "t": time.time()}
        w.forget_routes()
        self.log(f"Routing: fetching {nm} first for the rooms that hurt on the way to {target[0]}/{target[1]} (you said yes)")
        return True

    def _boxed_in(self, here, limit=150) -> bool:
        """Fewer than `limit` rooms lead on from here at all on the map (any exit, no rules): a ship, a cell."""
        w = self.s.world
        seen, todo = {tuple(here)}, [tuple(here)]
        while todo and len(seen) < limit:
            r = w.rooms.get(todo.pop())
            for ex in (r.exits.values() if r else ()):
                to = tuple(ex.to) if getattr(ex, "to", None) else None
                if to and to in w.rooms and to not in seen:
                    seen.add(to)
                    todo.append(to)
        return len(seen) < limit

    def _no_go(self, target, msg) -> bool:
        """A Go to that isn't setting off, and why: logged, alerted, and popped up only for your own Go to."""
        self.log(msg)
        self.status = "Not going — see the log"
        self.no_route_msg = msg
        self.s.on_alert(msg)
        gu = getattr(self, "_goto_by_user", None)
        if gu and not isinstance(target, (set, frozenset)) and gu[0] == tuple(target) and time.time() - gu[1] < 600:
            self.s.on_no_route(msg)
        return False

    def _door_power_unknown(self, route) -> bool:
        """A locked door on the way that picklocks / strength decide, and yours aren't read yet ('st')."""
        if self.door_power() is not None:
            return False
        w = self.s.world
        for ex in route or ():
            if ex.kind not in ("door", "key") or ex.action_cmds():
                continue
            m = re.search(r"\[(?:or\s+)?(\d+)\s+picklocks", ex.etype or "", re.I)
            if m and int(m.group(1)) < 1000:
                need = w.exit_need(ex) if ex.kind == "key" else None
                if need and need[0] in (self.held_items() or ()):
                    continue                         # (the key's in hand)
                return True
        return False

    def _hp_unknown(self, route, here=None) -> bool:
        """Your real max HP not read yet ('st'), and a trap or room on the way could do the max HP the prompt has shown
        (regr2 #1: with the max-HP wall waiting for 'st', an L8 walked into the White Forest and hung up)."""
        st = self.st
        if getattr(st, "max_hp_read", True):
            return False
        w, hp = self.s.world, int(st.max_hp or 0)
        held = self.held_items() or set()
        for ex in route or ():
            d = 0
            if ex.kind == "trap":
                m = w.TRAP_RE.search(ex.etype or "")
                d = int(m.group(1)) if m else 0
            if ex.to in (getattr(w, "room_spells", None) or {}):
                d = max(d, w.room_damage(ex.to, held))
            if d and (hp <= 0 or d >= hp):
                return True
        if hp > 0 and any(dmg >= hp for _r, dmg in w.hurt_stretches(route, held)):
            return True                              # (0.8.223: a stretch of rooms that hurt, over the prompt's max HP)
        # (…or on the way back out: with max HP unread the way-out check counts a 600-damage trap as a way out — an L30
        #  warrior was stranded in the Large Cave, 17/3445: regr3 #1)
        if here and route and hp > 0:
            saved = w.char
            try:
                with w._plan_lock:
                    w.char = dict(saved or {}, max_hp=hp)
                    pk = w.pocket(tuple(route[-1].to), level=self.route_level(), have=set(self._door_have()), cap=3000)
            except Exception:
                pk = None
            finally:
                w.char = saved
            if pk is not None and tuple(here) not in pk:
                return True
        return False

    def _out_unknown(self, here, route) -> bool:
        """The way back out of where a Go to ends depends on a door your picklocks / strength decide, not read yet."""
        w = self.s.world
        try:
            with w._plan_lock:
                dest, have = tuple(route[-1].to), set(self._door_have())
                pk = w.pocket(dest, level=self.route_level(), have=have, cap=3000, unknown_walls=True)
                if pk is None or tuple(here) in pk:
                    return False
                # (only when the stats could change the answer: with those doors open there IS a way out — not a
                #  '1000' door or a room MME shows no way out of, which no 'st' helps; m12pyr L2)
                pk2 = w.pocket(dest, level=self.route_level(), have=have, cap=3000)
        except Exception:
            return False
        return pk2 is None or tuple(here) in pk2

    def _round_stuck(self, here, target, route, ask):
        """A way to target without the '1000' doors on `route`, planned as the keyed route plans (keys fetched, doors
        picked / bashed): the route, or None."""
        if not (self.cfg.auto_get_items or self.cfg.bash_key_doors) or isinstance(target, (set, frozenset)):
            return None
        w = self.s.world
        stuck = {id(ex) for ex in route if w.stuck_door(ex)}
        saved = getattr(w, "shut_doors", None)
        w.shut_doors = set(saved or ()) | stuck
        w.forget_routes()
        try:
            alt = self.keyed_route(here, target, ask)
        except Exception:
            alt = None
        finally:
            w.shut_doors = saved if saved is not None else set()
            w.forget_routes()
        if alt and not any(w.stuck_door(ex) for ex in alt):
            return alt
        return None

    def _goto_check(self, here, target, route, then, ask):
        """0.8.222 (Dan's picks from the 11-20 bug hunt), just before a Go to sets off. None = go; otherwise goto()'s
        answer: True = parked for 'st', False = not going (the reason logged and alerted)."""
        w = self.s.world
        self._goto_out = set()
        if not route or not here:
            return None
        dest = tuple(route[-1].to)
        rr = w.room(dest)
        where = f"{dest[0]}/{dest[1]} {rr.name}" if rr else f"{dest[0]}/{dest[1]}"
        # the only way is a '1000' door nobody at any level opens: say so now, don't try it 40 times (regress #3: a
        # level-30 warrior at 15/731 NE on the way to the Throne Room 15/416)
        prev = tuple(here)
        for ex in route:
            if w.stuck_door(ex):
                alt = self._round_stuck(here, target, route, ask)
                if alt:
                    # another way in that a key or your picklocks open (m1315 R5: the Dark-Elf Castle 8/560 — dive the
                    # moat, then 8/633 D with the moldy key or 251 picklocks — not the '1000' door at 8/559 S)
                    self._goto_alt = alt
                    return self._goto_check(here, target, alt, then, ask)
                r_ = w.room(prev)
                op = w.DOOR_OPENERS.get((tuple(ex.to), ex.dir))
                return self._no_go(target, (
                    f"Not going to {where}: the only way is the {DIR_WORDS.get(ex.dir, ex.dir).lower()} door in "
                    f"{r_.name if r_ else 'a room'} ({prev[0]}/{prev[1]}, {(ex.etype or '').strip()}) — nobody at any "
                    + (f"level can pick or bash it; the game opens it with {op}, which MudPilot doesn't do yet — "
                       f"open it by hand, then Go to again" if op else
                       "level can pick or bash it, and nothing MudPilot knows opens it")))
            prev = tuple(ex.to)
        # (after the '1000' check: no stats open those — M14B-4)
        # a locked door on the way and your picklocks / strength not read yet: 'st' first, a few seconds (walk_D2: one
        # walk went 135 rooms to the Brynhall door before finding it couldn't open it)
        if self.s.telnet.connected and ((self.door_power() is None and (self._door_power_unknown(route) or
                self._out_unknown(here, route))) or self._hp_unknown(route, here)) and self.ready("goto_st", 30):
            self._pending_abil = (target, then, ask, time.time())
            self.log("Go to: " + ("the way goes through a locked door and your picklocks / strength aren't known yet"
                                  if self.door_power() is None and not self._hp_unknown(route, here) else
                                  "a trap or room on the way could do your whole max HP, and that isn't read yet")
                     + " — checking 'st' first")
            self.status = "Checking your stats (st) before routing…"
            self.send("st")
            return True
        # once there, a way back out this character can use (walk_D2 D2-2: Stone Barracks 14/6217 and 14/6229, Manor
        # Stables, Ruined Manor — in by a plain exit, out only by one-sided doors nobody could open). Doors nobody can
        # open count as walls; ones beyond your picklocks / strength only when there's nobody to ask
        # (keys and items count as the Go to's own planning counts them — fetched when MudPilot fetches keys; this
        #  check is about doors nobody can open)
        held_ = set(self.held_items() or ())
        # (keys count as fetched, as Go to plans them — but not a rope / harness-style item an exit needs you to carry,
        #  unless you have it or the way in needs it: once inside you can't go and buy one — m12 #2, the low character
        #  in the Stone Tunnel / Webbed Cave pocket 1/1542, whose only way out is the rope exit)
        have = set(self._door_have()) - (set(w.carry_item_set()) - held_)
        # (0.8.223, Dan — m149 R2: a key you'd have to fetch from outside doesn't count for the way back out — a thief
        #  picked the jail cell's 101 door in and couldn't pick the 151 door out; the jail key drops outside)
        keys_ = self._key_items() - held_
        have -= keys_
        came, prev = set(), tuple(here)
        for ex in route:
            need = w.exit_need(ex) if ex.kind in ("key", "item") else None
            if need and not (ex.kind == "key" and need[0] not in held_ and w.door_beaten(ex, set()) is True):
                have.add(need[0])                    # (fetched for the way in: in hand for the way out too — not
                                                     #  when the walk picks / bashes that door instead)
            have |= set(ex.action_items() or ()) | set((getattr(ex, "req", None) or {}).get("items") or ())
            if ex.kind in ("door", "key") and (w.door_beaten(ex, have) is False or
                                                (tuple(ex.to), ex.dir) in w.OPENS_ANYWAY):
                # (0.8.223, regr222 #3: a key door's other side typed as a plain locked door — Fiery Lair, Molten River —
                #  opens with the same key: worlddb.door_beaten / key_twin, not this)
                # (the way in is already a door beyond the party — said yes to, or the walk tries it: back out through
                #  it is no worse. A door we CAN open in, with a different one out — Stone Barracks — isn't this)
                came.add((tuple(ex.to), prev))
            prev = tuple(ex.to)
        try:
            with w._plan_lock:
                pk = w.pocket(dest, level=self.route_level(), have=have, asked=ask is not None, cap=3000,
                              allow=frozenset(came))
                for _ in range(4):
                    # a key whose source is inside where you'd be (the statue key past the orb door): to be had there
                    if pk is None or tuple(here) in pk:
                        break
                    more = set()
                    for k in pk:
                        for ex in w.rooms[k].exits.values():
                            nd = w.exit_need(ex) if ex.kind == "key" and ex.to not in pk else None
                            if nd and nd[0] in keys_ and nd[0] not in have and self._key_sources(nd[0]) & pk:
                                more.add(nd[0])
                    if not more:
                        break
                    have |= more
                    pk = w.pocket(dest, level=self.route_level(), have=have, asked=ask is not None, cap=3000,
                                  allow=frozenset(came))
        except Exception as ex_:
            self.log(f"Go to: couldn't check the way back out ({ex_})")
            pk = None
        if pk is not None and tuple(here) not in pk:
            # already in a dead end yourself, and the target's in the same one: going there makes nothing worse (m1617
            # #2: a Go to 9 rooms on inside the Mausoleum, 17/2202 → 17/2205, was refused)
            try:
                with w._plan_lock:
                    pk_here = w.pocket(tuple(here), level=self.route_level(), have=have, asked=ask is not None,
                                       cap=3000, allow=frozenset(came))
            except Exception:
                pk_here = None
            if pk_here is not None and dest in pk_here:
                pk = None
        if pk is not None and tuple(here) not in pk:
            # only when it's the doors that shut it in (Dan's rule): with every door open, still no way back — MME shows
            # no way out (Ozrinom's 17/2243, the Tomb of the Pharaoh 12/2250), sea rooms round an island — that's the
            # map, not this character; it walks there as before (m12pyr #1, m1617 #5, M14B-2)
            try:
                with w._plan_lock:
                    pk_open = w.pocket(dest, level=self.route_level(), have=have, asked=ask is not None, cap=3000,
                                       allow=frozenset(came), doors_open=True)
            except Exception:
                pk_open = None
            if pk_open is not None and tuple(here) not in pk_open:
                pk = None
        if pk is not None and tuple(here) not in pk and self.cfg.auto_get_items and self.cfg.check_needed_items:
            # (0.8.223: the way back out needs a carried item a shop sells — a rope to climb out of Dark-Elf City's Large
            #  Hole, 8/460 U: buy it first, as the way in's items are, instead of refusing. Once inside you can't —
            #  m12 #2 — which is why it's fetched before setting off)
            buy = set()
            for k in pk:
                for ex in w.rooms[k].exits.values():
                    nd = w.exit_need(ex) if ex.kind == "item" and ex.to not in pk else None
                    if nd and not nd[1] and nd[0] not in held_ and \
                            (self.errands.source_for(nd[0]) or {}).get("kind") == "shop":
                        buy.add(nd[0])
            if buy:
                try:
                    with w._plan_lock:
                        pk2 = w.pocket(dest, level=self.route_level(), have=have | buy, asked=ask is not None,
                                       cap=3000, allow=frozenset(came))
                except Exception:
                    pk2 = set()
                if pk2 is None or tuple(here) in pk2:
                    self._goto_out = buy
                    self.log(f"Go to: the way back out of {where} needs {', '.join(w.item_name(n) for n in sorted(buy))}"
                             f" — getting it first")
                    return None
        if pk is not None and tuple(here) not in pk:
            outs, hurts = [], []
            for k in sorted(pk):
                for ex in w.rooms[k].exits.values():
                    if ex.to not in pk and ex.to in w.rooms and ex.kind in ("door", "key"):
                        outs.append(f"{DIR_WORDS.get(ex.dir, ex.dir).lower()} of {k[0]}/{k[1]} "
                                    f"({(ex.etype or 'a door').strip()})")
                    elif ex.to not in pk and ex.to in w.rooms and ex.kind == "item":
                        need = w.exit_need(ex)
                        if need and not need[1]:
                            hurts.append(f"{DIR_WORDS.get(ex.dir, ex.dir).lower()} of {k[0]}/{k[1]} (needs "
                                         f"{w.item_name(need[0])}, which you don't carry)")
                    elif ex.to not in pk and ex.to in w.rooms and (getattr(ex, "req", None) or {}).get("items"):
                        its = [w.item_name(int(i)) for i in ex.req["items"] if int(i) not in have]
                        if its:
                            hurts.append(f"'{ex.text_command or ex.dir}' in {k[0]}/{k[1]} (needs {', '.join(its)}, "
                                         f"which you don't carry)")
                    elif ex.to not in pk and ex.to in w.rooms:
                        hw = w.hp_wall(ex, have)
                        if hw:
                            hurts.append(f"{DIR_WORDS.get(ex.dir, ex.dir).lower()} of {k[0]}/{k[1]} (up to {hw} "
                                         f"damage)")
            msg = (f"Not going to {where}: once there, there's no way back out this character can use"
                   + (" — the ways out are doors nobody in the party can open: " + "; ".join(outs[:3]) if outs else
                      "") + (" (nobody's here to ask about trying them)" if outs and ask is None else "")
                   + ((" — " if not outs else "; and ") + "the other ways out: " + "; ".join(hurts[:3])
                      if hurts else ""))
            return self._no_go(target, msg)
        return None

    def _key_items(self) -> set:
        """Every item a key door ('Key: N') needs."""
        w = self.s.world
        c = w.__dict__.get("_key_items_c")
        if c is None:
            c = set()
            for r in w.rooms.values():
                for ex in r.exits.values():
                    if ex.kind == "key":
                        nd = w.exit_need(ex)
                        if nd:
                            c.add(nd[0])
            w._key_items_c = c = frozenset(c)
        return set(c)

    def _key_sources(self, num) -> set:
        """Rooms an item can be had in (MME 'obtained': its shops, the monsters that drop it, where it lies)."""
        w = self.s.world
        g = (w.gear.get(num) if getattr(w, "gear", None) else None) or {}
        out = set()
        for m in re.finditer(r"(Shop|Monster) #(\d+)", g.get("obtained", "") or ""):
            if m.group(1) == "Shop":
                out |= {tuple(r) for r in (w.shops.get(int(m.group(2)), {}).get("rooms") or [])}
            else:
                out |= {tuple(r) for r in ((w.monsters.get(int(m.group(2))) or {}).get("spawn_rooms") or [])}
        for rm, items in (getattr(w, "room_items", None) or {}).items():
            if num in (items or ()):
                out.add(tuple(rm))
        return out

    def _bank_way(self, here, target, then, ask) -> bool:
        """0.8.222 (Dan, 11-20 bug hunt): the only thing in the way is a toll or a fare your cash won't cover —
        MudPilot doesn't know your bank balance, so plan as if the bank has it and go there first, the way bank runs
        for items work (an empty account: the withdraw comes back short and the Go to says no route). True = off."""
        cfg, st = self.cfg, self.st
        tr = getattr(self.s, "trips", None)
        if tr is None or tr.trip or not cfg.toll_bank_run or st.wealth is None or isinstance(target, (set, frozenset)):
            return False
        w = self.s.world
        # (0.8.224 speed — w1617: the bare search below still cost ~2.5 s on every no-route Go to. No toll or fare on
        #  the whole map over the cash you carry: money can't be what's in the way)
        tolls = w.__dict__.get("_toll_exits")
        if tolls is None:
            tolls = []
            for r_ in w.rooms.values():
                for ex in r_.exits.values():
                    m = w.TOLL_RE.search(ex.etype or "") if ex.kind == "toll" else None
                    pr = int(m.group(1)) if m else int((getattr(ex, "req", None) or {}).get("price") or 0)
                    if pr:
                        tolls.append((pr, tuple(ex.to)))
            w._toll_exits = tolls
        dear = {to for pr, to in tolls if pr > (st.wealth or 0)}
        if not dear:
            return False
        try:
            if not (dear & w.leads_to(target)):
                return False                     # (none of them leads on towards the target at all)
        except Exception:
            pass
        # (0.8.223 speed, regr2 #5 / regr3 #3: one bare search first — every item, money no object. No way even so, or
        #  a way with no toll or fare on it: the money isn't what's in the way, so skip the whole plan below)
        try:
            saved = w.char
            with w._plan_lock:
                try:
                    w.char = dict(saved or {}, wealth=10 ** 12)
                    bare = w.route(here, target, level=self.route_level(), have=self.plan_items(target))
                finally:
                    w.char = saved
            if bare is None or not any(ex.kind == "toll" or (getattr(ex, "req", None) or {}).get("price")
                                       for ex in bare):
                return False
        except Exception:
            pass
        self._bank_plan = True
        try:
            route = self.plan_route(here, target, ask)
        except Exception:
            route = None
        finally:
            self._bank_plan = False
            try:
                self.s.route_char()
            except Exception:
                pass
        if not route:
            return False
        r = w.room(target)
        mp = path_from_route(w, here, route, name=f"Go to {target[0]}/{target[1]} {r.name}")
        need = self.path_toll(mp)
        if need <= (st.wealth or 0):
            return False                             # (it wasn't the money in the way)
        self._goto_alt = None
        chk = self._goto_check(here, target, route, then, ask)
        if chk is not None:
            # (the same checks as any Go to before the bank run, not after it — flags2 #2: withdrew 2M for the
            #  Blackwater fare, then the Go to was refused anyway)
            self._bank_no = chk is False
            return True
        if not tr.withdraw_for(mp, False, need - (st.wealth or 0), why="the tolls / fares"):
            return False
        t = tr.trip
        if t is not None:
            t["goto"], t["then"] = tuple(target), then
        return True

    CALL_OFF_SECS = 120

    def drop_parked(self):
        """Forget every Go to that's waiting to go — on 'i', 'abil', 'who', the room — and make one still being worked
        out on the planner's thread never start (Fable review, 2026-11-11: Stop during 'Calculating route…' or
        'Checking your inventory…' and it walked off seconds later)."""
        self._pending_goto = self._pending_abil = None
        self._goto_retry = self._await_inv = self._goto_after_who = None
        self._stop_seq = getattr(self, "_stop_seq", 0) + 1

    def parked(self) -> bool:
        """A Go to waiting to go on (an answer to 'i', 'abil' or 'who', the room, or the planner's thread)."""
        return bool(getattr(self, "_planning", False) or any(
            getattr(self, n, None) for n in ("_pending_goto", "_pending_abil", "_goto_retry", "_await_inv",
                                             "_goto_after_who")))

    def _stopped_since(self, seq0) -> bool:
        if getattr(self, "_stop_seq", 0) == seq0:
            return False
        self.log("Go to: stopped while it was being worked out — not going")
        return True

    def call_off_goto(self, target, why: str):
        """A Go to nobody needs any more (a party member's @comeback, and they're back): stop it if it's walking,
        and make sure one still being worked out on the planner's thread — or waiting on 'i' / 'abil' — never
        starts (Dan, 2026-11-11: Revolution's @comeback was called off while it was still planning; flung out of the
        Dao Lord's room, it then searched the whole map twice and popped up 'No walkable route')."""
        target = tuple(target)
        self._called_off = (target, time.time(), why)
        for attr in ("_pending_goto", "_pending_abil"):
            p = getattr(self, attr, None)
            if p and not isinstance(p[0], (set, frozenset)) and tuple(p[0]) == target:
                setattr(self, attr, None)
        gr = getattr(self, "_goto_retry", None)
        if gr and tuple(gr["args"][0]) == target:
            self._goto_retry = None
        gw = getattr(self, "_goto_after_who", None)
        if gw and tuple(gw[0]) == target:
            self._goto_after_who = None
        aw = getattr(self, "_await_inv", None)
        if aw and aw[0] is not None and aw[0].title.startswith("Go to ") and                 getattr(self, "_goto_target", None) == target:
            self._await_inv = None                   # waiting on 'i' before setting off: it never sets off
        if self.walking and self.path and self.path.title.startswith("Go to ") and                 getattr(self, "_goto_target", None) == target:
            self.stop(f"Stopped: {why}")

    def called_off(self, target) -> bool:
        co = getattr(self, "_called_off", None)
        if not co or isinstance(target, (set, frozenset)) or tuple(target) != co[0]:
            return False
        if time.time() - co[1] > self.CALL_OFF_SECS:
            self._called_off = None
            return False
        if self.ready(f"calledoff{co[0]}", 30):
            self.log(f"Go to {co[0][0]}/{co[0][1]} called off — {co[2]}")
        self.status = "Idle"
        return True

    def stop(self, why="Stopped"):
        self._expect_dest = None                     # (a step in flight when stopped: not 'placed by the path' later)
        self._opening_dir = None
        lc = getattr(self.s, "lair_camp", None)
        if lc is not None:
            lc.note_stop(why)          # your Stop, a hang-up, Hands off, a death, Disconnect end Camp lairs (0.8.201)
        if getattr(self, "_guard_hunt", False):
            self._guard_hunt, self.hunt_target = False, None     # (the guard of a portal on the walk we stop)
        if why.startswith("Stopped by you") and not self.walking and (self.st.resting or self.cfg.auto_rest):
            # nothing walking to stop — it's the resting you want to stop (Buddy, 2026-10-29: Stop ×4 and it went on
            # 'Resting to full'): no auto rest for 2 minutes, so you can take over
            self._no_rest_until = time.time() + 120
            self._stop_norest = self._no_rest_until   # (a walk you start next ends it: start_path — m1315 R4)
            self._idle_rest = False
            why = "Stopped by you — not resting for 2 minutes"
        self._regoto_at = 0                          # nothing queued from this trip restarts it later
        if why.startswith("Stopped by") and hasattr(self, "peruse"):
            self.peruse.stop()
        self.drop_parked()
        if hasattr(self, "x"):
            self.x.stop_roam()
            if why.startswith("Stopped by you"):
                self.x.stop_pvp()
        if why.startswith("Stopped by you"):
            # Dan, 2026-10-30: Buddy's @summon, then Stop — and Revolution set off for Buddy again the same second
            # (the rejoin), and again a minute later. Your Stop ends the chase: comeback, rejoin, all of it
            self._user_stop_at = time.time()
            cb = getattr(self.s, "comeback", None)
            chasing = [n for n in ([cb.fetch["name"]] if cb and cb.fetch else []) +
                       list(getattr(cb, "missing", {}) or {}) +
                       [((getattr(self.s, "_rejoin", None) or {}).get("leader"))] if n]
            if cb is not None:
                cb.fetch, cb.missing = None, {}
            self.s._rejoin = None
            tr_ = getattr(self.s, "trips", None)
            if tr_ is not None and tr_.trip:
                # (0.8.201, realm walk: Stop never ended a bank/shop trip — at the bank, or on its way, it finished
                #  by itself and its walk back hijacked the next Go to)
                tr_.reset("stopped")
                self.log("Trip: cancelled (you stopped it)")
            if chasing:
                self.log(f"Not going after {', '.join(dict.fromkeys(chasing))} any more (you stopped it)")
        if self.walking and self.path and not self.path.title.startswith("Go to "):
            self.last_path, self.last_loop = self.path, self.loop
        if self.walking and self.path:
            # what Rego picks up again: a Go to (and the loop after it) or the loop/path itself
            self.resume = {"path": self.path, "loop": self.loop, "after": self.after_goto,
                           "target": getattr(self, "_goto_target", None) if self.path.title.startswith("Go to ") else None}
        er = getattr(self.errands, "active", None) if hasattr(self, "errands") else None
        if er and er.get("then") and er["then"][0] is not None:
            # stopped on the way to fetch a key: Rego goes to where we were really going (it fetches the key again
            # if it's still needed). PVE, 2026-10-30: Stop/Rego on the golden lion key detour resumed only
            # 'Go to 12/2005', got the key and stood there — the Pharoah (12/2085) was forgotten
            mp_, lp_ = er["then"]
            self.resume = {"path": mp_, "loop": lp_, "after": er.get("after"), "target": er.get("target")}
        self.walking = False
        self.path = None
        self.detour = None
        self.after_goto = None
        self._boss_hold = None
        if hasattr(self, "x"):
            self.x.waiting_on = []                   # nothing walking, nothing to wait for
            self.x._wait_since = 0.0
        if hasattr(self, "errands"):
            self.errands.cancel()
        if why.startswith(("Stopped:", "Not walking")) and "died" not in why:
            self.s.notify.send("stop", why)
        self.status = why
        self.set_mode("manual")
        self.log(why)

    def give_up(self, why, mp=None, after=None, target=None):
        """A walk that can't have what it needs (the party's rafts didn't get bought, no shop sells it, no cash)
        doesn't go: say why, and — a boss hunt, or a Go to with a loop to come back to — back to the loop instead
        of standing there. Nothing to go back to: stop with the reason (Dan, 2026-11-09: 'if whatever needs to
        happen doesn't… it just not go and state why'; Evolution walked to the Ancient Ruin with no rafts for the
        party, then stood after the crimson mist). True = went back to a loop."""
        er = getattr(self, "errands", None)
        if er is not None:
            er.cancel()
        now = time.time()
        again = now - getattr(self, "_gave_up_at", 0) < 90      # going back failed the same way: stop there
        self._gave_up_at = now
        bh = getattr(self.s, "bosshunt", None)
        if bh is not None and bh.active and not again:
            self.log(f"{why} — giving up the boss hunt")
            self.s.notify.send("stop", why)
            self.s.on_alert(why)
            bh._done("not going — the way needs what we couldn't get")
            return True
        back = after if isinstance(after, MPath) and not after.title.startswith("Go to ") else None
        if back is not None and (back is mp or again or
                                 (mp is not None and not str(getattr(mp, "title", "")).startswith("Go to "))):
            back = None                       # (the loop itself can't start: nothing to go back to)
        here = self.st.room
        if back is not None and target and not isinstance(target, (set, frozenset)) and back.steps and \
                back.steps[0].room == tuple(target) and not any(x.room == here for x in back.steps):
            back = None                       # the loop is where this Go to was going: no other way back to it
        if back is None:
            self.stop(why)
            self.no_route_msg = why                  # (0.8.225, walks: @goto said "walking to…", @status nothing)
            self.s.on_alert(why)
            return False
        self.stop(f"{why} — back to {back.title} instead")
        self.s.on_alert(why)
        if here and back.resolved and back.steps and back.steps[0].room and not any(x.room == here for x in back.steps):
            # (worked out off the window's thread — HUNT_1123 #24; no way to its start: start it from here, as before)
            self.goto_bg(back.steps[0].room, then=back, done=lambda ok: ok or self.start_path(back, loop=True))
            return True
        self.start_path(back, loop=True)
        return True

    def idle_text(self) -> str:
        """'Idle', or why we're parked and that Rego carries on (Dan, 2026-10-30: Revolution sat 'Idle' a long
        while, stopped by a follower's @stop, with nothing saying so)."""
        r = getattr(self, "resume", None)
        fl = getattr(getattr(self, "x", None), "_following", None)
        if fl:
            # following someone: their walk is ours, and Rego won't carry on a trip of our own (rego()). Dan,
            # 2026-11-16: Revolution PVE, back in Evolution's party, still said "Stopped (before the restart)" an
            # hour later — and the health watch took it for a stuck character
            return f"Following {fl}"
        if not r:
            return "Idle"
        what = (f"to {r['target'][0]}/{r['target'][1]}" if r.get("target") else
                f"'{r['path'].title}'" if r.get("path") is not None else "")
        note = getattr(self, "stop_note", "") or "stopped"
        return f"Stopped ({note}) — Rego carries on {what}".strip()

    def rego(self) -> bool:
        """Carry on with whatever was running when you stopped (MegaMUD's Rego)."""
        if self.dead_blocked("carrying on (Rego)"):
            return False
        r = getattr(self, "resume", None)
        if not r:
            return False
        leader = getattr(self.x, "_following", None) if hasattr(self, "x") else None
        if leader:
            # following someone: they walk, we follow — a Rego (ours or their @rego) mustn't send us off on our
            # own old trip
            self.resume = None
            self.log(f"Rego: following {leader} — not carrying on a trip of my own")
            return False
        if not self.st.room and not getattr(self, "_rego_retry", None):
            # just back in, the room not known yet (Miserable PVE, 2026-11-06: 'Can't route: current room unknown',
            # the room confirmed 2 s later, the Go to never carried on): look, and Rego again once we know
            self._rego_retry = time.time()
            self.log("Rego: finding out where we are first")
            self.send("")
            return True
        self._rego_retry = None
        self.resume = None
        self.stop_note = ""
        if r.get("target"):
            self.log("Rego: carrying on to where we were going")
            ok = bool(self.goto(r["target"], then=r.get("after")))
            if not ok and not self.walking:
                self.resume = r                      # it didn't go (still planning, no route yet): Rego can try again
            return ok
        mp = r["path"]
        self.log(f"Rego: {mp.title}")
        here = self.st.room
        if here and mp.resolved and mp.steps and mp.steps[0].room and not any(x.room == here for x in mp.steps):
            ok = bool(self.goto(mp.steps[0].room, then=mp))
            if not ok and not self.walking:
                self.resume = r
            return ok
        self.start_path(mp, loop=r.get("loop"))
        return True

    # ---------------------------------------------------------- per tick
    def _account(self, now):
        """Where the time goes (fighting / walking / resting / waiting / idle) — logged every 10 min,
        plus how long we sit in a room before taking the next step."""
        st = self.st
        last = getattr(self, "_acct_t", None)
        self._acct_t = now
        if last is None or now - last > 5:
            return
        if not hasattr(self, "acct"):
            self.acct, self.step_gaps, self._acct_since = {}, [], now
        if st.in_combat:
            b = "fighting"
        elif st.resting or st.meditating:
            b = "resting"
        elif self.walking and st.pending:
            b = "moving"
        elif self.walking and (self.s.remote.holding() or self.x.waiting_on or
                               str(self.status).startswith(("Waiting", "Holding"))):
            b = "waiting on party"
        elif self.walking:
            b = "in a room, between steps"
        else:
            b = "not walking"
        self.acct[b] = self.acct.get(b, 0) + (now - last)
        if now - self._acct_since >= 600:
            tot = sum(self.acct.values()) or 1
            parts = ", ".join(f"{k} {v / tot:.0%}" for k, v in sorted(self.acct.items(), key=lambda kv: -kv[1]))
            gaps = sorted(self.step_gaps)
            gap = f" · room→next step median {gaps[len(gaps) // 2]:.1f}s" if gaps else ""
            self.log(f"Last 10 min: {parts}{gap}")
            self.acct_summary = f"{parts}{gap}"
            self.acct, self.step_gaps, self._acct_since = {}, [], now

    def tick(self):
        # (a Go to being worked out on another thread — bgplan.py — doesn't stop the rest: fighting, healing,
        # running still happen; only walking and new Go tos wait for it. Dan: locking up like that in PvP is
        # dangerous)
        st, cfg = self.st, self.cfg
        rr = getattr(self.s, "routerec", None)
        if rr is not None:
            rr.poll()                          # Record Path / Record Loop: a room change is a step
        if not self.s.telnet.connected or self.paused:
            return
        now = time.time()
        if getattr(self, "_wpn_swap_back", None):
            self._weapon_swap_back()
        tr = getattr(self, "_tp_resend", None)
        if tr and now >= tr[1]:
            self._tp_resend = None
            self.log(f"Telepath wasn't delivered — sending it again: {tr[0][:60]}")
            self.s.send(tr[0], from_bot=True)
        rt = getattr(self, "_rego_retry", None)
        if rt and self.walking:
            self._rego_retry = None             # you (or something) started a walk meanwhile: that one wins
        elif rt and (st.room or now - rt > 30):
            if st.room and getattr(self, "resume", None):
                self.rego()                     # we know where we are now: carry on
            else:
                self._rego_retry = None
                if self.resume:
                    self.log("Rego: still not sure where we are — press Enter (look), then Rego")
        gr = getattr(self, "_goto_retry", None)
        if gr and self.walking:
            self._goto_retry = None             # a walk started meanwhile: that one wins
        elif gr and (st.room or now - gr["t"] > 15):
            self._goto_retry = None
            tg, th, ak = gr["args"]
            self.replan(tg, th, ak, retry=False, looked=True)   # room known now: go, worked out off the window's
            # thread like the one you started (still unknown after 15 s: it says so)
        self._account(now)
        self._info_flush()
        self._late_flush()
        if getattr(self, "_al_pending", None):
            self._al_pending_tick(now)
        if not self.walking and getattr(self, "_bring", None) and self._bring.get("typed"):
            self._waiting_for_party_through(now)
        da = getattr(self, "_death_hangup_at", 0)
        if da and now >= da:
            self._death_hangup_at = 0
            self.s.safety.hangup("died — hanging up as set (Settings → Health)")
            return
        if st.dead:
            if self.walking:
                self.stop("Stopped: character died")
            return
        if st.room:
            prev = getattr(self, "_last_room", None)
            if prev and prev != st.room and getattr(self.s.world, "segments", None):
                from .board_fixes import note_move
                note_move(self.s.world, prev, st.room)   # how far through a fixed route (the level 4 maze) we are
            self._last_room = st.room
            if st.view and st.view.monsters:
                self._last_mobs = [sh for sh, _r in st.view.monsters][:4]
        self.manual.tick()                     # (ends a hand-fought fight you've walked out of / stopped on)
        self._lair_learn(now)
        self._take_abil_answer(now)            # an 'abil' answer counts wherever you stand (signs, monsters…)
        pa = getattr(self, "_pending_abil", None)
        rd_ = getattr(self, "_abil_read", None)
        abil_out = bool(rd_ and rd_[0] == "sent" and rd_[1] >= pa[3] - 1 and now - pa[3] < 10) if pa else False
        if pa and now - pa[3] > 3 and not abil_out and not self._st_unanswered(pa, now):
            # (waits for the 'abil' answer to be taken in: re-planning at 3 s used the old flags, then the 5-minute
            # once-per-place limit gave up - Evolution, NeutralQuest 4 -> 5 at the Grey Lord, 2026-11-05)
            self._pending_abil = None
            self.replan(pa[0], then=pa[1], ask=pa[2])
            return
        rg = getattr(self, "_regoto_at", 0)
        if rg and now >= rg and not st.in_combat:
            self._regoto_at = 0
            tgt = getattr(self, "_goto_target", None)
            if tgt:
                self.goto_bg(tgt, then=self.after_goto)
                return
        pg = getattr(self, "_pending_goto", None)
        if pg:
            target, then, ask, seq, at = pg
            if st.inv_seq > seq or now - at > 6:
                self._pending_goto = None
                self.replan(target, then=then, ask=ask, retry=True)   # off the window's thread, like the first try
            return
        aw = getattr(self, "_await_inv", None)
        if aw:
            mp_, loop_, seq_, at_ = aw
            if st.inv_seq > seq_:
                self._await_inv = None
                self.start_path(mp_, loop_)          # inventory's in: check again
            elif now - at_ > 8 and st.inv_seq:
                self._await_inv = None
                st.inv_at = now                      # (the re-check before a fetch: go with the list we have)
                self.start_path(mp_, loop_)
            elif now - at_ > 8:
                self._await_inv = None
                self.log("Couldn't read your inventory — walking without the key/item check")
                self.start_path(mp_, loop_, checked=True)
            return
        # detect being hit (HP dropped while monsters are here)
        if self._last_hp is not None and st.hp < self._last_hp and st.view and st.view.monsters:
            self._attacked_at = now
        self._last_hp = st.hp
        if self.regen.feed(st.resting, st.hp, st.max_hp, st.ma, st.max_ma,
                           healed_recently=now - self._cool.get("heal", 0) < 6, now=now) and st.resting:
            self._ticks_this_rest = getattr(self, "_ticks_this_rest", 0) + 1

        # keep the room display fresh
        if st.need_refresh:
            if self.ready("refresh_evt", 1.5):
                st.need_refresh = False
                self.send("")
                self._refresh_at = now
            return                             # never act on a stale room (e.g. cast at a mob that just died)
        ra = getattr(self, "_refresh_at", 0)
        if ra and now - ra < 2.5 and (not st.view or (st.view.t or 0) < ra):
            return                             # (0.8.224, real logs — 1,077 rest starts undone 2 s later: the zombie's
                                               #  parts show up in the room answer; wait for it, 2.5 s at most)
        if not st.room and now - getattr(st, "dark_at", 0) < 20 and self.maybe_locate():
            return                             # Buddy, 2026-10-28: pressed Enter in a dark room for minutes — 'pro'
        if (now - st.view.t > cfg.refresh_secs if st.view else True) and not self.hurrying():
            if self.ready("refresh", cfg.refresh_secs) and not st.pending:
                self.send("")
                return

        if self.maybe_locate():
            return
        targets_ = self.attackable()
        if st.in_combat and not targets_ and st.view and st.view.monsters and cfg.break_cmd and \
                not getattr(self.x, "pvp_target", None) and all(self._unkillable(r) for _s, r in st.view.monsters) \
                and self.ready("break_nontarget", 4):
            # pyramid top, 2026-10-28: the stone sphinx (0 exp, 9999 HP) holds combat after the area spell — the
            # game repeated esto at it every round (3 casts, 210 mana) with nothing left to kill. Only for what can't
            # be killed: Dan, 2026-10-30 — it broke off the floating key it was there to kill ('very few reasons
            # except sneak and hide to break combat')
            self.log(f"Only {', '.join(sh for sh, _r in st.view.monsters)} left — nothing to kill; breaking combat")
            self.send(cfg.break_cmd)
        mobs = self.manual.prefer(self._eco_filter(self.x.leader_target(self.x.party_limits(targets_))))
        in_range = cfg.min_mobs <= len(mobs) <= max(self.x.max_mobs(), cfg.min_mobs)
        being_hit = (now - self._attacked_at) < 6 or st.in_combat
        if st.room != getattr(self, "_room_at", (None, 0))[0]:
            self._room_at = (st.room, now)
        self._being_hit = being_hit
        hunted = bool(self.hunt_target) and any(self._is_hunted(r) for _s, r in mobs)

        # 0b. down at 0 HP or less (mortally wounded): MajorMUD refuses every command until a heal or regen brings you
        # back over 0 — no flee, no heal casts, nothing sent; just wait (0.8.202, Wayfarer: a flee every 3 s at -5 HP
        # with running off, heals spammed)
        if st.max_hp and st.hp is not None and st.hp <= 0:
            if self.status != "Down (HP 0 or less) — waiting":
                self.log(f"HP {st.hp}/{st.max_hp} — mortally wounded; the game won't take commands, waiting")
            self.status = "Down (HP 0 or less) — waiting"
            return
        if self._swap_tick(mobs, in_range):
            return
        self.x.stat_block_tick()
        # 0. stunned: anything sent now is wasted (and a spell or flee queued now would go off late)
        if self.x.stunned():
            if self.status != "Stunned — waiting it out":
                self.log("Stunned — holding everything until it wears off")
            self.status = "Stunned — waiting it out"
            self._was_stunned = True
            return
        if getattr(self, "_was_stunned", False):
            self._was_stunned = False
            for k in ("cast", "attack", "heal", "run", "pbless"):
                self._cool[k] = 0               # fresh start: act on what's happening now
        self._stale_combat(now)
        # 1. run
        if cfg.auto_combat and st.max_hp and cfg.run_pct and st.hp_pct() < cfg.run_pct and (mobs or st.in_combat):
            if self.ready("run", 3):
                self.flee()
            return
        # 1b. keep running if Run distance > 1
        if self._run_left and not st.pending and st.room and st.room != self._run_from:
            self._run_left -= 1
            self._run_from = st.room
            if self.ready("run", 1):
                self.flee(onward=True)
            return
        # 1b. PvP: spells / attacks at a player
        if self.x.pvp_tick():
            return
        # 2. heal (yourself or the party member who needs it most) and cures
        if cfg.cures_first and self.x.cure_tick():
            return
        if cfg.auto_heal and self.heal_tick():
            return
        if self.x.cure_tick():
            return
        if getattr(self.x, "pvp_hold", 0) >= now:
            return      # (0.8.201, bug hunt: between PvP rounds — the heals / cures above went first, nothing else)
        if self.x.full_tick():
            return
        self.x.leader_watch()
        # 2b. party check (feeds the Party window) and party rank
        if self.party_tick():
            return
        if self.x.rank_tick():
            return
        # 2b'. you're fighting it by hand (an attack / targeted spell you typed): nothing offensive from us — the
        # run / hang-up / heals above still happen (Dan, 2026-10-29: his dtch and our fork took turns)
        if self.manual.tick():
            self.status = self.manual.label()
            return
        if self.redress.tick():
            return                             # your gear back on after recovering your corpse
        # 2c. attack on room entry: walked into hostile monsters — the attack goes out now, ahead of
        # blesses and the out-of-combat cast cooldown (healing, cures and rank still come first)
        if self._entry_attack(mobs, in_range, being_hit):
            return
        # 2a. learn the spell list (once per session), before the first fight
        if cfg.auto_spells and not st.in_combat and self.maybe_read_spells():
            return
        if not mobs and not (st.view and st.view.items) and self._read_quest_flags():
            return
        if cfg.auto_regen_gear and (not st.carrying or getattr(self, "_inv_stale", False)) and not mobs and \
                not st.in_combat and not st.pending and st.last_prompt and \
                time.time() - self.s._connected_at > 8 and self.ready("regen_inv", 20):
            # auto regen gear plans from the inventory: read it before the first rest, and again after any gear
            # change (post-rest swaps, you typing 'eq'), or it plans from what you had on before
            self._inv_asked = time.time()
            self.send("i")
            return
        if cfg.auto_spells and st.known_spells is None and time.time() - self._spells_asked_at < 4:
            return      # wait for the list to come back
        # 2b. bless / buff upkeep
        if cfg.auto_bless:
            self.bless_msgs_tick()
        if cfg.auto_bless and self.buffs_tick(mobs, in_range):
            return
        if cfg.auto_bless and self.x.party_bless_tick():
            return
        # 2d. the room task's item on the floor (the golden lion key): grab it before fighting anything else here.
        # PVE, 2026-10-28: killed the floating key, then cast at an undead priest — the key was gone by the time
        # it looked again, and it spent minutes stepping out and back for another
        task = (getattr(self.s.world, "room_tasks", None) or {}).get(st.room)
        if task and st.view and task["item"] not in (self.held_items() or set()) and \
                task["item_name"] in " ".join(n for _q, n in st.view.items).lower() and self.ready("task_get", 0.8):
            self.status = f"Grabbing the {task['item_name']}"
            self.send(task["get"])
            return
        # 3. fight (an event's boss is always fought, whatever the mob range or Combat switch)
        if hunted:
            mobs.sort(key=lambda m: not self._is_hunted(m[1]))
            self.fight(mobs)
            return
        held_fight = bool(not cfg.auto_combat and mobs and being_hit and self._held_now())
        if held_fight and self.ready("held_fight_said", 30):
            # 0.8.224 (Dan): held / engulfed with Combat off — you can't walk away, so fight back
            self.log("Held and being hit with Combat off — fighting back")
        if (cfg.auto_combat or held_fight) and mobs and not self._step_flag("NOATTACK"):
            if in_range or (being_hit and cfg.defend_out_of_range) or held_fight:
                if self.attack_last_hold(mobs, being_hit):
                    return
                if self.fight(mobs) is not False:
                    return
                # (0.8.201, bug hunt: False = only monsters the weapon can't hurt here — carry on / walk on)
        if st.in_combat and not ((not cfg.auto_combat or self._rushing()) and self.walking and self.path):
            self.status = "In combat"
            return
        if st.in_combat and self._rushing() and self.ready("rush_said", 20):
            self.log("Running for the gate before it shuts — not stopping to fight")
        if st.in_combat and self.ready("combat_off_said", 20):
            # Combat switched off mid-fight while walking: don't stand there finishing it — walk on out
            self.log("Combat is off — walking on out of the fight")
        if not mobs:
            self._pre_done = False
            self._danger_open_done = False
            self._risky = None
        # 4. loot (Cash and Get are separate switches, as in MegaMUD)
        if (cfg.auto_loot or cfg.loot_cash or self.errands.active or cfg.recover_corpse) and self.loot():
            return
        if self.x.stash_tick():
            return
        if self.stash.tick():
            return                                   # hiding / picking up the rafts: the walk waits
        if self.x.drop_unwanted():
            return
        # 4b. light / hide / search
        if self.lights.tick():
            return
        if self.misc_tick():
            return
        # 5. rest
        if cfg.auto_rest and self.should_rest(mobs, in_range):
            return
        # 6. errands: off to get a key/item a path needs (a room task first: the floating key's out-and-back)
        if not self.walking and self._room_task(time.time()):
            return
        if not self.walking and self.errands.tick():
            return
        if not self.walking and self.peruse.tick():
            return
        if not self.walking and self.partyflags.tick():
            return
        # 6b. walk (leaders wait for hurt party members; blind = stay put)
        if self.walking:
            if self.x.wait_for_party() or (self.x.blocked_by_ailment() and not st.in_combat):
                self.idle_regen(mobs)
                return
            kt = self.x.ailments.get("knocked")
            if kt and time.time() - kt < 30:
                self.status = "Knocked flat — waiting to get up"
                return                                # can't walk on your back (the party's been told @held)
            self.walk(mobs, in_range)
        elif self.x.roam_tick():
            return
        elif self.x.leader_gone and not mobs:
            self.status = f"Waiting — {self.x.leader_gone}"
            self.idle_regen(mobs)
        elif not mobs and not st.in_combat and self.s.partysync.peer_resting():
            pr = self.s.partysync.peer_resting()
            self.status = f"{pr} is resting — topping up too"
            self.idle_regen(mobs, why=f"resting with {pr} (party sync)")
        elif not st.resting and mobs and not cfg.auto_combat:
            # Dan, 2026-11-17: Buddy's Combat button was switched off at a reconnect and he followed the party for
            # three hours without swinging — nothing said so
            self.status = f"Combat is off — not attacking {len(mobs)} mob(s)"
            if self.ready("combat_off_note", 600):
                self.log("Combat is off — not attacking the monsters here (Combat button, or @auto-combat on)")
        elif not st.resting:
            self.status = self.idle_text() if not mobs else f"{len(mobs)} mob(s) here — outside {cfg.min_mobs}-{cfg.max_mobs} range" \
                if cfg.auto_combat and not in_range else self.status

    # ---------------------------------------------------------- combat
    @staticmethod
    def _unkillable(rec) -> bool:
        """0 exp and 9999 HP — the pyramid's stone sphinx: fighting it is just spending mana."""
        return bool(rec) and (rec.get("exp") or 0) <= 0 and (rec.get("hp") or 0) >= 9999

    def _can_hit_fallback(self, mobs, rec, avail):
        """Your spells can't hurt this one (a magical monster — the prismatic dragon is 'Magical 2': only level 20+
        single-target spells or any area spell): anything else you know that can (Dan, 2026-10-30: Evolution had
        blaze and never cast it). None = nothing can."""
        sb, cfg, st = self.s.spellbook, self.cfg, self.st
        from .spells import spell_kind
        usual = self.s.spell_candidates() if cfg.auto_spells else             [sb.find(x) for x in (cfg.attack_spells or []) if sb.find(x)]
        usual = [sp for sp in usual if sp.get("Number") not in sb.refused and spell_kind(sp) in (None, "single")]
        if any(not sb.useless(rec, sp) for sp in usual):
            # one of your single-target spells CAN hurt it (switched on or not) — the usual choice came up empty for
            # another reason (the mana reserve, Cast off, resisted). That's melee, not an earthquake on one nightshade at 2 mana (Dan,
            # 2026-11-11: Evolution under his 80 reserve logged 'nightshade is magical' and quaked singles)
            return None
        # nothing usual can touch it: an area spell may go out even under the 'at least N' count (it's the only way to
        # hurt a magical one) — still only with Nuke on
        cands = [sp for sp in self._my_area_only(self.s.spell_candidates()) if not sb.useless(rec, sp)
                 and sp.get("Number") not in sb.refused]
        if self.aoe_blocked():
            cands = [sp for sp in cands if spell_kind(sp) in (None, "single")]   # the AoE safety holds here too
        if not cands:
            return self._engage_anyway(mobs, rec)
        ms = sb.find((cfg.multi_spell or "").strip()) if (cfg.multi_spell or "").strip() else None
        if ms and any(sp.get("Number") == ms.get("Number") for sp in cands):
            # your multi-mob spell can hit it: that one, not whatever rates highest (Dan, 2026-11-02: multi spell
            # set to chaos storm, Evolution kept casting swarm at the geists)
            cands = [sp for sp in cands if sp.get("Number") == ms.get("Number")]
        got = sb.auto_pick(cands, [m[1] for m in mobs if m[1]], st.level or cfg.char_level, avail, 0.0,
                           self.spellcasting(), cfg.spell_dmg_bonus, "damage", area_min=0)
        if not got and [n for n in (st.party or {}) if n.lower() != (cfg.my_name or "").lower()]:
            # (0.8.201, bug hunt: only with a party, as _engage_anyway — alone at 5 mana it sent a spell the game
            # refused every round instead of resting or running)
            # not the mana for any of them: cast the one that hits anyway — it engages, so the party's kill counts
            # for you even if the spell fizzles (Dan, 2026-11-01: Evolution vs the blood skeletons — "use whatever
            # he can that hits, whether or not he has the mana")
            got = sb.auto_pick(cands, [m[1] for m in mobs if m[1]], st.level or cfg.char_level, 10 ** 6, 0.0,
                               self.spellcasting(), cfg.spell_dmg_bonus, "mana", area_min=0)
        if not got:
            return self._engage_anyway(mobs, rec)    # (spell immunity: none of them does anything to it)
        if got and self.ready("cant_hit_note", 30):
            self.log(f"{rec['name']} is magical — your usual spells can't hurt it; casting {got[0]['Name']}")
        return got

    def area_ok(self, n_mobs: int | None = None) -> bool:
        """Area spells allowed: Nuke on, 'Use area spells when there are at least N' ticked (unticked = never), and —
        given a count — at least N monsters here (Dan, 2026-11-11: "nuke is aoe spells"; set to 5, it quaked 1)."""
        cfg = self.cfg
        if not (cfg.auto_nuke and cfg.use_area_min):
            return False
        if self.aoe_blocked():
            return False      # AoE safety (a stranger here on a PvP board…): every area spell, openers and fallbacks too
        return n_mobs is None or n_mobs >= max(2, int(cfg.multi_min_mobs or 0))

    def spell_ok(self, sp, n_mobs: int | None = None) -> bool:
        """This attack spell may go out: single-target ones need Cast, area ones Nuke (and enough monsters)."""
        from .spells import spell_kind
        if not sp:
            return False
        if spell_kind(sp) in (None, "single"):
            return self.cast_on()
        return self.area_ok(n_mobs)

    def cast_on(self) -> bool:
        """Single-target attack spells: on with Combat, off without it (Dan, 2026-11-12: "Combat spells should be part
        of the combat area... if attack is off spells are off by default. if attack is on, combat spells are on").
        There's no separate Cast button any more; the old auto_cast setting is left alone and not read."""
        return bool(self.cfg.auto_combat)

    def _my_area_only(self, spells, n_mobs: int | None = None) -> list:
        """The attack spells the auto picks may use: single-target ones only with Cast on, area ones only with Nuke on
        (and enough monsters, given a count). With a multi spell set, that's the only area spell: Evolution kept
        picking swarm over his chaos storm whenever swarm rated a little higher (Revolution, 2026-11-03)."""
        from .spells import spell_kind
        spells = [sp for sp in spells if self.spell_ok(sp, n_mobs)]
        ms = (self.cfg.multi_spell or "").strip().lower()
        if not ms:
            return list(spells)
        return [sp for sp in spells if spell_kind(sp) in (None, "single")
                or ms in ((sp.get("Short") or "").lower(), (sp.get("Name") or "").lower())]

    def _useless_here(self, sp, recs, rec) -> bool:
        """A spell that can't do anything here: a single-target spell judged on the monster it goes at, an area spell
        only when it can't hurt any of them. (Dan, 2026-11-14: a large nightmare and a small gorehoof walked in on
        Miserable — magma blast hurts the nightmare, but the gorehoof is Magical 5, so 'useless against any of them'
        threw magma blast out, the storm was held for 3+ monsters, and the mage swung 'a nightmare' for 8.)"""
        from .spells import spell_kind
        sb = self.s.spellbook
        if spell_kind(sp) in (None, "single"):
            return sb.useless(rec, sp) if rec else all(sb.useless(r, sp) for r in recs)
        return all(sb.useless(r, sp) for r in recs)

    def _engage_anyway(self, mobs, rec):
        """Nothing you have can hurt it (the blood skeletons: Magical 3 and spell immunity 20 — swarm, level 12, does
        nothing): cast something anyway, so you're in the fight and get your share of the party's kill (Dan,
        2026-11-01). The spell you set to 0 mana in Game Data → Spells first, then an area spell, then the cheapest."""
        from .spells import is_attack_spell, spell_kind, fight_spell
        sb = self.s.spellbook
        known = [sp for sp in self._my_area_only(self.s.spell_candidates()) if is_attack_spell(sp)
                 and sp.get("Number") not in sb.refused and fight_spell(sp, [rec])]
        if not known or not [n for n in (self.st.party or {}) if n.lower() != (self.cfg.my_name or "").lower()]:
            return None                          # alone, a spell that can't hurt it is just a wasted round
        mine = {str(k) for k in (getattr(self.cfg, "spell_mana", None) or {})}
        # the strongest you can afford, not the cheapest: a magical monster's line is a spell level, so the bigger
        # spell is the one that may land — and once one lands, MudPilot counts it (and anything stronger) as able to
        # hurt it from then on. The cheapest was vine strike, a level-1 spell, every time (Dan, 2026-11-14: "casting
        # vine strike… it's getting ugly quick")
        avail = (self.st.ma - (self.cfg.spell_mana_reserve or 0)) if self.st.max_ma else 10 ** 6
        level = lambda x: int(x.get("ReqLevel") or x.get("Level") or 0)
        sp = min(known, key=lambda x: (str(x.get("Number")) not in mine, spell_kind(x) == "single",
                                       int(x.get("ManaCost") or 0) > avail, -level(x), int(x.get("ManaCost") or 0)))
        if self.ready("engage_note", 60):
            self.log(f"Nothing you have can hurt {rec['name']} — casting {sp['Name']} anyway, so you're in the fight "
                     "for your share of the exp")
        kind = spell_kind(sp) or "single"
        return sp, 0, 0.0, kind, "to engage (can't hurt it)"

    def _is_hunted(self, rec) -> bool:
        return bool(self.hunt_target and rec and rec["name"].lower() == self.hunt_target["name"].lower())

    def _bank_rooms(self) -> set:
        """pMUD's default safe rooms are the banks (and the Pier): MME's bank shops, for any board."""
        w = self.s.world
        if getattr(self, "_banks_for", None) is not w:
            self._banks_for = w
            self._banks = set(self.s.trips.banks()) if hasattr(self.s, "trips") else set()
        return self._banks

    def attackable(self):
        st, cfg = self.st, self.cfg
        if not st.view:
            return []
        ign = [x.lower() for x in cfg.ignore_mobs]
        only = [x.lower() for x in cfg.only_mobs]
        out = []
        if st.room and not st.in_combat and (f"{st.room[0]}/{st.room[1]}" in (cfg.safe_rooms or []) or
                                             (getattr(cfg, "banks_safe", True) and st.room in self._bank_rooms())):
            # a safe room (town, quest NPCs): only fight back what's already on you
            return [(sh, rec) for sh, rec in st.view.monsters if self._attacked_me(sh)]
        for shown, rec in st.view.monsters:
            if self._is_hunted(rec):
                out.append((shown, rec))
                continue
            base = (rec["name"] if rec else shown).lower()
            if any(i and i in base for i in ign):
                continue
            if only and not any(o and o in base for o in only):
                continue
            if rec is None and not only:
                continue  # unknown thing — not in MME, probably an NPC/player
            if rec and cfg.skip_zero_exp and rec["exp"] <= 0 and not only:
                continue
            if rec and rec["exp"] <= 0 and (rec.get("hp") or 0) >= 9999:
                continue          # can't be killed (the pyramid's stone sphinx: 9999 HP, 0 exp) — even if it swings
            if rec and not only and not self.hostile(rec) and not self._attacked_me(shown):
                continue          # guards, the mayor, shopkeepers — leave them alone unless they start it
            if rec and self._too_strong_mob(rec) and not st.in_combat and not self._attacked_me(shown) \
                    and time.time() - getattr(self, "_attacked_at", 0) > 6:
                continue          # ran from it twice lately (fight3 #2): not starting that fight again
            out.append((shown, rec))
        return out

    # ---------------------------------------------------------- Eco travel
    HURRY_RE = re.compile(r"strange feeling that time is running out", re.I)

    def hurrying(self) -> bool:
        """Pyramid level 1 is timed ("You have a strange feeling that time is running out!") — run it."""
        h = getattr(self, "_hurry", None)
        if not h:
            return False
        st, now = self.st, time.time()
        v = st.view
        if v and v.name.lower() == h["area"]:
            h["seen"] = True                         # (the message comes before the pyramid room shows)
        if h.get("up_from") and st.room and st.room != h["up_from"] and h.get("up_seq") != st.view_seq \
                and now - h.get("up_at", 0) < 10:
            h["ups"] = h.get("ups", 0) + 1           # made it up a level
            h["up_from"] = None
            self.log(f"Pyramid: up to level {h['ups'] + 1}")
        if now > h["until"] or (h.get("seen") and v and v.name not in ("(dark)", "") and v.name.lower() != h["area"]) or \
                h.get("ups", 0) >= 2:
            self._hurry = None
            self._no_rest_until = 0
            self.log("Past the timed levels (or out of the pyramid) — back to normal: resting, @wait, fights")
            return False
        return True

    def waiting_off(self) -> bool:
        """NoWait, the pyramid timer, or a room that kills you if you stay: ignore @wait and hurt members."""
        return bool(getattr(self.cfg, "no_wait", False) or self.hurrying() or self.in_deadly())

    DEADLY_RE = re.compile(r"^you are (?:drowning|suffocating|choking)|^you can'?t breathe|^the water fills your lungs",
                           re.I)

    def in_deadly(self) -> bool:
        """In a room you can't stay in (Settings → deadly_rooms; learned when 'You are drowning!' shows)."""
        v = self.st.view
        if not v or not v.name:
            return False
        names = {n.lower() for n in (getattr(self.cfg, "deadly_rooms", None) or [])}
        return v.name.lower() in names

    def _deadly_line(self, text):
        if not self.DEADLY_RE.search(text.strip()):
            return
        v = self.st.view
        if v and v.name and v.name != "(dark)" and not self.in_deadly():
            self.cfg.deadly_rooms = list(getattr(self.cfg, "deadly_rooms", None) or []) + [v.name]
            self.s.on_settings_changed()
            self.log(f"'{v.name}' kills you if you stay — MudPilot won't stop in it again")
        if not self.walking:
            self._flee_deadly()

    def _flee_deadly(self):
        """Drowning and not walking (stopped, waiting, regrouping): get out — carry on with the trip if there
        is one, else back the way we came."""
        if not self.ready("deadly_flee", 2):
            return
        r = getattr(self, "resume", None)
        if r and self.rego():
            self.log("Drowning — carrying on with the trip to get out")
            return
        st, w = self.st, self.s.world
        here = st.room
        prev = next((k for k in reversed(st.history[:-1]) if k != here), None) if st.history else None
        rr = w.room(here) if here else None
        ex = next((e for e in (rr.exits.values() if rr else []) if prev and e.to == prev), None)
        if ex is None and st.view and st.view.exits:
            d = "U" if "U" in st.view.exits else sorted(st.view.exits)[0]
            self.log(f"Drowning — getting out ({DIR_WORDS.get(d, d)})")
            self.send(d.lower())
            return
        if ex is not None:
            self.log(f"Drowning — back the way we came ({DIR_WORDS.get(ex.dir, ex.dir)})")
            self.send(ex.text_command if ex.kind == "text" and ex.text_command else ex.dir.lower())

    def eco_active(self) -> bool:
        """Eco is on and we're on our way somewhere (Go to, or a path that isn't a loop)."""
        if not (self.cfg.eco_travel and self.walking and self.path and not self.loop):
            return False
        # stopped — resting, meditating, held by an @wait: nothing's being walked past, so fight what's here
        # (Dan, 2026-10-28: PVE meditated next to a fierce orc lieutenant while it beat Buddy to the ground)
        hold = getattr(self.s.remote, "holding", None)
        return not (self.st.resting or self._swap or (hold and hold()))

    def eco_limits(self):
        cfg, st = self.cfg, self.st
        lvl = st.level or cfg.char_level or 1
        # auto: what's worth stopping for grows with you — level × 50, or half a minute of your exp/hr if
        # that's more (two level-47s stopping for a lone 1,100-exp sandworm isn't worth the pause)
        rate = 0.0
        try:
            rate = float(self.s.stats.exp_rate(1800) or 0)
        except Exception:
            pass
        worth = int(cfg.eco_min_exp or 0) or max(lvl * 50, int(rate * 30 / 3600))
        hit = int(cfg.eco_max_hit or 0) or max(25, int((st.max_hp or 300) * 0.08))
        return worth, hit

    def eco_note_hit(self, text):
        from .timeline import HIT_RE
        m = HIT_RE.match(text)
        if m and self.st.view:
            nm = m.group(1).lower()
            self._eco_hits = getattr(self, "_eco_hits", {})
            self._eco_hits[nm] = max(self._eco_hits.get(nm, 0), int(m.group(2)))
            self._eco_taken = [x for x in getattr(self, "_eco_taken", []) if time.time() - x[0] < 10]
            self._eco_taken.append((time.time(), int(m.group(2))))

    def _eco_filter(self, mobs):
        """Eco travel: walk past bandits, thugs and little spiders — they'd only scratch you — and stop
        for what's worth it (sandworms at 40+) or what actually hurts. Below the Eco HP % (or once one
        hits harder than the limit) everything on you is fought as usual."""
        # (the timed pyramid: the leader runs past them — followers fight what's on them as they go. Every
        #  character gets the 'time is running out' message, and nobody attacked anything: Dan, 2026-11-04)
        following = bool(getattr(self.x, "_following", None))
        if mobs and ((self.hurrying() and not following) or self.in_deadly()):
            st = self.st
            if st.max_hp and st.hp_pct() < int(self.cfg.eco_hp_pct or 60):
                return mobs
            if getattr(self, "_hurry_said", None) != st.view_seq:
                self._hurry_said = st.view_seq
                self.log("Timed pyramid: running past " + ", ".join(sorted({sh for sh, _r in mobs})))
            return []
        if not mobs or not self.eco_active():
            return mobs
        st = self.st
        # (a party member fighting the little ones that follow us is fine — Dan: they kill them on the run. What
        #  leaves them behind is a knock-down, and that holds the walk: see 'member down' in note_line)
        worth, hit = self.eco_limits()
        if st.max_hp and st.hp_pct() < int(self.cfg.eco_hp_pct or 60):
            return mobs
        hits = getattr(self, "_eco_hits", {})
        keep, skip = [], []
        for shown, rec in mobs:
            name = (rec["name"] if rec else shown).lower()
            avg = ((rec or {}).get("attack_data") or {}).get("mme_avg") or 0
            seen = max([v for k, v in hits.items() if name in k or shown.lower() in k] or [0])
            ct = getattr(self, "_cast_target", None)
            fighting = st.in_combat and ct and ct.lower() in shown.lower()
            if self._is_hunted(rec) or fighting or (rec and rec["exp"] >= worth) or avg >= hit or seen >= hit \
                    or time.time() - getattr(self, "_aggro", {}).get(shown.lower(), 0) < 30:
                keep.append((shown, rec))           # (one already swinging at you is in the fight: finish it)
            else:
                skip.append((shown, rec))
        if skip and not keep and st.max_hp and int(self.cfg.eco_pack_pct or 0):
            # one locust is nothing; ten following you are. What counts is what they actually do to you — at
            # level 50 a room of orc rogues mostly misses — so: the last round's damage (6 s) against the limit
            took = sum(d for t, d in getattr(self, "_eco_taken", []) if time.time() - t < 6)
            if took >= st.max_hp * int(self.cfg.eco_pack_pct) / 100:
                if getattr(self, "_pack_said", None) != st.room:
                    self._pack_said = st.room
                    self.log(f"Eco: {len(mobs)} here hit you for {took} last round "
                             f"(≥ {self.cfg.eco_pack_pct}% HP) — clearing the room")
                keep, skip = list(mobs), []
        if keep and skip:
            # stopping here anyway (the leader's worth it): take the whole room — an area spell gets them all
            # for the price of one, and the rest would only keep swinging at you while you fight
            keep, skip = list(mobs), []
        if skip and getattr(self, "_eco_said", None) != (st.view_seq if not keep else None, st.room):
            self._eco_said = (st.view_seq if not keep else None, st.room)
            self.why("eco_skip", room=st.room, skipped=[sh for sh, _r in skip], kept=[sh for sh, _r in keep],
                     worth=worth, hit=hit)
            if not keep:
                names = ", ".join(sorted({sh for sh, _r in skip}))
                self.log(f"Eco: walking past {names} (under {worth:,} exp, hits under {hit})")
        return keep

    # MME alignment: 0 Good, 1 Evil, 2 Chaotic evil, 3 Neutral, 4 Lawful good, 5 Neutral evil, 6 Lawful evil
    GOOD_ALIGNS, NEUTRAL_ALIGNS = {0, 4}, {3}

    def hostile(self, rec) -> bool:
        """Good/Lawful good (guards, the mayor) → you'd get evil points: leave them.
        Neutral (wild turkey, shopkeepers, healers) → not hostile: leave them.
        Evil → fair game. Anything that attacks you is fought back regardless.
        Your own Enemy / Neutral / Friend for it (Game Data → Monsters, '@enemy <name>') comes first."""
        att = (getattr(self.cfg, "monster_attitude", None) or {}).get((rec.get("name") or "").lower())
        if att == "enemy":
            return True
        if att in ("neutral", "friend"):
            return False
        al = int(rec.get("align") or 0)
        if al in self.GOOD_ALIGNS:
            return bool(self.cfg.attack_good)
        if al in self.NEUTRAL_ALIGNS:
            return bool(self.cfg.attack_neutral)   # neutral (wild turkey, shopkeepers…) isn't hostile
        return True

    def _attacked_me(self, shown) -> bool:
        t = getattr(self, "_aggro", {}).get(shown.lower())
        return bool(t and time.time() - t < 120)

    def _note_aggro(self, text):
        """Remember a non-hostile mob that hits or attacks us, so we defend ourselves."""
        st = self.st
        if not st.view or not st.view.monsters:
            return
        low = text.lower()
        me = (self.cfg.my_name or "").lower()
        mates = [n.lower() for n in (st.party or {}) if n.lower() != me]
        mate = next((n for n in mates if re.search(r"\b(?:at|attacks|hits|slashes|bites|stabs|smashes|crushes|claws|"
                                                  r"punches|kicks|lashes|whips|burns|strikes|stings)\s+"
                                                  + re.escape(n) + r"\b", low)), None)
        if mate:
            # it's on a party member: eco doesn't walk past it (Buddy, level 1, behind a level-55 leader)
            for shown, _rec in st.view.monsters:
                sl = shown.lower()
                if low.startswith((sl, "the " + sl, "a " + sl, "an " + sl)):
                    self._aggro = getattr(self, "_aggro", {})
                    self._aggro[sl] = time.time()
            return
        if not re.search(r"\byou\b.*(?:damage|!)|attacks you|at you", low):
            return
        if '"' in low:
            return                                   # it's talking ('The bishop says, "Have you found the chalice?"')
        for shown, _rec in st.view.monsters:
            sl = shown.lower()
            if low.startswith((sl, "the " + sl, "a " + sl, "an " + sl)) and " you" in low[len(sl):]:
                rest = low[low.index(sl) + len(sl):].split()
                if rest and rest[0] in self.FRIENDLY_VERBS:
                    continue                         # "The bishop smiles at you hopefully" — Buddy smashed him
                    # for it, turning in the chalice (Dan, 2026-11-05)
                self._aggro = getattr(self, "_aggro", {})
                self._aggro[sl] = time.time()

    FRIENDLY_VERBS = FRIENDLY_VERBS

    # (0.8.201, bug hunt: "You slap / jumpkick / critically … / surprise …" weren't ours, so the stall watchdog fired
    # mid-fight; any "You <verb> … for N damage!" is our own hit, as combatlog reads it)
    OWN_ATTACK_RE = re.compile(r"^you (?:make a|cast|draw|attempt|hit|miss|swing|slash|stab|bash|smash|punch|kick|"
                               r"strike|crush|lunge|fire|shoot|backstab|fail|slap|jumpkick|critically|surprise|glow|summon|raise your palm)"
                               r"|^your (?:spell|attack|blow|strike)|^you (?!gain\b|lose\b)[a-z].* for \d+ damage!"
                               # 0.8.224 (real logs: 103 of 106 watchdog re-sends came mid-spell): the game's spell lines
                               r"|^your (?!.*\bheal)[a-z].* for \d+ damage!|^.*\byour foes for \d+ damage"
                               r"|^you raise your hands|^you move your hands|^your foes .* for \d+ damage"
                               r"|^you reach out and touch|\bdrains .* of life for \d+ damage",
                               re.I)

    def _stall_check(self, now):
        """pMUD's stall watchdog: still being hit, but no attack of ours for a while (a repeating spell can stop
        without a *Combat Off*) — attack again rather than stand there."""
        st, cfg = self.st, self.cfg
        secs = float(cfg.stall_secs or 0)
        if not secs or not st.in_combat or now - self._attacked_at > 6:
            return
        last = max(getattr(self, "_own_attack_at", 0), getattr(self, "_cast_sent_at", 0),
                   getattr(self, "_area_armed", 0) or 0, getattr(self, "_last_hit_at", 0) or 0)
        if now - last < secs:
            return
        if self.ready("stall_said", 20):
            self.log(f"No attack of ours {f'for {now - last:.0f} s' if last else 'yet'} while being hit — attacking again")
        self._cast_target, self._last_spell, self._area_armed = None, None, 0
        self._cool["cast"] = 0
        self._cast_sent_at = now

    def fight(self, mobs):
        st, cfg = self.st, self.cfg
        now_ = time.time()
        ka = getattr(self, "_kill_at", 0)
        if ka and now_ - ka < 3 and st.view is not None and (st.view.t or 0) < ka:
            # something just died: this monster list is from before — wait for the room to show again rather than
            # cast into an empty room ("Your spell has no effect in this room!", 192 times in one of Evolution's runs)
            return
        self._stall_check(now_)
        # Cast = single-target attack spells, Nuke = area spells (Dan, 2026-11-11: "nuke is aoe spells")
        nuke = (self.cast_on() or cfg.auto_nuke) and self.x.may_cast_attack()
        n_mobs = len(mobs)
        area_ok = nuke and self.area_ok(n_mobs)
        mob = mobs[0]
        tgt = self.target_word(mob)
        rec = mob[1]
        # dangerous fight: curse first (e.g. mystic mist), then the hardest-hitting spells
        risky = self.fight_is_dangerous(mobs)
        sb_ = self.s.spellbook
        if risky and cfg.danger_opener_spell and nuke and not getattr(self, "_danger_open_done", False) and \
                self.spell_ok(sb_.find(cfg.danger_opener_spell), n_mobs) and \
                not sb_.useless(rec, sb_.find(cfg.danger_opener_spell)):
            if self.ready("dopen", 3):
                self._danger_open_done = True
                self.status = f"Dangerous fight ({risky}) — opening with {cfg.danger_opener_spell}"
                self.log(self.status)
                self.send(cfg.cast_cmd.format(short=cfg.danger_opener_spell, target=tgt))
            return
        # opener: cast once at the start of each fight
        if cfg.pre_attack_spell and cfg.auto_preattack and nuke and not st.in_combat and not self._pre_done and \
                self.spell_ok(sb_.find(cfg.pre_attack_spell), n_mobs) and \
                not sb_.useless(rec, sb_.find(cfg.pre_attack_spell)):
            if self.ready("pre", 3):
                self._pre_done = True
                self.status = f"Opening with {cfg.pre_attack_spell}"
                self.send(cfg.cast_cmd.format(short=cfg.pre_attack_spell, target=tgt))
            return
        # your own choice for this monster (Game Data → Monsters, double-click) beats everything automatic
        ov = self.monster_spell(rec)
        aoe_no = self.aoe_blocked()
        # (a blank Area spell = the best one you know, picked below — Dan, 2026-11-05: Revolution's 'fire' for drooling
        # geists and nightshades kept him on single-target in full rooms for days, because this asked for multi_spell)
        crowded = not aoe_no and (cfg.multi_spell or cfg.auto_spells) and area_ok
        if ov and crowded and ov.lower() != (cfg.multi_spell or "").lower():
            from .spells import spell_kind
            if spell_kind(self.s.spellbook.find(ov) or {}) in (None, "single"):
                ov = None         # a single-target pick for this monster: a crowded room still gets the area spell
        if ov and not self.spell_ok(self.s.spellbook.find(ov), n_mobs) and self.s.spellbook.find(ov):
            ov = None             # its switch is off (Cast for a single-target spell, Nuke for an area one)
        if ov is not None and nuke:
            if self._cast_override(ov, mob, rec, tgt, len(mobs)):
                return
        elif ov is not None and not nuke:
            ov = None
        # area spell when the room is crowded enough
        floor_held = None                     # the area spell's mana floor said no: the auto pick keeps to it too
        ms_sp = self.s.spellbook.find(cfg.multi_spell) if cfg.multi_spell else None
        ms_recs = [m[1] for m in mobs if m[1]]
        # (0.8.201, bug hunt: the multi spell went out with only a mana check — swarm at three blood skeletons it
        # can't touch every round until the mana was gone, and one the character hasn't learned resent every 2 s)
        ms_ok = bool(ms_sp) and ms_sp.get("Number") not in self.s.spellbook.refused and \
            not self.s.spell_too_low(ms_sp) and not (ms_recs and all(self.s.spellbook.useless(r, ms_sp)
                                                                     for r in ms_recs))
        if ov is None and not aoe_no and cfg.multi_spell and area_ok and ms_ok:
            sp = ms_sp
            cost = int(sp.get("ManaCost", 0)) if sp else 0
            # the big area spell mustn't take you under half the rest line (esto at 70 from 129 left you at
            # 25 with the fight still going) — unless this fight is dangerous, then spend it
            floor = int(cfg.spell_mana_reserve or 0)
            if st.max_ma and cfg.rest_below_ma and not risky:
                floor = max(floor, int(st.max_ma * cfg.rest_below_ma / 200))
            if not st.max_ma or st.ma - floor >= cost:
                if st.in_combat and getattr(self, "_area_armed", 0):
                    return        # the game repeats it every round; re-sending only toggles combat and loses one
                if not st.in_combat and time.time() - (getattr(self, "_area_armed", 0) or 0) < 3.5:
                    return        # (0.8.224, real logs — 1,513 times: just sent, no *Combat Engaged* yet)
                if self.ready("cast", cfg.spell_round_secs if st.in_combat else 2.0):
                    self.status = f"Casting {cfg.multi_spell} ({len(mobs)} mobs)"
                    self.x.counted_cast()
                    self.why("cast", spell=cfg.multi_spell, target=None, area=True, mobs=len(mobs),
                             in_combat=st.in_combat)
                    self._area_armed = time.time()
                    self._last_spell, self._cast_target = None, None   # single-target picks re-arm after it
                    self._attack_cmd = (cfg.cast_cmd.format(short=cfg.multi_spell, target="").strip(), time.time())
                    self._al_answered = set()
                    self.s.spellbook.note_cast(rec, sp)    # (0.8.201: so 'no effect' / 'refused' get learned)
                    self.send(self._attack_cmd[0])
                return
            floor_held = floor
        self._area_armed = 0
        if nuke and self.cast_on() and rec and len(mobs) == 1 and \
                self._drain_heal(mob, rec, tgt, risky):
            return
        if ov is None and nuke and rec and self._set_spell(mobs, mob, rec, tgt, aoe_no):
            return
        pick = None
        if ov is not None and not getattr(self, "_ov_useless", False):
            nuke = False                        # set to melee (or its spell can't go out right now): swing
        self._ov_useless = False
        avail = st.ma - cfg.spell_mana_reserve if st.max_ma else 10 ** 6
        saving = self.mana_saving() and not (risky and cfg.danger_big_spells)   # a dangerous fight gets the big spells
        if cfg.auto_spells and rec and nuke:
            recs = [m[1] for m in mobs if m[1]]
            mode = "damage" if cfg.spell_pick == "damage" and not saving else "mana"

            def pick_auto(excl=()):
                sb_ = self.s.spellbook
                cands_ = [sp_ for sp_ in self._my_area_only(self.s.spell_candidates(), n_mobs)
                          if not self._useless_here(sp_, recs, rec)]
                return self.s.spellbook.auto_pick(cands_, recs, st.level or cfg.char_level,
                                                  avail, cfg.spell_min_pct / 100, self.spellcasting(),
                                                  cfg.spell_dmg_bonus, mode,
                                                  area_min=max(2, cfg.multi_min_mobs) if cfg.use_area_min else 0,
                                                  exclude=excl)
            got = pick_auto()
            if got and got[3] != "single" and (aoe_no or floor_held is not None):
                from .spells import spell_kind
                # someone outside the party is here: single-target only. Under the area spell's mana floor: no area
                # spell that would take us below it (esto at 70 with 129 left and a floor of 120 went out anyway)
                area = tuple(sp["Number"] for sp in self.s.spell_candidates() if spell_kind(sp) not in (None, "single")
                             and (aoe_no or int(sp.get("ManaCost") or 0) > st.ma - floor_held))
                got = pick_auto(area)
            got = self._dial_back(got, rec, risky, mode, pick_auto)
            if not got and (self._caster_only() or self._no_melee(rec)):
                # (0.8.201, bug hunt: a level-50+ druid / priest, which _no_melee() keeps from swinging, got neither
                # this nor melee against a high-MR monster — it stood there 'waiting for mana' with full mana)
                # 0.8.184: nothing over the minimum (the hanging tree resists comet, chain lightning blocked by
                # strangers here) — a mage still casts the spell that hurts it most (magma blast), never swings
                # (Dan, 2026-11-12: "it'll certainly hit harder than melee… if he's resistant… use magm")
                from .spells import spell_kind
                sb_ = self.s.spellbook
                cands_ = [sp_ for sp_ in self._my_area_only(self.s.spell_candidates(), n_mobs)
                          if not self._useless_here(sp_, recs, rec)]
                area_ = tuple(sp_["Number"] for sp_ in cands_ if aoe_no and spell_kind(sp_) not in (None, "single"))
                got = sb_.auto_pick(cands_, recs, st.level or cfg.char_level, avail, 0.0, self.spellcasting(),
                                    cfg.spell_dmg_bonus, "damage",
                                    area_min=max(2, cfg.multi_min_mobs) if cfg.use_area_min else 0, exclude=area_)
                if got and float(got[1] or 0) <= 0:
                    got = None                       # nothing hurts it: melee after all
            if got:
                sp, eff, ratio, kind, note = got
                self._cast_pick(sp, eff, ratio, note, mob, rec, "" if kind != "single" else tgt, len(mobs))
                return
        elif cfg.attack_spells and rec and nuke:
            lst = [x for x in cfg.attack_spells
                   if (self.s.spellbook.find(x) or {}).get("Number") not in self.s.spellbook.refused
                   and self.spell_ok(self.s.spellbook.find(x), n_mobs)
                   and not self.s.spell_too_low(self.s.spellbook.find(x))]
            if saving:                          # cheapest first while saving mana
                lst.sort(key=lambda x: int((self.s.spellbook.find(x) or {}).get("ManaCost", 0) or 0))
            pick = self.s.spellbook.choose(lst,
                                           rec, st.level or cfg.char_level, avail,
                                           cfg.spell_min_pct / 100, self.spellcasting(), cfg.spell_dmg_bonus)
            if not pick and (not cfg.spell_fallback_melee or self._caster_only() or self._no_melee(rec)):
                # 0.8.184: a mage never melees while a spell can hurt it (Dan, 2026-11-12: Miserable PVE swung at
                # the hanging tree: no spell rated over the minimum, area spells blocked by strangers in the room).
                # A below-par spell beats a mage's fists; melee only when no spell hurts it or none is affordable
                rows = self.s.spellbook.evaluate(lst, rec, st.level or cfg.char_level,
                                                 self.spellcasting(), cfg.spell_dmg_bonus)
                caster = self._caster_only() or self._no_melee(rec)     # (0.8.201, bug hunt: same as above)
                pick = next(((r[0], r[1], r[2], r[3], r[5]) for r in rows if r[2] > 0 and
                             (not caster or (int((r[0] or {}).get("ManaCost", 0) or 0) <= avail
                                             and not self.s.spellbook.useless(rec, r[0])))), None)
        if not pick and rec and nuke and (cfg.attack_spells or cfg.auto_spells):
            alt = self._can_hit_fallback(mobs, rec, avail)
            if alt:
                sp, eff, ratio, kind, note = alt
                self._cast_pick(sp, eff, ratio, note, mob, rec, "" if kind != "single" else tgt, len(mobs))
                return
        if pick:
            sp, rated, eff, ratio, src = pick
            self._cast_pick(sp, eff, ratio, f"rated {rated}, {src}", mob, rec, tgt, len(mobs))
            return
        if (cfg.attack_spells or cfg.auto_spells) and rec and self._last_spell is not None:
            self.spell_info = f"No spell ≥{cfg.spell_min_pct}% vs {rec['name']} — melee"
            self._last_spell = None
        nm = ((rec or {}).get("name") or mob[0]).lower()
        immune = self._melee_immune_now()
        if (nm in immune or self._needs_better_weapon(rec)) and self._swap_weapon_for(rec, nm, mob[0]):
            return                                      # wielding one that can hurt it: fight() swings next tick
        if nm in immune:
            # "Your weapon has no effect against this monster" — swinging at it forever does nothing.
            # (0.8.201, bug hunt: this sat below the 'already fighting' check, so after our own swing it was never
            # reached and the bot kept "Fighting ghost" with no effect; and with the ghost first in the list it
            # froze there and never swung at the orc next to it, or walked on)
            others = [m for m in mobs if ((m[1] or {}).get("name") or m[0]).lower() not in immune]
            mt = (getattr(self, "_melee_target", None) or "").lower()
            if st.in_combat and self._melee_on and mt and mt != nm and any(
                    ((m[1] or {}).get("name") or m[0]).lower() == mt for m in others):
                self.status = f"Fighting {mt}"          # already swinging at one the weapon can hurt
                return
            if st.in_combat and (not others or (self._melee_on and (not mt or mt == nm))):
                self.status = f"Your weapon can't hurt {mob[0]} — leaving it"
                if self.ready("break_off", 10):
                    self.send(cfg.break_cmd or "brea")
                    self._melee_on = False
                return
            if not others:
                self.status = f"Your weapon can't hurt {mob[0]} — leaving it"
                return False                            # nothing here it can hurt: tick() walks on
            mob = others[0]                             # swing at the first one the weapon can hurt
            tgt, rec = self.target_word(mob), mob[1]
        if st.in_combat and self._melee_on:
            self.status = f"Fighting {mob[0]}"
            return
        if self._no_melee(rec):
            # a level-50+ caster never swings unless the monster is immune to all its magic (Dan, 2026-11-14) —
            # out of mana it waits for the next spell rather than punch for 8
            if self._mana_backoff(mob, rec):
                return
            self.status = f"Not meleeing {mob[0]} — waiting for mana / a spell that hurts it"
            if self.ready("no_melee_note", 60):
                self.log(f"Not meleeing {mob[0]}: a caster at your level only swings at a monster immune to all your "
                         "magic")
            return
        if not st.in_combat and time.time() - getattr(self, "_attack_sent_at", 0) < 3.5:
            return        # waiting for *Combat Engaged* from the last attack
        if not st.in_combat and time.time() < getattr(self, "_attack_backoff_until", 0):
            self.status = f"Attack on {mob[0]} came out as speech — waiting, then trying again"
            return        # (0.8.202: the last attack was said aloud — see note_line)
        if self.ready("attack", 2.0):
            self.status = f"Attacking {mob[0]} ({len(mobs)} here)"
            self._attack_sent_at = time.time()
            self._melee_target = (rec or {}).get("name") or mob[0]
            atk = cfg.attack_cmd.format(target=tgt)
            if cfg.backstab_weapon and re.match(r"^\s*(?:bs|backstab)\b", atk, re.I):
                from .gamestate import wielded
                self._bs_back = cfg.main_weapon or wielded(st.carrying) or ""
                self.send(f"eq {cfg.backstab_weapon}")     # the backstab blade for one attack…
            self.send(atk)
            self._attack_cmd = (atk, time.time())
            self._al_answered = set()
            self._melee_on = True

    CASTER_ONLY = ("mage",)

    RESIST_SKIP = 50          # a monster this resistant (%) to a spell's element: don't use that spell on it

    def _real_reason_not(self, sp, rec) -> str | None:
        """A real reason not to cast the spell you set (Dan, 2026-11-14: "mudpilot should be automatically using the
        spell that's set unless it has a real good reason not to… if the monster is 50% immune or better to the
        element… Seems like when it tries to do too much thinking on its own it fucks it up"). Only: the game said
        "no effect", it resists the element by half or more, it's below a level-50 caster, the game refused it,
        or you can't afford it. Not MME's Magical rule, not damage ratings, not saving mana."""
        sb, st, cfg = self.s.spellbook, self.st, self.cfg
        if not sp:
            return "not a spell MudPilot knows"
        if sp.get("Number") in sb.refused:
            return "the game won't let you cast it"
        if rec and (rec.get("num", 0), sp.get("Number")) in sb.no_effect:
            return "it had no effect on it"
        if self.s.spell_too_low(sp):
            return "too low a spell at your level"
        if rec:
            from .spells import calc
            c = calc(sp, st.level or cfg.char_level, rec, self.spellcasting(), cfg.spell_dmg_bonus)
            if c.resist_pct >= self.RESIST_SKIP:
                return f"it resists that element {c.resist_pct}%"
            if c.round_dmg <= 0 and calc(sp, st.level or cfg.char_level, None, self.spellcasting(),
                                         cfg.spell_dmg_bonus).round_dmg > 0:
                return "it can't hurt it at all (spell immunity, or the wrong kind of monster)"
        cost = int(sp.get("ManaCost") or 0)
        if st.max_ma and st.ma - (cfg.spell_mana_reserve or 0) < cost:
            return "no mana"
        return None

    def _set_spell(self, mobs, mob, rec, tgt, aoe_no) -> bool:
        """Your attack spell list (Options → Spells), in your order: the first one with no real reason against it
        goes out. Everything automatic only comes in when none of yours can."""
        cfg = self.cfg
        from .spells import spell_kind
        n = len(mobs)
        for short in cfg.attack_spells or []:
            sp = self.s.spellbook.find(short)
            if not sp or not self.spell_ok(sp, n):
                continue
            single = spell_kind(sp) in (None, "single")
            if not single and (aoe_no or not self.area_ok(n)):
                continue                        # an area spell on your list: only where area spells are allowed
            if single and not aoe_no and (cfg.multi_spell or cfg.auto_spells) and self.area_ok(n):
                continue                        # a crowded room: the area spell (yours, or the best one) comes first
            if self._real_reason_not(sp, rec):
                continue
            from .spells import calc
            lvl = self.st.level or cfg.char_level
            eff = calc(sp, lvl, rec, self.spellcasting(), cfg.spell_dmg_bonus).round_dmg
            rated = calc(sp, lvl, None, self.spellcasting(), cfg.spell_dmg_bonus).round_dmg or 1
            self._cast_pick(sp, eff, eff / rated, "your attack spell", mob, rec,
                            tgt if spell_kind(sp) in (None, "single") else "", n)
            return True
        return False

    def _no_melee(self, rec) -> bool:
        """A level-50+ full caster whose spells (any of them, cheap ones included) can still hurt this monster."""
        s, cfg = self.s, self.cfg
        if not (cfg.attack_spells or cfg.auto_spells) or int(self.st.level or cfg.char_level or 0) < s.LOW_SPELL_FROM                 or not s.full_caster() or not rec:
            return False
        x = getattr(self, "x", None)
        if not (self.cast_on() or cfg.auto_nuke) or (x is not None and not x.may_cast_attack()):
            # (0.8.201, walk check: no spell can go out — Combat off at a guard, or max_off_casts used up — so the
            #  no-melee rule left a mage standing at the deranged priest for the full 300 s, neither casting nor
            #  swinging. When it can't cast, it swings)
            return False
        from .spells import is_attack_spell
        sb = s.spellbook
        mine = [sp for sp in s.known_spell_dicts() if is_attack_spell(sp) and sp.get("Number") not in sb.refused]
        return any(not sb.useless(rec, sp) for sp in mine)

    def _mana_backoff(self, mob, rec) -> bool:
        """0.8.223 (Dan, m1617c N1): a level-50+ caster that won't swing (_no_melee) and hasn't the mana for any spell
        that hurts this monster backs off a room and rests to full — standing there neither swinging, resting nor
        moving lasted minutes, until a hang-up. Not a follower (that's the leader's call); not with Rest off."""
        st, cfg, s = self.st, self.cfg, self.s
        if not cfg.auto_rest or not st.max_ma or st.ma is None:
            return False
        if st.party and not self.x.leading():
            return False
        from .spells import is_attack_spell
        sb = s.spellbook
        costs = [int(sp.get("ManaCost") or 0) for sp in s.known_spell_dicts()
                 if is_attack_spell(sp) and sp.get("Number") not in sb.refused and not sb.useless(rec, sp)]
        if not costs or st.ma - int(cfg.spell_mana_reserve or 0) >= min(costs):
            return False                             # a spell that hurts it is affordable: it casts
        if not self.ready("mana_backoff", 20):
            return False
        self.log(f"Out of mana for {mob[0]} (MA {st.ma}/{st.max_ma}, the cheapest spell that hurts it is {min(costs)}) "
                 f"— backing off a room to rest")
        self._msg_rest_full = time.time()            # (rest to full: Rest below MA may be off)
        self.flee(count=False)
        return True

    def _caster_only(self) -> bool:
        """A class whose melee is hopeless next to its spells (a mage): it casts whatever hurts, never swings
        while a spell can (Dan, 2026-11-12: 'A mage should never use melee unless they cant hit')."""
        cls = (self.st.char_class or self.cfg.char_class or "").strip().lower()
        return cls in self.CASTER_ONLY

    def _aoe_friendly(self) -> list:
        """Monsters here we don't attack (never-attack list, guards / neutral NPCs / good ones with attacking those
        off) that an area spell would hit anyway (0.8.201, Dan). Not unknown things (players / NPCs MME lacks are
        the AoE safety's job), not what can't be killed (the stone sphinx), not one that's attacking us."""
        st, cfg = self.st, self.cfg
        if not st.view or not st.view.monsters:
            return []
        ign = [x.lower() for x in (cfg.ignore_mobs or []) if x]
        only = [x.lower() for x in (cfg.only_mobs or []) if x]
        out = []
        for shown, rec in st.view.monsters:
            if not rec or self._unkillable(rec) or self._is_hunted(rec):
                continue
            base = (rec.get("name") or shown).lower()
            if any(i in base for i in ign):
                out.append(shown)
            elif not (only and any(o in base for o in only)) and not self.hostile(rec) and \
                    not self._attacked_me(shown):
                out.append(shown)
        return out

    def aoe_blocked(self) -> str | None:
        """pMUD's AoE safety: no area spells while someone outside the party is in the room (a PvP board
        reads an area spell as an attack), while we don't know who's here, or just after the party broke."""
        cfg, st = self.cfg, self.st
        # (0.8.201, bug hunt / Dan: an area spell hits everything in the room — a guard, a neutral shopkeeper or
        # something on your never-attack list got hit and fought back. Held while one's here, whatever AoE safety
        # says; the single-target spells still go out)
        fr = self._aoe_friendly()
        if not cfg.aoe_safety and not fr:
            return None
        why = f"{', '.join(fr)} here (not a target)" if fr else None
        if why:
            pass
        elif not st.view or time.time() - (st.view.t or 0) > 120:
            why = "not sure who's in the room"
        else:
            party = {n.lower() for n in st.party} | {(cfg.my_name or "").lower()}
            others = [p.split()[0].strip(".,") for p in (st.view.players or [])
                      if p.split() and p.split()[0].strip(".,").lower() not in party]
            if others and cfg.pvp_realm:          # on a PVE realm an area spell can't touch another player
                why = f"{', '.join(others)} in the room (not in the party)"
            elif time.time() - getattr(self.x, "_party_broke_at", 0) < 5:
                why = "the party just broke up"
            elif cfg.pvp_realm and hasattr(self.x, "walked_in") and self.x.walked_in():
                # Dan, 2026-11-18: Miserable logged back in where he'd hung up, straight into Revolution's
                # repeating tempest — single-target from the moment someone walks in, before the room list catches up
                why = f"{self.x.walked_in()} just walked in"
        if why and getattr(self, "_aoe_said", None) != (st.room, why):
            self._aoe_said = (st.room, why)
            self.log(f"No area spells: {why}")
        return why

    def monster_spell(self, rec):
        """Your per-monster pick: None = automatic, "" = melee only, else a spell's short name."""
        ms = self.cfg.monster_spells or {}
        if rec and any(t.get("melee") and t["monster"] == (rec.get("name") or "").lower()
                       for t in (getattr(self.s.world, "room_tasks", None) or {}).values()):
            return ""                                # the floating key: spells don't touch it — melee only
        if not rec or not ms:
            return None
        name = (rec.get("name") or "").lower()
        if name in ms:
            return (ms[name] or {}).get("spell", "")
        from .spelltune import family
        fam = family(name)
        e = ms.get(fam)
        if e and e.get("variants"):
            return e.get("spell", "")
        return None

    def _cast_override(self, short, mob, rec, tgt, n) -> bool:
        """Cast your chosen spell on this monster. False → melee instead (melee only, no mana, unknown spell)."""
        st, cfg = self.st, self.cfg
        if not short:
            self.spell_info = f"{rec['name']}: melee only (your setting)"
            return False
        sp = self.s.spellbook.find(short)
        if not sp:
            self.spell_info = f"{rec['name']}: your spell '{short}' isn't known — melee"
            return False
        if self.s.spell_too_low(sp):
            self.spell_info = f"{rec['name']}: {sp['Name']} is too low a spell at your level — picking a real one"
            self._ov_useless = True
            return False
        sb_ = self.s.spellbook
        why_not = self._real_reason_not(sp, rec)
        if why_not and why_not != "no mana":
            self.spell_info = f"{rec['name']}: {sp['Name']} — {why_not}; trying a spell that can"
            self._ov_useless = True
            return False
        if ((rec or {}).get("num", 0), sp.get("Number")) in sb_.no_effect:
            # only the game's own "no effect" overrules your pick for a monster — not MME's Magical rule, which had
            # Evolution quaking a single copsewight instead of the elemental fury he'd set (Dan, 2026-11-14)
            self.spell_info = f"{rec['name']}: {sp['Name']} had no effect on it — trying a spell that can"
            self._ov_useless = True               # (not 'melee': a magical monster shrugs that off too)
            return False
        cost = int(sp.get("ManaCost") or 0)
        if st.max_ma and st.ma - cfg.spell_mana_reserve < cost:
            self.spell_info = f"{rec['name']}: not enough mana for {sp['Name']} — melee"
            return False
        from .spells import calc
        lvl = st.level or cfg.char_level       # (0.8.201, bug hunt: the game's level wins over a stale setting)
        eff = calc(sp, lvl, rec, self.spellcasting(), cfg.spell_dmg_bonus).round_dmg
        rated = calc(sp, lvl, None, self.spellcasting(), cfg.spell_dmg_bonus).round_dmg or 1
        self._cast_pick(sp, eff, eff / rated, "your choice for this monster", mob, rec, tgt, n)
        return True

    @staticmethod
    def _round_mana(sp) -> int:
        """Mana a full round of it costs: several casts a round for a quick spell (magma blast, 166 energy: 6 × 5)."""
        e = int(sp.get("EnergyCost") or 0)
        return max(1, int(sp.get("ManaCost") or 0) * (int(1000 / e) if 0 < e <= 500 else 1))

    def _kill_mana(self, row, rec) -> float:
        """Mana to kill this monster with this spell: casts needed for its HP × mana a cast. A quick spell stops when
        it dies (2 magma blasts finish what a second sphere of implosion would cost 25 for — Dan, 2026-11-03).
        No HP known: a round's mana for a round's damage."""
        sp, dmg = row[0], float(row[1] or 0)
        e = int(sp.get("EnergyCost") or 0)
        casts = int(1000 / e) if 0 < e <= 500 else 1
        per_cast = dmg / casts if casts else dmg
        hp = float((rec or {}).get("hp") or 0)
        if not hp or per_cast <= 0:
            return self._round_mana(sp) / max(dmg, 1)
        return math.ceil(hp / per_cast) * max(1, int(sp.get("ManaCost") or 0))

    def _dial_back(self, got, rec, risky, mode, pick):
        """Spell efficiency: k steps down the ladder of usable single-target spells for this monster
        (the spell tuner decides k from how the fights go). Dangerous fights and bosses: hardest spell."""
        tune = getattr(self.s, "spelltune", None)
        if not got or not tune or mode != "damage" or risky or rec.get("boss") or got[3] != "single":
            return got
        k = tune.level(rec.get("name", ""))
        cheap = int(self.cfg.spell_cheap_below_exp or 0)
        if cheap and float(rec.get("exp") or 0) < cheap:
            k = max(k, int(self.cfg.spell_eff_max_steps or 0) or 2)   # trash: the cheapest spell that still works
        floor = got[1] * max(0, min(100, int(self.cfg.spell_eff_floor_pct or 0))) / 100
        most = max(0, int(self.cfg.spell_eff_max_steps or 0))
        ladder, excl = [got], set()
        while len(ladder) <= max(k, 1) and len(ladder) <= most:   # one past k: the tuner learns if a weaker one exists
            excl.add(ladder[-1][0]["Number"])
            nxt = pick(tuple(excl))
            if not nxt or nxt[3] != "single":
                break
            if nxt[1] < floor:
                break                                # never down to a toy spell (magic missile at level 47)
            if self._kill_mana(nxt, rec) * STEP_DOWN_GAIN > self._kill_mana(ladder[-1], rec):
                break                                # not really cheaper to kill it with: keep the harder spell
            ladder.append(nxt)
        tune.note_ladder(rec.get("name", ""), len(ladder))
        return ladder[min(k, len(ladder) - 1)]

    # ---------------------------------------------------------- mana throttle
    def mana_saving(self) -> bool:
        """Mana is getting near the rest line: use the most mana-efficient spells so the fights
        keep going and mana regen catches up, instead of sitting down to meditate."""
        st, cfg = self.st, self.cfg
        if not cfg.mana_throttle or not st.max_ma or not cfg.rest_below_ma:
            return False
        on = st.ma_pct() < cfg.rest_below_ma + int(cfg.mana_throttle_band or 0)
        if on != getattr(self, "_saving_mana", False):
            self._saving_mana = on
            self.log("Mana getting low — switching to cheaper spells to keep going" if on
                     else "Mana back up — full-damage spells again")
        return on

    def cheapest_attack_cost(self) -> int:
        cfg = self.cfg
        if cfg.auto_spells:
            sps = self.s.spell_candidates()
        else:
            sps = [self.s.spellbook.find(x) for x in cfg.attack_spells or []]
        costs = [int(sp.get("ManaCost", 0) or 0) for sp in sps if sp and sp.get("Number") not in self.s.spellbook.refused]
        costs = [c for c in costs if c > 0]
        return min(costs) if costs else 0

    def mana_rest_can_wait(self) -> bool:
        """Mana is under 'rest below' but HP is fine: keep walking on cheap spells while there's
        mana for a few of them (and never below half the rest line)."""
        st, cfg = self.st, self.cfg
        if not cfg.mana_throttle or not st.max_ma:
            return False
        cheap = self.cheapest_attack_cost()
        if not cheap:
            return False
        floor = max(cfg.rest_below_ma / 2, 100.0 * (3 * cheap + int(cfg.spell_mana_reserve or 0)) / st.max_ma)
        return st.ma_pct() >= floor

    def _drain_heal(self, mob, rec, tgt, risky) -> bool:
        """Dan: the last monster, a weak one, and you're down to where you'd rest after the fight — drain it
        (dtch: a little mana for 50-100 HP) to come out of the fight not needing that rest. Not on one that's
        kicking your ass (kill that as fast as you can), not on undead (nothing to drain), not with the mana
        you'd rest for. True = cast (or waiting to)."""
        cfg, st = self.cfg, self.st
        # (judged by how hard it hits below, not by 'dangerous' — MME flags a giant spider as a boss)
        if not getattr(cfg, "drain_heal", True) or not st.max_hp or not st.max_ma:
            return False
        sp = self.s.spellbook.find((getattr(cfg, "drain_spell", "") or "dtch").strip())
        if not sp or sp.get("Number") in self.s.spellbook.refused or self.s.spellbook.useless(rec, sp):
            return False
        short = (sp.get("Short") or "").lower()
        # not one of yours (only mages have deathtouch). Until this session's 'spells' list is read: last session's,
        # else what the class can learn (Dan, 2026-11-04: Buddy, a Paladin, sent 'dtch serpent' right after a relog)
        known = st.known_spells if st.known_spells is not None else (cfg.known_spells or None)
        if known is not None:
            if short not in {str(k).lower() for k in known}:
                return False
        else:
            from .spells import class_spells
            cname = (st.char_class or cfg.char_class or "").lower()
            cls = next((k for k, v in self.s.world.classes.items() if v.get("Name", "").lower() == cname), 0)
            if not cls or sp["Number"] not in {c["Number"] for c in class_spells(self.s.world, cls, 0)}:
                return False
        # drain up to your rest max or 90%, whichever is lower, then back to a real spell (Dan, 2026-11-14)
        goal = min(90, int(cfg.rest_until_hp or 100))
        if st.hp * 100 / st.max_hp >= goal:
            return False
        nm_ = (rec.get("name") or "").lower()
        ab_ = rec.get("abils") or {}
        if rec.get("undead") or 109 in ab_ or "109" in ab_ or nm_ in getattr(self, "_drain_immune", set()):
            return False                             # undead / NonLiving (elementals): nothing to drain — PVE died
            # dtch'ing a surf elemental, "Your spell has no effect", HP 537 → dead (2026-10-29)
        dr = getattr(self, "_drain_track", None)
        if dr and dr[0] == nm_ and time.time() - dr[3] < 40 and st.hp < dr[1] and dr[2] >= 2:
            self._drain_immune = getattr(self, "_drain_immune", set()) | {nm_}
            self.log(f"Draining {rec.get('name')} isn't working (HP {dr[1]} → {st.hp} over {dr[2]} drains) — "
                     "killing it instead")
            return False
        avg = float(((rec.get("attack_data") or {}).get("mme_avg")) or 0)
        hits = getattr(self, "_eco_hits", {})
        seen = max([v for k, v in hits.items() if (rec.get("name") or "").lower() in k] or [0])
        if max(avg, seen / 2) > st.max_hp * 0.06:
            return False                             # it hurts: the hardest-hitting spell, kill it fast
        cost = int(sp.get("ManaCost") or 0)
        floor = max(int(cfg.spell_mana_reserve or 0), int(st.max_ma * (cfg.rest_below_ma or 30) / 100))
        if st.ma - cost < floor:
            return False
        if not self.ready("cast", cfg.spell_round_secs if st.in_combat else 2.0):
            return True
        self.status = f"Draining {mob[0]} ({sp.get('Name')}) — HP {st.hp}/{st.max_hp}, back over {goal}% before it dies"
        if self.ready("drain_note", 30):
            self.log(self.status)
        self.why("cast", spell=short, target=(rec or {}).get("name"), area=False, note="drain heal", hp=st.hp, mobs=1)
        self._last_spell = sp["Number"]
        self._cast_sent_at, self._cast_target, self._cast_area = time.time(), (rec or {}).get("name"), False
        self.s.spellbook.note_cast(rec, sp)
        self.x.counted_cast()
        dr = getattr(self, "_drain_track", None)
        fresh = dr and dr[0] == nm_ and time.time() - dr[3] < 40      # (the same fight: drains a round apart)
        self._drain_track = (nm_, dr[1], dr[2] + 1, time.time()) if fresh else (nm_, st.hp, 1, time.time())
        self.send(cfg.cast_cmd.format(short=short, target=tgt).strip())
        self._melee_on = False
        return True

    def fight_is_dangerous(self, mobs) -> str | None:
        """Why this fight counts as dangerous (for the curse opener), or None. Decided once per fight."""
        cfg, st = self.cfg, self.st
        if not (cfg.danger_opener_spell or cfg.danger_big_spells):
            return None
        if getattr(self, "_risky", None) is not None and getattr(self, "_risky_key", None) == st.room:
            return self._risky or None
        recs = [r for _s, r in mobs if r]
        why = ""
        if cfg.danger_opener_mobs and len(mobs) >= int(cfg.danger_opener_mobs):
            why = f"{len(mobs)} monsters"
        elif any(r.get("boss") for r in recs):
            why = "a boss"
        elif st.max_hp and st.hp:
            from .danger import fight_estimate
            est = fight_estimate(self.s.danger, recs)
            if est >= st.hp * int(cfg.danger_opener_pct or 50) / 100:
                why = f"~{est:.0f} damage expected"
        self._risky, self._risky_key = why, st.room
        return why or None

    def spellcasting(self) -> int:
        """Your Spellcasting: what the game showed last ('st'), else the Combat tab's number."""
        return int(self.st.spellcasting or self.cfg.spellcasting or 0)

    def _cast_pick(self, sp, eff, ratio, note, mob, rec, tgt, n):
        st, cfg = self.st, self.cfg
        now = time.time()
        self._area_cast_t = now if not tgt else 0     # the game repeats it each round (see extras: a player walks in)
        # MajorMUD repeats your attack spell every round by itself. Sending it again restarts the
        # fight ("*Combat Off*" / "*Combat Engaged*") and loses a round — so only re-send when the
        # spell or target changes, or our hits have stopped coming.
        same = self._last_spell == sp["Number"] and getattr(self, "_cast_target", None) == (rec or {}).get("name")
        landing = now - max(getattr(self, "_last_hit_at", 0), getattr(self, "_cast_sent_at", 0)) < \
            float(cfg.spell_round_secs) * 2.2
        if now < getattr(self, "_cast_block_until", 0):
            return        # "You have already cast a spell this round!" — the next round, not before
        same_target = getattr(self, "_cast_target", None) == (rec or {}).get("name")
        cur_t = getattr(self, "_cast_target", None)
        # the game is repeating the drain spell (death touch) but the drain is done — at the rest max / 90%: switch
        # now, or it drains every round to 100% (Dan, 2026-11-14: Miserable PVE 75% → 84 → 91 → 99% on dtch)
        dsp = self.s.spellbook.find((getattr(cfg, "drain_spell", "") or "dtch").strip())
        drain_done = bool(dsp) and self._last_spell == dsp.get("Number") and sp.get("Number") != dsp.get("Number")
        alive = bool(cur_t and st.view and any((r or {}).get("name") == cur_t for _s, r in st.view.monsters))
        # ...unless what we'd cast now is far better: out of mana it settles for magic missile, and once the mana
        # is back that one wasted round beats two minutes of 35-damage rounds (PVE died that way, 2026-11-02:
        # magm wanted, mmis kept, mana 384, HP 632 → dead).
        much_better = eff >= 2 * (getattr(self, "_cast_eff", None) or eff + 1) or drain_done
        # an area spell the game is repeating that isn't allowed any more (a stranger walked in, the room dropped
        # under the 'at least N'): send the new choice, which stops the repeat — don't keep it going
        area_stale = bool(getattr(self, "_cast_area", False)) and sp.get("Number") != self._last_spell             and not self.area_ok(n)
        # The game is already repeating our spell: an area spell (esto) hits everyone, and a single-target one
        # keeps going at its monster while that's still here. Re-sending — because the room list came back
        # in a different order, or the picker now prefers another monster — only toggles *Combat Off* /
        # *Combat Engaged* and wastes the round.
        if st.in_combat and self._last_spell is not None and landing and \
                (getattr(self, "_cast_area", False) or alive) and not same and not much_better and not area_stale:
            cur = self.s.world.spells.get(self._last_spell) or {}
            cost = int(cur.get("ManaCost") or 0)
            if not st.max_ma or st.ma - cfg.spell_mana_reserve >= cost:
                self.status = f"Casting {cur.get('Name', 'spell')} ({n} here)"
                self.why("keep_casting", spell=cur.get("Short"), wanted=sp.get("Short"), target=cur_t,
                         why="the game is repeating it — not re-sending")
                return
        if st.in_combat and same_target and self._last_spell is not None and self._last_spell != sp["Number"] \
                and now - getattr(self, "_cast_sent_at", 0) < 20 and not much_better and not area_stale:
            cur = self.s.world.spells.get(self._last_spell) or {}
            cost = int(cur.get("ManaCost") or 0)
            if not st.max_ma or st.ma - cfg.spell_mana_reserve >= cost:
                # mid-fight: the game keeps repeating the current spell; changing it now restarts the fight
                # (*Combat Off*) and loses a round. The new choice starts with the next monster.
                self.status = f"Casting {cur.get('Name', 'spell')} at {mob[0]} ({n} here)"
                return
        if st.in_combat and same and landing:
            self.status = f"Casting {sp['Name']} at {mob[0]} ({n} here)"
            return
        if not st.in_combat and now - getattr(self, "_cast_sent_at", 0) < 3.5:
            self.status = f"Casting {sp['Name']} at {mob[0]} — waiting for the fight to start"
            return        # just cast it: a second one before *Combat Engaged* restarts the fight
        self.spell_info = f"{sp['Name']} on {rec['name']}: {eff} dmg/round ({ratio:.0%} of rated, {note})"
        if self._last_spell != sp["Number"]:
            if self._last_spell is not None:
                c, f = self.s.spellbook.tries.get(sp["Number"], (0, 0))
                seen = f", casts landed {c - f}/{c}" if c >= 6 else ""
                self.log(f"Switching spell → {sp['Name']} ({eff} dmg/round, {ratio:.0%} effective vs {rec['name']}, "
                         f"{note}, Spellcasting {self.spellcasting()}{seen})")
            self._last_spell = sp["Number"]
        if self.ready("cast", cfg.spell_round_secs if st.in_combat else 2.0):
            self.status = f"Casting {sp['Name']} at {mob[0]} ({n} here)"
            self._cast_sent_at, self._cast_target = time.time(), (rec or {}).get("name")
            self._cast_area = not tgt
            self._cast_eff = eff
            self.why("cast", spell=sp.get("Short") or sp["Name"], target=(rec or {}).get("name"), area=not tgt,
                     dmg=eff, pct=round(ratio, 2), note=note, mobs=n, in_combat=st.in_combat)
            self.s.spellbook.note_cast(rec, sp)
            self.x.counted_cast()
            self._attack_cmd = (cfg.cast_cmd.format(short=sp.get("Short") or sp["Name"], target=tgt).strip(), now)
            self._al_answered = set()                 # a fresh attack of ours: answer whoever joins it
            self.send(self._attack_cmd[0])
        self._melee_on = False

    def misc_tick(self) -> bool:
        """Auto-light in dark rooms, auto-hide while resting, auto-search rooms MME says hide an exit."""
        st, cfg = self.st, self.cfg
        if st.in_combat:
            return False
        dim = cfg.light_dim_rooms and time.time() - self._dim_at < 3
        if cfg.auto_light and cfg.light_cmd and st.view and (st.view.name == "(dark)" or dim) and self.ready("light", 20):
            # learn how dark is too dark for you (race, gear): the MME light of the room you couldn't see in
            k = st.room or getattr(self, "_expect_dark_room", None)
            lr = self.s.world.room(k) if k else None
            if lr is not None:
                self._too_dark = max(getattr(self, "_too_dark", -10 ** 6), int(lr.light or 0))
            self._lit_at = time.time()
            self.send(cfg.light_cmd)
            return True
        if cfg.auto_hide and st.resting and not self._hidden_seq == st.view_seq and self.ready("hide", 30):
            self._hidden_seq = st.view_seq
            self.send(cfg.hide_cmd)
            return True
        if cfg.auto_search and st.room and not self.x.in_any_stash(st.room):
            # (never a stash room: searching turns the hidden stash into loot — 0.8.201, bug hunt)
            # every room, once (Search each room × times): hidden gold and items (Dan, 2026-11-07). Hidden exits on
            # the way are searched by the walker whatever this says ('search north' till it's found — _search_gate)
            if st.room != self._searched_room:
                self._searched_room, self._search_left = st.room, max(int(cfg.search_count or 1), 1)
            if getattr(self, "_search_left", 0) and self.ready("search", 2):
                self._search_left -= 1
                self.send("search")
                if not self._search_left:
                    self.send("")                 # look again: whatever it turned up shows, and the Get button takes it
                return True
        return False

    def set_mode(self, mode: str):
        """MegaMUD manual/auto defaults: apply that mode's switches when walking starts/stops."""
        cfg = self.cfg
        if mode == self._mode:
            return
        self._mode = mode
        if cfg.ignore_mode_defaults:
            return
        d = (cfg.mode_defaults or {}).get(mode) or {}
        changed = False
        for k, v in d.items():
            if k in ("no_hang", "no_wait", "hands_off"):
                continue                              # never switched by a mode — only by you
            if hasattr(cfg, k) and getattr(cfg, k) != v:
                setattr(cfg, k, v)
                changed = True
        if changed:
            self.s.on_settings_changed()

    def maybe_locate(self) -> bool:
        """Lost or unsure which room this is? Ask the board (`pro` on Dan's board) instead of guessing."""
        st, cfg = self.st, self.cfg
        cmd = (cfg.locate_cmd or "").strip()
        dark = time.time() - getattr(st, "dark_at", 0) < 20
        if not cmd or self._locate_failed >= 3 or st.in_combat or st.pending or not (st.view or dark)                 or self.in_deadly():
            return False
        if st.room:
            self._unsure_since = 0.0
            return False
        now = time.time()
        if not self._unsure_since:
            self._unsure_since = now
        # a couple of seconds for the normal tracker to narrow it down by itself first
        if now - self._unsure_since < 2.5 or now - self._locate_at < 15:
            return False
        if self._locate_at and st.locate_ok == self._locate_seen:
            self._locate_failed += 1          # the last `pro` didn't give a room we could read
            if self._locate_failed >= 3:
                self.log(f"'{cmd}' didn't return a room number 3 times — turned it off for this session")
                return False
        self._locate_seen = st.locate_ok
        self._locate_at = now
        st.locate_until = now + 4
        self.status = f"Checking location ({cmd})"
        self.send(cmd)
        return True

    QUEST_CMD_RE = re.compile(r"^\s*(?:say|ask|give|push|pull|press|twist|turn|raise|lift|touch|use|place|put|"
                              r"drop|offer|pray|kneel|read|insert|ring|light|search|dig)\b", re.I)

    def note_quest_cmd(self, cmd):
        """A command that might finish a quest step (said by you or the bot): read 'abil' again shortly. Leading,
        the party's MudPilots check theirs too for a while (Dan, 2026-11-09: tell me when his flag goes up)."""
        if self.QUEST_CMD_RE.match(cmd or ""):
            self._quest_poke = time.time()
            if not getattr(self.x, "_following", None):
                try:
                    self.s.partysync.quest_watch()
                except Exception:
                    pass

    QUEST_WATCH_EVERY = 30        # while a quest watch is on: read 'abil' this often (in a quiet moment)
    LOGIN_QUIET = 20              # the first read of a session: not before this long in the game...
    LOGIN_LATE = 300              # ...and say so once if no quiet moment has come by now

    def _quiet_for_abil(self, now):
        """A dull moment to type 'abil': nothing to fight, nobody strange here, not hurt, not resting, not running.
        None = quiet, else why not (Dan: not straight after hanging up on PvP or getting in with low HP)."""
        st = self.st
        if st.in_combat or st.pending or st.resting or not st.last_prompt or now - st.last_prompt > 3:
            return "busy"
        v = st.view
        if v and v.monsters:
            return "monsters here"
        party = {n.lower() for n in (st.party or {})} | {(self.cfg.my_name or "").lower()}
        if v and any((p or "").split()[0].lower() not in party for p in (v.players or []) if (p or "").split()):
            return "a stranger here"
        if st.max_hp and st.hp_pct() < 80:
            return "hurt"
        try:
            if self.hurrying():
                return "hurrying"
        except Exception:
            pass
        return None

    def flag_name(self, a) -> str:
        w = self.s.world
        return self.st.abil_names.get(int(a)) or (getattr(w, "abil_names", {}) or {}).get(int(a)) or f"ability {a}"

    def is_quest_flag(self, a) -> bool:
        # 'granted' also holds things like ManaRegen(145): only quest flags — the ones exit gates check, or
        # named as quests (DaoLordQuest, GoodQuest…)
        w = self.s.world
        gates = getattr(w, "_gate_abils", None)
        if gates is None:
            gates = w._gate_abils = {int(m.group(1)) for r in w.rooms.values() for ex in r.exits.values()
                                     for m in w.ABIL_GATE_RE.finditer(ex.etype or "")}
        return int(a) in gates or "quest" in self.flag_name(a).lower()

    def flag_text(self, a, v) -> str:
        nm = self.flag_name(a)
        return (f"{nm} ({a})" if not nm.startswith("ability ") else nm) + f" = {v}"

    def _new_quest_flags(self, gained: dict, old: dict | None = None):
        """A quest flag appeared or changed: log it, and tell the party - their MudPilots say who went up (Dan,
        2026-11-09); a MegaMUD leader gets the old '{Quest flag: ...}' telepath."""
        gained = {a: v for a, v in gained.items() if self.is_quest_flag(a)}
        if not gained:
            return
        old = old or {}
        txt = ", ".join(self.flag_text(a, v) + (f" (was {old[a]})" if a in old else "") for a, v in gained.items())
        self.log(f"New quest flag: {txt}")
        try:
            told = self.s.partysync.tell_quest(gained)
        except Exception:
            told = set()
        leader = getattr(self.x, "_following", None)
        if leader and leader.lower() != (self.cfg.my_name or "").lower() and leader.lower() not in told:
            self.send(f"/{leader} {{Quest flag: {txt}}}"[:126])

    def _take_abil_answer(self, now) -> bool:
        """Take in the answer to an 'abil' we sent (4 s after it, once it's all in). Runs every tick, wherever you are:
        it used to wait for a room with no monsters and no items, so in Town Square (small sign, large sign) the answer
        was never saved - Evolution asked the Grey Lord 'box' (NeutralQuest 4 -> 5) and every Go to to Annora still
        planned with 4 (2026-11-05). True = just taken in."""
        st, cfg = self.st, self.cfg
        rd = getattr(self, "_abil_read", None)
        if not (rd and rd[0] == "sent" and now - rd[1] > 4):
            return False
        granted = {str(aid): v for (src, aid), (v, t) in st.abil_rows.items() if src == "granted" and t >= rd[1]}
        if granted:
            old = dict(cfg.known_abils or {})
            cfg.known_abils = granted
            self.s.on_settings_changed()
            gained = {a: v for a, v in granted.items() if old and old.get(a) != v}
            if gained or not old:
                self.s.world.forget_routes()      # quest gates may have opened: plan afresh
            if gained:
                self._new_quest_flags(gained, {a: old[a] for a in gained if a in old})
            elif not getattr(self, "_flags_logged", False):
                self.log(f"Read your quest flags ({len(granted)}) — routing knows which quest gates you've opened")
            self._flags_logged = True
            try:
                self.s.partysync.quest_read(granted)   # a teammate who doesn't know ours yet gets them once
            except Exception:
                pass
        self._abil_read = ("done", now)
        return True

    def _read_quest_flags(self) -> bool:
        """pMUD: read your whole ability table once a session (quest flags among it) so routing knows which
        quest gates are open before it plans — and keep it for next time."""
        now = time.time()
        if self._take_abil_answer(now):
            return False
        rd = getattr(self, "_abil_read", None)
        if rd and rd[0] == "done":
            # read again a few seconds after a quest-style command (say / ask / give / push…), or every half hour:
            # that's how a new quest flag gets noticed
            poke = getattr(self, "_quest_poke", 0)
            watch = getattr(self, "_quest_watch_until", 0) > now and now - rd[1] > self.QUEST_WATCH_EVERY
            if not ((poke > rd[1] and now - poke > 4) or now - rd[1] > 1800 or watch):
                return False
            rd = None
        if rd:
            return False
        first = not getattr(self, "_abil_read", None)
        inside = now - max(self.s._connected_at, getattr(self.s, "_entered_at", 0) or 0)
        if first and inside < self.LOGIN_QUIET:
            return False                              # just in (a hang-up, a relog): not straight away
        why = self._quiet_for_abil(now)
        if why:
            if first and inside > self.LOGIN_LATE and not getattr(self, "_abil_late_said", 0):
                self._abil_late_said = now
                self.log(f"Quest flags: waiting for a quiet moment to read them ({why})")
            return False
        if not self.ready("abil_all", 30):
            return False
        self._abil_read = ("sent", now)
        self.send("abil")
        return True

    def maybe_read_spells(self):
        """Ask the game for the spell list once per session (and after a level-up)."""
        st = self.st
        if self._spells_asked or not st.last_prompt or st.in_combat or st.pending:
            return False
        if time.time() - st.last_prompt > 3:
            return False
        self._spells_asked = True
        self._spells_asked_at = time.time()
        if not (st.char_class or self.cfg.char_class) or not st.level:
            self.send("stat")
        self.send("spells")
        return True

    @staticmethod
    def target_word(mob) -> str:
        """The whole name as the room shows it: 'smash large stitched zombie', never 'smash zombie' - the last word
        alone hit whichever zombie the game found first (Dan, 2026-11-21: "it should use the entire text ... there's
        a handful of areas that'll bite us"). A counted entry ('2 stitched zombies') goes by the monster's own name."""
        shown, rec = mob
        s = re.sub(r"^(?:a|an|the|some)\s+", "", (shown or "").strip(), flags=re.I)
        if not s or re.match(r"^\d+\s", s):
            s = rec["name"] if rec else re.sub(r"^\d+\s+", "", s)
        return s.strip()

    def flee(self, onward=False, retry=False, count=True):
        """Run. Only ever through an exit the room actually shows right now — a wrong guess
        ("There is no exit in that direction!") costs a round while you're being hit. count=False: not a run from
        something too strong (backing off to rest for mana) — not counted by _note_run."""
        st, cfg = self.st, self.cfg
        if not onward and not retry:
            self.x.on_flee()
            self._flee_tried = set()
        tried = getattr(self, "_flee_tried", set())
        here = st.room
        last = st.history[-2] if len(st.history) >= 2 else None
        room = self.s.world.room(here) if here else None
        shown = set(st.view.exits) if st.view and st.view.exits else None
        def ok(d):
            return d not in tried and (shown is None or d in shown)
        dirs = []
        # (the room we came from is the one we just ran out of, a minute ago: not straight back into it — m1018 #2, 12
        #  runs between two rooms, then a hang-up at 22/130 HP)
        rf_ = getattr(self, "_run_from", None)
        fled_from = bool(last and rf_ == last and time.time() - getattr(self, "_flee_at", 0) < 60)
        if room and last and cfg.go_back_if_running and not onward and not fled_from:
            dirs = [d for d, ex in room.exits.items() if ex.to == last and ex.visible and ok(d)]
        if not dirs and shown:
            dirs = [d for d in sorted(shown, key=lambda d: DIRS.index(d) if d in DIRS else 99) if ok(d)]
            if (onward or fled_from) and room and last:    # keep going away, not back into the fight
                away = [d for d in dirs if not (d in room.exits and room.exits[d].to == last)]
                dirs = away or dirs
            if room and rf_ and time.time() - getattr(self, "_flee_at", 0) < 60:
                # (nor back into the room the first run left, a few runs on — fight3 #3)
                away = [d for d in dirs if not (d in room.exits and room.exits[d].to == rf_)]
                dirs = away or dirs
            # plain exits first: a closed door or a trap is a bad way out
            if room:
                dirs.sort(key=lambda d: 0 if (d in room.exits and room.exits[d].kind == "normal") else 1)
        if not dirs and shown is None and room:
            dirs = [d for d, ex in room.exits.items() if ex.kind == "normal" and ok(d)]
        if dirs:
            if cfg.break_before_running and st.in_combat and cfg.break_cmd and not onward and not retry:
                self.send(cfg.break_cmd)
            self.status = f"Running {DIR_WORDS.get(dirs[0], dirs[0])} (HP {st.hp}/{st.max_hp})"
            self.log(self.status)
            self._fled = True
            self._flee_dir, self._flee_at = dirs[0], time.time()
            tried.add(dirs[0])
            self._flee_tried = tried
            if not onward and not retry:
                self._run_left = max(int(cfg.run_distance or 1), 1) - 1
                self._run_from = here
                if count:
                    self._note_run(here)
            self.send(dirs[0].lower())                  # n / se / u … like MegaMUD
        else:
            self._run_left = 0
            self.status = "Low HP — no exit to run to"
            self.log("Can't run: no usable exit here")

    def flee_failed(self):
        """'There is no exit in that direction!' right after running: try the next exit at once."""
        if getattr(self, "_flee_dir", None) and time.time() - getattr(self, "_flee_at", 0) < 4:
            self._flee_dir = None
            self.log("That way out didn't work — trying another exit")
            self.flee(retry=True)

    RUN_WINDOW = 600            # two runs from the same monster in the same room this close together…
    TOO_STRONG_SECS = 1800      # …and it's too strong for you for this long

    def _note_run(self, room):
        """0.8.223 (Dan, fight3 #2): ran from the same monster in the same room twice in 10 minutes — it's too strong
        for you. For 30 minutes the room is kept out of routes (world.user_avoid) and the monster isn't attacked
        unless it starts it, instead of run, rest, walk straight back in, run (the dockhands, the Chrono Lord)."""
        st, now = self.st, time.time()
        recs = [rec for _s, rec in ((st.view.monsters if st.view else None) or []) if rec]
        if not room or not recs:
            return
        try:
            worst = max(recs, key=self.s.danger.mob_dpr)
        except Exception:
            worst = recs[0]
        name = worst.get("name") or "monster"
        runs = {k: v for k, v in (getattr(self, "_runs", None) or {}).items() if now - v[-1] < self.RUN_WINDOW}
        key = (tuple(room), name.lower())
        runs[key] = [t for t in runs.get(key, []) if now - t < self.RUN_WINDOW] + [now]
        self._runs = runs
        if len(runs[key]) < 2:
            return
        runs.pop(key, None)
        ts = self.__dict__.setdefault("_too_strong", {})
        ts[tuple(room)] = (now + self.TOO_STRONG_SECS, name)
        w = self.s.world
        w.user_avoid = frozenset(getattr(w, "user_avoid", None) or ()) | {tuple(room)}
        r = w.room(room)
        self.log(f"Ran from the {name} at {r.name + ' ' if r else ''}{room[0]}/{room[1]} twice — too strong for you: "
                 f"going round that room and leaving the {name} alone for 30 minutes")

    def too_strong_rooms(self) -> frozenset:
        """Rooms you ran from the same monster twice in (see _note_run), for the next 30 minutes."""
        d = getattr(self, "_too_strong", None)
        if not d:
            return frozenset()
        now = time.time()
        for k in [k for k, v in d.items() if v[0] <= now]:
            del d[k]
        return frozenset(d)

    def too_strong_note(self, rooms=None) -> str:
        """'the dockhand at 14/3799 (too strong for you for 25 more minutes)' for the rooms given (all of them by
        default), or ''."""
        d = getattr(self, "_too_strong", None) or {}
        ks = [k for k in (rooms if rooms is not None else self.too_strong_rooms()) if k in d]
        if not ks:
            return ""
        now = time.time()
        return ", ".join(f"the {d[k][1]} at {k[0]}/{k[1]}" for k in ks[:3]) + \
            f" (ran from it twice — too strong for you for {max(1, round((max(d[k][0] for k in ks) - now) / 60))} " \
            f"more minutes)"

    def _stale_combat(self, now):
        """0.8.223 (m1018 #2b): our move landed in another room with monsters in it and 'in combat' is still on from
        the room we left: if none of them has hit us in 6 s and we haven't started a fight here, it's over."""
        st = self.st
        mv = getattr(st, "moved_at", None)
        if not st.in_combat or not mv or mv[0] != st.room or now - mv[1] < 6:
            return
        if getattr(st, "combat_on_at", 0) >= mv[1] or getattr(self, "_attacked_at", 0) >= mv[1]:
            return
        if any(t >= mv[1] for t in (getattr(self, "_aggro", None) or {}).values()):
            return                                   # (one swung at us here, even if it missed)
        st.in_combat = False
        self.log("Moved away from the fight and nothing here has hit us — not in combat any more")

    def _too_strong_mob(self, rec) -> bool:
        nm = ((rec or {}).get("name") or "").lower()
        d = getattr(self, "_too_strong", None)
        if not nm or not d:
            return False
        now = time.time()
        return any(v[0] > now and v[1].lower() == nm for v in d.values())

    # ---------------------------------------------------------- bless / buffs
    # Buff rule (settings.buffs entries):
    #   name      label shown in the UI                     e.g. "Nightmare tap"
    #   cast      command to send                           e.g. "ntap"
    #   ability   ability name as your board prints it      e.g. "Spellcasting" (blank = timer only)
    #   op, value keep ability  >= value  (or <=)           e.g. ">=", 100
    #   every     recast every N seconds (timer rules)      e.g. 300
    #   off_msg   text that means it wore off (optional)    e.g. "nightmare fades"
    #   in_combat allow casting during combat
    #   enabled
    def _check_key(self, b):
        cmd = (b.get("check_cmd") or "").strip()
        return ("probe:" + cmd.lower()) if cmd else "general"

    def _checked_at(self, b):
        k = self._check_key(b)
        return self._abil_checked_at if k == "general" else self._rule_checked.get(k, 0)

    def buff_status(self, b) -> tuple:
        """(needs_cast, description)"""
        st = self.st
        now = time.time()
        key = b.get("cast", "")
        op, want = b.get("op", ">="), int(b.get("value", 0) or 0)

        def judge(val, note=""):
            ok = val >= want if op == ">=" else val <= want
            return (not ok), f"{val:+d}{note} (want {op} {want:+d})"

        if self._buff_off.get(key):
            return True, "wore off"
        ab = str(b.get("ability") or "").strip()
        if ab:
            src = b.get("source") or "spells"
            checked = self._checked_at(b)
            if st.abil_id(ab) is not None or ab.isdigit():
                v = st.abil_value(ab, src, since=checked)
                if v is not None:
                    return judge(v[0])
                if not checked:
                    return False, "waiting for first check"
                if getattr(st, "abil_seen_at", 0) < checked:
                    # the board hasn't answered this check yet (lag, or the reply got lost in spam):
                    # that's "don't know", not "not active" — never recast flux on a missing reply
                    return False, "checking…" if now - checked < 8 else "waiting for an abil reply"
                if now - checked < 1.5:
                    return False, "checking…"
                return judge(0, f" — no {src} line")      # the table came back without it = not active
            v = st.ability(ab)                              # generic "Name: +100" style boards
            if v is not None and v[1] >= checked:
                return judge(v[0])
            return (False, "checking…") if now - checked < 3 else (bool(checked), "not showing")
        if (b.get("check_cmd") or "").strip():           # number-only probe (other boards)
            pk = self._check_key(b)
            v = st.abilities.get(pk)
            checked = self._rule_checked.get(pk, 0)
            if v is None or v[1] < checked:
                return False, "checking…" if now - checked < 4 else "no reading yet"
            return judge(v[0])
        every = int(b.get("every") or 0)
        if not every and self.learned_duration(b):
            every = max(10, self.learned_duration(b) - self.bless_margin(b))   # from 'st'
        if not every and not ab and not (b.get("check_cmd") or "").strip():
            every = self.auto_recast(b) or 0
        if every:
            last = self._buff_cast.get(key, 0)
            left = int(every - (now - last))
            return left <= 0, ("due" if left <= 0 else f"recast in {left}s")
        # MME doesn't know this one's duration: cast it, then recast when the wear-off message shows
        # (learned the first time) — and every 5 minutes as a fallback
        last = self._buff_cast.get(key, 0)
        if not last or now - last > 300:
            return True, "not cast yet" if not last else "5 min since last cast"
        return False, "until it wears off"

    def spell_for_cast(self, cast: str):
        """The MME spell a cast command uses: 'bles', 'cast bles', 'c prot {name}' → that spell."""
        words = [w for w in (cast or "").replace("{name}", "").split() if w.lower() not in ("cast", "c")]
        if words and words[0].lower() == "use" and len(words) > 1:
            # an item's spell ("use crozier" → emerald-tipped crozier → divine intervention, 8 min)
            q = " ".join(words[1:]).lower()
            for g in (getattr(self.s.world, "gear", {}) or {}).values():
                if q in (g.get("name") or "").lower() and 43 in (g.get("abils") or {}):
                    sp = self.s.world.spells.get(int(g["abils"][43]))
                    if sp:
                        return sp
            return None
        for w in words[:2]:
            sp = self.s.spellbook.find(w)
            if sp:
                return sp
        return None

    ST_TIMER_RE = re.compile(r"^(.+?[!.])\s+\((\d+)s\)$")

    def learned_duration(self, b) -> int | None:
        """How long this bless really lasts at your level, as 'st' showed right after a cast (None until seen;
        a level-up makes it relearn, since some blesses get longer)."""
        lvl = self.st.level or self.cfg.char_level      # the game's own level wins over a stale setting
        return int(b["secs"]) if b.get("secs") and b.get("secs_level") == lvl else None

    def _st_line(self, text):
        """'st' output (time-left lines like 'You feel protected! (216s)'): learn each bless's full duration at
        this level from a reading taken just after casting it. (extras._sync_bless lines up the recast.)"""
        now = time.time()
        t = text.strip()
        if re.match(r"^Name:\s+\S.*Lives/CP", t):
            self._st_judge()
            self._st_read, self._st_timer_lines = now, 0
            # the latest bless cast before this reading — a recast after it mustn't hide that this reading
            # came after a cast (0.8.201, bug hunt: stock bless recast loop)
            self._st_cast_before = max(self._buff_cast.values(), default=0)
            return
        m = self.ST_TIMER_RE.match(t)
        if not m or now - getattr(self, "_st_read", 0) > 3:
            return
        self._st_timer_lines = getattr(self, "_st_timer_lines", 0) + 1
        self._st_no_timers = 0                       # this board shows bless time-left (Paradigm)
        msg, secs = m.group(1).strip().lower(), int(m.group(2))
        lvl = self.st.level or self.cfg.char_level
        for b in self.cfg.buffs or []:
            if (b.get("on_msg") or "").strip().lower() != msg:
                continue
            cast_at = self._buff_cast.get(b.get("cast", ""), 0)
            if cast_at and now - cast_at < 30:       # fresh cast: this is (nearly) its full length
                full = secs + int(now - cast_at)
                if b.get("secs_level") != lvl or abs(int(b.get("secs") or 0) - full) > 5:
                    self.log(f"Learned {b.get('name') or b.get('cast')} lasts {full}s at level {lvl} (st)")
                b["secs"], b["secs_level"] = full, lvl

    def _st_judge(self):
        """A finished 'st' reading with no time-left lines although a bless was cast shortly before: most boards'
        'st' doesn't show bless timers (stock MajorMUD). Twice in a row and we stop asking for them."""
        read = getattr(self, "_st_read", 0)
        if not read or getattr(self, "_st_judged", 0) == read or time.time() - read < 3:
            return
        self._st_judged = read
        if getattr(self, "_st_timer_lines", 0):
            return
        recent = any(0 < read - t < 120 for t in self._buff_cast.values()) or \
            0 < read - getattr(self, "_st_cast_before", 0) < 120
        if recent:
            self._st_no_timers = getattr(self, "_st_no_timers", 0) + 1
            if self._st_no_timers == 2:
                self.log("This board's 'st' doesn't show bless time left — going by spell durations instead")

    def _st_due(self, buffs) -> bool:
        """Time to read 'st' for bless timers: a few seconds after casting one, else every 3 minutes — only on a
        board whose 'st' shows them (Paradigm); elsewhere blesses go by MME durations and wear-off messages."""
        if not any((b.get("on_msg") or "").strip() for b in buffs):
            return False
        self._st_judge()
        if getattr(self, "_st_no_timers", 0) >= 2:
            return False
        now = time.time()
        read = getattr(self, "_st_read", 0)
        last_cast = max((self._buff_cast.get(b.get("cast", ""), 0) for b in buffs), default=0)
        fresh_cast = last_cast > read and now - last_cast > 2.5
        return (fresh_cast or now - read > 180) and self.ready("st_timers", 15)

    def _item_bless_waiting(self, b) -> bool:
        """'use crozier' and the pack isn't read yet (just logged in): wait for it rather than guess — straight after
        PVEREV's 0.8.187 restart it cast blind, 'eq emerald-tipped crozier' with the golden chalice still on."""
        if (self.st.carrying or "").strip():
            return False
        m = re.match(r"^\s*use\s+(.+?)\s*$", b.get("cast") or "", re.I)
        if not m:
            return False
        from . import itemspells
        word = m.group(1).lower()
        return any(word in (g.get("name") or "").lower()
                   for items in itemspells.table(self.s.world).values() for g in items)

    def _item_bless_cmds(self, b):
        """'use crozier' on a bless whose item casts a spell (an unlimited-use item MME knows): ['#etc'], which goes
        out as itemspells.expand's swap — remove the off-hand item for a two-hander, equip, use, put things back.
        None when it isn't such an item or it isn't in your pack (the plain equip/cast path then)."""
        m = re.match(r"^\s*use\s+(.+?)\s*$", b.get("cast") or "", re.I)
        if not m:
            return None
        from . import itemspells
        word = m.group(1).lower()
        carrying = self.st.carrying or ""
        have = {n.lower() for n in itemspells._carried(carrying)}
        for al, items in itemspells.table(self.s.world).items():
            for g in items:
                name = (g.get("name") or "").lower()
                if word in name and name in have:
                    # one '#etc': Session.send expands it into the swap (sending the expanded commands here as well
                    # would do the swap twice — its 'use …' gets expanded again while the crozier isn't on yet)
                    return [al] if itemspells.expand(self.s.world, al, carrying) else None
        return None

    def bless_msgs_tick(self):
        """Now and then: bless start / end lines from the Messages file (extras.fix_bless_messages)."""
        if self.ready("bless_msgs", 600):
            try:
                self.x.fix_bless_messages()
            except Exception as ex:
                self.log(f"Bless messages: couldn't check them ({ex})")

    def auto_recast(self, b) -> int | None:
        """Default recast time for a timer bless: the spell's duration (MME) minus the margin."""
        from .spells import default_recast
        sp = self.spell_for_cast(b.get("cast") or "")
        return default_recast(sp, self.cfg.char_level or self.st.level, self.bless_margin(b))

    def bless_margin(self, b) -> int:
        """How long before a bless runs out to recast it: the margin setting — and for one that gives AC or DR,
        at least 5% of its duration (Dan: an AC bless lapsing is a big difference in the damage you take)."""
        base = int(self.cfg.bless_margin_secs or 15)
        sp = self.spell_for_cast(b.get("cast") or "")
        ids = {int(a[0]) for a in ((sp or {}).get("abils") or []) if len(a) >= 2 and a[0] is not None}
        if not ids & {2, 7}:                       # MME ability 2 = AC, 7 = DR
            return base
        from .spells import spell_duration
        dur = self.learned_duration(b) or spell_duration(sp, self.cfg.char_level or self.st.level) or 0
        return max(base, int(dur * 0.05))

    PRELUDE_RE = re.compile(r"makes a quick grasping gesture|speaks a vile word|begins to chant|raises (?:its|his|her) "
                            r"(?:arms|hands)|eyes begin to glow|gathers? (?:its|dark) power", re.I)

    def buffs_tick(self, mobs, in_range) -> bool:
        st, cfg = self.st, self.cfg
        if self.hurrying() and not getattr(self.x, "_following", None):
            return False                 # timed pyramid, leading: no bless, abil or st upkeep — every second counts
            #                              (followers keep blessing: they don't set the pace — Dan, 2026-11-04)
        if time.time() - getattr(self, "_prelude_at", 0) < 2.5:
            return False                 # a monster is winding up a spell (hold/stun?): keep the round free
        buffs = [b for b in (cfg.buffs or []) if b.get("enabled", True) and b.get("cast")]
        if not buffs:
            return False
        now = time.time()
        # per-rule checks like "abil 145" (one at a time, never mid-fight)
        if not st.in_combat and not st.abil_probe:
            for b in buffs:
                cmd = (b.get("check_cmd") or "").strip()
                if not cmd:
                    continue
                pk = self._check_key(b)
                every = max(8, int(b.get("check_secs") or cfg.abil_check_secs))
                if now - self._rule_checked.get(pk, 0) >= every:
                    self._rule_checked[pk] = now
                    if not str(b.get("ability") or "").strip():
                        nums = {int(n) for n in re.findall(r"\d+", cmd)}
                        st.abil_probe = (pk, now + 3, nums, cmd)
                    self.send(cmd)
                    return True
        # bless timers from 'st' (Paradigm): costs no round, so fine mid-fight too
        if cfg.bless_st_timers and not st.resting and self._st_due(buffs):
            self.send("st")
            return True
        # periodic ability check (never interrupts a fight)
        if cfg.abil_check_cmd and any(b.get("ability") and not (b.get("check_cmd") or "").strip()
                                      for b in buffs) and not st.in_combat and not st.abil_probe:
            if now - self._abil_checked_at >= max(10, cfg.abil_check_secs):
                self._abil_checked_at = now
                st.abil_capture_until = now + 3
                self.send(cfg.abil_check_cmd)
                return True
        # mid-fight: only just after a round has gone off, so the attack is armed again before the next one
        # and no round is lost (casting a bless takes you out of combat)
        window_ok = not st.in_combat or self.just_after_round()
        for b in buffs:
            if st.in_combat and not (cfg.bless_in_combat or b.get("in_combat")):
                continue
            if st.resting and not st.in_combat and not (cfg.bless_while_resting or b.get("while_resting")):
                continue
            prio = bool(b.get("priority") or b.get("in_combat"))
            if mobs and in_range and cfg.auto_combat and not prio and not (st.in_combat and cfg.bless_in_combat):
                continue          # fight first; Priority blesses go up even with monsters here (MegaMUD)
            if st.in_combat and not window_ok:
                continue          # wait for the start of the next round
            need, why = self.buff_status(b)
            key = b["cast"]
            if not need:
                if not why.startswith(("checking", "waiting")):
                    self._rerolls.pop(key, None)       # target met — reset the reroll counter
                continue
            if now - self._buff_cast.get(key, 0) < 4:
                continue  # just cast it; give the re-check time to come back
            nx = getattr(self, "_buff_noeffect", {}).get(key)
            if nx and nx[0] >= 3 and now - nx[1] < 600:
                self.buff_note[key] = "skipped — the game says 'Your command had no effect' (not a spell you have?)"
                continue
            if self._item_bless_waiting(b):
                continue  # an item's spell: wait until the pack has been read, so the swap is known
            if not self.may_cast():
                return False      # a spell already went out this round
            # guardrails so chasing a good roll can't drain you dry
            floor = int(b.get("min_mana_pct", 25) or 0)
            if st.max_ma and floor and st.ma_pct() < floor:
                self.buff_note[key] = f"holding — mana below {floor}%"
                continue
            sp_ = self.spell_for_cast(key) if st.max_ma and not re.match(r"\s*use\s", key, re.I) else None
            if sp_ and int(sp_.get("ManaCost") or 0) > st.ma:
                # it would only get "You do not have enough mana" (0.8.201, bug hunt)
                self.buff_note[key] = f"holding — not enough mana ({sp_.get('ManaCost')} needed)"
                continue
            tries = self._rerolls.get(key, 0)
            cap = int(b.get("max_rerolls", 8) or 0)
            if cap and tries >= cap:
                if not (why.startswith("wore off") or " — no " in why):
                    # out of casts with a low roll up: keep it until it wears off (a fresh set of casts every
                    # minute burned 8 flux casts in 95 s — ~160 mana — chasing +110)
                    self.buff_note[key] = f"keeping {why.split(' (')[0]} until it wears off ({tries} casts)"
                    continue
                tries = 0
            self._rerolls[key] = tries + 1
            self._buff_cast[key] = now
            self._buff_off.pop(key, None)
            self.buff_note.pop(key, None)
            label = b.get("name") or key
            self.status = f"Casting {label} ({why})" + (f" — reroll {tries}" if tries else "")
            self.log(self.status)
            eq = (b.get("equip_cmd") or "").strip()
            back = (b.get("unequip_cmd") or "").strip()
            fighting = st.in_combat
            seq = None if back else self._item_bless_cmds(b)
            if seq:
                # an item's spell: the same swaps as '#etc' — a two-hander needs the off-hand item off first, then
                # weapon and off-hand go back (Dan, 2026-11-12: PVEREV's crozier never went on — "You may not
                # ready a 2-handed weapon with your golden chalice worn!" — so divine intervention never went up)
                for c in seq:
                    self.send(c)
            else:
                if eq and not back:
                    from .gamestate import wielded
                    was = wielded(st.carrying or "")
                    back = f"eq {was}" if was else ""
                if eq:
                    self.send_macro(eq)               # e.g. wield emerald-tipped crozier
                self.send(b["cast"])
                if eq and back:
                    self.send_macro(back)             # …and your weapon goes straight back in hand
            self.x.note_cast_buff(key)
            if fighting:
                self._cool["cast"] = 0            # re-arm the attack straight after (fight() sees *Combat Off*)
                ac = getattr(self, "_attack_cmd", None)
                if ac and now - ac[1] < 60:
                    # the bless stopped the attack the game was repeating: put it straight back (Evolution,
                    # 2026-11-01: "no attack of ours for 8–15 s while being hit" 188 times a day, after skin / star)
                    self.send(ac[0])
                    self._cast_sent_at = now
            # re-check ~2s after casting so a bad roll is rerolled quickly
            if (b.get("check_cmd") or "").strip():
                pk = "probe:" + b["check_cmd"].strip().lower()
                self._rule_checked[pk] = now - max(8, int(b.get("check_secs") or cfg.abil_check_secs)) + 2
            elif b.get("ability") and cfg.abil_check_cmd:
                self._abil_checked_at = now - max(10, cfg.abil_check_secs) + 2
            return True
        return False

    PORTAL_CMD_RE = re.compile(r"^(?:go|enter|step|jump|climb|dive|walk|crawl|swim|touch|pull|push|say)\b", re.I)

    def portal_cmd_just_sent(self, secs=5.0):
        """The portal / room command you (or the path) sent in the last few seconds, if any."""
        now_ = time.time()
        b = getattr(self, "_bring", None)
        if b and b.get("cmd") and now_ - b["t"] < secs:
            return b["cmd"]
        return next((c for t_, c in reversed(getattr(self.s, "_recent_sent", []))
                     if now_ - t_ < secs and c and c.upper() not in DIR_WORDS and c.lower() not in DIR_WORDS.values()
                     and not c.startswith(("@", ".", "/")) and self.PORTAL_CMD_RE.match(c)), None)

    SOLO_RE = re.compile(r"^you are not in a party", re.I)
    PARTY_NEWS_RE = re.compile(r"\b(?:joined|joins) your (?:travel )?party|^you (?:have invited|are now following|have "
                               r"joined|join)\b|is now following you|invites you to (?:join|follow)|"
                               r"^the following people are in your travel party", re.I)

    PICKS_UP_RE = re.compile(r"^(\w+) picks up (?:an? |the |some )?(.+?)\.?$")

    def _melee_immune_map(self) -> dict:
        m = getattr(self, "_melee_immune", None)
        if isinstance(m, set):                       # (older shape: no weapon recorded)
            m = self._melee_immune = {k: "" for k in m}
        return m or {}

    def _melee_immune_now(self) -> set:
        """Monsters the weapon in hand can't hurt ("Your weapon has no effect…" seen with this weapon)."""
        wpn = self._wielded_now().lower()
        return {k for k, w in self._melee_immune_map().items() if not w or not wpn or w == wpn}

    # ── weapon swap for monsters that need a more magical weapon (Dan, 2026-11-16: Buddy's holy avenger, magic 3,
    #    can't hurt the copsewights in Hidden Copse, magic 4; his ice crystal falchion can — "have it equip an item
    #    that would allow it to attack rather than not attack") ──
    def _knocked_down_now(self) -> bool:
        """Knocked off our feet / held just now: the game says 'Your command had no effect.' to the path's step
        because we can't move, not because we're in another room (Dan, 2026-11-16: the Stonecaps knockdowns had
        Miserable asking 'pro' every few minutes, and every answer was the room it already thought)."""
        now = time.time()
        try:
            mr = self.s.msgrules
            if "held" in mr.conditions or now - (getattr(mr, "cleared_at", {}) or {}).get("held", 0) < 5:
                return True     # (or just got up: the step's 'no effect' can come a moment after 'held gone', 15:50:34)
        except Exception:
            pass
        return any(now - float(self.x.ailments.get(k) or 0) < 10 for k in ("knocked", "held", "stunned"))

    def _wielded_now(self) -> str:
        """The weapon in hand: the game's "You are now holding X" until the pack is read again."""
        h = getattr(self, "_held", None)
        if h and getattr(self, "_inv_stale", False):
            return h
        return wielded_(self.st.carrying or "")

    def _gear_named(self, name):
        nm = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "")).strip().lower()
        if not nm:
            return None
        idx = getattr(self, "_gear_idx", None)
        if idx is None:
            idx = self._gear_idx = {(g.get("name") or "").lower(): g
                                    for g in (getattr(self.s.world, "gear", {}) or {}).values()}
        return idx.get(nm)

    def _wpn_magic(self, name) -> int | None:
        g = self._gear_named(name)
        return int((g.get("abils") or {}).get(28, 0) or 0) if g else None

    def _needs_better_weapon(self, rec) -> bool:
        """MME says the monster needs a weapon more magical than the one in hand (hit-magic, abil 28)."""
        if not getattr(self.cfg, "auto_weapon_swap", True) or not rec:
            return False
        need = int(((rec.get("abils") or {}).get(28, 0)) or 0)
        if not need:
            return False
        cur = self._wpn_magic(self._wielded_now())
        return cur is not None and cur < need

    def _swap_weapon_for(self, rec, nm, label="") -> bool:
        """Wield a carried weapon that can hurt this monster: magical enough for it (MME), not already seen
        failing on it, the least magical that does it and then the hardest-hitting. Your own weapon goes back on
        once the fight's over (_weapon_swap_back)."""
        if not getattr(self.cfg, "auto_weapon_swap", True) or not self.ready("weapon_swap", 6):
            return False
        from .itemspells import _carried
        st = self.st
        cur = self._wielded_now()
        if not cur:
            return False                                # bare hands / martial arts: nothing to swap
        cur_m = self._wpn_magic(cur) or 0
        need = int((((rec or {}).get("abils") or {}).get(28, 0)) or 0)
        failed = getattr(self, "_wpn_failed", set())
        best = None
        for n in _carried(st.carrying):
            g = self._gear_named(n)
            if not g or int(g.get("ItemType") or -1) != 1 or n.lower() == cur.lower() or (nm, n.lower()) in failed:
                continue
            m = int((g.get("abils") or {}).get(28, 0) or 0)
            if m <= cur_m or (need and m < need):
                continue
            k = (m, -(int(g.get("Min") or 0) + int(g.get("Max") or 0)))
            if best is None or k < best[0]:
                best = (k, n)
        if not best:
            return False
        n = best[1]
        if not getattr(self, "_wpn_swap_back", None):
            self._wpn_swap_back = self.cfg.main_weapon or cur
        self._wpn_try = (nm, n.lower(), time.time())
        self.log(f"{cur} can't hurt {label or nm} — switching to {n} (magic {best[0][0]}) and attacking again")
        self.status = f"Switching to {n} for {label or nm}"
        self.send(f"eq {n}")
        self.send("i")                                  # (re-read: what's in hand now)
        self._melee_on = False
        self._attack_sent_at = 0
        return True

    def _weapon_swap_back(self):
        """After a swap: your own weapon again once nothing here needs the other one and the fight's over."""
        back = getattr(self, "_wpn_swap_back", None)
        st = self.st
        if not back or st.in_combat or not self.ready("weapon_back", 4):
            return
        cur = self._wielded_now()
        if cur.lower() == back.lower():
            self._wpn_swap_back = None
            return
        bm = self._wpn_magic(back) or 0
        failed = getattr(self, "_wpn_failed", set())
        for sh, rec in ((st.view.monsters if st.view else None) or []):
            nm = ((rec or {}).get("name") or sh).lower()
            if (nm, back.lower()) in failed or int((((rec or {}).get("abils") or {}).get(28, 0)) or 0) > bm:
                return                                  # still one here only the swapped weapon can hurt
        self._wpn_swap_back = None
        self.log(f"Fight over — back to {back}")
        self.send(f"eq {back}")
        self.send("i")

    def note_line(self, text: str):
        low = text.lower()
        st = self.st
        self._st_line(text)
        self.manual.note_line(text)
        self.redress.note_line(text)
        self.errands.note_line(text)
        self.lights.note_line(text)
        if self.__dict__.get("_token_router") is not None:
            self._token_router.note_line(text)    # a teleport token that didn't go: walk instead (tokens.py)
        if hasattr(self.s, "scrolls"):
            self.s.scrolls.note_line(text)
        if hasattr(self.s, "training"):
            self.s.training.note_line(text)
        self.peruse.note_line(text)
        self.s.remote.note_invite(text)
        if "doors on this level creak and thump" in low:
            self._creak_at = time.time()          # this level's doors open and shut by themselves
        mpu = self.PICKS_UP_RE.match(text.strip())
        if mpu and mpu.group(1) in (st.party or {}) and mpu.group(1).lower() != (self.cfg.my_name or "").lower():
            task = (getattr(self.s.world, "room_tasks", None) or {}).get(st.room)
            if task and task["item_name"] in mpu.group(2).lower():
                self._task_holder = (mpu.group(1), time.time())
        if self.OWN_ATTACK_RE.match(text.strip()):
            self._own_attack_at = time.time()
        if self.SOLO_RE.match(text.strip()):
            self._solo = True                    # solo: party checks stop until there's party news
        elif self.PARTY_NEWS_RE.search(text.strip()):
            self._solo = False
        ml = re.match(r"^(\w+) is no longer following you\.?$", text.strip())
        if ml and not getattr(self, "_bring", None):
            # you typed (or walked) a portal command and the party broke on it (a vortex does that): same as
            # a path step — get them through after you
            now_ = time.time()
            cmd = self.portal_cmd_just_sent()
            if cmd and self.cfg.party_teleport_bring:
                self._bring = {"dest": None, "names": [ml.group(1)], "t": now_, "from": None, "cmd": cmd,
                               "broke": True, "typed": True}
        self._deadly_line(text)
        self._desert_drink(text)
        mp_ = re.match(r"^you (?:picked up|took|get|pick up)\s+(?:an?\s+|the\s+|\d+\s+)?(.+?)[.!]?$", text.strip(), re.I)
        if mp_:
            nm_ = mp_.group(1).strip().lower()
            num_ = next((n for n, it in self.s.world.items.items() if (it.get("name") or "").lower() == nm_), None)
            if num_ is not None:
                self._picked_items = self.picked_items() | {num_}
                self._picked_seq = st.inv_seq
        if self.HURRY_RE.search(text):
            v_ = st.view
            if not getattr(self, "_hurry", None):     # (levels 1 and 2 are timed: until you reach level 3)
                self._hurry = {"until": time.time() + 1200, "area": "great pyramid", "up_from": None, "ups": 0}
            self._no_rest_until = self._hurry["until"]
            self.log("Pyramid timer — until level 3: no resting, no @wait, no stopping to fight (unless HP is "
                     "low); only a held / knocked-down party member is waited for")
        ma = re.match(r"^([A-Z][a-z'-]+) (?:appears in a flash of light|steps out of|walks into the room|"
                      r"arrives|appears|emerges|climbs|crawls|drops|falls)\b", text.strip())
        bb = getattr(self, "_bring", None)
        if ma and bb and any(n.lower() == ma.group(1).lower() for n in bb.get("names", [])):
            # one we're waiting on just came through: look now (don't wait for the 4 s re-look) so the
            # invite goes straight out
            if self.ready("bring_arrive", 1):
                self.send("")
        mh = re.match(r"^You cast (.+?) on (\w+), healing (\d+) damage", text.strip())
        me_ = ((self.cfg.my_name or "").split() or [""])[0].lower()
        if mh and me_ and mh.group(2).lower() == me_:
            hs = self.smart._spell(self.cfg.heal_cmd)
            if hs and (hs.get("Name") or "").lower() == mh.group(1).lower():
                self.smart.learn_heal(int(mh.group(3)))      # smart resting: how much the heal really gives
        if re.search(r"^you attempt to cast .*(?:but|and) fail|^you fail to cast|^your spell fails", low):
            self.smart.rgen_fizzled()
            bc = getattr(self, "_buff_cast", {})
            if bc:
                k, t = max(bc.items(), key=lambda kv: kv[1])
                if time.time() - t < 4:
                    # a fizzle isn't a roll: don't count it toward 'max casts in a row', and try again next round
                    if self._rerolls.get(k):
                        self._rerolls[k] -= 1
                    self._buff_cast[k] = time.time() - 3
        if low.strip() == "your command had no effect.":
            # Dan, 2026-11-18: Revolution (druid) had a 'flux' rule — a mage spell — and sent it 8 times in a row,
            # each 'Your command had no effect.'. Three in a row: leave that rule alone for 10 minutes and say why
            # (one could be a knockdown or a hold)
            bc = getattr(self, "_buff_cast", {})
            recent = [kv for kv in bc.items() if time.time() - kv[1] < 4]
            if len(recent) > 1:
                # (0.8.224, real logs: flux — a mage spell — and ntap went out together; ntap, the druid's real one,
                #  got the blame and was switched off for 10 min. Blame the one that isn't a spell we have, or none)
                odd = [kv for kv in recent if self._cmd_spell(kv[0], kv[0].split()) is None]
                bc = dict(odd) if len(odd) == 1 else {}
            if bc:
                k, t = max(bc.items(), key=lambda kv: kv[1])
                if time.time() - t < 4:
                    nx = self.__dict__.setdefault("_buff_noeffect", {})
                    n_ = (nx.get(k, (0, 0))[0] if time.time() - nx.get(k, (0, 0))[1] < 120 else 0) + 1
                    nx[k] = (n_, time.time())
                    if self._rerolls.get(k):
                        self._rerolls[k] -= 1
                    if n_ == 3:
                        self.log(f"'{k}': 'Your command had no effect' 3 times — skipping it for 10 min. Is it a "
                                 f"spell this character has? (Settings → Bless / abilities)")
        if re.match(r"^you do not have enough mana", low):
            # a bless that never went off: it isn't up (a timer bless counted as up for its whole length), and it
            # isn't a reroll (0.8.201, bug hunt: "not enough mana" for blesses)
            bc = getattr(self, "_buff_cast", {})
            if bc:
                k, t = max(bc.items(), key=lambda kv: kv[1])
                if time.time() - t < 4:
                    if self._rerolls.get(k):
                        self._rerolls[k] -= 1
                    self._buff_cast[k] = time.time() - 3
                    self._buff_off[k] = True
        if self.PRELUDE_RE.search(text) and not low.startswith("you"):
            self._prelude_at = time.time()
            self.why("prelude", line=text.strip()[:80])
        mp_ = re.match(r"^(?:the |an? )?(.+?) moves to protect (?:the |an? )?(.+?)[.!]", text.strip(), re.I)
        if mp_:
            self._protector = (mp_.group(1).lower(), mp_.group(2).lower(), time.time())
        mne = re.match(r"^your spell has no effect on (?:the |an? )?(.+?)[.!]?$", low)
        if mne and getattr(self, "_drain_track", None) and time.time() - getattr(self, "_cast_sent_at", 0) < 8:
            nm_ = mne.group(1).strip()
            if nm_ not in getattr(self, "_drain_immune", set()):
                self._drain_immune = getattr(self, "_drain_immune", set()) | {nm_}
                self.log(f"Can't drain {nm_} (no effect) — won't try again")
        # 0.8.200 (MudPlay's notes): the game's own "too fast" lines. Stock drops a telepath past 4 per 3 s per
        # receiver — an @command that never arrived; send it again once, a moment later
        if "telepath not sent" in low:
            lt = getattr(self.s, "_last_tp", None)
            if lt and time.time() - lt[1] < 5 and getattr(self, "_tp_resent", None) != lt:
                self._tp_resent = lt
                self._tp_resend = (lt[0], time.time() + 2.0)
        elif re.search(r"typing too quickly|command ignored|too many messages sent|why don'?t you slow down", low):
            if self.ready("too_fast_note", 60):
                self.log(f"The game says we're sending too fast: '{text.strip()}'")
        # 0.8.200 (MudPlay's notes): the game refuses the rest — don't resend it every 4 s
        if re.match(r"^you are too sick to rest", low):
            self._sick_rest_until = time.time() + 30
        elif re.match(r"^you are too sick to meditate", low):
            self._sick_med_until = time.time() + 30
        elif low.startswith("meditation will not help at this time"):
            if st.ma:
                st.max_ma = st.ma                    # mana's full: our max was stale (gear changed it)
            self._sick_med_until = time.time() + 10
        if "too heavy to move" in low:
            self._heavy_move_at = time.time()
            if not getattr(self, "_heavy_since", 0) or time.time() - self._heavy_move_at_prev > 30:
                self._heavy_since = time.time()
            self._heavy_move_at_prev = time.time()
        if "too heavy to move" in low and self.ready("heavy_move_i", 20):
            self.log("Too heavy to move — reading the pack")
            self.send("i")                           # (makeroom / drop rules work from a fresh pack)
        gr = getattr(st, "gate_refused", None)
        if gr and time.time() - gr[3] < 2 and getattr(self, "_gate_seen", None) != gr[3]:
            self._gate_seen = gr[3]
            key = (gr[0], str(gr[1]).lower())
            hits = [t for t in getattr(self, "_gate_hits", {}).get(key, []) if time.time() - t < 120] + [time.time()]
            self._gate_hits = {**getattr(self, "_gate_hits", {}), key: hits}
            if len(hits) >= 2 and (self.walking or self.path):
                where = f" at {gr[0][0]}/{gr[0][1]}" if gr[0] else ""
                why = f"Stopped: '{gr[2]}' going {gr[1]}{where} — that gate won't let this character through"
                self.stop(why)
                self.s.on_alert(why)
                self.s.notify.send("stop", why)
        if re.match(r"^your (?:weapon|fists|feet) (?:has|have) no effect against", low):   # (fists/feet: martial arts, 0.8.200)
            tgt = ""
            if st.view and st.view.monsters:
                tgt = ((st.view.monsters[0][1] or {}).get("name") or st.view.monsters[0][0])
            tgt = getattr(self, "_melee_target", None) or tgt
            if self.manual.active:
                # (0.8.201, bug hunt: you're fighting it by hand — it's your target, not the one MudPilot last
                # swung at; the orc it killed earlier got marked immune and froze the next orc fight)
                tgt = next(((r or {}).get("name") or sh for sh, r in ((st.view.monsters if st.view else None) or [])
                            if sh == self.manual.mob), self.manual.mob)
            if tgt:
                # remembered for the weapon in hand only (0.8.200, Dan: Buddy's holy avenger couldn't hurt the
                # copsewights; he switched to the ice crystal falchion, which can, and still never swung at them)
                wpn = self._wielded_now().lower()
                self._melee_immune = {**self._melee_immune_map(), tgt.lower(): wpn}
                if wpn:
                    self._wpn_failed = getattr(self, "_wpn_failed", set()) | {(tgt.lower(), wpn)}   # (survives swaps)
                self.log(f"Your weapon{f' ({wpn})' if wpn else ''} has no effect on {tgt} — won't melee it with that "
                         "one (spells still fine)")
        if re.match(r"^you (?:are now (?:holding|wielding)|wield) ", low):
            # ("You have removed holy avenger." / "You are now holding ice crystal falchion." — Buddy's swap)
            # a different weapon in hand: what the old one couldn't hurt, this one may (the pack's re-read shows it)
            if self._melee_immune_map():
                self._melee_immune = {}
                self.log("Weapon changed — trying melee again on monsters the old weapon couldn't hurt")
        mk = re.match(r"^([A-Z][a-z]+) (?:is knocked (?:down|flat|to the ground|off (?:his|her|their) feet)|is stunned|"
                      r"is held|falls to the ground|"
                      r"is paralyzed|is webbed)", text.strip())
        if mk and any(n.lower() == mk.group(1).lower() for n in st.party) and \
                mk.group(1).lower() != (self.cfg.my_name or "").lower():
            # pMUD: a party member can't move — the leader waits for them (12 s), then checks the party
            self.hold("member down", f"{mk.group(1)} can't move")
            self._member_down_until = time.time() + 12
            self._cool["par"] = time.time() - float(self.cfg.party_check_secs or 5) + 1; self._par_soon_until = time.time() + 20
        md = re.search(r"\b(?:you|hits?|bites?|claws?|slashes|smashes|stabs|crushes|burns|shocks?|strikes?)\b.*?\b"
                       r"([A-Z][a-z]+) for (\d+) damage", text)
        if md and md.group(1) in st.party and md.group(1).lower() != (self.cfg.my_name or "").lower() \
                and int(md.group(2)) >= 30 and not text.lower().startswith("your "):
            self._cool["par"] = min(self._cool.get("par", 0), time.time() - float(self.cfg.party_check_secs or 5) + 1); self._par_soon_until = time.time() + 20
        mh = re.match(r"^(\w+) casts (.+?) on (\w+)", text.strip())
        if mh and mh.group(1).lower() != (self.cfg.my_name or "").lower() and \
                re.search(r"heal|cure|mend|restor|regenerat|vigor|life", mh.group(2), re.I):
            tgt = mh.group(3)
            if tgt.lower() == "you":
                tgt = self.cfg.my_name or tgt
            if any(n.lower() == tgt.lower() for n in self.st.party):
                # someone else just healed them: that 'par' is out of date — wait for a fresh one
                self._pheal_at[tgt.lower()] = time.time()
                self._cool["par"] = time.time() - float(self.cfg.party_check_secs or 5) + 1; self._par_soon_until = time.time() + 20
        if "already cast a spell this round" in low:
            left = self.s.clock.left()
            self._cast_block_until = time.time() + ((left[0] if left else 2.5) + 0.2)
        if low.startswith("you may not sneak right now"):
            self._no_sneak_room = st.room             # move on without sneaking here, don't spam 'sn'
        self.x.note_line(text)
        self._note_aggro(text)
        self._search_line(text)
        self._disarm_line(text)
        if self.cfg.eco_travel:
            self.eco_note_hit(text)
        if low.startswith("your ") and re.search(r"\bfor \d+ damage", low):
            self._last_hit_at = time.time()           # our spell/attack is landing
        mh_ = self.HEALED_RE.match(low) if low.startswith("you cast ") else None
        if mh_ and mh_.group(2) == (self.cfg.my_name or "").lower():
            hs = self.__dict__.setdefault("_heal_seen", {})
            hs[mh_.group(1)] = (hs.get(mh_.group(1)) or [])[-5:] + [int(mh_.group(3))]
        if re.match(r"^you gain [\d,]+ experience", low):
            self._kill_at = time.time()               # the room list is stale until it's shown again (fight())
        elif not low.startswith(("you ", "your ")) and re.search(
                r"turns to dust|dies in a heap|breathes its last|falls to the ground dead|collapses (?:in a heap|dead)",
                low):
            # the death line comes before 'You gain … experience' — Evolution's 'fist nightshade' went out in between:
            # "You don't see nightshade here!" (2026-11-11). Same wait for the room to show again
            self._kill_at = time.time()
        if "combat off" in low:
            mine = time.time() - max(getattr(self, "_last_spell_at", 0), getattr(self, "_al_sent_at", 0)) < 0.8
            if not mine:
                self._cast_target = None
                self._area_armed = 0                  # the area spell stopped: send it again if still crowded
            # (a *Combat Off* right after our own attack went out is that re-send toggling combat, not the fight
            # ending — treating it as the end sent the spell again, which toggled it again: Evolution, 2026-11-01,
            # 5 'swar's for one bat)
        wt = getattr(self, "_wpn_try", None)
        if wt and time.time() - wt[2] < 5 and re.match(r"^you (?:may not|can ?not|can't|are not (?:strong|able)|"
                                                        r"don't have|do not have)\b", low):
            # the game wouldn't let us wield it (two-hander with a shield on, too weak, class…): not for this one
            self._wpn_failed = getattr(self, "_wpn_failed", set()) | {(wt[0], wt[1])}
            self._wpn_try = None
            self.log(f"Couldn't wield {wt[1]} — not trying it on {wt[0]} again")
        if getattr(self, "_bs_back", None) and ("combat engaged" in low or "combat off" in low or "backstab" in low):
            w_, self._bs_back = self._bs_back, None
            self.send(f"eq {w_}")                          # …then your usual weapon again
        lw = getattr(self, "_loot_wait", None)
        if lw and lw[1] > 0 and re.match(r"^(you picked up|you took|you get|you don't see|you can't carry|"
                                        r"you are carrying too much|that is too heavy|you cannot)", low):
            lw[1] -= 1
        if re.match(r"^you are surrounded by .*\band vanish|^with a sickening lurch, you fall|^you re-appear\b|"
                    r"^you fall (?:down|through)|^the floor (?:gives way|opens)", low):
            self._flung_at = time.time()             # a trap moved us: whoever isn't here got left, not 'behind a door'
        if re.match(r"^you (?:are now wearing|are now holding|have removed|remove) ", low):
            mh = re.match(r"^you are now holding (?:an? |the )?(.+?)\.?$", text.strip(), re.I)
            if mh:
                self._held = mh.group(1)
            self._inv_stale = True                    # the gear changed: re-read 'i' before auto regen gear plans
        elif low.startswith("you are carrying ") and not low.startswith("you are carrying too"):
            self._inv_stale = False                   # the post-rest 'i' (sent after the swap back) is in
        mz = re.match(r"^you picked up 0 (.+?)[.!]?$", low)
        if mz:
            # 'You picked up 0 gold crown': too heavy to carry another coin (hauling). Read the inventory again and
            # leave that pile alone here for a while, instead of asking for it every look
            self._no_coin = {k: t for k, t in getattr(self, "_no_coin", {}).items() if time.time() - t < 300}
            self._no_coin[(st.room, coin_kind(mz.group(1).strip()) or mz.group(1).strip())] = time.time()   # "gold crown" vs the room's "40 gold crowns"
            if self.ready("zero_coin_inv", 30):
                self.log(f"Picked up 0 {mz.group(1)} — too heavy? Re-reading the inventory and leaving it here")
                self.send("i")
        if ("no exit in that direction" in low or "can't go that way" in low or "cannot go that way" in low)                 and self._rush_retry():
            return
        if "no exit in that direction" in low or "can't go that way" in low or "cannot go that way" in low:
            self.flee_failed()
            key = (getattr(self, "_resends", None) or (None, 0))[0]
            ne = getattr(self, "_no_exit", None)
            dark_ = st.view is not None and st.view.name == "(dark)"
            lc_ = getattr(st, "located", None)
            if dark_ and self.walking and self.path and key and ne and ne[0] == key and time.time() - ne[1] < 90 and \
                    not (lc_ and tuple(lc_[0]) == tuple(st.room or ()) and lc_[1] >= ne[1] - 1):
                # (in the dark nothing shows we're where we think: ask 'pro' again — its answer was in already, so
                #  the 6 s limit doesn't hold it back — before calling it a wall. A real exit was walled for 2 hours,
                #  then the way round from the wrong room walled more and it stopped: dark3 D1)
                if not getattr(st, "locate_until", 0) or st.locate_until < time.time():
                    self._locate_at = 0
                if self.locate_now("no exit, in the dark"):
                    self._no_exit = (key, time.time())
                    return                           # (no 'pro' to be had: as before, below)
            if self.walking and self.path and key and st.room and key[0] == st.room and not st.in_combat \
                    and ne and ne[0] == key and time.time() - ne[1] < 90:
                # the second time from a room we're sure of: a wall, not a miss — go round it now, and a Go to
                # doesn't come back to try it again (Dan: try once, never run into the wall over and over)
                self._no_exit, self._resends = None, (None, 0)
                rm = self.s.world.room(st.room)
                mv = key[1]
                d = next((ex.dir for ex in (rm.exits.values() if rm else [])
                          if ex.dir.lower() == mv or ex.accepts(mv)), mv.upper())
                self.s.world.wall(st.room, d)
                if not self.route_around(st.room, d, f"there's no exit {mv} from {st.room[0]}/{st.room[1]} "
                                                     "(the game says so)"):
                    self.stop(f"Stopped: no exit {mv} from {st.room[0]}/{st.room[1]} and no other way on MME's map")
                return
            if key:
                self._no_exit = (key, time.time())
            if self.walking and st.view is not None and st.view.name == "(dark)":
                # pMUD: 'no exit' in a dark room — we can't see where we are: drop the guess and ask the board
                st.pending.clear()
                self._expect_seq = None
                if not self.locate_now("no exit in the dark"):
                    self.send("")
            elif self.walking and self.path and not st.in_combat:
                # the step the path says is here isn't: we're not where we think (a look-alike room in the
                # pyramid). Ask the board where we are rather than typing the same move again
                st.pending.clear()
                self._expect_seq = None
                if self.locate_now("no exit where the path expects one"):
                    self.log("'No exit in that direction' — checking where we really are")
                self._drop_bad_learned()
        lc_ = getattr(self, "_last_cmd", None) or ("", False)
        said_ = re.match(r'^you say "(.+)"$', low.strip())
        # (0.8.202, Wayfarer: with fast talk on, a room command that isn't one here comes back as speech —
        #  'You say "go hole"' — the same as talk-slow's 'Your command had no effect.')
        if self.walking and self.path and (low.strip() == "your command had no effect." or
                                           (said_ and said_.group(1).strip() == str(lc_[0]).strip().lower())) \
                and not lc_[1] and not self._knocked_down_now() \
                and time.time() - getattr(self, "_step_sent_at", 0) < 5 \
                and time.time() - getattr(self, "_macro_at", 0) >= 4 \
                and time.time() - max((getattr(self, "_buff_cast", None) or {}).values(), default=0) >= 4:
            # (0.8.224, real logs — 40 false 'pro' checks: a bless sent with the step said it, not the step)
            # (0.8.200: and only when the last thing we sent wasn't an attack or a spell. Paradigm says it, too, for
            # an attack on a monster a party member has just killed, a spell that can't go, a 'break' or a 'bash'
            # at a wall — MudPlay's notes. Arriving and swinging at the party's kill read as "wrong room".)
            # (not right after a swap line: Miserable PVE's post-meditate 'eq pho' with the feather already on said
            # it, and every rest counted as knocked off the path — 7 in 5 min stopped the loop, Dan, 2026-11-05)
            # a room's own command ('go hole') that does nothing: we're not in the room the path thinks — a text
            # exit doesn't fail at random (Dan, 2026-10-30: 'go hole' over and over in 2/193, a look-alike of 2/487)
            st.pending.clear()
            self._expect_seq = None
            if self.pilot.on():
                self.pilot.trusted = None
            if self.locate_now("the path's command had no effect"):
                self.log("'Your command had no effect.' — the path thinks this is another room; checking where we are")
            self._drop_bad_learned()
        if self.walking and self.path and low.strip() == "your command had no effect." \
                and time.time() - getattr(self, "_step_sent_at", 0) < 5 and not getattr(self, "_chance_need", None):
            # a '(Chance)' step that needs an item ('dig grave' needs a shovel): "no effect" = the item's gone (the dig
            # takes the shovel now and then) — read the pack; _resend_guard decides (m12 #4: dug on, grave to grave)
            k_ = self._resends[0] if self._resends else None
            cx_ = self._chance_exit(k_[0], k_[1]) if (k_ and k_[0]) else None
            nd_ = self.s.world.exit_need(cx_) if cx_ is not None else None
            need_ = ([nd_[0]] if nd_ else []) + (self._opener_items(cx_) if cx_ is not None else [])
            if need_:                                # (MME: 'dig grave' is a text exit whose req items has the shovel)
                self._chance_need = {"seq": st.inv_seq, "t": time.time(), "num": need_[0], "move": k_[1]}
                self.send("i")
        ac_ = getattr(self, "_attack_cmd", None)
        if said_ and ac_ and said_.group(1).strip() == str(ac_[0]).strip().lower() and time.time() - ac_[1] < 5:
            # (0.8.202, Wayfarer: 'You say "bash wizard"' — the game took the attack as speech: blind, or no such
            #  target here. Don't swing again blind every few seconds — back off (longer each time) and look again)
            self._melee_on = False
            self._atk_refused = getattr(self, "_atk_refused", 0) + 1
            self._attack_backoff_until = time.time() + min(30, 5 * self._atk_refused)
            st.need_refresh = True
            if self.ready("atk_said_note", 20):
                self.log(f"'{ac_[0]}' came out as speech — the game didn't take the attack; looking again first")
        if "*combat engaged*" in low:
            self._atk_refused = 0
        if self.walking and self.path and not st.in_combat and re.match(r"^you don'?t see .+ here", low) \
                and time.time() - getattr(self, "_action_sent_at", 0) < 4:
            # 'ask sphinx fire' → "You don't see sphinx fire here": the path's room action is for a room
            # we're not in. Find out where we are instead of asking again and again
            if self.locate_now("path action target missing"):
                self.log(f"'{text.strip()}' — the path thinks this is another room; checking where we are")
            self._drop_bad_learned()
        if "dimly lit" in low:
            self._dim_at = time.time()
        if re.match(r"^nothing happens\.?$", low.strip()) and time.time() - getattr(self, "_dig_at", 0) < 5:
            # after 'dig': no spade to dig with (Dan) — read the inventory; _dig_out_of_spades decides
            self._dig_nothing = getattr(self, "_dig_nothing", 0) + 1
            if not getattr(self, "_dig_check", None):
                self._dig_check = {"seq": self.st.inv_seq, "t": time.time()}
                self.send("i")
        elif re.match(r"^you (?:dig|found|find|unearth|uncover)\b", low.strip()):
            self._dig_nothing = 0
        if self._opening_dir and re.search(r"\b(?:is|are|was|were)\s+not\s+locked|wasn'?t locked|isn'?t locked", low):
            # "The gate was not locked." — it's shut, not locked: open it and go, don't keep picking/bashing
            # (Dan: three 'pick west' on an unlocked gate, then a bash that cost HP)
            d_ = self._opening_dir
            self._locked_dir = None
            self._lock_tries.pop(d_, None) if hasattr(self, "_lock_tries") else None
            self._opening_dir = d_
            self.send(f"open {DIR_WORDS.get(d_, d_).lower()}")
            self._door_wait_until = time.time() + 2.5
        elif self._opening_dir and re.search(r"\b(is|are) locked\b|\blocked\.", low):   # (not "blocked." — loopsD D1)
            self._locked_dir = self._opening_dir
            self._door_wait_until = 0
        if re.search(r"^you (?:successfully )?(?:unlock(?:ed)?|pick(?:ed)?) (?:the )?(?:door|lock)", low):
            # unlocked is not open — after a key OR a pick the door still has to be opened (Dan); the pyramid key
            # door said "You successfully unlocked the door.", then 'w' got "The door is closed!" and the key was
            # gone. The next try at this door is 'open'. (A bashed door is open.)
            d_ = self._opening_dir or getattr(self, "_pre_door_dir", None)
            if d_ and st.room:
                self._key_done = (st.room, d_, time.time(), True)      # the path's 'use … key' is done, open sent
                # open it now, before the step (Dan: 'pick east', 'e' → "The door is closed!", then 'open east')
                self._unlocked = None
                self._locked_dir = None
                self._opening_dir = d_
                self.send(f"open {DIR_WORDS.get(d_, d_).lower()}")
                self._door_wait_until = time.time() + 2.5
        if self._opening_dir and re.search(r"^you (?:open|bashed|bash .* open)|"
                                           r"bash(?:ed|es)? the door (?:open|to the)|the door (?:is|swings|bursts) open|"
                                           r"the door is now open|is already open|that is not a door|isn't closed", low):
            # the door's open (you, or a partner bashing it): walk through — no 'open' again first
            self._door_wait_until = 0
            self._opened = (self.st.view_seq, self._opening_dir)
            self._door_open_dir = self._opening_dir
        elif self._opening_dir and re.search(r"attempts? to (?:bash|pick).* fail|you fail(?:ed)? to (?:pick|bash)|"
                                             r"your (?:attempts?|efforts?) .*fail", low):
            self._door_wait_until = 0
            self._locked_dir = self._opening_dir          # still shut: next try (pick / bash)
        if low.strip() == "*combat off*":
            # a fight's over: the next one waits for the party again (Revolution, 2026-10-30: the party opened
            # on the first monster, then he opened every next one in the room himself)
            ac = getattr(self, "_attack_cmd", None)
            if not (ac and time.time() - ac[1] < 2):
                # (a re-attack shows *Combat Off* / *Combat Engaged* at once — Dan: that's not the fight ending, so
                #  who we've answered stays answered; otherwise two attack-last MudPilots answer each other forever)
                self._fight_over_at = self._mobs_since = time.time()
                self._al_answered = set()
                # (0.8.201, bug hunt: the swing's over too — nothing else cleared these, so fight() went on thinking
                # it was meleeing, and a later "no effect" got blamed on the monster we'd killed earlier)
                self._melee_on = False
                self._melee_target = None
        # attack last: a party member has started the fight — melee, a targeted spell, or an area
        # spell with no target ("Revolution makes a sweeping gesture!") all count
        if st.party and text[:1].isupper():
            nm = re.sub(r"'s$", "", text.split()[0].rstrip(",.!"))   # (rstrip("'s") made Skittles 'Skittle')
            if nm in st.party and nm.lower() != (self.cfg.my_name or "").lower() and not re.search(r"\byou\b", low):
                started = re.match(r"^\w+\s+(?:moves to attack|swings|attacks|hits|slashes|smashes|stabs|bashes|punches|kicks|strikes|"
                                   r"lunges|casts|fires|shoots|backstabs|crushes|cuts|pierces|whips|clubs|jumpkicks|"
                                   r"sneaks up|makes a sweeping gesture|gestures|invokes|chants|summons|calls down)", text)
                if started and re.match(r"^\w+\s+casts\b", text):
                    # (0.8.201, bug hunt: "Evolution casts cure poison on Buddy!" made Buddy re-attack, and a re-send
                    # toggles combat and costs a round — only a cast at a monster here starts a fight)
                    mc = re.search(r"\bcasts .+? (?:at|on) (?:the |an? )?(.+?)[.!]*$", text.strip())
                    on = mc.group(1).strip().lower() if mc else ""
                    if not (on and st.view and not any(on == p.lower() for p in st.party) and
                            any(sh.lower() == on or on.endswith(sh.lower()) or sh.lower().endswith(on)
                                for sh, _r in st.view.monsters)):
                        started = None
                mobs_here = st.view and any(sh.lower() in low for sh, _r in st.view.monsters)
                if started or mobs_here:
                    self._party_engaged_at = time.time()
                if started:
                    self._attack_after_party(nm)
        for b in self.cfg.buffs or []:
            msg = (b.get("off_msg") or "").strip().lower()
            if msg and msg in low:
                self._buff_off[b.get("cast", "")] = True

    # ---------------------------------------------------------- loot
    def loot(self) -> bool:
        st, cfg = self.st, self.cfg
        v = st.view
        if not v or not v.items:
            return False
        if self._looted_seq == st.view_seq:
            return False
        lw = getattr(self, "_loot_wait", None)
        if lw and lw[1] > 0 and time.time() < lw[0]:
            return False                 # earlier 'get's haven't answered yet — don't grab the same pile twice
        now = time.time()
        la = getattr(self, "_loot_asked", None)
        if la and la["room"] == st.room and now - la["t"] < 15:
            # Dan, 2026-11-07: an item 'get' that didn't take (too heavy, the weight unknown or the encumbrance
            # stale) — leave it here for a while instead of asking for it every look; the party picks it up
            for qty, name in v.items:
                if name.lower() in la["names"]:
                    self._no_item[(st.room, name.lower())] = now
                    self.log(f"Couldn't pick up the {name} — leaving it here (the party can take it)")
        self._loot_asked = None
        self._no_item = {k: t for k, t in self._no_item.items() if now - t < 300}
        wants, asked = [], {}
        lvl = st.level or cfg.char_level or 0
        never = [w.lower() for w in (cfg.loot_never or []) if w.strip()]
        in_stash = self.x.in_any_stash(st.room)
        errand_items = self.errands.wanted()
        dropped_coins, queued_w = False, 0      # queued_w: weight of the 'get's already asked for this look
        for qty, name in v.items:
            mc = re.match(r"^corpse of (.+?)[.!]?$", name.strip(), re.I)
            if mc and cfg.recover_corpse and (cfg.my_name or "").lower() in mc.group(1).lower() \
                    and self.ready("corpse", 30):
                self.log("Your corpse is here — recovering your things")
                wants.append(f"recover corpse {mc.group(1)}")
                self._after_corpse = time.time()
                continue
            ck = coin_kind(name)
            if in_stash and (ck in (cfg.stash_coins or []) or (not ck and self.x.is_stash_item(name))):
                continue                        # never pick your own stash back up
            if ck and cfg.loot_cash:
                if time.time() - getattr(self, "_no_coin", {}).get((st.room, ck), 0) < 300:
                    if self.x.want_coin(ck, lvl):
                        self._party_grab(name, f"get {qty} {name}")
                    continue                    # it gave us 0 of these a moment ago (too heavy)
                if st.enc and st.enc[0] >= st.enc[1] and not self.x.make_room_for(ck, qty):
                    # Evolution, 2026-11-01: 3024/3024 and still trying every pile — nothing more fits
                    if self.ready("coins_full", 300):
                        self.log(f"Not picking up coins — you're at {st.enc[0]}/{st.enc[1]} encumbrance (full)")
                    if self.x.want_coin(ck, lvl):
                        self._party_grab(name, f"get {qty} {name}")
                    continue
                if not self.x.want_coin(ck, lvl):
                    continue                    # e.g. copper after level 5, silver after 10
                if cfg.coins_not_heavy and st.enc and (st.enc[3] >= int(cfg.coins_heavy_pct or 66) or
                                                       str(st.enc[2]).lower() == "heavy")                         and not self.x.make_room_for(ck, qty):
                    # Dan, 2026-11-07: an option — coins aren't worth walking Heavy for (dropping cheaper ones for
                    # this better coin still goes ahead: that doesn't add weight)
                    if self.ready("coins_heavy", 300):
                        self.log(f"Not picking up coins — {st.enc[3]}% encumbrance, Heavy (Loot: don't pick up coins "
                                 "once I'm Heavy)")
                    continue
                drops = self.x.make_room_for(ck, qty)
                if drops:
                    dropped_coins = True        # the encumbrance changed: read it again (0.8.201, bug hunt)
                wants += drops
                wants.append(cfg.get_cash_cmd.format(qty=qty, item=name))
                # (copper looted is counted from "You picked up N …" in gamestate — not what was asked for)
            elif not ck:
                rule = self.item_rule(name)
                if rule.get("never"):
                    continue
                listed = cfg.auto_loot and not any(n in name.lower() for n in never) and \
                    any(w and (w.strip() == "*" or w.lower() in name.lower()) for w in cfg.loot_items)
                if not (listed or rule.get("get") or name.lower() in errand_items):
                    continue
                if listed and not rule.get("get") and name.lower() not in errand_items \
                        and self.s.chestloot.cheap(name):
                    # 0.8.201 (Dan): a shop pays next to nothing for it — not worth carrying to one (Loot: Drop
                    # cheap loot); anything with an item rule, a quest item or one MME has no price for still comes
                    if self.ready(f"cheap_{name.lower()}", 300):
                        v = self.s.chestloot.value(name) or 0
                        self.log(f"Leaving the {name} — a shop pays only {v // 100}g {v % 100}c for it")
                    continue
                n = qty
                if not (listed or rule.get("get")):
                    n = 0 if self.carried_count(name) else 1   # an errand wants one ('get' took all 10 green keys)
                    if n <= 0:
                        continue
                if rule.get("max") is not None:
                    n = min(n, max(0, rule["max"] - self.carried_count(name)))
                    if n <= 0:
                        continue                    # you have as many as you want
                if (st.room, name.lower()) in self._no_item:
                    self._party_grab(name, f"get {name}")
                    continue                    # refused a moment ago: not again every look
                fit = self.how_many_fit(name, n, queued_w)
                if fit < n:
                    if not fit:
                        self.why("too_heavy", item=name)
                        if self.ready(f"heavy_{name}", 60):
                            self.log(f"Leaving the {name} — it'd be over your encumbrance")
                        self._party_grab(name, f"get {name}")
                        continue
                    n = fit
                wants.append(cfg.get_item_cmd.format(item=name, qty=n))
                queued_w += n * self.item_weight(name)
                if n >= qty:
                    asked[name.lower()] = name      # (took part of a pile on purpose: what's left isn't a refusal)
        self._looted_seq = st.view_seq
        if not wants:
            return False
        if dropped_coins:
            wants.append("i")                   # coins dropped: the encumbrance the next look checks is stale
        if asked:
            self._loot_asked = {"room": st.room, "t": now, "names": asked}
        self.status = "Looting"
        self._loot_wait = [time.time() + 3.0, sum(1 for w in wants if w.lower().startswith("get"))]
        for w in wants:
            self.send(w)
        self.send("")  # re-look so we see what's left
        return True

    def _party_grab(self, name, cmd) -> bool:
        """You can't carry it: a party member's MudPilot standing here picks it up ('/Buddy @do get platinum
        bracers' — Dan, 2026-11-07). The strongest first; one at a time, 20 s apart, each asked once per pile."""
        st, cfg = self.st, self.cfg
        if not st.party or not st.room:
            return False
        now = time.time()
        ga = self._grab_asked = {k: g for k, g in getattr(self, "_grab_asked", {}).items() if now - g["t0"] < 300}
        g = ga.setdefault((st.room, name.lower()), {"t0": now, "t": 0, "who": set()})
        if now - g["t"] < 20:
            return False
        try:
            peers = {p.lower() for p in self.s.partysync.peers}
            info = {n.lower(): d for n, d in self.s.partysync.info().items()}
        except Exception:
            peers, info = set(), {}
        me = (cfg.my_name or "").lower()
        here_ = {p.split()[0].strip(".,").lower() for p in ((st.view.players if st.view else []) or []) if p.split()}
        helpers = [n for n in (st.party or {}) if n.lower() != me and n.lower() in peers and n.lower() in here_
                   and n.lower() not in g["who"]]
        if not helpers:
            return False
        n = max(helpers, key=lambda h: int((info.get(h.lower()) or {}).get("str") or 0))
        g["t"] = now
        g["who"].add(n.lower())
        self.send(f"/{n} @do {cmd}")
        self.log(f"Too heavy for me — asked {n} to pick up the {name}")
        return True

    # ---------------------------------------------------------- per-item rules, weight
    def item_rule(self, name) -> dict:
        """Loot tab → Item rules, one per line, pMUD-style:
            rope and grapple: max 1        — pick up till you have one
            broadsword: drop                — never keep it (drops it if it's in your pack)
            silver dagger: get, max 3       — always pick up, up to 3
            iron key: keep 1                — never drop or sell the last one
            rusty dagger: never             — never pick it up"""
        rules = getattr(self, "_rules_cache", None)
        src = tuple(self.cfg.item_rules or [])
        if not rules or rules[0] != src:
            parsed = {}
            for ln in src:
                if ":" not in ln:
                    continue
                item, spec = ln.split(":", 1)
                d = {}
                for part in re.split(r"[,;]", spec):
                    p = part.strip().lower()
                    m = re.match(r"^(max|keep)\s+(\d+)$", p)
                    if m:
                        d[m.group(1)] = int(m.group(2))
                    elif p in ("get", "drop", "never", "stash"):
                        d[p] = True
                if item.strip():
                    parsed[item.strip().lower()] = d
            rules = self._rules_cache = (src, parsed)
        low = (name or "").lower()
        base = re.sub(r"^(?:\d+\s+|an?\s+|the\s+|some\s+)", "", low)
        for k in (low, base, base.rstrip("s")):
            if k in rules[1]:
                return rules[1][k]
        return {}

    def carried_count(self, name) -> int:
        from .gamestate import parse_item_list
        low = (name or "").lower().rstrip("s")
        return sum(q for q, n in parse_item_list(self.st.carrying or "")
                   if re.sub(r"\s*\([^)]*\)\s*$", "", n).lower().rstrip("s") == low)

    def item_weight(self, name) -> int:
        """MME Encum of one `name` (0 = unknown)."""
        w = self.s.world
        it = w.item_names.get((name or "").lower()) or w.item_names.get((name or "").lower().rstrip("s"))
        return int((it or {}).get("encum") or 0)

    def how_many_fit(self, name, n, queued=0) -> int:
        """pMUD: check the weight before picking up (MME Encum vs your encumbrance from 'i'). Unknown → n.
        queued: weight of the 'get's already asked for in this look (0.8.201, bug hunt: two 50-weight items with 60
        free were both asked for against the same encumbrance — the second was refused and never handed on)."""
        enc = self.st.enc
        per = self.item_weight(name)
        if not enc or not per:
            return n
        room = enc[1] - enc[0] - sum(getattr(self, "_reserved_weight", {}).values()) - int(queued or 0)
        return max(0, min(n, room // per))

    # ---------------------------------------------------------- rest
    def _rest_broken_here(self) -> bool:
        """0.8.224 (Dan, logEVO): 3 rests a fight broke up in this room in the last 2 minutes — something keeps
        spawning on us (the Abandoned Temple hallway: "a fight broke it up" 6 times in 3 minutes, then a hang-up)."""
        room = tuple(self.st.room) if self.st.room else None
        now = time.time()
        rb = [(t, r) for t, r in (getattr(self, "_rest_broken", None) or []) if now - t < 120]
        self._rest_broken = rb
        return bool(room) and sum(1 for _t, r in rb if r == room) >= 3

    def _rest_elsewhere(self, mobs) -> bool:
        """Walking a loop and this is a lair (monsters spawn here)? Keep going to the next room
        without one — at most cfg.safe_rest_steps ahead — unless HP is getting low."""
        cfg, st, w = self.cfg, self.st, self.s.world
        n = int(cfg.safe_rest_steps or 0)
        if not n and self._rest_broken_here():
            n = 3                             # (0.8.224: a room that keeps breaking rests up — see _rest_broken_here)
        if getattr(self, "_danger_hp", 0):
            return False                      # resting up for a dangerous lair next: rest right here
        if not n or not self.walking or not self.path or not st.room or self._fled or st.in_combat:
            return False
        if st.max_hp and st.hp_pct() < max(30, int(cfg.rest_below_hp or 0) - 25):
            return False                      # too hurt to go looking — rest right here
        if cfg.rest_below_ma and st.max_ma and st.ma_pct() < cfg.rest_below_ma:
            return False                      # not the mana for the next room's fight: rest at your rest % (Dan,
            # 2026-11-03: PVE walked on at 37% into three crabs and was down to 129 mana)
        here = w.room(st.room)
        if not here or not (here.lair or self._rest_broken_here()):
            return False
        steps = self.path.steps
        for k in range(n):
            j = (self.idx + k) % len(steps) if steps else 0
            dest = steps[j].dest if steps else None
            r = w.room(dest) if dest else None
            if r and not r.lair:
                self.status = f"Resting in a quieter room {k + 1} step{'s' if k else ''} on"
                return True
        return False

    def idle_regen(self, mobs, why=None):
        """Standing around waiting on the party anyway? Then rest or meditate — whichever is lower,
        HP or mana — unless both are full. Getting up again is automatic when we walk on."""
        st, cfg = self.st, self.cfg
        if not cfg.auto_rest:
            return                  # Rest is off: no resting at all — not while waiting, not with the party
        if st.resting or st.in_combat or (mobs and cfg.auto_combat) or not st.max_hp:
            return
        if time.time() < getattr(self, "_no_rest_until", 0):
            return                  # you pressed Stop: not sitting back down for a bit
        hp = st.hp_pct()
        ma = st.ma_pct() if st.max_ma else 100
        if hp >= 100 and ma >= 100:
            return
        if not self.ready("idle_regen", 6):
            return
        medi = cfg.use_meditate and ma < hp and (cfg.meditate_cmd or "").strip()
        self._idle_rest = True
        hold = self.s.remote.holding()
        self._rest_reason = why or (f"waiting on {self.s.remote.hold_text(hold)}" if hold else "waiting on the party")
        self.status = ("Meditating" if medi else "Resting") + " while we wait"
        # the rest/meditate gear goes on for these too — unless we're already over 'rest until': then the next tick
        # calls it rested, swaps the gear straight back and stands us up, and 6 s later it all starts again
        # (0.8.208: Miserable PVE swapped 4 rings/capes on and off every 6 s while waiting on Buddy — Dan, 2026-11-19)
        # 0.8.224 (Dan): no gear swap at all for these — they're short and the party walks on any second (Miserable
        # PVE's regen set on and off for every wait; once the game said "slow down"). A real rest swaps as usual
        self.send(cfg.meditate_cmd if medi else cfg.rest_cmd)

    def _shortfall(self):
        """How far below 'rest until' HP and mana still are (in %, 0 = there)."""
        st, cfg = self.st, self.cfg
        hp = max(0.0, cfg.rest_until_hp - st.hp_pct()) if st.max_hp else 0.0
        ma = max(0.0, cfg.rest_until_ma - st.ma_pct()) if (st.max_ma and cfg.rest_below_ma) else 0.0
        return hp, ma

    # ---------------------------------------------------------- smart resting
    def _smart_act(self, dh, full, mobs):
        """Smart resting's next step ('heal' / 'rgen' / 'meditate' / 'rest'), or None for the usual rules."""
        st, cfg = self.st, self.cfg
        if not cfg.smart_rest or st.in_combat or mobs or not st.max_hp or not st.max_ma or self._fled                 or st.hp is None or st.ma is None:
            return None
        tgt_hp = 100 if full else max(cfg.rest_until_hp, dh)
        tgt_ma = 100 if full else (cfg.rest_until_ma if cfg.rest_below_ma else 0)
        return self.smart.next_action(st.hp, st.max_hp, st.ma, st.max_ma, tgt_hp, tgt_ma)

    def _smart_cast(self, act) -> bool:
        """Cast the heal / regeneration smart resting picked (one a round). True = this tick is used."""
        cfg = self.cfg
        cmd = cfg.heal_cmd if act == "heal" else cfg.hp_regen_cmd
        if not cmd or not self.slot_free() or not self.ready("smart_cast", 3):
            return True
        p = self.smart.last_plan or {}
        self.status = (f"Smart rest: {'healing' if act == 'heal' else 'regeneration'} — {p.get('name', '')}, "
                       f"~{p.get('secs', 0):.0f} s (resting ~{p.get('rest_secs', 0):.0f} s)")
        sig = (p.get("name"), act)
        if getattr(self, "_smart_said", None) != sig:
            self._smart_said = sig
            self.log(self.status)
        if act == "rgen":
            self.smart.cast_rgen()
        self.send(cmd)
        return True

    def _up_on_tick(self) -> bool:
        """A regen tick just landed and left us a sliver short of 'rest until' — less than half
        of what a tick gives. Get up now rather than sit through a whole extra tick for 1-2%."""
        cfg, rc = self.cfg, self.regen
        if not cfg.rest_up_on_tick or not rc.learned or not rc.just_ticked() or getattr(self, "_rest_full", False):
            return False
        if self.st.hp_pct() < cfg.rest_below_hp:
            return False                       # never get up still in the danger zone
        if cfg.rest_below_ma and self.st.max_ma and self.st.ma_pct() < cfg.rest_below_ma:
            return False                       # (0.8.225, logs: nor under the mana line — we'd sit straight back down,
                                               #  with a full gear swap each way: 186 times on PVE in a day)
        need_hp, need_ma = self._shortfall()
        g_hp, g_ma = rc.gain("hp"), rc.gain("ma")
        if (need_hp and (not g_hp or need_hp > g_hp / 2)) or (need_ma and (not g_ma or need_ma > g_ma / 2)):
            return False
        self._rest_end = (f"up on the tick ({need_hp:.0f}% HP / {need_ma:.0f}% mana short; "
                          f"saved ~{rc.period:.0f} s)")
        self._uptick_said = rc.last_tick              # (0.8.225, #29: the rest's own summary line says it — 1,466 a day)
        return True

    def _topoff_one_more(self) -> bool:
        """'Rest until' reached on a tick, and one more tick would fill us right up: take it — it
        saves a whole separate rest (sitting down, waiting for the first tick) later. Solo only:
        a party shouldn't wait on our top-off."""
        cfg, st, rc = self.cfg, self.st, self.regen
        if not cfg.rest_smart_full or not rc.learned:
            return False
        tp = getattr(self, "_topoff", None)
        if tp:
            if time.time() < tp:
                self.status = "Resting — one more tick tops us off"
                return True
            self._topoff = None
            return False
        if getattr(self, "_topoff_used", False):
            return False
        if not rc.just_ticked() or [n for n in st.party if n.lower() != (cfg.my_name or "").lower()]:
            return False
        if st.view and st.view.monsters or self.s.remote.holding():
            return False
        g_hp, g_ma = rc.gain("hp"), rc.gain("ma")
        miss_hp = 100 - st.hp_pct() if st.max_hp else 0
        miss_ma = (100 - st.ma_pct()) if st.max_ma else 0
        if (miss_hp <= 0 or miss_hp > g_hp) and (miss_ma <= 0 or miss_ma > g_ma):
            return False                       # already full, or one tick won't get there
        if (miss_hp > g_hp * 1.05 and miss_hp > 0) or (miss_ma > g_ma * 1.05 and miss_ma > 0):
            return False
        # wait for the tick of the stat that's short, not the fastest one (0.8.227, Dan: PVE sat at 100% HP / 86%
        # mana — HP ticks every ~5 s meditating, mana every ~15-30 s, so it waited 7 s and got nothing). A tick
        # that far off isn't worth standing around for: up and walking.
        wait = max([p for k, miss in (("hp", miss_hp), ("ma", miss_ma)) if miss > 0
                    for p in [rc.stat_period(k) or rc.period]] or [rc.period])
        if wait > self.TOPOFF_MAX_WAIT:
            return False
        self._topoff = time.time() + wait + 2
        self._topoff_used = True
        self._rest_end = "topped off on one more tick"
        return True

    TOPOFF_MAX_WAIT = 10      # seconds: a top-off tick due later than this isn't waited for
    DONTREST_MARGIN = 12      # seconds: up and gone this long before the room's monsters are due back

    def _dontrest_window(self, mobs) -> bool:
        """A don't-rest room we can still rest in for a while: how long depends on how fast the room fills back up
        (Dan, 2026-11-20: "sometimes they need to leave immediately, sometimes it's a 90 second regen and he can
        safely rest for 80 seconds before moving 1 room"). From the lair clock's refill time — the earliest it's
        been seen stocked again, if that's sooner — counted from when it was cleared this visit, less
        DONTREST_MARGIN. A room with no refill time learned yet: no resting, as before."""
        st, now = self.st, time.time()
        room = st.room
        if not room or mobs or st.in_combat:
            self._dr_clear = None
            return False
        clr = getattr(self, "_dr_clear", None)
        if not clr or clr[0] != room:
            clr = self._dr_clear = (room, now)
        lc = self.s.lairclock
        est = lc.estimate(room)
        if est is None:
            return False
        try:
            soonest = min((x[0] for x in lc.data.get(lc.key(room), {}).get("s", []) if x[1]), default=est)
        except Exception:
            soonest = est
        left = min(est, soonest) - self.DONTREST_MARGIN - (now - clr[1])
        if left <= 0:
            if st.resting and self.ready("dr_window_said", 20):
                self.log(f"Don't-rest room: monsters due back in {self.DONTREST_MARGIN} s — moving on")
            return False
        if not st.resting and self.ready("dr_window_said", 20):
            self.log(f"Don't-rest room, but it takes ~{min(est, soonest):.0f} s to fill — resting up to {left:.0f} s")
        return True

    def should_rest(self, mobs, in_range) -> bool:
        st, cfg = self.st, self.cfg
        if not st.max_hp:
            return False
        if self._rushing() and not st.resting:
            return False                      # the lever gate shuts on a timer: rest on the far side
        if self.in_deadly() and not st.resting:
            return False                      # never sit down where you drown
        dh = getattr(self, "_danger_hp", 0) if self.walking else 0
        full = getattr(self, "_rest_full", False) or \
            time.time() - getattr(self, "_msg_rest_full", 0) < 600     # auto-tune / a message rule: rest to full
        if full:
            dh = 100
        low_hp = st.hp_pct() < max(cfg.rest_below_hp, dh)
        low_ma = (cfg.rest_below_ma and st.max_ma and st.ma_pct() < cfg.rest_below_ma) or \
            (full and st.max_ma and st.ma < st.max_ma)
        # (0.8.207, Dan: "it clearly says rest below 70% mana" — Revolution walked on at 44%: the mana throttle let
        #  him go down to half the line on cheap spells. 'Rest below MA' is the line now; the throttle only picks
        #  cheaper spells above it. mana_rest_can_wait() is no longer used for this)
        # meditating is for mana: HP over the rest-below line needn't reach rest-until too — waiting on it kept
        # Miserable PVE meditating till the game woke him at full mana (Dan, 2026-11-03)
        hp_ok = st.hp_pct() >= max(cfg.rest_until_hp, dh) or             (st.meditating and not full and not dh and st.hp_pct() >= cfg.rest_below_hp)
        topped = hp_ok and (not st.max_ma or not (cfg.rest_below_ma or full)
                                                                or st.ma_pct() >= (100 if full else cfg.rest_until_ma))
        if not st.resting and getattr(self, "_rest_begun", False) and not topped and not st.in_combat and not mobs \
                and time.time() - (getattr(self, "_last_spell_at", 0) or 0) < 4:
            # 0.8.225 (logs — Buddy, 178 of 188 rests): our own heal mid-rest stood us up at 81% with rest-below 80,
            # and the walk went on short of 'rest until' (once into three manticores and a hang-up): keep resting
            low_hp = low_hp or st.hp_pct() < max(cfg.rest_until_hp, dh or 0)
        if topped and getattr(self, "_msg_rest_full", 0):
            self._msg_rest_full = 0
        if self._step_flag("DONTREST") and not self._fled and not self._dontrest_window(mobs):
            return False
        pz = self.x.ailments.get("poison")
        # (not while there's no resting anyway — the pyramid timer, a message rule: Miserable stood on level 2,
        #  bee-poisoned at 65% HP, 'waiting for it to wear off before resting' with the clock running, Dan 2026-11-10)
        no_rest = (time.time() < getattr(self, "_no_rest_until", 0) and not self._fled) or self.hurrying() \
            or self.in_deadly()
        if pz and (low_hp or low_ma) and not st.in_combat and time.time() - pz < 90 and st.hp_pct() > 25 \
                and not no_rest and not (cfg.cure_poison_cmd and not cfg.ignore_poison):
            # pMUD: the poison stings break the rest anyway — wait it out standing (a cure goes first if set)
            self.status = "Poisoned — waiting for it to wear off before resting"
            return True
        if time.time() < getattr(self, "_no_rest_until", 0) and not self._fled and st.hp_pct() > 30:
            return False                  # a message rule says keep going (desert heat…)
        if st.resting and getattr(self, "_idle_rest", False) and not (low_hp or low_ma or self._fled):
            # only sat down because we were waiting on the party: get up once nobody needs us to wait
            pacing = getattr(self, "_pace_until", 0) > time.time()
            together = (not self.walking) and self.s.partysync.peer_resting()
            if not self.s.remote.holding() and not self.x.waiting_on and not pacing and not together:
                self._idle_rest = False
                self._rest_end = "lair ahead should be ready" if getattr(self, "_pace_until", 0) else "done waiting"
                self._pace_until = 0
                return False
            self.status = "Resting while we wait"
            return True
        if st.resting and topped and self._topoff_one_more():
            return True
        if st.resting and not topped and not self._fled and self._up_on_tick():
            topped = True
        if st.resting and not topped and cfg.smart_rest and self.regen.just_ticked():
            act = self._smart_act(dh, full, mobs)
            if act in ("heal", "rgen"):
                return self._smart_cast(act)       # stands us up just after the tick; we sit straight back down
        if st.resting:
            self._rest_broke_at = 0
            if topped:
                self._rest_end = self._rest_end if getattr(self, "_rest_end", None) else "topped up"
                self._topoff = None
                self._fled = False
                if getattr(self, "_rest_begun", False):
                    self._rest_begun = False
                    self.x.after_rest()
                if self.end_swap("rested"):
                    return True       # gear back on first; walk/fight next tick
                return False
            if not self._swap and not st.in_combat and not getattr(self, "_rest_begun", False) \
                    and not getattr(self, "_idle_rest", False) and self.ready("typed_rest_swap", 30):
                # (not a party-wait rest of our own — idle_regen sets _idle_rest; those don't swap, 0.8.224 #11)
                # a rest we didn't start (Dan typed 'rest' walking around by hand): the swap only ever went with our
                # own rest command, so it rested in the fighting set — the faded shawl's −100 HP regen (Dan,
                # 2026-11-22). Swap now, then sit back down (the eq / remove stands you up)
                kind = "med" if getattr(st, "meditating", False) else "rest"
                pre, post = self._swap_cmds(kind)
                if pre.strip() or post.strip() or self.cfg.auto_regen_gear:
                    self._begin_swap(kind)
                    if self._swap:
                        self.log(f"You sat down yourself — {'meditate' if kind == 'med' else 'rest'} gear swap, "
                                 "then back down")
                        self.send(cfg.meditate_cmd if kind == "med" else cfg.rest_cmd)
                        self.status = "Meditating" if kind == "med" else "Resting"
                        return True
            # HP/mana stuck short of the top for a minute: the prompt's max only ever grows, so a max that dropped
            # (regen gear swapped out a +max ring, a +max bless wore off) leaves us resting for good — 'st' gives the
            # real max (0.8.201, bug hunt: stale max HP)
            sig, now_ = (st.hp, st.ma), time.time()
            if sig != getattr(self, "_rest_sig", None):
                self._rest_sig, self._rest_sig_at = sig, now_
            elif now_ - self._rest_sig_at > 60 and self.ready("rest_st", 120):
                self._rest_sig_at = now_
                self.log("Rest: HP/mana haven't moved for a minute — reading 'st' in case the max dropped")
                self.send("st")
            self.status = f"Resting (HP {st.hp}/{st.max_hp}" + (f", MA {st.ma}/{st.max_ma})" if st.max_ma else ")")
            return True
        if (low_hp or low_ma or self._fled) and not topped:
            if cfg.auto_combat and mobs and in_range:
                return False  # fight first
            if not cfg.auto_combat and mobs and getattr(self, "_being_hit", False) and not st.resting:
                # 0.8.224 (Dan, logEVO): Combat off and being hit — sitting down only gets broken up again (5 rests
                # at the Crimson Fortress with demonhunters hitting for 60-150, then a hang-up). Walking: walk on;
                # standing: don't sit down here
                if self.ready("hit_no_rest_said", 20):
                    self.log("Not resting: being hit with Combat off" + (" — walking on" if self.walking else ""))
                if self.walking:
                    return False
                self.status = "Being hit with Combat off — not resting here"
                return True
            if self._rest_elsewhere(mobs):
                return False  # a lair room: rest a step or two on, where nothing spawns on you
            act = self._smart_act(dh, full, mobs)
            if act in ("heal", "rgen"):
                return self._smart_cast(act)
            if cfg.auto_regen_gear and getattr(self, "_inv_stale", False) and not self._swap:
                # 2026-10-28 PVE: resting in the fighting set (faded shawl, −100 HP regen) took ~310 s instead of
                # ~75 s — read 'i' and give it a moment, then the regen set goes on
                asked = getattr(self, "_inv_asked", 0)
                if time.time() - asked > 20:
                    self._inv_asked = time.time()
                    self.send("i")
                    return True
                if time.time() - asked < 3:
                    return True
            if self.ready("rest", 4):
                medi = cfg.use_meditate and low_ma and not low_hp and not self._fled
                if act in ("meditate", "rest"):
                    medi = act == "meditate" and bool(cfg.meditate_cmd)   # smart resting's pick
                now_ = time.time()
                no_rest_, no_med_ = now_ < getattr(self, "_sick_rest_until", 0), now_ < getattr(self, "_sick_med_until", 0)
                if not medi and no_rest_ and cfg.use_meditate and not no_med_ and st.ma_pct() < 100:
                    medi = True                      # Paradigm lets a poisoned character meditate
                if (medi and no_med_) or (not medi and no_rest_):
                    self.status = "Too sick to rest — waiting (a cure goes first if set)" if no_rest_ else \
                        "Mana's full — meditating won't help"
                    return not (medi and no_med_ and not low_hp)
                self.status = "Meditating" if medi else "Resting"
                self._topoff_used, self._topoff, self._rest_end = False, None, None
                self._rest_reason = ("auto-tune: topping up before a trial" if full else
                                     "ran from a fight" if self._fled else
                                     f"danger ahead: resting to {dh:.0f}% HP" if (dh and st.hp_pct() >= cfg.rest_below_hp
                                                                                    and low_hp) else
                                     f"HP below {cfg.rest_below_hp}% ({st.hp_pct():.0f}%)" if low_hp else
                                     f"mana below {cfg.rest_below_ma}% ({st.ma_pct():.0f}%)")
                self._begin_swap("med" if medi else "rest")
                # a real rest now: an old "idle rest" flag (a wait broken by a fight or a move) would end it at
                # rest-below instead of rest-until (0.8.201, bug hunt: leftover idle-rest flag)
                self._idle_rest = False
                if not getattr(self, "_rest_begun", False):
                    self._rest_begun = True
                    self.x.before_rest(low_hp, medi)
                self.send(cfg.meditate_cmd if medi else cfg.rest_cmd)
            return True
        self._fled = False
        if getattr(self, "_rest_begun", False) and not topped and not st.in_combat:
            # sat down (and told the leader @wait), a fight broke the rest, and we're over the rest line now: no
            # rest is coming, so say @ok — the leader waited for our next rest to top up (0.8.201, bug hunt:
            # broken rest never sent @ok). A few seconds first, so a flicker of 'not resting' doesn't count.
            now_ = time.time()
            if not getattr(self, "_rest_broke_at", 0):
                self._rest_broke_at = now_
            elif now_ - self._rest_broke_at > 5:
                self._rest_begun, self._rest_broke_at = False, 0
                self.x.after_rest()
        else:
            self._rest_broke_at = 0
        if getattr(self, "_rest_begun", False) and topped:
            self._rest_begun = False
            self.x.after_rest()
        if self._swap and not st.resting and topped:
            self.end_swap("rested")
            return True
        return False

    # ---------------------------------------------------------- healing
    HEALED_RE = re.compile(r"^you cast (.+?) on (\w+), healing (\d+) damage")

    def _heal_too_small(self, cmd) -> bool:
        """0.8.224 (Dan, logMB): a heal far smaller than what's coming in — 'mihe' healed 5-14 HP a round while 3
        nightshades did 100-420, and each cast is a round with no attack. In a heavy fight (the last rounds took 10%+
        of your max HP), skip a self-heal whose last few casts averaged under a quarter of the damage per round."""
        st = self.st
        sp = self._cmd_spell(cmd, (cmd or "").split())
        name = (sp.get("Name") or "").lower() if sp else ""
        seen = (getattr(self, "_heal_seen", None) or {}).get(name) or []
        if len(seen) < 3 or not st.max_hp:
            return False                         # (not enough casts seen yet: heal as set)
        cl = getattr(self.s, "combatlog", None)
        now = time.time()
        rounds = [r for r in list(getattr(cl, "rounds", None) or []) if now - r.get("last", r.get("t", 0)) < 15][-2:]
        if not rounds:
            return False
        taken = sum(r.get("taken", 0) for r in rounds) / len(rounds)
        avg = sum(seen) / len(seen)
        if taken < 0.10 * st.max_hp or avg >= 0.25 * taken:
            return False
        if self.ready("heal_small_said", 30):
            self.log(f"Not healing: {name or cmd} heals ~{avg:.0f} and the fight's taking ~{taken:.0f} a round — "
                     "attacking instead")
        return True

    def heal_tick(self) -> bool:
        """Heal yourself or the party member who needs it most (MegaMUD Spells + Party tabs):
        minor / major heals by HP %, an area heal when enough of the party is hurt, priority
        players counted as lower, and a request for healing if you can't heal yourself."""
        st, cfg = self.st, self.cfg
        now = time.time()
        me = (cfg.my_name or "").lower()
        pri = {n.strip().lower() for n in (cfg.party_heal_priority or []) if n.strip()}
        bonus = int(cfg.party_priority_bonus or 0)
        cands = []          # (score, who-or-None, command)
        mine = None

        def afford(cmd):
            # a heal spell costing more than the mana you have only gets "not enough mana" — a 0-mana priest sent
            # one every 3 s and never asked for a heal (0.8.201, bug hunt: heals ignore mana)
            w = (cmd or "").split()
            if not w or not st.max_ma:
                return True
            sp = self.s.spellbook.find(w[1] if w[0].lower() in ("cast", "c") and len(w) > 1 else w[0])
            return not sp or int(sp.get("ManaCost") or 0) <= st.ma
        # Dan: heal only above a mana % — low in a fight, higher out of one so there's mana left to move on and
        # bless. Someone under 30% HP gets healed whatever the mana
        ma_line = int((cfg.heal_min_ma_fight if st.in_combat else cfg.heal_min_ma_rest) or 0)
        ma_low = bool(ma_line and st.max_ma and 100 * st.ma < ma_line * st.max_ma)

        def mana_ok(hp_pct):
            return not ma_low or hp_pct < 30
        broke = False       # wanted to heal yourself but can't pay for it
        if st.max_hp:
            hp = st.hp_pct()
            b = bonus if me in pri else 0
            if not mana_ok(hp):
                pass
            elif cfg.major_heal_cmd and hp < cfg.major_heal_pct and afford(cfg.major_heal_cmd):
                mine = (hp - b, None, cfg.major_heal_cmd)
            elif cfg.heal_cmd and hp < cfg.heal_pct and afford(cfg.heal_cmd):
                mine = (hp - b, None, cfg.heal_cmd)
            broke = not mine and mana_ok(hp) and bool((cfg.major_heal_cmd and hp < cfg.major_heal_pct) or
                                      (cfg.heal_cmd and hp < cfg.heal_pct))
            if mine and cfg.smart_rest and not st.in_combat and hp >= int(cfg.smart_rest_safe_hp or 0) \
                    and not self.attackable():
                # smart resting: out of a fight and out of the danger zone, a heal goes out only when it's the
                # quicker way back (mana spent on it has to be meditated back too). None = not enough learned yet
                act = self._smart_act(getattr(self, "_danger_hp", 0) if self.walking else 0, False, [])
                if act is not None and act != "heal":
                    mine = None
            if mine:
                cands.append(mine)
        hurt = 0
        if cfg.party_heal and st.party and (not st.resting or cfg.rest_heal_party):
            fresh = max(30.0, 4 * float(cfg.party_check_secs or 5))
            for name, info in st.party.items():
                low = name.lower()
                if low == me or now - info.get("t", 0) > fresh:
                    continue
                pl = self.s.players.data.get(low) if hasattr(self.s, "players") else None
                if pl and pl.get("dont_heal"):
                    continue
                hp = info.get("hp", 100)
                if info.get("t", 0) <= self._pheal_at.get(low, 0):
                    continue            # healed since that reading — wait for a fresh 'par'
                # (counted only on a fresh reading: an old one recast the area heal every 3 s on members it had
                #  just healed — 0.8.201, bug hunt)
                if hp < cfg.party_area_pct:
                    hurt += 1
                b = bonus if low in pri else 0
                minor = (cfg.party_heal_cmd or "").strip() or (f"{cfg.heal_cmd} {{name}}" if cfg.heal_cmd else "")
                if not mana_ok(hp):
                    continue
                if cfg.party_major_cmd and hp < cfg.party_major_pct + b and afford(cfg.party_major_cmd):
                    cands.append((hp - b, name, cfg.party_major_cmd))
                elif minor and hp < cfg.party_heal_pct + b and afford(minor):
                    cands.append((hp - b, name, minor))
            if st.max_hp and st.hp_pct() < cfg.party_area_pct:
                hurt += 1
        # area heal
        if cfg.party_heal and cfg.party_area_cmd and hurt >= max(2, cfg.party_area_count) and                 (not ma_low or any(c[0] < 30 for c in cands)):
            major_needed = any(c[2] in (cfg.party_major_cmd, cfg.major_heal_cmd) for c in cands if c[2])
            if cfg.area_over_major or not major_needed:
                if self.slot_free() and self.ready("heal", 3):
                    self.status = f"Area heal ({hurt} hurt)"
                    self.log(self.status)
                    self.send(cfg.party_area_cmd)
                    for n in st.party:
                        self._pheal_at[n.lower()] = now
                    self._cool["par"] = now - float(cfg.party_check_secs or 5) + 2; self._par_soon_until = time.time() + 20
                    return True
                return False
        # nobody can heal you? ask for it
        if not mine and cfg.request_heal_pct and st.party and st.max_hp and st.hp_pct() < cfg.request_heal_pct \
                and (broke or not (cfg.heal_cmd or cfg.major_heal_cmd)) and self.ready("reqheal", 20):
            self.send(cfg.request_heal_cmd.replace("{hp}", str(int(st.hp_pct()))))
            return True
        if not cands or not self.slot_free():
            return False
        if mine and not cfg.heal_party_over_self:
            pick = mine
        else:
            pick = min(cands, key=lambda c: c[0])
        _score, who, cmd = pick
        # mid-fight: heal just after a round goes off and re-arm the attack, so no round is lost —
        # unless it's urgent (a major heal), which goes now
        # (a major heal waits for the window too — only someone about to drop gets it at once)
        hp_now = st.hp_pct() if who is None else (st.party.get(who) or {}).get("hp", 100)
        urgent = cmd in (cfg.major_heal_cmd, cfg.party_major_cmd) and bool(cmd) and hp_now < 30
        if st.in_combat and not urgent and not self.early_in_round():
            return False
        if who is None and st.in_combat and self._heal_too_small(cmd):
            return False
        if not self.ready("heal", 3):
            return False
        if st.in_combat:
            self._cool["cast"] = 0                # re-arm the attack straight after
        if who is None:
            self.status = "Healing"
            self.send(cmd)
        else:
            self._pheal_at[who.lower()] = now
            self.status = f"Healing {who} ({st.party[who]['hp']}%)"
            self.log(self.status)
            self.send(cmd.replace("{name}", who).replace("{target}", who) if "{" in cmd else f"{cmd} {who}")
            self._cool["par"] = now - float(cfg.party_check_secs or 5) + 2; self._par_soon_until = time.time() + 20   # re-check the party soon
        ac = getattr(self, "_attack_cmd", None)
        if st.in_combat and ac and now - ac[1] < 60 and self._bot_attack_ok():
            # the heal stopped the attack the game was repeating: put it straight back, so the next round
            # swings / casts ('gdhe buddy^Msrip dragon' — Dan)
            self.send(ac[0])
            self._cast_sent_at = now
        return True

    # ---------------------------------------------------------- after a death
    def on_death(self):
        """Died: stop for good (no Rego, no watchdog restart, no resuming after a reconnect), tell your
        phone where and to what, and — if set — hang up once the death has played out."""
        cfg, w = self.cfg, self.s.world
        now = time.time()
        if now - getattr(self, "_death_at", 0) < 20:
            return                                   # the same death, seen twice
        self._death_at = now
        self.s.loopstats.note_death()
        room = getattr(self, "_last_room", None)
        r = w.room(room) if room else None
        mobs = getattr(self, "_last_mobs", None) or []
        where = f" at {r.name} ({room[0]}/{room[1]})" if r else ""
        what = f" fighting {', '.join(mobs)}" if mobs else ""
        if self.walking:
            self.stop("Stopped: character died")
        else:
            self.status = "Stopped: character died"
        self.resume = None                           # Rego / the watchdog won't walk back into it
        self.s._drop_resume = None
        # forget the old life: no queued goto, detour, summon, errand, re-invite or comeback restarts it
        self.detour = None
        self.after_goto = None
        self._pending_goto = None
        self._expect_seq = None
        self.s._reinvite, self.s._reinvite_at = [], 0
        # what you were carrying is on your corpse now: forget it until the next 'i' (gear watch, gear
        # modes, keys for doors and errands all read this)
        self.st.carrying = ""
        self.st.wealth = None
        # 0.8.201, bug hunt: the coins and the encumbrance went with it — a naked character still thought it was
        # full (loot refused coins) and stash / drop sent commands for coins it didn't have
        self.st.coins = {}
        self.st.enc = None
        # and the rest swap: its 'eq <fighting gear>' would fire for gear that's in the corpse (Redress dresses you
        # from what's remembered once the corpse is back)
        self._swap, self._swap_back, self._swap_rested = None, [], False
        self._save_swap_owed([])
        self._search_wait = None
        try:
            self.errands.active = None
            self.s.remote._summon = None
            self.s.bosshunt.reset("died")
            self.s.trips.reset("died")
            self.s.scrolls.cancel("died")
            self.s.training.reset("died")
            self.s.comeback.reset("died")
        except Exception:
            pass
        self.s.watchdog.gave_up = True
        # a new life has no poison / blindness: a blindness kept past death held the walk and cast cure blind
        # every 4 s (0.8.201, bug hunt: ailments kept after death)
        self.x.ailments.clear()
        try:
            self.x.care._reported.clear()            # (0.8.224.2, review: a new life isn't knocked down either)
        except Exception:
            pass
        self.dead_hold = now                         # nothing walks until you start it yourself (dead_blocked)
        hang = (cfg.death_action or "stay") == "hangup"
        msg = f"Died{where}{what}." + (" Hanging up." if hang else " Staying put — nothing restarts until you do.")
        self.log(msg)
        self.s.on_alert("Died" + where)
        self.s.notify.send("death", msg)
        if hang:
            self._death_hangup_at = now + max(3, int(cfg.death_hangup_secs or 8))

    def dead_blocked(self, what) -> bool:
        """After a death MudPilot never walks by itself — no rejoin, comeback, errand, resume or watchdog
        (Dan, 2026-10-30: 'it should never try to recover by itself' — naked and solo it dies again). Someone
        starting it does: your Go to / Loop / Rego in the window, or a friend's @goto / @summon / @comeback /
        @loop / @rego. That clears it. True = refused."""
        if not getattr(self, "dead_hold", 0):
            return False
        import inspect
        try:
            frames = [(os.path.basename(f.filename), f.function) for f in inspect.stack()[2:12]]
        except Exception:
            frames = []
        ui = ("app.py", "gotodlg.py", "pathbuilder.py", "mapview.py", "roominfo.py")
        loop_fns = ("_loop", "main", "mainloop", "callit", "__call__", "_restart_quit")
        auto = ("session.py", "comeback.py", "errands.py", "control.py", "events.py", "watchdog.py",
                "bosshunt.py", "shoptrips.py", "scrolls.py")
        # nearest caller first: a button / menu / Goto pick, or a friend's @command — not the bot's own tick
        # (which runs under the window's loop) and not MudPilot's own automatic walks
        for m, fn in frames:
            if m in auto:
                break
            if (m in ui and fn not in loop_fns) or (m == "remote.py" and fn.startswith(("c_", "_goto_bg"))):
                self.dead_hold = 0
                self.log("Walking again (someone started it) — after the death")
                return False
        if self.ready("dead_hold_note", 20):
            self.log(f"Not {what}: died — nothing walks until you start it yourself (Go to / Loop / Rego)")
        self.status = "Died — waiting for you"
        return True

    def _entry_attack(self, mobs, in_range, being_hit) -> bool:
        st, cfg = self.st, self.cfg
        if not (cfg.attack_on_entry and cfg.auto_combat and mobs and in_range) or st.in_combat:
            return False
        seq = st.view_seq
        if getattr(self, "_entry_seq", None) == seq:
            return False
        if self._step_flag("NOATTACK") or (st.max_hp and st.hp_pct() < max(cfg.heal_pct, cfg.rest_below_hp)):
            return False                       # hurt: heal / rest rules decide first
        self._entry_seq = seq
        self._cool["cast"] = 0
        self._cool["attack"] = 0
        self._cool["pre"] = 0
        self.fight(mobs)
        return True

    def _held_now(self) -> bool:
        """Held, webbed or engulfed (a minute at most since the line — a missed 'you can move again' can't leave
        it on)."""
        a = getattr(self.x, "ailments", None) or {}
        t = a.get("held")
        return bool(t) and time.time() - t < 60

    def attack_last_hold(self, mobs, being_hit) -> bool:
        """Attack last no longer holds the attack back (Revolution, 2026-10-31: "it's waiting for others to attack
        first — I want it to attack immediately, then attack again if someone attacks after me"). The attack goes at
        once; _attack_after_party re-sends it when a party member joins in."""
        return False

    def _bot_attack_ok(self) -> bool:
        """The bot's own attack may go out again: not paused, Combat on, and not a fight you've taken over by hand."""
        man = getattr(self, "manual", None)
        fighting = bool(self.cfg.auto_combat or getattr(self, "hunt_target", None))   # (an event's boss: Combat or not)
        return not self.paused and fighting and not (man is not None and getattr(man, "active", False))

    AL_OPENER_SECS = 1.5

    def _al_pending_tick(self, now):
        """Attack last: a party member joined before our own opening cast landed — re-send once it's had the time."""
        p = getattr(self, "_al_pending", None)
        if not p:
            return
        ac = getattr(self, "_attack_cmd", None)
        if not ac or ac[1] != p[1] or not self.st.in_combat or now - p[1] > 10:
            self._al_pending = None      # (we've attacked again meanwhile, or the fight's over: nothing to re-send)
            return
        if now - p[1] >= self.AL_OPENER_SECS:
            self._al_pending = None
            self._attack_after_party(p[0])

    def _attack_after_party(self, name):
        """Attack last: a party member just joined the fight after us — attack again, so we're the last to."""
        cfg, st = self.cfg, self.st
        ac = getattr(self, "_attack_cmd", None)
        now = time.time()
        if not self._bot_attack_ok():
            return
        if not cfg.attack_last or not ac or now - ac[1] > 30 or not (st.in_combat or now - ac[1] < 5):
            return
        done = self.__dict__.setdefault("_al_answered", set())
        if name.lower() in done or len(done) >= 6:
            return                  # (no time gap: Evolution joining 1 s after Buddy went unanswered — Dan, 2026-10-31)
        if now - ac[1] < self.AL_OPENER_SECS:
            # 0.8.224 (Dan: "fix it please this is big" — PVEREV, 5,781 toggles a week): our attack's first cast lands
            # ~0.4 s after *Combat Engaged*; a re-send before that is *Combat Off* / *Engaged* and the opening cast is
            # thrown away (1,867 of 2,093 re-sends in one trace came before our first cast). Wait till it's had time
            # to land, then re-send (tick: _al_pending_tick)
            self._al_pending = (name, ac[1])
            return
        period = float(getattr(getattr(self.s, "clock", None), "period", 5.0) or 5.0)
        recent = [t for t in getattr(self, "_al_times", []) if now - t < period]
        if len(recent) >= 5:
            # two MudPilots both on attack last answer each other forever (each re-attack looks like the other
            # joining): at most 5 a round — a party has 5 others at most (Dan, 2026-10-31)
            self._al_times = recent
            return
        self._al_times = recent + [now]
        done.add(name.lower())
        self._al_sent_at = now
        self.send(ac[0])
        self._attack_cmd = (ac[0], now)

    # ---------------------------------------------------------- party
    def party_tick(self):
        """MegaMUD-style party check: 'par' every few seconds so the Party window stays current."""
        cfg, st = self.cfg, self.st
        secs = float(cfg.party_check_secs or 0)
        if self.hurrying() and not getattr(self.x, "_following", None):
            # timed pyramid, leading: 41 'par's cost a 4-minute run — but none at all left party heals with no HP
            # to go on (Dan, 2026-11-04: "blessing and healing were both shit"). Every 15 s; followers as usual
            secs = max(secs, 15.0) if secs > 0 else 0
        if secs <= 0:
            return False
        if st.pending and self.walking and time.time() - self._cool.get("par", 0) < secs * 3:
            return False                # mid-move — but never let it lapse for long on a walk
        # (0.8.199: only on our own walk. A follower sitting still with an unanswered look 'pending' held every
        # 'par' back 12 s — and each party heal waits for a fresh 'par': Revolution healed Miserable once every
        # 12-15 s while resting, and the rests ran long — Revolution, 2026-11-15)
        if getattr(self, "_solo", False) and not st.party:
            return False        # the game said we're not in a party: no 'par' until party news (note_line)
        if not st.party and getattr(self, "_par_tries", 0) >= 1 and not self.ready("par_solo", 300):
            return False        # not in a party: just check now and then
        if self.walking and st.party:
            # walking: a 'par' just before a move holds the room back ~0.13 s (Evolution's trace, 0.8.139: 1.87 s vs
            # 1.74 s on 43% of moves — the whole step gap to MegaMUD). Nobody gets hurt between fights, so check once
            # combat is engaged (the round is ticking anyway) and every few seconds in a long fight; out of combat
            # only a 60 s backstop for poison and the like (Dan, 2026-11-01)
            if st.in_combat:
                if not getattr(self, "_par_this_fight", False):
                    self._par_this_fight = True
                    self._cool["par"] = 0
            else:
                self._par_this_fight = False
                if time.time() >= getattr(self, "_par_soon_until", 0):
                    secs = max(secs, 60)
                # (0.8.208: but not while a member is being healed / knocked down / hit: each party heal waits for
                #  a fresh 'par', and the 60 s backstop held it back — Revolution healed Miserable once every 15 s,
                #  7 s median from heal to the next 'par', 40% over 10 s — Dan, 2026-11-19)
        if self.ready("par", secs):
            self._par_tries = getattr(self, "_par_tries", 0) + 1
            self.send("par")
            return True
        return False

    # ---------------------------------------------------------- walking
    JOIN_WAIT = 40                       # seconds the walk waits for someone invited to start following

    PARTY_BASH = 4                       # bashes each helper sends per ask
    HELP_SECS = 60                       # a door only a follower can open: their go before trying round it
    HELP_MAX = 180                       # ...and in all, when it's the only way
    HELP_ASK_WAIT = 20                   # nobody to ask (not here, not a MudPilot) this long: as before

    def _door_helpers(self, room, d, hands, ex, now) -> bool:
        """A locked door only followers can bash / pick (partyB P4, party3 D3, partyA #4): ask them ('@do bash east'
        / '@do pick east', again every 20 s — _party_bash), try 'open' every few seconds while they work, and only
        after HELP_SECS fetch its key (when something drops / sells it) or go round; the only way: keep at it till
        HELP_MAX. True = handled this tick; False = nobody could be asked, the usual tries go on."""
        hd = getattr(self, "_help_door", None)
        if not hd or hd["at"] != (room, d) or now - hd["seen"] > 15:
            hd = self._help_door = {"at": (room, d), "t0": now, "seen": now, "next": 0.0, "asked": False,
                                    "round": False, "off": False, "op0": getattr(self, "_opened", None)}
        hd["seen"] = now
        if hd["off"]:
            return False
        op = getattr(self, "_opened", None)
        if op and op != hd["op0"] and op[1] == d:
            self._help_door = None                   # they got it open: the walk goes through
            return True
        word = DIR_WORDS.get(d, d)
        self._party_bash(d, hands)
        hb = getattr(self, "_bash_help", None)
        if hb and hb[0] == room and hb[1] == d and now - hb[2] < 25:
            hd["asked"] = True
        el = now - hd["t0"]
        if not hd["asked"] and el >= self.HELP_ASK_WAIT:
            hd["off"] = True
            return False
        names = ", ".join(hands)
        if hd["asked"] and el >= self.HELP_SECS and not hd["round"]:
            hd["round"] = True
            w = self.s.world
            need = w.exit_need(ex) if ex is not None else None
            # its key, if there's somewhere to get one (not "quest item?" — that ended the Go to with Revolution there
            # to bash it: partyB P4)
            if need and self.errands.source_for(need[0], near=room) and self._fetch_door_key(room, d, ex):
                self._help_door = None
                return True
            if self.route_around(room, d, f"the door {word} didn't open for {names}"):
                self._help_door = None
                return True
            self.log(f"The door {word} is the only way — {names} keep at it")
        if el >= self.HELP_MAX:
            self._help_door = None
            self.stop(f"Stopped: the door {word} is locked — {names} couldn't open it in {self.HELP_MAX // 60} min")
            return True
        if hd["asked"] and now >= hd["next"]:
            hd["next"] = now + 3.0
            self._opening_dir = d
            self.send(f"open {word.lower()}")        # (try it while they work: a picked lock still needs opening)
        self._locked_dir = d                         # (back here next tick: the "locked" answer doesn't pace this)
        verb = "picking" if (ex is not None and not re.search(r"/strength", ex.etype or "", re.I)) else "bashing"
        self.status = (f"Door {word} locked — {names} {verb} it" if hd["asked"]
                       else f"Door {word} locked — waiting for {names} to {verb[:-3]} it")
        self._last_progress = now
        return True

    def _party_bash(self, d, strong=None):
        """Leading and bashing a door: the party's MudPilots in the room bash it too (Dan, 2026-10-30) — every
        bash is a roll on that player's strength, so more hands get it open sooner. Asked again every 20 s."""
        cfg, st = self.cfg, self.st
        if not getattr(cfg, "party_bash_help", True) or not self.x.leading():
            return
        hb = getattr(self, "_bash_help", None)
        now = time.time()
        if hb and hb[0] == st.room and hb[1] == d and now - hb[2] < 20:
            return
        try:
            peers = {p.lower() for p in self.s.partysync.peers}
        except Exception:
            peers = set()
        here = {p.split()[0].lower() for p in ((st.view.players if st.view else []) or []) if p}
        me = (cfg.my_name or "").lower()
        helpers = [n for n in (st.party or {}) if n.lower() != me and n.lower() in peers and n.lower() in here]
        if strong:
            # the door wants more strength than yours: the ones who have it — and say so if they're not here
            helpers = [n for n in helpers if n.lower() in {x.lower() for x in strong}]
            if not helpers and self.ready("bash_wait_strong", 20):
                self.log(f"The door needs {', '.join(strong)} to bash it — waiting for them here")
        if not helpers:
            return
        word = DIR_WORDS.get(d, d)
        # each helper does what they're good at: a picker picks, a strong one bashes (Dan, 2026-11-01 — the party
        # sync tells the leader everyone's strength and picklocks)
        rr_ = self.s.world.room(st.room) if st.room else None
        dm = self.DOOR_NEED_RE.search(((rr_.exits.get(d).etype if rr_ and rr_.exits.get(d) else "") or ""))
        need = int(dm.group(1)) if dm and dm.group(1).isdigit() else 0
        try:
            info = {k.lower(): v for k, v in self.s.partysync.info().items()}
        except Exception:
            info = {}
        how = []
        for n in helpers[:5]:
            i = info.get(n.lower(), {})
            pick_ok = need and int(i.get("pick") or 0) >= need
            bash_ok = not dm or (dm.group(2) and (not need or int(i.get("str") or 0) >= need))
            if need and i.get("str") is not None and not (pick_ok or bash_ok):
                continue                             # (the prismatic dragon's door, 201: nobody's bash does a thing)
            verb = "pick" if pick_ok and not bash_ok else "bash"
            if dm and not dm.group(2):
                verb = "pick"                        # '[or 100 picklocks]': bashing it only hurts
            self.send(f"/{n} @do " + "^M".join([f"{verb} {word}"] * self.PARTY_BASH))
            how.append(f"{n} ({verb})")
            self._bash_help = (st.room, d, now)
        if how:
            self.log(f"Asked {', '.join(how)} to help with the door {word}")

    RUSH_TRIES = 8          # (Dan, 2026-11-20: redoing a timed gate is normal here — never wait on a human)

    def _rushing(self):
        """The lever gate this step is part of, between the first lever and going through (Dan, 2026-10-30: the
        mummy's gate 1/1056 N — levers in 1/1038 and 1/1044 — shuts on a timer; walking too slowly missed it)."""
        mp = self.path if self.walking else None
        for r in (getattr(mp, "rush", None) or []):
            if r["first"] <= self.idx <= r["gate"]:
                return r
        return None

    def _rush_retry(self) -> bool:
        """'No exit in that direction' at a lever gate: it shut before we got there — back round the levers."""
        r = self._rushing()
        if not r or self.idx != r["gate"] or self.st.room not in (None, r["room"]):
            return False
        if self.pilot.on():
            return False                             # Go to: the pilot goes back round the actions itself
        r["tries"] = r.get("tries", 0) + 1
        d = DIR_WORDS.get(r["dir"], r["dir"])
        if r["tries"] > self.RUSH_TRIES:
            self.stop(f"Stopped: the {d} gate in {r['room'][0]}/{r['room'][1]} shut before we got there "
                      f"{self.RUSH_TRIES} times")
            return True
        self.log(f"The {d} gate shut before we got there — pulling the levers again, faster "
                 f"(try {r['tries'] + 1} of {self.RUSH_TRIES + 1})")
        self.idx = r["begin"]
        self._resends, self._expect_seq = (None, 0), None
        self.st.pending.clear()
        return True

    def _step_flag(self, name) -> bool:
        if not self.walking or not self.path or not self.path.steps:
            return False
        i = min(self.idx, len(self.path.steps))     # (0.8.225, logs: the lap's last step — idx is past it in flight)
        if name in ("NOATTACK", "DONTREST") and i > 0 and any(p and p[0] == "move" for p in self.st.pending) and \
                (not self.st.view or (self.st.view.t or 0) < (self._step_sent_at or 0)):
            i -= 1          # (0.8.224, real logs — 1,925 chai cast at a No-attack room's monsters on the way out: the
                            #  move is on its way, so we still stand in the room the last step left from)
        if i >= len(self.path.steps):
            return False
        stp = self.path.steps[i]
        on = stp.flag(name) or (name in ("NOATTACK", "DONTREST") and bool(stp.room)
                                and stp.room in self._runthru_rooms())
        # a run-through room (loop editor, 0.8.211): no fighting, no resting — straight out the other side
        if on and name == "NOATTACK" and self._pinned():
            if self.ready("pinned_said", 20):
                self.log("Pinned in a no-attack room (knocked down / can't get out while being hit) — fighting back")
            return False
        return on

    STUCK_AFTER = 2       # a move sent this long ago that didn't take
    PINNED_AFTER = 4      # hit in the same room this long, whatever the reason

    def _pinned(self) -> bool:
        """Can't move: knocked down / held / stunned — fight at once, hit yet or not — or being hit with the path's
        move sent STUCK_AFTER s ago and still here (or PINNED_AFTER s in the room). No attack is for running
        through, not for lying there taking it (Dan, 2026-11-20: Miserable PVE knocked down in the zombie pen's
        no-attack room, 920 -> 88 HP in 33 s without a swing or a spell, then died a room later; "attack
        immediately as soon as he gets knocked down, held, or otherwise can't move")."""
        if self._knocked_down_now():
            return True
        if not getattr(self, "_being_hit", False):
            return False
        room, since = getattr(self, "_room_at", (None, 0))
        if room is None or room != self.st.room:
            return False
        now = time.time()
        sent = getattr(self, "_step_sent_at", 0) or 0
        return (sent > since and now - sent >= self.STUCK_AFTER) or now - since >= self.PINNED_AFTER

    def _runthru_rooms(self) -> set:
        """This path's run-through rooms (loop editor): entered just after a combat round goes off and left
        before the next one, so no round lands there (Dan, 2026-11-19)."""
        mp = self.path
        if not mp:
            return set()
        from .extras import room_text
        key = (os.path.basename(mp.filename) if getattr(mp, "filename", None) else mp.title).lower()
        return {room_text(t) for t in ((self.cfg.loop_runthru or {}).get(key) or [])} - {None}

    RUNTHRU_PER_ROOM = 1.0       # seconds to allow for walking into a room and out again
    RUNTHRU_MARGIN = 0.8

    def _round_wait(self, step, rt: set) -> bool:
        """Hold before stepping into a run-through room until a combat round has just gone off, so we're in and
        out (every run-through room in a row) before the next one. False = go now."""
        clock = getattr(self.s, "clock", None)
        left = clock.left() if clock else None
        dest = step.dest
        if left is None:
            if self.ready(f"rt_noclock_{dest}", 60):
                self.log(f"Run-through room {dest[0]}/{dest[1]}: no round timing yet (no fight seen lately) — "
                         f"going straight through")
            return False
        n, mp, i = 0, self.path, self.idx
        while i < len(mp.steps) and mp.steps[i].dest in rt and n < 6:
            n, i = n + 1, i + 1
        period = clock.period
        need = min(period - 0.4, self.RUNTHRU_MARGIN + self.RUNTHRU_PER_ROOM * max(n, 1))
        rem = left[0]
        now = time.time()
        held = getattr(self, "_rt_hold", None)
        if not held or held[0] != (dest, self.idx):
            held = self._rt_hold = ((dest, self.idx), now)
        if rem >= need or now - held[1] > period * 3:
            self._rt_hold = None
            return False                             # a round only just went off: in and out before the next
        self.status = f"Timing the round: into {dest[0]}/{dest[1]} in {rem:.1f}s"
        return True

    def _index_for_current(self, start=0):
        st, mp = self.st, self.path
        if not mp:
            return None
        here = st.room
        n = len(mp.steps)
        # nearest step first (a step or two either side), not the first match round the loop: a loop
        # through look-alike rooms (Rotting Glade, Trail…) shouldn't jump 20 steps back on a hiccup
        order = [start % n]
        for k in range(1, n):
            order.append((start + k) % n)
            order.append((start - k) % n)
        order = list(dict.fromkeys(order))
        if here:
            for j in order:
                if mp.steps[j].room == here:
                    return j
            return None
        # location ambiguous: a path planned on MME's map knows its rooms — one of the candidates must be
        # a step's room (look-alikes share a hash, so the hash alone could jump 100 steps ahead)
        if getattr(mp, "resolve_note", "") == "built from MME" or mp.title.startswith("Go to "):
            cands = set(st.candidates or [])
            for j in order:
                if mp.steps[j].room in cands:
                    return j
            return None
        hashes = {self.s.world.room(c).mega_hash for c in st.candidates if self.s.world.room(c)}
        for j in order:
            if mp.steps[j].hash in hashes:
                return j
        return None

    def _loop_rooms_near(self, here, mp, depth=3) -> bool:
        """A room of this path within `depth` moves of here, on MME's map."""
        w = self.s.world
        rooms = {tuple(s.room) for s in mp.steps if s.room}
        if not rooms or not here:
            return False
        seen, frontier = {tuple(here)}, [tuple(here)]
        for _ in range(depth):
            nxt = []
            for k in frontier:
                r = w.room(k)
                for ex in (r.exits.values() if r else []):
                    to = tuple(ex.to) if getattr(ex, "to", None) else None
                    if to and to not in seen:
                        if to in rooms:
                            return True
                        seen.add(to)
                        nxt.append(to)
            frontier = nxt
        return False

    def _anchor(self) -> bool:
        """If we're in a room whose hash matches a step but the path was resolved to a
        look-alike area, re-resolve it from where we really are."""
        here, mp = self.st.room, self.path
        if not here or not mp:
            return False
        if getattr(mp, "resolve_note", "") == "built from MME" or mp.title.startswith("Go to "):
            # a path planned on MME's map already knows its rooms: off it means walk back (replan), never
            # 'this look-alike room must be step 150' — the Great Pyramid is all the same room
            return False
        if any(s.room == here for s in mp.steps):
            return False
        if self._loop_rooms_near(here, mp):
            # a room of the path a step or three away (started beside the loop on the Ocean Floor's open grid): walk
            # back to it — re-anchoring here slid the whole lap onto a parallel look-alike column (m1617c R1, OCDWLOOP)
            return False
        h = self.s.world.room(here).mega_hash
        n = len(mp.steps)
        for k in range(n):
            j = (self.idx + k) % n
            if mp.steps[j].hash == h and anchor_path(self.s.world, mp, j, here):
                self.idx = j
                self.log(f"Path re-anchored at step {j + 1} on {here[0]}/{here[1]}")
                return True
        return False

    # ---------------------------------------------------------- what's holding the walk (pMUD-style)
    def hold(self, source: str, why: str):
        """Something asks the walk to wait. Only that source's release() lets it go again."""
        self.holds = getattr(self, "holds", {})
        if source not in self.holds:
            self.log(f"Walk held by {source}: {why}")
        self.holds[source] = (why, time.time())

    def release(self, source: str):
        h = getattr(self, "holds", {})
        if h.pop(source, None):
            self.log(f"Walk hold released: {source}")

    def regroup_hold(self):
        """After a MudPilot restart the leader waits in place for the party it had, re-inviting them, instead of
        looping solo (Dan, 2026-10-28: Miserable ran off before Buddy was back in the realm). Returns the names
        still missing, or None. Gives up after comeback_wait_mins so a follower who never comes doesn't hang us."""
        rg = getattr(self.s, "_regroup", None)
        if not rg or not self.cfg.reinvite_after_reconnect:
            return None
        now, st = time.time(), self.st
        party = {n.lower() for n in (st.party or {})}
        missing = [n for n in rg["names"] if n.lower() not in party]
        if not missing or now > rg["until"]:
            if missing:
                self.log(f"Regroup: {', '.join(missing)} didn't come back in {self.cfg.comeback_wait_mins:g} min "
                         "— carrying on without them")
            self.s._regroup = None
            return None
        if now - rg.get("asked", 0) > 6:
            rg["asked"] = now
            here = {p.split()[0].strip(".,").lower() for p in (st.view.players if st.view else []) if p.split()}
            for n in missing[:5]:
                if n.lower() in here:
                    self.send(f"invite {n}")          # in the room with us: invite (session adds the @join)
            self.status = f"Regrouping after restart — waiting for {', '.join(missing)}"
        return ", ".join(missing)

    def walk_holds(self) -> dict:
        """Every reason the walk is waiting right now, by who asked: {source: why}. The walk runs only
        when this is empty — combat ending can't restart a walk a dropped member or a message rule is holding."""
        st = self.st
        out = {k: v[0] for k, v in getattr(self, "holds", {}).items()}
        hold = self.s.remote.holding()
        f = getattr(self.s.comeback, "fetch", None)
        if hold and f and f.get("phase") == "going" and f.get("name", "").lower() == hold.lower():
            hold = None     # they said @wait (can't move) and @comeback: we're walking to them — that's the point
        if hold:
            out["party @wait"] = f"waiting for {self.s.remote.hold_text(hold)}"
        held = self.s.msgrules.holding_walk()
        if held:
            out["message rule"] = held
        gone = self.s.comeback.holding() if (self.loop or (self.path and self.path.title.startswith("Go to "))) else None
        if gone:
            out["comeback"] = f"waiting for {gone} (regrouping)"
        rg = self.regroup_hold()
        if rg:
            out["regroup"] = f"waiting for {rg} after restart"
        if st.hp is not None and st.max_hp and st.hp <= 0:
            out["mortally wounded"] = "HP 0 or below"        # (0.8.202: at 0 too; max_hp: no prompt read yet)
        if out and self.in_deadly():
            # standing still here kills you (the underwater passage drowns you in ~15 s): nothing holds the walk
            return {k: v for k, v in out.items() if k == "mortally wounded"}
        return out

    def walk(self, mobs, in_range):
        st, cfg, mp = self.st, self.cfg, self.path
        now = time.time()
        if getattr(self, "_planning", False):
            self.status = "Calculating route — one moment please…"
            return                             # the new route is on its way (bgplan): don't walk the old one
        jw = getattr(self.s, "_join_watch", None) or {}
        waiting = [n for n, w in jw.items() if now - w.get("t0", w["t"]) < self.JOIN_WAIT]
        if waiting and self.x.leading():
            # invited and not following yet ('X started to follow you.' not seen): don't leave them behind
            # (Dan, 2026-10-30: 'if one of them had lagged out and didn't join would he still have gone?')
            self.status = f"Waiting for {', '.join(waiting)} to join"
            return
        if getattr(self, "_drift_release_at", 0) and now >= self._drift_release_at:
            self._drift_release_at = 0
            self.release("drift")
        if getattr(self, "_member_down_until", 0) and now >= self._member_down_until:
            self._member_down_until = 0
            self.release("member down")
        holds = self.walk_holds()
        if holds:
            self.status = "Waiting — " + "; ".join(holds.values())
            self._last_progress = now
            if "message rule" not in holds and "mortally wounded" not in holds:
                self.idle_regen(mobs)
            return
        if now - getattr(self, "_user_moved_at", 0) < float(cfg.pause_on_typed_move or 0):
            self.status = "You're driving — waiting a moment"
            self._last_progress = now
            return
        if self._at_sea(now):
            return
        self._confirm_arrival()
        if self._waiting_for_party_through(now):
            return
        if now - (getattr(st, "cant_act_at", 0) or 0) < 3:
            # 'You are fast asleep.' / 'You are paralyzed!' / 'You are too stunned to move anywhere!': the game ate the
            # move — not the exit's fault; give it a moment instead of resending at once (0.8.202, Wayfarer)
            self.status = "Can't act right now — trying the step again in a moment"
            self._last_progress = now
            return
        if not any(e[0] == "move" for e in st.pending) and not self._awaiting_move(now):
            if st.pending and now - getattr(st, "_sent_at", 0) < 2.0:
                return                               # a look's answer is on its way — no need to time the step out
            st.pending.clear()                       # only looks left over (their rooms already came in): go on
        if st.pending or self._awaiting_move(now):
            # waiting for the result of the last move
            if now - self._step_sent_at > cfg.step_timeout:
                self.log("Step timed out — refreshing")
                st.pending.clear()
                self._expect_seq = None
                self.send("")
                self._step_sent_at = now
            return
        if now < getattr(self, "_door_wait_until", 0):
            self.status = "Waiting for the door"
            return                                   # open / pick / bash went out: hear what happened before moving
        if st.room != self._lock_room:
            self._lock_tries, self._lock_room = {}, st.room
        if self._locked_dir and self._timed_door(st.room, self._locked_dir):
            d, self._locked_dir = self._locked_dir, None
            n = self._lock_tries.get(d, 0) + 1
            self._lock_tries[d] = n
            tr_ = self.__dict__.setdefault("_timed_round_at", {})
            if n > self.TIMED_TRIES and n <= 40 and now - tr_.get((st.room, d), 0) >= self.TIMED_ROUND_SECS:
                # 0.8.224 (Dan, regression walks): the pyramid's timed doors are spliced back into the new route, so
                # going round put the same door back and it re-planned every tick (~12 log lines a second for minutes).
                # Once every TIMED_ROUND_SECS; 'open' every 2 s in between, as before the retries ran out
                tr_[(st.room, d)] = now
                if self.route_around(st.room, d, f"the door {DIR_WORDS.get(d, d)} didn't open ({n - 1} tries)"):
                    return                             # another way round: don't stand here trying for 2 minutes
            if n > 40 and now - tr_.get((st.room, d), 0) >= self.TIMED_ROUND_SECS:
                tr_[(st.room, d)] = now                # (0.8.224.3, loops hunt: the 10 s limit held after try 40 too)
                if not self.route_around(st.room, d, f"the door {DIR_WORDS.get(d, d)} never opened"):
                    self.stop(f"Stopped: the door {DIR_WORDS.get(d, d)} never opened (tried 'open' for 2 minutes)")
                return
            # a door nobody can pick or bash ('[1000 picklocks/strength]'): it's opened some other way, or on a timer
            # (the Great Pyramid's). Try 'open' every few seconds — never walk into it while it's closed (Dan,
            # 2026-11-01: Buddy sent 'e' into the Slum Street Rusted Gate, 1/1169, ~80 times, never 'open east')
            self.status = f"Door {DIR_WORDS.get(d, d)} closed — trying to open it ({n})"
            self._timed_retry_at = now + 2.0
            self._timed_dir = d
            return
        if getattr(self, "_timed_dir", None) and st.room:
            if now < getattr(self, "_timed_retry_at", 0):
                return
            d, self._timed_dir = self._timed_dir, None
            self._opening_dir = d
            self.send(f"open {DIR_WORDS.get(d, d).lower()}")
            self._door_wait_until = now + 2.5
            return
        if self._locked_dir:
            d, self._locked_dir = self._locked_dir, None
            n = self._lock_tries.get(d, 0)
            key = self._door_key(st.room, d)
            lk_ = self.__dict__.setdefault("_lock_keys", {})
            if key and lk_.get((st.room, d)) != key:
                # the key turned up while we stood here (dropped, or handed over): it gets its go — the tries so far
                # were counted without it, and n landed past 'use … key' (partyA #5, the Black House door)
                n = 0
                self._lock_tries.pop(d, None)
            lk_[(st.room, d)] = key
            k = 1 if key else 0                       # pMUD: the key first, then pick, then bash
            picks = int(cfg.attempt_pick or 0) if (cfg.pick_locks or self.can_pick_doors()) else 0
            bashes = int(cfg.attempt_bash or 0)
            rr_ = self.s.world.room(st.room) if st.room else None
            dx_ = rr_.exits.get(d) if rr_ else None
            at_ = self.s.world.action_at(dx_) if dx_ is not None else None
            if at_ and at_ != st.room and self.pilot.redo_remote(st.room, d):
                # opened from another room (a lever down the hall): not 'pull lever' here, not a bash — go and do it
                self._lock_tries.pop(d, None)
                return
            acts = dx_.action_cmds() if (dx_ is not None and dx_.kind == "door") else []
            unbashable = dx_ is not None and "1000 picklocks" in (dx_.etype or "").lower()
            dm = self.DOOR_NEED_RE.search((dx_.etype or "") if dx_ is not None else "")
            if dm and dm.group(1).isdigit() and not (st.strength or st.picklocks) and \
                    getattr(self, "_door_st", None) != (st.room, d):
                # what the door needs is known, your strength and picklocks aren't: 'st' first (Buddy, 2026-11-02:
                # ~20 bashes at the prismatic dragon's door, '[201 picklocks/strength]')
                self._door_st = (st.room, d)
                self._locked_dir = d
                self.send("st")
                self.status = f"Door {DIR_WORDS.get(d, d)} locked — checking your strength first"
                self._door_wait_until = now + 2.5
                return
            if dm and not dm.group(2):
                bashes = 0                            # '[or 100 picklocks]': no strength in it — bashing just hurts
            if dm and dm.group(1).isdigit() and dm.group(2) and st.strength and st.strength < int(dm.group(1)) \
                    and not self.door_hands(dx_):
                bashes = 0                            # too strong a door for you, and for everyone in the party
            if dm and dm.group(1).isdigit() and (st.picklocks or st.strength) and (st.picklocks or 0) < int(dm.group(1)):
                picks = 0                             # (party Miserable, picklocks 0, bashed the Black House door 3x)
            # your picklocks cover this door ('[or 41 picklocks/strength]', you have 60): picking is the first choice —
            # before the key, before bashing (Dan, 2026-11-01: Miserable PVE bashed with Pick locks ticked)
            pick_ok = bool(dm) and (st.picklocks or 0) > 0 and \
                (dm.group(1).lower() == "any" or (st.picklocks or 0) >= int(dm.group(1)))
            if pick_ok:
                picks = max(picks, int(cfg.attempt_pick or 0) or 3)
            weak = dm and dm.group(1).isdigit() and dm.group(2) and st.strength and st.strength < int(dm.group(1)) \
                and self.door_hands(dx_)
            # too weak for it yourself, someone in the party isn't: they bash, you try the door
            self._bash_by = weak if (weak and not key and not pick_ok) else None
            # only a follower can open it (too strong for you to bash, or picklocks-only and yours don't cover it):
            # they bash / pick it, paced on them — not on the instant "locked" answers to your 'open', which used the
            # tries up in ~1 s and called the Go to off (partyB P4, party3 D3, partyA #4)
            mine_ok = pick_ok or bool(dm and dm.group(1).isdigit() and dm.group(2)
                                      and (st.strength or 0) >= int(dm.group(1)))
            # (your strength not read: you bash it yourself, as before — test_only_door, the Darkwood tree house)
            known_ = bool(st.strength) if (dm and dm.group(2)) else bool(st.strength or st.picklocks)
            hands = self.door_hands(dx_) if (dm and dm.group(1).isdigit() and known_ and not key and not mine_ok
                                             and not acts
                                             and not unbashable and getattr(cfg, "party_bash_help", True)
                                             and self.x.leading()) else []
            if hands and self._door_helpers(st.room, d, hands, dx_, now):
                return
            if acts:
                # MME knows the room command that unlocks it ('turn stand'): that, then the door — never a bash
                order = ["^M".join(acts), "open {dir}"] * max(
                    [2] + [int(a.get("tries") or 0) for a in dx_.actions])   # (the crowbar's strength test: 4)
            else:
                order = [cfg.pick_cmd] * picks if pick_ok else []
                order += [f"use {key} {{dir}}"] * k
                if pick_ok:
                    order += [cfg.bash_cmd] * bashes  # (the picks went first)
                elif unbashable:
                    order += ["open {dir}"]           # 1000 picklocks/strength: no pick or bash will ever do it
                elif getattr(cfg, "bash_doors_first", True) and not self.can_pick_doors():
                    order += [cfg.bash_cmd] * bashes + [cfg.pick_cmd] * picks + ["open {dir}"]
                else:
                    order += [cfg.pick_cmd] * picks + [cfg.bash_cmd] * bashes
            ul = getattr(self, "_unlocked", None)
            if ul and ul[0] == st.room and ul[1] == d and now - ul[2] < 60:
                cmd = "open {dir}"                      # unlocked a moment ago (the key's gone): just open it
                self._unlocked = None
            elif n < len(order):
                cmd = order[n]
            else:
                if self._fetch_door_key(st.room, d, dx_):
                    return                            # its key: from the party, the floor, or whoever drops it
                if self.route_around(st.room, d, f"the door {DIR_WORDS.get(d, d)} won't open"):
                    return
                keep_bash = bool(cfg.bash_cmd and bashes and not unbashable and n < len(order) + 40)
                # (your picklocks cover it and bashing's no use: keep picking, as bashing keeps going — m14c M14C-2, an
                #  L60 thief left inside the Stone Barracks after 3 missed picks)
                keep_pick = bool(not keep_bash and pick_ok and cfg.pick_cmd and not unbashable and n < len(order) + 40)
                if not (keep_bash or keep_pick):
                    self.stop(f"Stopped: the door {DIR_WORDS.get(d, d)} is locked")
                    return
                # the only way there: keep bashing it (Dan, 2026-11-02: "Need to bash if its closed")
                cmd = cfg.bash_cmd if keep_bash else cfg.pick_cmd
                self._bash_by = None
            self._lock_tries[d] = n + 1
            self.status = f"Door {DIR_WORDS.get(d, d)} locked — {cmd.split()[0]} (try {n + 1})"
            if cmd == cfg.bash_cmd:
                self._party_bash(d, getattr(self, "_bash_by", None))
                hb = getattr(self, "_bash_help", None)
                if not (hb and hb[0] == st.room and hb[1] == d and now - hb[2] < 25):
                    self._bash_by = None      # nobody stronger was asked (not here, not a MudPilot): bash it yourself
            sent_cmd = "open {dir}" if (cmd == cfg.bash_cmd and getattr(self, "_bash_by", None)) else cmd
            for part in sent_cmd.format(dir=DIR_WORDS.get(d, d)).split("^M"):
                self.send(part)               # (your own bash would only hurt you: try the door while they bash)
            self._opening_dir = d
            self._door_wait_until = now + 3.0
            return
        if st.door_closed_dir:
            d = st.door_closed_dir
            st.door_closed_dir = None
            mp_ = self.path
            if mp_ and mp_.steps and not self.detour and st.room:
                # the bumped move was this path's last step (walk moved idx on as it sent it): back to that step, so
                # once the door's open the walk goes through it, not on past the room behind it (loopsB B3: dead-end
                # rooms behind doors that weren't shown closed — Guest Quarters 8/688 — were skipped)
                p_ = (self.idx - 1) % len(mp_.steps)
                ps = mp_.steps[p_]
                if ps.room == st.room and (ps.dir or "").upper() == (norm_dir(str(d)) or str(d)).upper():
                    self.idx = p_
            if getattr(cfg, "bash_doors_first", True):
                self._locked_dir = d                 # bash first (closed doors here are nearly always locked)
                return
            self._opening_dir = d
            self.send(f"open {DIR_WORDS.get(d, d)}")
            self._door_wait_until = now + 2.5
            return
        if st.locate_until > now:
            # 'pro' is out: hear where we are before the next move — its answer clears the move queue, so a move sent in
            # between was lost, and in the dark the bot thought it never moved, walled a real exit and stopped (loopsC
            # LC2, Storm Mountain at 16/1020)
            self.status = "Checking location"
            return
        if self._room_task(now):
            return                                   # something to do here before going on (the floating key)
        if self.pilot.on() and self.pilot.prepare(now):
            return                                   # Go to: the pilot is finding out where we are (pilot.py)
        if self.s.scripters.trailing(mobs):
            return                                    # trailing someone scripting our loop, inside it (scripters.py)
        # follow a detour back onto the path first
        if self.detour:
            ex = self.detour[0]
            if st.room and st.room != self._detour_from:
                # did we arrive where we expected?
                if st.room == self._detour_expect:
                    self.detour.pop(0)
                    self._detour_fails = 0
                    if not self.detour:
                        self.detour = None
                        self.idx = self._index_for_current(self.idx) or self.idx
                        return
                    ex = self.detour[0]
                else:
                    self.detour = None   # went somewhere else; recompute
                    return
            elif self._detour_from is not None:
                if not st.room:
                    # the move went somewhere we can't place: look, don't send the old move from who-knows-where
                    if self.ready("detour_look", 3):
                        self.send("")
                    if not self.locate_now("lost on a detour") and now - self._step_sent_at > 15:
                        self.detour = None
                    return
                sw = getattr(self, "_search_wait", None)
                if sw and sw["room"] == st.room and sw["dir"] == ex.dir:
                    self._send_exit(ex)              # still searching for it — not a failed move
                    return
                if st.move_failed == getattr(self, "_detour_fail_seen", None):
                    self._send_exit(ex)              # nothing failed since we last looked (e.g. a refresh)
                    return
                self._detour_fail_seen = st.move_failed
                # still in the room we left: that move failed (confusion eating it doesn't count)
                if now - getattr(st, "confused_fail_at", 0) > 6:
                    self._detour_fails = getattr(self, "_detour_fails", 0) + 1
                if self._detour_fails >= 2:
                    self._detour_fails = 0
                    self.s.world.fail_edge(st.room, ex.dir)
                    self.log(f"Detour: {DIR_WORDS.get(ex.dir, ex.dir)} from {st.room[0]}/{st.room[1]} didn't work "
                             "twice — planning round it")
                    self.detour = None
                    if self._drifted("detour"):
                        return
                    return
            self._send_exit(ex)
            return

        if self.idx >= len(mp.steps):
            last = mp.steps[-1].dest if mp.steps else None
            if last and st.room and st.room != last and not self.loop:
                # didn't actually make the final move — step back and retry
                j = self._index_for_current(0)
                if j is not None:
                    self.idx = j
                    return
            if self.loop and getattr(self, "_lap_sw", None) == (id(mp), st.steps_walked):
                # not a step walked since the last lap was counted: a retry of a last move that didn't land, not another
                # lap — each one counted, firing every lap-end hook (loopsA LA2: the Mummy regen loop's 'n', 4 laps in
                # 0.7 s). (Counted here, where idx wraps, so a last step that's gone round still counts: loopsD R1)
                self.idx = 0
                return
            if self.loop:
                self._lap_sw = (id(mp), st.steps_walked)
                self.idx = 0
                self.laps = getattr(self, "laps", 0) + 1
                rec = self.s.loopstats.lap_end(mp)
                self.s.autotune.lap_end()
                try:
                    self.s.advisor.lap_check(mp)
                except Exception as ex:
                    self.log(f"Advisor: {ex}")
                if self.x.stash_at_lap_end(mp):
                    return
                if self.s.training.lap_end(mp):
                    return                            # a level banked: off to the trainer (training.py, 0.8.200)
                if self.s.trips.lap_end(mp):
                    return
                if self.lights.lap_end(mp):
                    return                            # short of a light strong enough for this loop: buy one
                if self.s.scrolls.lap_end(mp):
                    return                            # new spells to learn since the level-up: scroll shops
                if self._rotate(mp, rec):
                    return
            else:
                done = mp.title
                nxt = self.after_goto
                self.walking = False
                self.path = None
                self.after_goto = None
                self.status = f"Arrived: {done}"
                self.log(self.status)
                self._check_arrival_meetup(mp.steps[-1].dest if mp.steps else None)
                if done.startswith("Go to "):
                    self.switches_on("Arrived")
                if nxt:
                    self.start_path(nxt)
                return
        step = mp.steps[self.idx]
        if not step.move and (not step.room or st.room == step.room or
                              (not st.room and (not st.candidates or step.room in st.candidates))):
            # in its room: do the commands. Anywhere else (dig dropped you in a Dark Pit) the walker below gets
            # you back first — fight what's down there, 'climb out' — then digging carries on
            return self._stay_step(step, now)
        here = st.room
        mme_path = getattr(mp, "resolve_note", "") == "built from MME" or mp.title.startswith("Go to ")
        on_track = (here == step.room) if (here and step.room) else \
            (step.room in (st.candidates or []) if (mme_path and step.room) else
             any(self.s.world.room(c).mega_hash == step.hash for c in st.candidates if self.s.world.room(c)))
        if on_track and getattr(self, "_loop_reset_pending", None) is mp:
            self._begin_loop(mp)
        if on_track and getattr(self, "_stash_pending", None) is mp:
            # (None back = the pack isn't read yet — just back in after a restart: 'i' asked, tried again next step)
            if getattr(self.x, "_following", None) or \
                    self.stash.on_loop(mp, tell=getattr(self, "_stash_tell", False)) is not None:
                self._stash_pending = self._stash_tell = None
        if not on_track and self._anchor():
            return
        if not on_track:
            j = self._index_for_current(self.idx)
            if j is not None:
                if j != self.idx:
                    old, n_ = self.idx, len(mp.steps)
                    self.log(f"Resynced to step {j + 1}/{n_}")
                    self.idx = j                      # take the new place first — a held tick mustn't log it again
                    ahead = (j - old) % n_
                    # a step or few further on (the move went through, we just missed the room coming in) is
                    # progress, not drift; backwards, or a big jump, is being knocked off the path
                    if not (0 < ahead <= 5) and self._drifted("resync"):
                        return
                self.idx = j
                step = mp.steps[j]
            elif here and mp.resolved:
                if now - getattr(self, "_replan_at", 0) < 0.8:
                    return                           # replan at most every 0.8 s
                self._replan_at = now
                # 0.8.225.1 (Dan: Miserable PVE's treasure digging kept stopping): a dig that drops you into the Dark Pit
                # is the loop working, not being knocked off it — every lap's climb out counted, 7 in 5 min stopped it
                dug = now - getattr(self, "_dig_at", 0) < self.DIG_DROP_SECS
                if not dug and self._drifted("detour"):
                    return
                targets = {s.room for s in mp.steps if s.room}
                route = self.back_route(here, targets)
                if route and self.loop and step.room and step.room != here:
                    # knocked off mid-lap: back to the step we were on when that's only a little further, not the
                    # nearest loop room anywhere — that skipped a whole spur of the lap (dark3 D2, JTVELOO2)
                    own = self.back_route(here, step.room)
                    if own and len(own) <= len(route) + 3:
                        route = own
                if route:
                    self.log(f"Off path at {here[0]}/{here[1]} — {len(route)}-step detour back")
                    self.detour = route
                    self._send_exit(route[0])
                    return
                self.stop("Stopped: lost and no route back to the path")
                return
            else:
                if here and not mp.resolved and not getattr(self.s, "paths_busy", None) and \
                        now - self._last_progress > 6:
                    # 0.8.224 (Dan, logEVO): a MegaMUD loop that isn't matched to MME's map can't be found again from
                    # a room off it — say so now, not after 60 s of Enter
                    self.stop(f"Stopped: off '{mp.title}' at {here[0]}/{here[1]}, and that loop isn't matched to "
                              "MME's map, so MudPilot can't find its way back — walk to the loop's start and start "
                              "it again")
                    return
                if self.ready("lost", 3):
                    self.status = "Lost — looking around"
                    self.send("")
                if now - self._last_progress > 60:
                    self.stop("Stopped: couldn't find the path for 60s")
                return
        # skip room if mobs outside range and auto combat on → keep walking
        left = len(mp.steps) - self.idx
        self.status = f"{left} room{'s' if left != 1 else ''} to go  {mp.title}" if not self.loop else \
            f"{left} left this lap  {mp.title}"
        dest_room = self.s.world.room(step.dest) if step.dest else None
        sneak_now = cfg.auto_sneak and (cfg.sneak_mode != "smart" or not dest_room or bool(dest_room.lair)
                                        or not st.party)
        if sneak_now and ((st.view and st.view.monsters) or getattr(self, "_no_sneak_room", None) == st.room):
            sneak_now = False      # the game won't let you sneak with monsters in the room (even peaceful ones)
        if sneak_now and self._sneak_hopeless():
            sneak_now = False
        if sneak_now and not st.sneaking and cfg.sneak_cmd and not st.in_combat:
            if cfg.dont_move_unless_sneaking:
                if self.ready("sneak_wait", 2):
                    self.send(cfg.sneak_cmd)
                self.status = "Waiting to sneak before moving"
                return
            self.send(cfg.sneak_cmd)
        rt = self._runthru_rooms()
        # pulled a timed gate's lever, or crossing a run-through room: no waiting about till we're through
        rushing = self._rushing() or (here is not None and here in rt)
        if not rushing and self._boss_ahead(step):
            return
        if not rushing and self._lair_wait(here):
            return
        if not rushing and self._danger_ahead(step, mobs):
            return
        if not rushing and self._hurt_ahead(step):
            return
        if not rushing and self._lair_pace(step, mobs):
            return
        if not rushing and self.s.scripters.holding(mobs):
            return                                    # someone clearing just ahead of us: let them come round
        self._danger_hp = 0
        if self._swap:
            self.end_swap("moving on")           # the rest gear comes off before the next step, not after
            return
        if self._search_gate(step.pre, step.dir, here):
            return
        if self._light_ahead(step):
            return
        if self.lights.before_step(step):
            return                                    # readying a carried light before a dark room (lights.py)
        if self._disarm_gate(step, here):
            return
        self._ward_gear(step)
        if self._key_door(step, here, now):
            return
        if self._guard_first(step, here, now):
            return
        if step.dest and step.dest in rt and here not in rt and not st.in_combat and self._round_wait(step, rt):
            return
        kd_ = getattr(self, "_key_done", None)
        for c in step.pre:
            ks_ = getattr(self, "_key_skip", None)
            if ((kd_ and kd_[0] == here and kd_[1] == step.dir and now - kd_[2] < 120) or
                    (ks_ and ks_[0] == here and ks_[1] == step.dir and now - ks_[2] < 120)) and \
                    re.match(r"^use .*\bkey\b", c, re.I):
                continue                            # unlocked already (the key crumbled), or it didn't work: not again
            mme_ = getattr(self.path, "resolve_note", "") == "built from MME"   # (your own paths: as written)
            ar = self.s.world.action_rooms(c) if (here and mme_) else set()
            if ar and here not in ar:
                # an exit action that's done in another room: the Mausoleum's 'twist sword' (17/2076) went out in the
                # Family Tomb right after 'twist hand' (Miserable PVE, 2026-11-06) — 'no effect', and in a
                # specific-order lock a wrong one can reset it. Only where MME says it's done.
                self.log(f"Not sending '{c}' here ({here[0]}/{here[1]}) — that's done in "
                         + ", ".join(f"{r[0]}/{r[1]}" for r in sorted(ar)[:3]))
                continue
            if not SEARCH_CMD_RE.match(c):
                self.send(path_text(c))
                self._action_sent_at = now          # a room action (ask sphinx / push block): watch its answer
                if c.lower().startswith("use ") and step.dir:
                    self._pre_door_dir = step.dir   # 'use lion key w': an unlock of the door this step goes through
        move = step.move
        party_form = False
        if move and move.lstrip(".").lower().startswith(("@party ", "@do ")):
            # a path / learned step written as '@party go vortex': the followers' half of it. Send the real
            # command too (and say it for them) — saying it alone left Miserable standing there
            from .worlddb import clean_move
            move = clean_move(move) or move
            party_form = True
        if st.view and st.view.t and hasattr(self, "step_gaps") and not st.in_combat:
            self.step_gaps.append(now - st.view.t)        # how long we stood here before moving on
        d_ = step.dir
        rx_ = self.s.world.room(here) if here else None
        dex_ = rx_.exits.get(d_) if (rx_ and d_) else None
        if dex_ is not None and dex_.kind == "door" and dex_.action_cmds() and \
                any(c in (step.pre or []) for c in dex_.action_cmds()):
            self._opened = (st.view_seq, d_)       # MME's room command opens this door (sent just now): walk on
        if d_ and st.view and d_ in (st.view.closed or set()) and getattr(self, "_opened", None) != (st.view_seq, d_):
            # pMUD: open a door you can see is closed before walking into it (saves a bump and a round trip);
            # a locked one answers "is locked" and the pick / bash tries take over. Never walked into while it's shown
            # closed and nothing said it opened (Dan, 2026-11-01: "never a reason to walk through a closed gate even
            # once") — the open / pick / bash tries go on until it opens or they run out (then round it, or stop)
            if getattr(self, "_door_seen", None) == (st.view_seq, d_):
                self._locked_dir = d_
                self.status = f"Door {DIR_WORDS.get(d_, d_)} still closed"
                return
            self._door_seen = (st.view_seq, d_)
            if getattr(cfg, "bash_doors_first", True):
                # Dan: closed doors are almost always locked — bash it before even trying to open it (a key you
                # carry still goes first; 'open' is the last thing tried)
                self._locked_dir = d_
                self.status = f"Door {DIR_WORDS.get(d_, d_)} closed — bashing it"
                return
            self._opening_dir = d_
            self.status = f"Opening the door {DIR_WORDS.get(d_, d_)}"
            self.send(f"open {DIR_WORDS.get(d_, d_)}")
            self._door_wait_until = now + 2.5
            return
        if self._no_such_exit(step, here):
            return
        if self._resend_guard(here, move):
            return
        self._bring_party(step, move, force=party_form)
        self._boat_check(here, move, step)
        self._expect_move()
        self._expect_dest = (step.dest, st.view_seq, here) if step.dest else None
        self.why("step", n=self.idx + 1, of=len(mp.steps), frm=here, move=move, to=step.dest,
                 room_sure=bool(st.room), path=mp.title[:40])
        if move.upper() == "U" and getattr(self, "_hurry", None) and self._hurry.get("seen"):
            self._hurry.update(up_from=here, up_at=now, up_seq=st.view_seq)   # up a level = out of the timed part
        self.send(move.lower() if move in DIR_WORDS else move)     # n / se / u, or a text exit as written
        self._step_sent_at = now
        self._last_progress = now
        self.idx += 1

    def _stay_step(self, step, now):
        """A step that doesn't move — only commands (Path builder, Dan 2026-10-28: dig for treasure in 13/211
        until there are 10 chests at 430% encumbrance, where you couldn't walk a loop anyway). Send them, give the
        game a round to answer (dig freezes about a round before 'you found…'), then the next step / lap."""
        sent = getattr(self, "_stay_sent", None)
        if self._dig_out_of_spades():
            return
        if sent is None or sent[0] is not step:
            if self._swap:
                self.end_swap("moving on")
                return
            if any(c.strip().lower().startswith("dig") for c in step.pre or []):
                if getattr(self, "_dig_check", None):
                    return                           # reading the inventory after "Nothing happens."
                self._dig_at = now
            for c in step.pre:
                self.send(path_text(c))
            self._stay_sent = (step, now)
            self.status = "Doing: " + ", ".join(step.pre or ["(nothing)"])
            self._last_progress = now
            return
        if now - sent[1] < 2.5 or self.st.last_prompt < sent[1] + 0.3:
            return
        self._stay_sent = None
        self._last_progress = now
        self.idx += 1

    SPADE_RE = re.compile(r"\b(?:spades?|shovels?)\b", re.I)

    DIG_DROP_SECS = 180        # off the path this soon after a dig: the dig dropped you (the Dark Pit) — not drift
    HEAVY_STOP_SECS = 180      # "too heavy to move" this long (no weakness wearing off): stop and say so

    def _dig_out_of_spades(self) -> bool:
        """Dan, 2026-10-28: 'dig treasure' → "Nothing happens." means you're out of spades. Read the inventory;
        no spade left → stop the dig loop (and say so). Three "Nothing happens" in a row stop it anyway."""
        dc = getattr(self, "_dig_check", None)
        if not dc:
            return False
        st = self.st
        if st.inv_seq == dc["seq"]:
            if time.time() - dc["t"] > 10:
                self._dig_check = None              # no inventory came back: carry on
            return False
        self._dig_check = None
        if not self.SPADE_RE.search(st.carrying or ""):
            self._dig_nothing = 0
            self.stop("Stopped digging: out of spades (\"Nothing happens.\" and none left in your pack)")
            self.s.on_alert("Out of spades — digging stopped")
            self.s.notify.send("stop", "Out of spades — digging stopped")
            return True
        if getattr(self, "_dig_nothing", 0) >= 3:
            self._dig_nothing = 0
            self.stop("Stopped digging: \"Nothing happens.\" three times in a row")
            self.s.on_alert("Digging: nothing happens — stopped")
            return True
        return False

    def _light_ahead(self, step) -> bool:
        """pMUD: light up *before* walking into a room MME says is as dark as one you've already had to
        light (so the room tracker never loses you in the dark). Learned per session: a character who
        sees in the dark never casts it."""
        cfg = self.cfg
        if not (cfg.auto_light and cfg.light_cmd) or self.st.in_combat:
            return False
        too = getattr(self, "_too_dark", None)
        dr = self.s.world.room(step.dest) if step.dest else None
        self._expect_dark_room = step.dest
        if too is None or not dr or int(dr.light or 0) > too:
            return False
        if time.time() - getattr(self, "_lit_at", 0) < 90 or not self.ready("light", 20):
            return False
        self._lit_at = time.time()
        self.status = "Lighting up — it's dark ahead"
        self.send(cfg.light_cmd)
        return True

    HEAT_RE = re.compile(r"^You suffer in the desert heat", re.I)
    DRINK_LASTS = 600                    # Dan: a waterskin keeps the heat off for 600 seconds

    def _desert_drink(self, text):
        """Dan, 2026-11-04: the Scorching Desert leaves alone whoever drank from a waterskin (its room spell skips
        anyone under the waterskin's spell) or wears the sunstone wristband. Use it coming into the desert (unless
        the last one is still working), then again only when the heat gets you — a waterskin has 3 uses, so none
        are spent on a timer. Each character does it for themselves — followers too, since it's on every line,
        not on the leader's steps."""
        w = self.s.world
        spn = (getattr(w, "room_spells", None) or {}).get(self.st.room) if self.st.room else None
        drinks = w.spell_drinks(spn) if spn else frozenset()
        if not drinks:
            self._in_desert = False
            return
        now, heat = time.time(), bool(self.HEAT_RE.match(text.strip()))
        last = getattr(self, "_drank_at", 0)
        came_in, self._in_desert = not getattr(self, "_in_desert", False), True
        if not heat and not (came_in and now - last >= self.DRINK_LASTS):
            return
        if heat and now - last < 10:
            return                                    # just drank: the game hasn't caught up
        have = self.held_items() or set()
        if have & (w.spell_items(spn) - drinks):
            return                                    # the sunstone wristband: nothing to drink for
        nm = next((w.item_name(i) for i in drinks & have if w.item_name(i)), None)
        if not nm:
            if heat and self.ready("no_waterskin", 120):
                self.log("Desert heat — and no waterskin to drink from (any shop with waterskins, 25 copper)")
            return
        self._drank_at = now
        self.log(f"Desert: using the {nm}" + (" (the heat got you)" if heat else " (it keeps the heat off)"))
        self.send(f"use {nm}")                     # Dan: "use waterskin works for sure"

    def _ward_gear(self, step):
        """pMUD: the room ahead casts something nasty on whoever walks in (MME room spell) and you carry an
        item that negates it — put it on first."""
        w = self.s.world
        spn = getattr(w, "room_spells", {}).get(step.dest) if step.dest else None
        if not spn:
            return
        sp = w.spells.get(spn) or {}
        from .spells import is_attack_spell
        if not (is_attack_spell(sp) or re.search(r"poison|drain|curse|blind|web|hold|paraly", sp.get("Name") or "", re.I)):
            return
        items = set(getattr(w, "negates", {}).get(spn) or []) & (self.held_items() or set())
        if not items:
            return
        from .gamestate import worn_list
        worn = {n.lower() for n, _slot in worn_list(self.st.carrying)}
        names = [w.item_name(i) for i in items]
        if any(n.lower() in worn for n in names if n):
            return
        nm = next((n for n in names if n), None)
        if nm and self.ready(f"ward_{nm}", 600):
            self.log(f"{w.room(step.dest).name if w.room(step.dest) else 'Next room'} casts {sp.get('Name', 'a spell')} "
                     f"on you — wearing {nm} (it stops that)")
            self.send(f"wear {nm}")

    # ---------------------------------------------------------- traps
    DISARM_OK_RE = re.compile(r"successfully disarmed|trap is already disarmed|there is no trap", re.I)
    DISARM_FAIL_RE = re.compile(r"\b(?:try|attempt)\s+(?:to|and)\s+disarm\s+the\s+trap\b|\bfail\s+to\s+disarm\b|"
                                r"\btrigger\s+the\s+trap\b|spikes\s+jut\s+out|as\s+you\s+fiddle\s+with\s+the\s+wire|"
                                r"an\s+arrow\s+shoots\s+out", re.I)

    def _trap_helper(self):
        """The party's best trap-disarmer standing here (their MudPilot told us its Traps skill), if they're better
        at it than you (Dan, 2026-11-01)."""
        st = self.st
        if not st.party or self.x.leading() is False:
            return None
        try:
            info = self.s.partysync.info()
        except Exception:
            info = {}
        here = {p.split()[0].strip(".,").lower() for p in ((st.view.players if st.view else []) or []) if p.split()}
        mine = int(getattr(st, "traps", 0) or 0) if self.cfg.disarm_traps else 0
        best = max(((int(d.get("traps") or 0), n) for n, d in info.items() if n.lower() in here), default=(0, None))
        return best[1] if best[0] > mine else None

    def _disarm_cmd(self, dw, d):
        word = DIR_WORDS.get(d, d).lower()
        if dw.get("by"):
            self.send(f"/{dw['by']} @do disarm trap {word}")
        else:
            self.send(f"disarm trap {word}")

    def _disarm_gate(self, step, here) -> bool:
        """pMUD: 'disarm trap <dir>' before a trapped exit, and wait for 'successfully disarmed' (or the trap
        going off). A couple of tries, then walk on through. True = waiting. Leading, the party's best disarmer
        does it if they're better at it than you — '@do disarm trap <dir>', and they say how it went."""
        cfg = self.cfg
        d = step.dir
        if not d or self.st.in_combat:
            return False
        r = self.s.world.room(here) if here else None
        ex = r.exits.get(d) if r else None
        # (0.8.208, Dan: Evolution walked the Vine Bridge's '(Spell Trap: 851)' east of 16/1206 without disarming it
        #  and was dropped into the mists — a spell trap is kept 'restricted' for the router, and this only knew '(Trap')
        spell_trap = ex is not None and ex.kind == "restricted" and "spell trap" in (ex.etype or "").lower()
        if not (step.flag("DISARM") or (ex is not None and ex.kind == "trap") or spell_trap):
            return False
        dw = getattr(self, "_disarm", None)
        if dw and dw["room"] == here and dw["dir"] == d:
            if dw["ok"]:
                return False
            wait = 12 if dw.get("by") else 6           # (a partner's answer comes by telepath)
            if dw["fail"] or time.time() - dw["t"] > wait:
                if dw["tries"] >= int(cfg.disarm_tries or 2):
                    dw["ok"] = True                  # walk on through it
                    self.log(f"Couldn't disarm the trap {DIR_WORDS.get(d, d)}"
                             + (f" ({dw['by']} tried)" if dw.get("by") else "") + " — going through anyway")
                    return False
                if dw["fail"]:
                    self.send("")                    # it went off: look at HP before trying again
                dw.update(t=time.time(), fail=False, tries=dw["tries"] + 1)
                self._disarm_cmd(dw, d)
            self.status = f"Disarming the trap {DIR_WORDS.get(d, d)}" + (f" ({dw['by']})" if dw.get("by") else "")
            return True
        helper = self._trap_helper()
        if not cfg.disarm_traps and not helper:
            return False
        self._disarm = {"room": here, "dir": d, "t": time.time(), "tries": 1, "ok": False, "fail": False,
                        "by": helper}
        if helper:
            self.log(f"Trap {DIR_WORDS.get(d, d).lower()} — asking {helper} to disarm it (better at traps)")
        self._disarm_cmd(self._disarm, d)
        self.status = f"Disarming the trap {DIR_WORDS.get(d, d)}" + (f" ({helper})" if helper else "")
        return True

    TRAP_REPORT_RE = re.compile(r"^(\w+) telepaths: \{trap (\w+) (disarmed|not disarmed)\}", re.I)

    def _disarm_line(self, text):
        df = getattr(self, "_disarm_for", None)
        if df and time.time() - df["t"] < 15:
            # disarming for the leader: say how it went (Dan: "the trap disarmer should let the leader know")
            if self.DISARM_OK_RE.search(text) or self.DISARM_FAIL_RE.search(text):
                ok = bool(self.DISARM_OK_RE.search(text))
                self.send(f"/{df['who']} {{trap {df['dir']} {'disarmed' if ok else 'not disarmed'}}}")
                self.log(f"Trap {df['dir']}: {'disarmed' if ok else 'not disarmed'} — told {df['who']}")
                self._disarm_for = None
        dw = getattr(self, "_disarm", None)
        if not dw:
            return
        if dw.get("by"):
            m = self.TRAP_REPORT_RE.match(text.strip())
            if m and m.group(1).lower() == dw["by"].lower():
                if m.group(3).lower() == "disarmed":
                    dw["ok"] = True
                    self.log(f"{dw['by']} disarmed the trap {m.group(2)}")
                else:
                    dw["fail"] = True
            return
        if self.DISARM_OK_RE.search(text):
            dw["ok"] = True
        elif self.DISARM_FAIL_RE.search(text):
            dw["fail"] = True

    # ---------------------------------------------------------- boats
    def _boat_check(self, here, move, step):
        """Boarding a boat (MME: a cast that puts you in a cabin, then a timed voyage): you'll be somewhere
        not on the path for a few minutes — that's the trip, not being lost."""
        r = self.s.world.room(here) if here else None
        ex = next((e for e in (r.exits.values() if r else []) if e.accepts(str(move))), None)
        req = getattr(ex, "req", None) if ex else None
        if req and req.get("voyage"):
            secs = req["voyage"] * 5
            self._boat = {"land": ex.to, "until": time.time() + secs + 90, "secs": secs}
            self.log(f"Boarding — about {secs // 60:.0f} min at sea to {ex.to[0]}/{ex.to[1]}")

    def _at_sea(self, now) -> bool:
        bt = getattr(self, "_boat", None)
        if not bt:
            return False
        st = self.st
        if st.room is None and bt["land"] in (st.candidates or []):
            # ashore in a room that looks like others (Kingsport Harbor, Wharf has 45 twins): the one the boat
            # lands in is among them — that's landing, not the 90 s slack after the estimate (0.8.189, realm walk
            # sweep: it sat 'At sea — about 329 s to go' on the wharf)
            st.candidates = [bt["land"]]
        if st.room == bt["land"] or now > bt["until"]:
            if st.room == bt["land"]:
                self.log("Landed")
            self._boat = None
            self._expect_seq = None
            st.pending.clear()
            self._last_progress = now
            return False
        self.status = f"At sea — about {max(0, int(bt['until'] - 90 - now))} s to go"
        self._last_progress = now
        self._step_sent_at = now
        return True

    # ---------------------------------------------------------- portals: bring the party through
    def _bring_party(self, step, move, force=False):
        """Followers walk after you on n/e/s/w — but not through 'go portal' / 'dive sinkhole'. Leading:
        say '@party <command>' first so MegaMUD / MudPilot followers do it too, then wait for them."""
        cfg, st = self.cfg, self.st
        m = str(move or "").strip()
        if step.dir or not m or m.startswith(("@", ".", "/")) or not cfg.party_teleport_bring:
            return
        me = (cfg.my_name or "").lower()
        members = [n for n in st.party if n.lower() != me]
        if not members or not self.x.leading():
            return
        # MegaMUD followers usually follow a typed exit by themselves — saying '@party go path' as well
        # sends them through it twice (Revolution went straight back out). Only say it for commands
        # they've been seen not to follow.
        r = self.s.world.room(st.room) if st.room else None
        ex = next((e for e in (r.exits.values() if r else []) if e.kind == "text" and e.accepts(m)), None)
        teleport = bool(ex is not None and "(Teleport)" in (ex.etype or ""))
        if force or teleport or m.lower() in [c.lower() for c in (cfg.party_say_cmds or [])]:
            # a room command that moves you by magic (dive sinkhole, go vortex): followers don't follow those
            # — 'go path' / 'go hole' / 'go crack' they do — so say it for them first, then check they made it
            self.log(f"Bringing the party through '{m}'")
            self.send(f"@party {m}")
            said = True
        else:
            said = False
        self._bring = {"dest": step.dest, "names": members, "t": time.time(), "from": st.room, "cmd": m,
                       "said": said}

    def _bring_to_comeback(self, missing) -> bool:
        """Hand members who didn't make it to the comeback: it holds the walk, asks them @where, walks there,
        invites them again, then picks the walk back up."""
        self._bring = None
        cb = self.s.comeback
        if not self.cfg.party_comeback or not missing:
            return False
        now = time.time()
        for n in missing:
            cb.missing.setdefault(n, {"t": now, "why": "left behind"})
        if not cb.fetch:
            cb._ask_where(missing[0])
        return True

    def _waiting_for_party_through(self, now) -> bool:
        b = getattr(self, "_bring", None)
        if not b:
            return False
        st = self.st
        if b.get("typed") and b["dest"] is None:
            b["dest"] = st.room                     # wherever the portal put us
        if getattr(self.x, "_party_broke_at", 0) >= b["t"] - 1:
            b["broke"] = True                       # going through broke the party (vortex): they're not 'in it'
        if st.room != b["dest"] and not (b.get("broke") and st.room != b.get("from")):
            # (once the party's broken, wherever we landed counts — a look-alike room the tracker isn't sure
            # of mustn't let the walk carry on without them)
            if now - b["t"] > 20:
                self._bring = None                  # never got there (failed, or somewhere else)
            return False
        here = {p.split()[0].strip(".,").lower() for p in (st.view.players if st.view else []) if p.split()}
        missing = [n for n in b["names"] if n.lower() not in here and (n in st.party or b.get("broke"))]
        if not missing:
            if b.get("broke"):
                # everyone's here, but the party is still broken: invite them back and don't take another step
                # until each one has joined again ("Revolution started to follow you" / a 'par' with them in it)
                me = (self.cfg.my_name or "").lower()
                out = [n for n in b["names"] if n.lower() != me and not any(
                    p.lower() == n.lower() for p in (st.party or {}))]
                if out:
                    if now - b.get("invited", 0) > 15:
                        if not b.get("invited"):
                            self.log(f"{', '.join(out)} came through — the party broke, inviting back before going on")
                        b["invited"] = now
                        for n in out[:5]:
                            self.send(f"invite {n}")          # session.send adds the @join telepath
                    b["t"] = now                              # no 30 s give-up while they're standing here
                    self.status = f"Regrouping — waiting for {', '.join(out)} to join the party"
                    return True
                if b.get("invited"):
                    self.log(f"{', '.join(b['names'])} back in the party — carrying on")
            self._bring = None
            return False
        if b.get("broke") and getattr(self, "_flung_at", 0) >= b["t"] - 1 and missing:
            # Dan, 2026-10-28 pyramid: a trap ('…and vanish!' / 'you fall down through the shaft') split us up,
            # not the block we'd just pushed — they're somewhere else entirely. Don't '@do push block' and walk
            # on after 30 s: ask them @where and go get them
            self.log(f"A trap flung us away from {', '.join(missing)} — finding them (@where)")
            return self._bring_to_comeback(missing)
        if b.get("broke") and not b.get("pulled") and now - b["t"] > (10 if b.get("said") else 1.5) and b.get("cmd"):
            # (told them with '@party' already? they're on their way — only ask again if they haven't come)
            # a vortex / portal breaks the party: they stand on the other side. Ask each one to step through
            # ('@do', the same as you'd type), then invite them again when they show up
            b["pulled"] = now
            for n in missing[:5]:
                self.send(f"/{n} @do {b['cmd']}")
            self.log(f"'{b['cmd']}' broke the party — asked {', '.join(missing)} to come through")
            b["t"] = now                            # give them the full wait from here
        if now - b["t"] > 8 and not b.get("broke") and b.get("cmd") and b["cmd"].lower() not in [c.lower() for c in (self.cfg.party_say_cmds or [])]:
            # they didn't follow this one: next time say '@party <cmd>' first; this time go and get them
            self.cfg.party_say_cmds = list(self.cfg.party_say_cmds or []) + [b["cmd"]]
            self.s.on_settings_changed()
            self.log(f"{', '.join(missing)} didn't follow '{b['cmd']}' — fetching them; next time I'll "
                     f"@party it first")
            self._bring = None
            cb = self.s.comeback
            for n in missing[:1]:
                cb.missing[n] = {"t": now, "why": "left behind"}
                cb._ask_where(n)
            return True
        if now - b["t"] > 30:
            self.log(f"{', '.join(missing)} didn't come through in 30 s — finding them (@where)")
            return self._bring_to_comeback(missing)
        self.status = f"Waiting for {', '.join(missing)} to come through"
        if self.ready("bring_look", 4):
            self.send("")
        return True

    # ---------------------------------------------------------- hidden exits: search, then wait for the answer
    SEARCH_FOUND_RE = re.compile(r"^you (?:found|find|discover|uncover)\b.*\b(?:exit|passage|door|way|opening)|"
                                 r"^you found (?:a|an|the) |"
                                 r"^[a-z]+ (?:found|finds|discovers|uncovers)\b.*\b(?:exit|passage|door|way|opening)",
                                 re.I)          # (a party member helping search found it)
    SEARCH_NONE_RE = re.compile(r"^you notice nothing|^you (?:don'?t|do not) (?:find|notice|see) anything|"
                                r"^you find nothing|^your search (?:reveals|turns up) nothing", re.I)

    SEARCH_CHECK_AT = 3                  # searches before looking to make sure it's the right room
    SEARCH_MAX = 20                      # then keep going up to this many (Dan, 2026-11-02: "the exit is there" —
    #                                      Buddy, a half-ogre, missed 10/275's north exit 8 times)
    PARTY_SEARCH = 4                     # each helper searches this many times, asked again every 20 s

    def _search_gate(self, pre, d, here) -> bool:
        """pMUD: 'search north', then wait — 'You found an exit…' means go, 'You notice nothing different'
        means search again — after 3, look to check it's the right room, then on up to 8 — then go round. Already in Obvious exits = no search needed.
        True = waiting (don't move this tick)."""
        cmds = [c for c in (pre or []) if SEARCH_CMD_RE.match(c)]   # (MegaMUD writes 'sea n' too — m12pyr #4)
        if not cmds:
            return False
        st = self.st
        if d and st.view and st.view.exits and d in st.view.exits:
            return False                             # it's open already
        sw = getattr(self, "_search_wait", None)
        if sw and sw["room"] == here and sw["dir"] == d:
            if sw["found"]:
                self._search_wait = None
                return False                         # found it: move now
            if sw.get("checking") is not None:
                # 3 searches found nothing: we looked to make sure we're where we think, before searching on
                if st.view_seq == sw["checking"] and time.time() - sw["t"] < 6:
                    return True                      # the room hasn't shown yet
                sw["checking"] = None
                if st.room != here:
                    self._search_wait = None         # somewhere else after all: let the walker sort it out
                    self.log(f"Searching {DIR_WORDS.get(d, d)}: not in {here[0]}/{here[1]} after all — re-checking")
                    return False
                if st.view and st.view.exits and d in st.view.exits:
                    self._search_wait = None
                    return False                     # it's open now
                self.log(f"Still in {here[0]}/{here[1]} and the {DIR_WORDS.get(d, d)} exit is hidden here — "
                         f"searching on (low Intelligence can take 4 or 5 tries)")
                sw["none"] = True
            if sw.get("checked") and self._party_search(cmds[0], d, sw):
                pass                                 # the party's MudPilots search too (Dan: '@party search north')
            if sw.get("helped") and time.time() - sw.get("looked", 0) > 4:
                sw["looked"] = time.time()
                self.send("")                        # did one of them find it? (the exit shows in the room)
            if sw["none"] or time.time() - sw["t"] > 6:
                if sw["tries"] >= self.SEARCH_CHECK_AT and not sw.get("checked"):
                    # Dan, 2026-10-30: half-ogres and kang need 4 or 5 — look first, make sure it's the right room
                    sw.update(checked=True, checking=st.view_seq, t=time.time(), none=False)
                    self.status = f"Searched {DIR_WORDS.get(d, d)} {sw['tries']} times — checking the room"
                    self.send("")
                    return True
                if sw["tries"] >= self.SEARCH_MAX:
                    self._search_wait = None
                    n = sw["tries"]
                    if sw.get("helped"):
                        # you and the party all searched and nobody found it: not findable from here — a wall for a
                        # day, so the next Go to doesn't climb up to it again
                        self.s.note_unfindable(here, d)
                    who = " (the party searched too)" if sw.get("helped") else ""
                    if self.route_around(here, d, f"Searched {DIR_WORDS.get(d, d)} {n} times and found nothing{who}"):
                        return True
                    self.stop(f"Stopped: searched {DIR_WORDS.get(d, d)} {n} times, no exit")
                    return True
                sw.update(t=time.time(), none=False, tries=sw["tries"] + 1)
                self.status = f"Searching {DIR_WORDS.get(d, d)} (try {sw['tries']})"
                self.send(cmds[0])
            return True
        self._search_wait = {"room": here, "dir": d, "t": time.time(), "tries": 1, "found": False, "none": False}
        self.status = f"Searching {DIR_WORDS.get(d, d)}"
        self.send(cmds[0])
        return True

    def _party_search(self, cmd, d, sw) -> bool:
        """The party's MudPilots in the room search with you ('@do search north' ×4, again every 20 s): a half-ogre
        can miss an exit 8 times running that the druid finds first go (Dan, 2026-11-02)."""
        now = time.time()
        if now - sw.get("asked", 0) < 20:
            return False
        st, cfg = self.st, self.cfg
        try:
            peers = {p.lower() for p in self.s.partysync.peers}
        except Exception:
            peers = set()
        me = (cfg.my_name or "").lower()
        here_ = {p.split()[0].strip(".,").lower() for p in ((st.view.players if st.view else []) or []) if p.split()}
        helpers = [n for n in (st.party or {}) if n.lower() != me and n.lower() in peers and n.lower() in here_]
        if not helpers:
            return False
        sw["asked"], sw["helped"] = now, True
        for n in helpers[:5]:
            self.send(f"/{n} @do " + "^M".join([cmd] * self.PARTY_SEARCH))
        self.log(f"Asked {', '.join(helpers)} to help search {DIR_WORDS.get(d, d).lower()}")
        return True

    def _search_line(self, text):
        t = text.strip()
        if getattr(self, "_search_left", 0) and (self.SEARCH_FOUND_RE.search(t) or
                                                 re.match(r"^you notice (?!nothing)", t, re.I)):
            # auto Search turned something up: no more searches here, look so the Get button takes it (Dan,
            # 2026-11-08: Buddy, half-ogre, low int — 'Search each room 4 times', but not once it's found)
            self._search_left = 0
            self.send("")
        sw = getattr(self, "_search_wait", None)
        if not sw:
            return
        if self.SEARCH_FOUND_RE.search(t):
            sw["found"] = True
        elif self.SEARCH_NONE_RE.search(t):
            sw["none"] = True

    # ---------------------------------------------------------- keys, failed exits, ways round
    def _room_task(self, now) -> bool:
        """board_fixes.TASKS: in 12/2005 the floating key has to die (melee — spells don't touch it) and its
        golden lion key picked up fast, before the key door ahead. Missed it? Step out and back: it respawns."""
        st = self.st
        tb = getattr(self, "_task_back", None)
        if tb and st.room and st.room != tb[0] and not self.walking:
            # stepped out to bring the monster back, with no path to take us in again: step back in
            self._task_back = None
            if now - tb[2] < 30:
                self._resends = (None, 0)
                self.send(tb[1].lower())
                return True
        task = (getattr(self.s.world, "room_tasks", None) or {}).get(st.room)
        mp = self.path
        er = getattr(self.errands, "active", None) if hasattr(self, "errands") else None
        on_errand = bool(task and er and any(t.get("num") == task["item"] for t in er.get("todo", [])))
        # standing in the room with nothing to walk (a Go to that ended here, or you walked in): get it anyway —
        # PVE, 2026-10-28, Go to 12/2005 arrived and stood next to the floating key for minutes
        idle_here = bool(task) and not self.walking
        if task and getattr(self.x, "_following", None) and not on_errand:
            # following: the leader gets the key and opens the door (Dan, 2026-11-09: he killed the floating
            # key leading Revolution, who then @'d him to hand it over). The leader asks us if we pick it up.
            self._task_state = None
            return False
        if not task or ((not mp or not mp.steps) and not on_errand and not idle_here):
            self._task_state = None
            return False
        # (on the errand for this very item — the Go to ended here — it's needed too: 0.8.79 stood there 6 min)
        need = on_errand or idle_here or any(task["get"].split()[-1] in " ".join(s.pre or []) or "lion key" in
                                             " ".join(s.pre or []) for s in mp.steps[self.idx:])
        if not need:
            return False
        got = self.picked_items()
        held = self.held_items() or set()
        if task["item"] in held or task["item"] in got:
            if getattr(self, "_task_state", None):
                self.log(f"Got the {task['item_name']} — on to the key door")
                self._task_state = None
            return False
        ts = self._task_state = getattr(self, "_task_state", None) or {"t": now, "respawned": 0, "out": None}
        # tries survive stepping out and back (the state resets when we leave the room — PVE, 2026-10-28, did
        # 'e'/'w' for 3+ minutes one room away from 12/2005, never reaching the give-up)
        tries = self.__dict__.setdefault("_task_tries", {})
        n0, t0 = tries.get(st.room, (0, now))
        if now - t0 > 600:
            n0, t0 = 0, now
        ts["respawned"] = max(ts["respawned"], n0)
        v = st.view
        holder = getattr(self, "_task_holder", None)
        if holder and now - holder[1] < 120:
            # a party member grabbed it (Revolution's MegaMUD auto-loot): ask them to hand it over
            if self.ready("task_ask", 20):
                me = self.cfg.my_name or ""
                self.log(f"{holder[0]} has the {task['item_name']} — asking them for it")
                self.send(f"/{holder[0]} @do give {task['item_name']} to {me}")   # (without 'to' MegaMUD said ok, gave nothing)
            self.status = f"Waiting for {holder[0]} to hand over the {task['item_name']}"
            return True
        floor = " ".join(n for _q, n in (v.items if v else [])).lower()
        if task["item_name"] in floor:
            if self.ready("task_get", 0.8):
                self.status = f"Grabbing the {task['item_name']}"
                self.send(task["get"])
            return True
        mob = next((sh for sh, _r in (v.monsters if v else []) if task["monster"] in sh.lower()), None)
        if mob:
            if not st.in_combat and self.ready("task_attack", 3):
                self.status = f"Killing the {task['monster']} (melee) for its {task['item_name']}"
                self.log(self.status)
                self.send(self.cfg.attack_cmd.format(target=self.target_word((mob, None))))
            return True
        if st.in_combat:
            return True
        # not here and no key on the floor: out and back in brings it back
        if now - ts["t"] > 4 and self.ready("task_respawn", 6):
            out, back = task["respawn"]
            if ts["respawned"] in (0, 2, 4) and not ts.get(f"pro{ts['respawned']}") and self.locate_now("room task"):
                # every pyramid room looks the same ('Great Pyramid', four doors): no key here — are we really in
                # the key room, or one room off? (Dan typed 'pro' and it walked straight there)
                ts[f"pro{ts['respawned']}"] = True
                self.log(f"No {task['monster']} at {st.room[0]}/{st.room[1]} — checking it's the right room "
                         f"({self.cfg.locate_cmd})")
                return True
            ts["respawned"] += 1
            tries[st.room] = (ts["respawned"], t0)
            if ts["respawned"] > 6:
                self.stop(f"Stopped: couldn't get the {task['item_name']} in {st.room[0]}/{st.room[1]}")
                return True
            self.log(f"No {task['monster']} here — stepping {DIR_WORDS.get(out, out).lower()} and back to bring it back")
            self._resends = (None, 0)             # deliberate repeats, not a move that isn't working
            self.send(out.lower())                # (a plan brings us straight back in; standing still, _task_back does)
            if not self.walking:
                self._task_back = (st.room, back, now)
            return True
        self.status = f"Waiting for the {task['monster']}"
        return True

    def _fetch_door_key(self, room, d, ex) -> bool:
        """A locked door we can't pick or bash and whose key we don't carry (the Black House door, Key 172 —
        black star key): ask the party for it, pick it up if it's lying here, else go and get it (a wandering
        monster that drops it is hunted right here). Dan, 2026-10-28. True = on it."""
        w = self.s.world
        need = w.exit_need(ex) if ex is not None else None
        if not need or not cfg_auto_get(self.cfg) or not self.walking or not self.path:
            return False
        num = need[0]
        if num in (self.held_items() or set()):
            return False
        mp, loop = self.path, self.loop
        ok, why = self.errands.plan(mp, loop, [num], near=room)
        if not ok:
            self.log(f"The door {DIR_WORDS.get(d, d).lower()} needs the {w.item_name(num)} — {why}")
            return False
        self.walking = False
        self.set_mode("auto")
        self.status = f"Getting the {w.item_name(num)} for the door"
        return True

    def _key_door(self, step, here, now) -> bool:
        """A path step 'use lion key w' through a closed door (pyramid, 2026-10-28): it used the key, our own
        locked-door handler used it again ('You don't have lion key'), walked into the still-shut door, then
        opened it. Now: the key once, hear the answer, 'open west', then walk."""
        d_ = step.dir
        st = self.st
        if not (d_ and here and st.view and d_ in (st.view.closed or set())):
            return False
        keys = [c for c in (step.pre or []) if re.match(r"^use .*\bkey\b", c, re.I)]
        if not keys or getattr(self, "_opened", None) == (st.view_seq, d_):
            return False
        kd = getattr(self, "_key_done", None)
        if kd and kd[0] == here and kd[1] == d_ and now - kd[2] < 120:
            if kd[3]:                                # open already went out: walk
                return False
            self._key_done = kd[:3] + (True,)
            self._opening_dir = d_
            self._door_wait_until = now + 2.5
            self.status = f"Unlocked — opening the door {DIR_WORDS.get(d_, d_).lower()}"
            self.send(f"open {DIR_WORDS.get(d_, d_).lower()}")
            return True
        if now < getattr(self, "_door_wait_until", 0):
            return True
        # (twice with no "unlocked" — "You don't have …", "doesn't fit", a key that crumbled on an earlier lap: stop
        #  sending the path's key text; the normal locked-door handling takes over — MME's key, pick / bash, an errand
        #  or round it. m1617c K1: 'use chiseled key(1264) SW' every 2.5 s, forever)
        kt = self.__dict__.setdefault("_key_tries", {})
        n_, t0_ = kt.get((here, d_), (0, now))
        if now - t0_ > 120:
            n_, t0_ = 0, now
        if n_ >= 2:
            self._key_skip = (here, d_, now)
            return False
        kt[(here, d_)] = (n_ + 1, t0_)
        for c in keys:
            self.send(path_text(c))
        self._pre_door_dir = self._opening_dir = d_
        self._door_wait_until = now + 2.5
        self.status = f"Unlocking the door {DIR_WORDS.get(d_, d_).lower()}"
        return True

    TIMED_TRIES = 6        # a '1000' door: 'open' this many times (~12 s), then round it if there's a way (Dan: 40 was "wildly excessive")

    def _timed_door(self, room, d) -> bool:
        """A door no one can pick or bash ('[1000 picklocks/strength]') — it opens on its own timer."""
        r = self.s.world.room(room) if room else None
        ex = r.exits.get(d) if r else None
        strict = bool(ex is not None and ex.kind == "door" and re.search(r"\[\s*1000 picklocks", ex.etype or "", re.I)
                      and not ex.action_cmds())      # (one a room command opens — 'turn stand' — isn't on a timer)
        if strict:
            return True
        if ex is not None and ex.kind == "door" and time.time() - getattr(self, "_creak_at", 0) < 30:
            # "Doors on this level creak and thump!" — some cycle by themselves, but not all: 12/2046's east door
            # took 'e' over and over until Dan bashed it (2026-10-28). A door you can pick or bash: do it now (PVE,
            # level 3 later that night — walked into 12/2046 E and 12/2031 W five times each, then 'pick' opened
            # them first try). Only one you can't gets ~5 s to open by itself first.
            if self.door_doable(ex) is not False:
                return False
            now = time.time()
            ct = self.__dict__.setdefault("_creak_tries", {})
            n, t0 = ct.get((room, d), (0, now))
            if now - t0 > 90:
                n, t0 = 0, now
            ct[(room, d)] = (n + 1, t0)
            if n < 5:
                return True
            if n == 5:
                self._lock_tries.pop(d, None)        # the waiting tries don't count against bash / pick
                self.log(f"The door {DIR_WORDS.get(d, d).lower()} didn't open by itself — trying it")
        return False

    def _door_key(self, room, d):
        """The key MME says opens this door, if you're carrying it (its name, as you'd type it)."""
        r = self.s.world.room(room) if room else None
        ex = r.exits.get(d) if r else None
        if not ex:
            return None
        need = self.s.world.exit_need(ex)
        if not need and ex.kind == "door":
            # (0.8.223, regr222 #3: the inside of a key door, typed as a plain locked door — the same door, same key)
            tw = self.s.world.key_twin(ex)
            need = self.s.world.exit_need(tw) if tw is not None else None
        if not need:
            return None
        have = self.held_items() or set()
        if need[0] not in have:
            return None
        name = self.s.world.item_name(need[0]) or ""
        # the whole name, always: 'use large iron key e', never 'use iron key e' - a shortened name clashes with
        # something else you carry sooner or later (the iron keyring at Thrag's door, Revolution; Dan, 2026-11-21:
        # "it should use the entire text of the item")
        return name or None

    def back_route(self, here, target):
        """A route for getting back on track: same rules as Go to (avoid list, keys you carry, your
        level), and round any exit that's just failed."""
        w, cfg = self.s.world, self.cfg
        avoid = self.avoid_set()
        if here and (tuple(here) in avoid or (cfg.avoid_mode or "ask").lower() == "allow"):
            # already in the avoided area (a loop you run in the Negative Power Plane / Black Wasteland / Webbed Mine),
            # or avoiding is off: the same rule Go to's own planning uses (loopsB B2: "lost and no route back to the
            # path" one room off the NPP loops)
            avoid = frozenset()
        route = w.route(here, target, level=self.route_level(),
                        have=self.held_items() or set(), avoid=avoid)
        try:                                         # back from the bank: round Shadow Master too (0.8.185)
            return self._boss_free_route(here, target, route)
        except Exception:
            return route

    ROUND_SAME_SECS = 180  # one exit 'gone round' over and over (a spliced segment door): this long, then stop
    TIMED_ROUND_SECS = 10  # a timed door that won't open: go round it at most this often (0.8.224)

    def route_around(self, here, d, why) -> bool:
        """An exit on the path won't work: remember it, and take another way to where the path goes next
        (Go to: plan the whole trip again without it). False = there's no other way."""
        if not here or not self.path:
            return False
        # the same exit 'gone round' again and again: board_fixes' splice puts a pyramid segment's door back into the
        # new route (that's how the timed doors get their retries), so a door that never opened was re-planned every
        # ~3 s forever (m12pyr L1). A few minutes of that per door, then "no other way" — the caller stops, saying why.
        # (Back-to-back only: the same door failing once a lap on a loop, minutes apart, isn't this)
        now_ = time.time()
        rt_ = self.__dict__.setdefault("_round_tries", {})
        n_, t0_, last_ = rt_.get((here, d), (0, now_, now_))
        if now_ - last_ > 30:
            n_, t0_ = 0, now_
        if n_ >= 3 and now_ - t0_ > self.ROUND_SAME_SECS:
            if self.ready("round_same", 30):
                self.log(f"…the {DIR_WORDS.get(d, d).lower()} exit of {here[0]}/{here[1]} keeps coming back as the way "
                         f"({n_} times in {int(now_ - t0_)} s) — not going round it again")
            rt_[(here, d)] = (n_, t0_, now_)
            return False
        rt_[(here, d)] = (n_ + 1, t0_, now_)
        w = self.s.world
        w.fail_edge(here, d)
        try:
            # (0.8.224, real logs — 1/160: 'ask Lord code', 'ask Lord code word', 'ask Lord codeword'… each tried 7
            #  times, 5 min standing still. A text exit that failed: its other wordings to the same room fail too)
            r_ = w.room(here)
            ex_ = r_.exits.get(d) if r_ else None
            if ex_ is not None and ex_.kind == "text":
                for d2, e2 in r_.exits.items():
                    if d2 != d and e2.kind == "text" and tuple(e2.to) == tuple(ex_.to):
                        w.fail_edge(here, d2)
        except Exception:
            pass
        self.log(f"{why} — going round it")
        # on the bottom bar too, while it walks the long way (Dan: "it doesn't say why")
        self.route_note = (f"Went round: {why.lower()} at {here[0]}/{here[1]}", time.time())
        self.why("route_around", frm=here, exit=d, why=why)
        mp = self.path
        if mp.title.startswith("Go to ") and mp.steps and mp.steps[-1].dest:
            dest, then = mp.steps[-1].dest, self.after_goto
            if not self.back_route(here, dest):
                (getattr(w, "failed_edges", None) or {}).pop((here, d), None)
                w.forget_routes()
                self.log(f"…but the {DIR_WORDS.get(d, d).lower()} exit is the only way to {dest[0]}/{dest[1]} — "
                         "staying with it")
                self.route_note = None
                return False
            if self.goto(dest, then=then, _retry=True):
                return True
            return False
        j = min(self.idx, len(mp.steps) - 1)
        while j < len(mp.steps) and mp.steps[j].room == here:
            j += 1                                   # rejoin past this room
        targets = [s.dest for s in mp.steps[max(0, j - 1):] if s.dest and s.dest != here][:6]
        for t in targets:
            route = self.back_route(here, t)
            if route and len(route) <= 60:
                self.log(f"…{len(route)}-step way round to {t[0]}/{t[1]}")
                self.detour, self._detour_from = route, None
                # the next visit to that room from here on, wrapping round a loop — not the first one in the path
                # (0.8.201, bug hunt: a loop through a hub twice jumped back to the earlier visit, re-walking half
                # the lap)
                n_ = len(mp.steps)
                self.idx = next((i % n_ for i in range(j, j + n_) if mp.steps[i % n_].room == t), self.idx + 1)
                self._send_exit(route[0])
                return True
        return False

    def _no_such_exit(self, step, here) -> bool:
        """The step says 'e' but the room on screen has no east exit (and the map has no hidden one there):
        we're not where we think — a look-alike room (48 'Rocky Trail's). Don't type into a wall over and
        over: ask the board where we are, then take the map route from there to where this step goes."""
        st = self.st
        d_ = step.dir
        v = st.view
        if self.in_deadly():
            return False                             # drowning: just take the step
        if not d_ or not v or v.exits is None or d_ in v.exits or v.name == "(dark)":
            self._wall = None
            return False
        r = self.s.world.room(here) if here else None
        ex = r.exits.get(d_) if r else None
        if ex is not None and not ex.visible:
            return False                             # a hidden exit MME knows about: the step opens/uses it
        now = time.time()
        w = getattr(self, "_wall", None)
        # (keyed on the room and step, not the redraw: each try's own blank line redraws the room, which used to start
        #  the count over, so it never stopped — loopsB B1, an endless 'pro' at 8/654 on the Dark-elf Moat loop)
        key = (tuple(here) if here else None, self.idx, d_)
        if not w or w[0] != key:
            self._wall = w = [key, now, 0, None, 0.0]
            shown = ", ".join(sorted(DIR_WORDS.get(x, x) for x in v.exits)) or "none"
            self.why("wall", step=self.idx + 1, move=d_, room=here, shown=sorted(v.exits))
            self.log(f"Step {self.idx + 1} goes {DIR_WORDS.get(d_, d_)}, but this {v.name} only shows "
                     f"{shown} — finding out where we really are")
            if self.locate_now("step goes through a wall"):
                return True
        if now - w[1] < 4 and st.locate_until > now:
            self.status = "Checking location"
            return True                              # the locate answer is on its way
        if w[2] and w[3] == st.view_seq and now - w[4] < 6:
            return True                              # the last try's room redraw isn't back yet
        w[2] += 1
        w[3], w[4] = st.view_seq, now
        here = st.room
        dest = step.dest
        if here and dest and here != dest:
            route = self.back_route(here, dest)
            if route and len(route) <= 40:
                self.log(f"At {here[0]}/{here[1]} — taking the map's way to step {self.idx + 1}'s room "
                         f"({len(route)} step{'s' if len(route) != 1 else ''})")
                self.detour, self._detour_from = route, None
                self.idx += 1                        # rejoin at the room this step leads to
                self._send_exit(route[0])
                return True
        if here:
            targets = {x.room for x in self.path.steps if x.room}
            route = self.back_route(here, targets) if targets else None
            if route:
                self.log(f"Off path at {here[0]}/{here[1]} — {len(route)}-step way back")
                self.detour = route
                self._send_exit(route[0])
                return True
        if w[2] >= 3:
            self.stop(f"Stopped: step {self.idx + 1} goes {DIR_WORDS.get(d_, d_)} but there's no such exit here, "
                      "and I can't tell which room this is")
            self.s.on_alert("Stopped — lost (no exit that way)")
        else:
            self.send("")
        return True

    def backstep(self) -> bool:
        """pMUD's Backstep: one step back to the room you came from (the exit that leads there)."""
        st, w = self.st, self.s.world
        hist = [h for h in st.history if h]
        here = st.room
        if not here or len(hist) < 2:
            self.log("Back: I don't know where you came from")
            return False
        prev = next((h for h in reversed(hist[:-1]) if h != here), None)
        r = w.room(here)
        ex = next((e for e in (r.exits.values() if r else []) if e.to == prev), None)
        if not ex:
            self.log("Back: no exit from here leads back")
            return False
        self.send(ex.text_command if ex.kind == "text" and ex.text_command else ex.dir.lower())
        return True

    def _check_arrival_meetup(self, target):
        """Arrived where a party member summoned us, but they aren't here (Dan, 2026-10-28: Miserable 'arrived' on
        Revolution but wasn't actually with him — a look-alike room, or he moved). Verify our room (pro) and ask
        them @where, then go to them."""
        sm = getattr(self.s.remote, "_summon", None)
        if not sm or sm.get("to") != target or time.time() - sm.get("t", 0) > 180:
            return
        by = sm.get("by")
        st = self.st
        here = {p.split()[0].strip(".,").lower() for p in (st.view.players if st.view else []) if p.split()}
        if not by or by.lower() in here:
            self.s.remote._summon = None                 # met up — nothing to chase
            return
        self.log(f"Arrived where {by} summoned me, but {by} isn't here — checking the room (pro) and asking @where")
        self.locate_now("summoner isn't in the room")
        self.s.remote._summon = None
        if self.cfg.party_comeback:
            cb = self.s.comeback
            cb.missing[by] = {"t": time.time(), "why": "left behind"}
            cb._ask_where(by)

    def locate_now(self, why="") -> bool:
        """Ask the board for the room number right away (pro → 'Location: 10,23')."""
        st, cfg = self.st, self.cfg
        cmd = (cfg.locate_cmd or "").strip()
        now = time.time()
        if not cmd or self._locate_failed >= 3 or st.in_combat or now - self._locate_at < 6 or \
                (self.in_deadly() and st.room):
            return False                         # (drowning and the tracker knows the room: don't stop to ask)
        self._locate_at, self._locate_seen = now, st.locate_ok
        st.locate_until = now + 4
        self.status = f"Checking location ({cmd})"
        self.send(cmd)
        return True

    def _drop_bad_learned(self):
        """The step that just failed used a way MudPilot 'learned' (not MME's): it was a bad guess — forget it,
        and plan the Go to again without it."""
        mp = self.path
        if not mp or not mp.steps:
            return
        for st_ in mp.steps[max(0, self.idx - 2):self.idx + 1]:
            if not st_.room or not st_.move:
                continue
            w = self.s.world
            r = w.rooms.get(st_.room)
            ex = next((e for e in (r.exits.values() if r else []) if w.LEARNED_TAG in (e.etype or "")
                       and (e.accepts(st_.move) or e.dir.lower() == st_.move.lower())), None)
            if ex and w.remove_learned(st_.room, st_.move, ex.to):
                self.log(f"Map: forgot '{st_.move}' at {st_.room[0]}/{st_.room[1]} — it was learned from a wrong "
                         "guess and doesn't work there; planning again without it")
                try:
                    self.s._learned_saved = -1
                    self.s.save_learned()
                except Exception:
                    pass
                tgt = getattr(self, "_goto_target", None)
                if tgt and mp.title.startswith("Go to "):
                    self._regoto_at = time.time() + 2.5      # once 'pro' has answered
                return

    def _confirm_arrival(self):
        """The room after a step: if what the game shows (name + exits + who's here, from one display) fits
        the room the path says we walked into, that's where we are — even when look-alike rooms
        (Rotting Glade, Trail…) leave the tracker unsure or it guessed a twin."""
        if self.pilot.on():
            self._expect_dest = None                 # Go to: the pilot places us (pro / tracker), never the path
            return
        ed = getattr(self, "_expect_dest", None)
        st = self.st
        if not ed or st.view is None or st.view_seq == ed[1] or st.pending:
            return
        self._expect_dest = None
        dest, origin = ed[0], ed[2]
        v = st.view
        if st.room == dest or v.name == "(dark)" or (origin and st.room == origin):
            return                                   # arrived as planned — or the move didn't happen
        lc = getattr(st, "located", None)
        if lc and st.room == lc[0] and time.time() - lc[1] < 20:
            return                                   # 'pro' just told us where we are: that beats the path's guess
        if self.s.world.match_room(dest, v.name, set(v.exits or [])):
            was = st.room or f"{len(st.candidates)} look-alikes"
            st.candidates = [dest]
            self.log(f"Placed by the path at {dest[0]}/{dest[1]} (the tracker had {was})")

    # ---------------------------------------------------------- one move at a time
    def _expect_move(self):
        self._expect_seq = self.st.view_seq
        self._expect_fail = self.st.move_failed

    def _awaiting_move(self, now) -> bool:
        """A move went out and the game hasn't answered yet (no new room, no 'you can't go that way').
        Never send the next step (or the same one again) until it does — otherwise a text exit like
        'go hole' that the room tracker didn't queue gets sent over and over while the room is coming in."""
        if self._expect_seq is None:
            return False
        st = self.st
        if st.view_seq != self._expect_seq or st.move_failed != self._expect_fail or st.dead:
            self._expect_seq = None
            return False
        return now - self._step_sent_at < min(float(self.cfg.step_timeout or 10), 10.0)   # never wait forever

    def _drifted(self, kind) -> bool:
        """pMUD's drift policy: knocked off the path (resync / detour) more than 6 times in 5 min, or 3 times
        the same way from the same room → stop and say so, instead of wandering."""
        now = time.time()
        here = self.st.room
        self._drift = [d for d in getattr(self, "_drift", []) if now - d[0] < 300] + [(now, kind, here)]
        same = sum(1 for d in self._drift if d[1] == kind == "detour" and d[2] == here and here)
        if len(self._drift) > 6 or same >= 3:
            why = (f"knocked off the path {len(self._drift)} times in 5 min" if len(self._drift) > 6
                   else f"the same {kind} from {here[0]}/{here[1]} 3 times")
            self._drift = []
            if now - getattr(self, "_drift_warned", 0) > 600:
                # first time: stop moving for a moment, look properly, then carry on
                self._drift_warned = now
                self.log(f"Drift: {why} — pausing 10 s and looking before carrying on")
                self.hold("drift", why)
                self._drift_release_at = now + 10
                self.st.pending.clear()
                self.send("")
                return True
            if self.st.room and now - getattr(self, "_drift_soft_at", 0) > 300:
                # we do know where we are (the room's certain): look properly, find our place, carry on —
                # an unattended night shouldn't end on a few missed room displays
                self._drift_soft_at = now
                self.log(f"Drift: {why} again — at {self.st.room[0]}/{self.st.room[1]} for sure, so pausing 30 s, "
                         "finding my place and carrying on")
                self.hold("drift", why)
                self._drift_release_at = now + 30
                self.st.pending.clear()
                if not self.locate_now("drifting"):
                    self.send("")
                return True
            self.stop(f"Stopped: {why} again — Copy diagnostics shows what happened")
            self.s.on_alert(f"Stopped: {why}")
            self.s.notify.send("stop", f"Stopped: {why}")
            return True
        return False

    CHANCE_TRIES = 40      # a '(Chance)' exit ('dig grave'): this many tries in its room, then stop

    def _chance_exit(self, here, move):
        """The '(Chance)' exit this move takes from here (it works now and then: 'dig grave'), or None."""
        r = self.s.world.room(here) if here else None
        m = str(move).strip()
        for ex in (r.exits.values() if r else []):
            if getattr(ex, "chance", False) and (ex.dir.lower() == m.lower() or ex.accepts(m)):
                return ex
        return None

    def _chance_item_gone(self, cn) -> bool:
        """A chance step's item ('dig grave' → the shovel) isn't in the pack any more: a Go to plans again (its
        needed-items check fetches another); anything else stops, saying what's missing."""
        nm = self.s.world.item_name(cn["num"]) or "item it needs"
        mp = self.path
        self._resends = (None, 0)
        if mp and mp.title.startswith("Go to ") and mp.steps and mp.steps[-1].dest and cfg_auto_get(self.cfg):
            self.log(f"'{cn['move']}' had no effect and the {nm} isn't in your pack any more — planning again to get one")
            self.goto_bg(mp.steps[-1].dest, then=self.after_goto, retry=True)   # (it says why if it can't)
            return True
        self.stop(f"Stopped: '{cn['move']}' needs the {nm}, and it isn't in your pack any more")
        self.s.on_alert(f"Need the {nm} for '{cn['move']}'")
        return True

    def _st_unanswered(self, pa, now) -> bool:
        """A Go to parked for 'st' (_goto_check): wait for the answer, up to 10 s. Re-planning at 3 s without it set off
        with the HP wall / door stats still unknown, and the 30 s 'st' cooldown wouldn't ask again (regr3 #5)."""
        if abs(self._cool.get("goto_st", 0) - pa[3]) > 1 or now - pa[3] > 10:
            return False
        st = self.st
        return not (st.max_hp_read and (st.picklocks or st.strength))

    def _move_kind(self, here, move) -> str:
        r = self.s.world.room(here) if here else None
        m = str(move).strip()
        if m.startswith((".", "@", "/")) or "@party" in m.lower() or "@do" in m.lower():
            return "party"
        for ex in (r.exits.values() if r else []):
            if ex.dir.lower() == m.lower() or ex.accepts(m):
                return ex.kind
        return ""

    def _resend_guard(self, here, move) -> bool:
        """Same move from the same room again and again without getting anywhere: refresh, then stop.
        A paid move (toll, boat fare) or a party command is never sent twice: a delayed answer would mean
        paying twice, or the whole party crossing a portal twice."""
        if self._lock_tries and (norm_dir(str(move)) or str(move).upper()) in {
                (norm_dir(str(k)) or str(k).upper()) for k in self._lock_tries}:
            return False                         # picking/bashing this door: retrying the move is the point
                                                 # (not a door left from somewhere else — loopsD D1: 'n' blocked forever)
        cn_ = getattr(self, "_chance_need", None)
        if cn_:
            if self.st.inv_seq == cn_["seq"] and time.time() - cn_["t"] < 10:
                self.status = "Checking your pack…"
                return True                          # the 'i' is on its way
            self._chance_need = None
            if self.st.inv_seq != cn_["seq"] and cn_["num"] not in (self.held_items() or set()):
                return self._chance_item_gone(cn_)
        key = (here, str(move).lower())
        last, n = self._resends
        if last == key and here and self._move_kind(here, move) in ("toll", "party"):
            self.stop(f"Stopped: '{move}' got no answer — not sending it again (it costs money or moves the party)")
            self.s.on_alert(f"Stopped at '{move}' — check the screen")
            return True
        if last == key and here and time.time() - getattr(self, "_heavy_move_at", 0) < 6:
            # 0.8.227.2 (Dan: PvP Miserable stopped): "You are too heavy to move!" is your pack, not the exit — never
            # counted against it (it went round NE, SW, E, then stopped on NW, the only way). A weakness wears off;
            # still too heavy after HEAVY_STOP_SECS: stop and say why. Try again every few seconds, not 6 a second
            now = time.time()
            if now - getattr(self, "_heavy_since", now) > self.HEAVY_STOP_SECS:
                self._resends = (None, 0)
                enc = getattr(self.st, "enc", None)
                at = f" ({enc[0]}/{enc[1]} encumbrance)" if enc and len(enc) > 1 else ""
                why = f"Stopped: too heavy to move{at} for {self.HEAVY_STOP_SECS // 60} minutes — drop something"
                self.stop(why)
                self.s.on_alert(why)
                return True
            if self.ready("heavy_wait_say", 20):
                self.log("Too heavy to move — waiting (a weakness wears off), then trying again")
            self.status = "Too heavy to move — waiting"
            self._resends = (key, n)
            if now - getattr(self, "_step_sent_at", 0) < 4:
                return True
            return False
        if last == key and here and time.time() - getattr(self.st, "confused_fail_at", 0) < 6:
            # confused / afraid: the game ate the move — that's not the exit failing, so don't count it
            if time.time() - getattr(self, "_confused_said", 0) > 20:
                self._confused_said = time.time()
                self.log("Confused — the game ate that move; trying again")
            self._resends = (key, n)
            return False
        n = n + 1 if (last == key and here) else 0
        self._resends = (key, n)
        if n == 4:
            self.log(f"'{move}' from {here[0]}/{here[1]} hasn't moved me after 4 tries — looking around first")
            self.st.pending.clear()
            self._expect_seq = None
            self.send("")
            self._step_sent_at = time.time()
            return True
        if n >= 8 and self._chance_exit(here, move) is not None:
            # a '(Chance)' exit (a ~5% dig): failing is what it does — keep at it here, never 'round it' to the next
            # graveyard room with the same dig (m12 #4: 52 digs in 400 s, grave to grave); CHANCE_TRIES, then stop
            if n >= self.CHANCE_TRIES:
                self._resends = (None, 0)
                self.stop(f"Stopped: '{move}' from {here[0]}/{here[1]} didn't take me anywhere in {n} tries "
                          "(it only works now and then)")
                return True
            return False
        if n >= 8:
            self._resends = (None, 0)
            d = next((ex.dir for ex in (self.s.world.room(here).exits.values() if self.s.world.room(here) else [])
                      if ex.dir.lower() == str(move).lower() or ex.accepts(str(move))), str(move).upper())
            if self.route_around(here, d, f"'{move}' from {here[0]}/{here[1]} isn't getting anywhere"):
                return True
            self.stop(f"Stopped: '{move}' from {here[0]}/{here[1]} isn't getting anywhere (8 tries)")
            return True
        return False

    # ---------------------------------------------------------- loop rotation
    def rotation_loops(self) -> list:
        keys = [k.lower() for k in (self.cfg.rotate_loops or [])]
        by = {self.x.loop_key(mp): mp for mp in self.s.paths if mp.is_loop}
        return [by[k] for k in keys if k in by]

    def _rotate(self, mp, rec) -> bool:
        """End of a lap on a rotation loop: move on to the next one when this one's lairs came up
        mostly empty (it needs time to refill) or after N laps — the other loop refills meanwhile."""
        cfg = self.cfg
        if not cfg.rotate_on or self.s.autotune.active:
            return False                 # (an auto-tune test stays on one loop)
        loops = self.rotation_loops()
        key = self.x.loop_key(mp)
        keys = [self.x.loop_key(x) for x in loops]
        if len(loops) < 2 or key not in keys:
            return False
        why = None
        if cfg.rotate_mode == "laps":
            if self.laps >= max(1, int(cfg.rotate_laps or 1)):
                why = f"{self.laps} lap{'s' if self.laps != 1 else ''} done"
        elif rec:
            tot = rec["lairs_full"] + rec["lairs_empty"]
            if tot and 100.0 * rec["lairs_empty"] / tot >= int(cfg.rotate_empty_pct or 50):
                why = f"{rec['lairs_empty']}/{tot} lairs were empty"
        if not why:
            return False
        nxt = loops[(keys.index(key) + 1) % len(loops)]
        if not nxt.resolved or not nxt.steps or not nxt.steps[0].room:
            self.log(f"Rotation: can't place '{nxt.title}' on the map — staying on {mp.title}")
            return False
        self.log(f"Rotation: {why} on {mp.title} — moving on to {nxt.title}")
        self._rotating_to = nxt
        if self.goto(nxt.steps[0].room, then=nxt):
            return True
        self._rotating_to = None
        return False

    # ---------------------------------------------------------- danger check
    def _stretch_damage(self):
        """(damage, what) the next steps of the path can do: a trap on this step and the rooms just ahead whose room
        spell hurts (magma, a bog, a river without a raft) — the whole stretch, MME's most per room."""
        w, mp = self.s.world, self.path
        if not mp or not mp.steps:
            return 0, ""
        have = self.held_items() or set()
        total, traps, rooms = 0, 0, 0
        for i, s in enumerate(mp.steps[self.idx:self.idx + 60]):
            d = 0
            ex = step_exit(w, s)                    # (0.8.201, walk check: room-command exits too)
            if ex is not None and ex.kind == "trap":
                m = w.TRAP_RE.search(ex.etype or "")
                d += int(m.group(1)) if m else 30
                traps += 1
            sd = w.room_damage(s.dest, have) if s.dest else 0
            if sd:
                rooms += 1
            d += sd
            if not d:
                break
            total += d
            if ex is not None and ex.kind == "trap" and not sd:
                break                                # (a trap into a room that doesn't hurt: you can rest there before
                                                     #  the next one — the Ebon Blade corridor's 33 traps read as one
                                                     #  9,975-damage stretch, so it never rested: m58 R1)
        what = " and ".join(([f"a trap" if traps == 1 else f"{traps} traps"] if traps else []) +
                            ([f"{rooms} room{'s' if rooms > 1 else ''} that hurt"] if rooms else []))
        return total, what

    def _rest_barred(self) -> bool:
        """should_rest won't sit down right now (Stop's 2 minutes, a message rule's 'keep going', the pyramid timer):
        holding a step to 'rest first' would then stand there until that runs out (0.8.221, bug hunt: Black Dragons
        6/415). Same test as should_rest's."""
        return time.time() < getattr(self, "_no_rest_until", 0) and not self._fled and self.st.hp_pct() > 30

    def _hurt_ahead(self, step) -> bool:
        """0.8.190 (Dan): rest to full before a trap or a stretch of rooms that hurt (Volcano magma, a bog, a river
        without a raft) when what you have wouldn't take it without going under the hang-up line. Already full and it
        still wouldn't: go anyway (said once) — sitting there won't make it smaller."""
        cfg, st = self.cfg, self.st
        if not cfg.auto_rest or not st.max_hp or st.in_combat or not step.dest:
            return False
        if self._rest_barred():
            return False
        if step.room and self.s.world.room_damage(step.room, self.held_items() or set()):
            return False                             # in the middle of it already: sitting here hurts too — on out
        dmg, what = self._stretch_damage()
        if not dmg:
            return False
        line = st.max_hp * ((int(cfg.hangup_hp_pct or 0) if cfg.hangup_low_hp else 0) + 5) / 100
        key = (step.room, step.dest)
        if st.hp - dmg > line:
            return False
        if st.hp >= st.max_hp or st.max_hp <= dmg:
            # full already, or full wouldn't cover it either (0.8.222, Dan — walk_D2 D2-3: it rested ~2 min to full
            # when slightly under; a room or trap that can do your whole max HP isn't planned at all)
            if getattr(self, "_hurt_said", None) != ("full", key):
                self._hurt_said = ("full", key)
                self.log(f"{what.capitalize()} ahead can do up to {dmg} damage — more than you can spare even at full "
                         f"HP; going on")
            return False
        now = time.time()
        if not getattr(self, "_danger_hp", 0):
            self._danger_since = now
        if now - getattr(self, "_danger_since", now) > 600 and not st.resting:
            return False                             # couldn't rest up (something keeps interrupting) — carry on
        self._danger_hp = 100
        if getattr(self, "_hurt_said", None) != key:
            self._hurt_said = key
            self.log(f"{what.capitalize()} ahead (up to {dmg} damage) — resting to full first")
        return True

    def _guard_first(self, step, here, now) -> bool:
        """0.8.190 (Dan): a portal / hole MME only lets you use with the room clear ('nomonsters': the Deranged Priest's
        'go hole', the master assassin's 'push panel'): fight what's there first, then go. True = holding the step."""
        st, cfg, w = self.st, self.cfg, self.s.world
        mv = str(step.move or "")
        r = w.room(here) if here else None
        ex = next((e for e in r.exits.values() if e.accepts(mv)), None) if (r and mv and not step.dir) else None
        guarded = bool(ex is not None and (getattr(ex, "req", None) or {}).get("nomonsters"))
        guards = [rec for _s, rec in ((st.view.monsters if st.view else None) or [])
                  if guarded and rec and float(rec.get("exp") or 0) > 0]
        if not guards:
            if getattr(self, "_guard_hunt", False):
                self._guard_hunt, self.hunt_target = False, None
                self._guard_at = None
            return False
        names = ", ".join(sorted({g["name"] for g in guards}))
        # (Combat off too — Dan, 2026-11-13: "if the mobs need to be cleared prior to taking an exit" it fights them:
        # the Altar of Blood's teleport is the only way out of there)
        ga = getattr(self, "_guard_at", None)
        if not ga or ga[0] != here:
            est = self._fight_too_strong(guards)
            if est and not st.in_combat:
                # (0.8.223, m349 #5: an L10 took on the 1000-HP ancient willow — the same 'can I win this?' check as
                #  any fight we choose)
                self.stop(f"Stopped: {names} guards '{mv}' here — too strong for you (~{est:.0f} damage to you, max HP "
                          f"{st.max_hp}); not fighting it")
                return True
            self._guard_at = (here, now)
            self.log(f"{names} guards '{mv}' here — fighting it first")
        elif now - ga[1] > 300:
            self.stop(f"Stopped: couldn't clear {names} from {here[0]}/{here[1]} for '{mv}' in 5 minutes")
            return True
        if not self.hunt_target:
            self.hunt_target, self._guard_hunt = guards[0], True
        if not st.in_combat and self.ready("guard_look", 6):
            self.send("")                            # (did it die / leave? the room shows who's still here)
        self.status = f"Clearing the way — {names} guards '{mv}'"
        self._last_progress = now
        return True

    def _danger_ahead(self, step, mobs) -> bool:
        """Next room is a lair whose full spawn could take more HP than we can spare: rest up first."""
        cfg, st = self.cfg, self.st
        if not cfg.danger_check or not step.dest or st.in_combat or mobs:
            return False
        if self._rest_barred():
            return False
        dest = self.s.world.room(step.dest)
        if not dest or not dest.lair:
            return False
        need, a = self.s.danger.needed_pct(step.dest)
        if need is None:
            return False
        if not a.get("observed"):
            # only MME's numbers so far (no fights seen here yet): a heads-up on loops, never a forced rest
            if need > 100 and self.loop and self.s.danger._said.get(("sim", step.dest)) is None:
                self.s.danger._said[("sim", step.dest)] = 1
                self.log(f"Heads-up: MME says up to {a['count']}× {a['mob']} at {step.dest[0]}/{step.dest[1]} could hit "
                         f"hard (~{a['dmg']} damage). It'll know for sure after a few fights there.")
            return False
        lap = getattr(self, "laps", 0)
        key = (step.dest, lap)
        said = self.s.danger._said
        if need > 100:
            if said.get(step.dest) != lap:
                said[step.dest] = lap
                msg = (f"Danger: up to {a['count']}× {a['mob']} at {step.dest[0]}/{step.dest[1]} could do ~{a['dmg']} "
                       f"damage — more than your HP")
                self.log(msg)
                if cfg.danger_stop:
                    self.s.notify.send("stop", msg)
                    self.stop(f"Stopped: {msg}")
                    return True
            need = 100
        if st.hp_pct() < need - 0.5 and cfg.auto_rest:
            if not getattr(self, "_danger_hp", 0):
                self._danger_since = time.time()
            if time.time() - getattr(self, "_danger_since", time.time()) > 600 and not st.resting:
                return False                    # couldn't rest up (something keeps interrupting) — carry on
            self._danger_hp = need
            if said.get(("rest",) + key[:1]) != lap:
                said[("rest",) + key[:1]] = lap
                self.log(f"Danger ahead: up to {a['count']}× {a['mob']} ({a['dpr']}/round each, ~{a['dmg']} damage) — "
                         f"resting to {need:.0f}% HP first")
            return True
        return False

    # ---------------------------------------------------------- lair refill pacing
    def _lair_learn(self, now):
        """Feed the lair clock: what each lair looked like when we walked in, and when we left it empty."""
        st, lc = self.st, self.s.lairclock
        room = st.room
        if not room or not st.view or st.pending:
            return
        dg = getattr(self, "_dg", None)
        if dg and dg["room"] != room:
            if dg["fought"]:
                self.s.danger.observe(dg["room"], dg["hp0"] - dg["min"])
            self._dg = dg = None
        elif dg:
            dg["min"] = min(dg["min"], st.hp)
            dg["fought"] = dg["fought"] or st.in_combat
        r = self.s.world.room(room)
        if not r or not r.lair:
            self._lc_room = room
            return
        if getattr(self, "_lc_room", None) != room:
            self._lc_room = room
            self._dg = {"room": room, "hp0": st.hp, "min": st.hp, "fought": st.in_combat}
            stocked = any(rec for _sh, rec in st.view.monsters)
            lc.arrive(room, stocked, now)
            if not stocked and self.walking and self.loop:
                self.s.scripters.lair_empty(room, now)   # someone else just cleared it? (scripters.py)
            self._lc_empty_t = now
        elif not st.view.monsters and not st.in_combat and now - getattr(self, "_lc_empty_t", 0) > 2:
            self._lc_empty_t = now
            lc.seen_empty(room, now)
        lc.save()

    LAIR_PACING = False                       # the whole feature, whatever the profile's lair_pace says

    def _lair_pace(self, step, mobs) -> bool:
        """Next room is a lair that won't have refilled yet, and we're not full: rest/meditate here
        for those seconds instead of walking in on an empty room and resting later anyway.
        Switched off for now (Dan, 2026-11-01: "it still has issues waiting for lairs — disable that feature entirely
        and circle back to it down the road"): LAIR_PACING."""
        if not self.LAIR_PACING:
            self._pace_until = 0
            return False
        cfg, st = self.cfg, self.st
        now = time.time()
        pu = getattr(self, "_pace_until", 0)
        if pu:
            if now < pu and (st.resting or now - getattr(self, "_pace_set", now) < 8):
                self.status = f"Lair ahead refills in {pu - now:.0f} s — resting meanwhile"
                if not st.resting:
                    self.idle_regen(mobs, why=f"pacing: lair ahead refills in {pu - now:.0f} s")
                return True
            self._pace_until = 0
            return False
        if not cfg.lair_pace or not self.loop or not step.dest or mobs or st.in_combat:
            return False
        if self.s.scripters.catching_up():
            return False                              # someone just ahead clearing our lairs: catch up, don't wait
        dest = self.s.world.room(step.dest)
        if not dest or not dest.lair or not st.max_hp:
            return False
        if st.hp_pct() >= 100 and (not st.max_ma or st.ma_pct() >= 100):
            return False                              # full anyway: nothing to gain by stopping
        # (not "only below the rest line" — 0.8.128 tried that for Revolution, Dan 2026-10-31: walking on reaches the
        #  lair before it's back and its spawn is lost for the lap; the wait is spent anyway, so meditate through it)
        if [n for n in st.party if n.lower() != (cfg.my_name or "").lower()] and self.x.leading() is False:
            return False                              # following: not our call
        rem = self.s.lairclock.remaining(step.dest, now)
        if rem is None or rem < 4 or rem > int(cfg.lair_pace_max or 45):
            return False
        refill = self.s.lairclock.estimate(step.dest) or 0
        period = float(getattr(getattr(self.s, "clock", None), "period", 5.0) or 5.0)
        lap = len(getattr(self.path, "steps", None) or []) * period       # ~a round a room, before any fighting
        try:
            # better: how long your laps really take, fights and all (Evolution, 2026-11-01: 10 rooms ≈ 50 s by the
            # count, but 0.8–1.5 min a lap really — and it paced at every sentry lair, 332k/hr down to 163k/hr)
            lap = max(lap, self.s.loopstats.lap_secs(self.path) or 0)
        except Exception:
            pass
        if refill and lap >= refill:
            # we're back round before it refills anyway: it'll be full next lap, so waiting only slows the lap
            # (Dan, 2026-10-31, the dark-elf sentries: "30 second regen, 10 or so rooms at 5 seconds a piece —
            # they're full by the time you hit the next lap")
            return False
        self._pace_until, self._pace_set = now + rem, now
        self.log(f"Lair {step.dest[0]}/{step.dest[1]} ahead refills in ~{rem:.0f} s — resting here meanwhile")
        self.idle_regen(mobs, why=f"pacing: lair ahead refills in {rem:.0f} s")
        return True

    def _lair_wait(self, here) -> bool:
        """Optional: on a loop, an empty lair room makes us wait a few seconds for it to fill."""
        cfg, st = self.cfg, self.st
        secs = int(cfg.lair_wait_secs or 0)
        if not secs or not self.loop or not here or (st.view and st.view.monsters):
            self._lair_wait_at = None
            return False
        r = self.s.world.room(here)
        if not r or not r.lair:
            return False
        if getattr(self, "_lair_wait_at", None) is None or self._lair_wait_room != here:
            self._lair_wait_at, self._lair_wait_room = time.time(), here
        left = secs - (time.time() - self._lair_wait_at)
        if left > 0:
            self.status = f"Waiting {left:.0f}s for the lair to fill"
            if self.ready("lair_look", 4):
                self.send("")
            return True
        return False

    def _boss_ahead(self, step) -> bool:
        """Stop before walking into a boss's room (Settings → Other → Bosses), like MegaMUD."""
        cfg = self.cfg
        dest = step.dest
        if not cfg.stop_before_boss or not dest or getattr(self, "_boss_ok", None) == dest:
            return False
        if dest == getattr(self, "_goto_target", None) and self.path and self.path.title.startswith("Go to "):
            return False                      # you asked to go there
        bosses = self.s.world.bosses_by_room().get(dest) or []
        skip = {n.strip().lower() for n in (cfg.boss_no_stop or [])}
        bosses = [b for b in bosses if b["name"].lower() not in skip and not self._is_hunted(b)
                  and b.get("exp", 0) > 0 and self.hostile(b)     # not the boatman or a shopkeeper
                  and not self._boss_dead(b)]
        if not bosses:
            return False
        pct = int(getattr(cfg, "boss_stop_pct", 40) or 0)
        st = self.st
        if pct and st.max_hp:
            from .danger import fight_estimate
            try:
                est = fight_estimate(self.s.danger, bosses)
            except Exception:
                est = None
            if est is not None and est < st.max_hp * pct / 100:
                if getattr(self, "_boss_easy_said", None) != dest:
                    self._boss_easy_said = dest
                    self.log(f"{', '.join(sorted({b['name'] for b in bosses}))} ahead — about {est:.0f} damage "
                             f"expected, under {pct}% of your HP: walking straight in")
                return False                  # a minor boss for you (the rakshasha sage at 47): no stopping
        r = self.s.world.room(dest)
        names = ", ".join(sorted({b["name"] for b in bosses}))
        self.status = f"Stopped before {names} — Alt+R to go in"
        if getattr(self, "_boss_hold", None) != dest:
            self._boss_hold = dest
            for b_ in bosses:
                try:
                    if not self.s.bosses.rec(b_).get("manual"):
                        self.s.bosses.track(b_)  # on the Bosses tab now, with its Stop box to untick
                except Exception:
                    pass
            self.log(f"Stopped before {names}'s room ({dest[0]}/{dest[1]} {r.name if r else ''}). "
                     f"Alt+R (Options → Resume) walks in; untick its Stop box on the Bosses tab to never stop for it.")
            self.s.on_alert(f"Stopped before {names}")
            self.s.notify.send("stop", f"Stopped before {names} — Alt+R to go in")
        return True

    def _boss_dead(self, b) -> bool:
        """Dead by its own clock (the Bosses tab: killed, not due back yet). 0.8.189, realm walk sweep: a wandering
        boss has a row of rooms (the Bloody Executioner, 17/590–594) — killed in the first, the walk still stopped
        before each of the others ('Alt+R to go in'), and an unattended walk just stood there."""
        try:
            _txt, left = self.s.bosses.status(b["num"])
        except Exception:
            return False
        return left is not None and left > 0

    def resume_boss(self):
        """Walk into the boss room we stopped before."""
        if getattr(self, "_boss_hold", None):
            self._boss_ok, self._boss_hold = self._boss_hold, None
            self.log("Going in")
            return True
        return False

    def _send_exit(self, ex):
        if self._swap:
            self.end_swap("moving on")
        self._detour_from = self.st.room
        self._detour_expect = ex.to
        self._detour_fail_seen = self.st.move_failed
        if ex.kind == "hidden" and "search" in ex.etype.lower() and \
                self._search_gate([f"search {DIR_WORDS.get(ex.dir, ex.dir).lower()}"], ex.dir, self.st.room):
            return
        if ex.kind == "hidden" and "search" in ex.etype.lower():
            pass                                     # searched (and found) by _search_gate
        elif ex.kind in ("hidden", "door") and ex.action_cmds() and self.s.world.action_at(ex) in (None, self.st.room):
            for c in ex.action_cmds():           # 'pull lever' etc. opens it
                self.send(c)
        cmd = ex.text_command if ex.kind == "text" and ex.text_command else ex.dir.lower()
        if self.st.room and self._resend_guard(self.st.room, cmd):
            return
        self.status = f"Detour → {ex.to[0]}/{ex.to[1]}"
        self._expect_move()
        self.send(cmd)
        self._step_sent_at = time.time()
        self._last_progress = time.time()
