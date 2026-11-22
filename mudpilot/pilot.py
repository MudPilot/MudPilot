"""Go to, pMUD's way: every step starts from where we really are.

The old walker follows a step counter (path.steps[idx]) and repairs it when it disagrees with the game
(resync / anchor / _confirm_arrival). In look-alike areas (the Great Pyramid: hundreds of 'Great Pyramid'
rooms with one or two exits) the counter and the real position drift apart and it loops.

The pilot drops the counter as the source of truth. Each time walk() is about to take a step:
  1. where am I — the room tracker's answer, or the board's room-number command ('pro') when the room is a
     look-alike we didn't reach by a plain, predicted step. A 'pro' answer always wins over a path guess.
  2. plan from HERE to the target (worlddb.route via Automation.plan_route — avoid list, keys, level, failed
     exits). The plan is cached in path.steps and kept while we're where it expects; anywhere else is simply
     the new 'here' and gets a fresh plan.
  3. hand walk() the one next step (path.steps[idx] starts in the room we're in), so everything walk() does
     around a step — doors, searches, traps, light, ward gear, swaps, sneak, portals / @party / regroup,
     tolls, boats, resend guard, 'no such exit' — is reused unchanged.
  4. walk() waits for the room display; next tick, repeat.

Remote actions (the 'push block' in 12/1808 that opens 12/1811's north wall) are planned like
megamud_files.path_from_route does — walk to the action room, do it, come back, go through — but the pilot
remembers which ones it has done this trip, so a re-plan halfway doesn't start the detour over (or skip it).

Only Go to paths ('Go to …' with a target) use the pilot, and only with Settings → Other → 'New Go to walker'
on; loops and imported MegaMUD paths keep the old walker.
"""
from __future__ import annotations

import time

from .megamud_files import STEPF, Step, path_from_route

DONE_SECS = 180.0      # a remote action (push block) counts as done for this long
ASK_SECS = 5.0         # how long a 'pro' gets to answer before we go by the room tracker
REDO_MAX = 8           # times we go back to redo a remote action whose wall didn't open (Dan, 2026-11-20: timed gates often need it again — no human)
# gates that shut on a timer: from the first action on, run — no fighting, no resting (Dan, 2026-10-30: the mummy's
# gate). Others get walked round fighting as usual: Ozrinom's tomb doors stayed open while the party fought its way
# between the hand and the sword (2026-11-06) — 28 rooms of vampire halls without fighting back would be worse.
TIMED_GATES = {((1, 1056), "N"),
               ((15, 477), "N")}   # the Darkened Tunnels: levers 15/604 + 15/730, ~225 rooms to run (Dan, 2026-11-20)


class Pilot:
    def __init__(self, auto):
        self.a = auto
        self.active = False
        self.mp = None
        self.target = None
        self.done: dict = {}       # (exit room, dir) -> when its remote action went out
        self.redo: dict = {}       # (exit room, dir) -> times we went back to do it again
        self.prog: dict = {}       # (exit room, dir) -> (how many of its actions are done, when)
        self._rush: list = []      # lever-gate runs in the plan being built (Automation._rushing)
        self._reset()

    def _reset(self):
        self.need_plan = True      # plan from here before the first step
        self.last = None           # the move that went out last: {frm, dest, plain, step, t}
        self.given = None          # the plan index walk() was handed
        self.trusted = None        # the room we're sure we're in
        self.asked = None          # a 'pro' waiting for its answer: {t, ok}
        self.pending = None        # a remote action we're on our way to: {key, at, cmds}
        self._noask_seq = None     # 'pro' didn't answer for this room display: don't ask again for it
        self._fallback_at = 0.0

    # ------------------------------------------------------------ helpers
    @property
    def st(self):
        return self.a.st

    @property
    def w(self):
        return self.a.s.world

    def wants(self, mp) -> bool:
        tgt = getattr(self.a, "_goto_target", None)
        return bool(getattr(self.a.cfg, "pilot_goto", True) and mp is not None and mp.title.startswith("Go to ")
                    and isinstance(tgt, tuple) and tgt in self.w.rooms)

    def start(self, mp):
        """start_path() just took on a path: pilot it if it's a Go to."""
        if not self.wants(mp):
            self.active, self.mp = False, None
            return
        tgt = tuple(self.a._goto_target)
        if mp.steps and mp.steps[-1].dest and mp.steps[-1].dest != tgt:
            self.active, self.mp = False, None        # _goto_target is left over from another trip
            return
        self.redo, self.prog = {}, {}
        self.active, self.mp, self.target = True, mp, tgt
        self._reset()
        st = self.st
        lc = getattr(st, "located", None)
        if st.room and lc and lc[0] == st.room and time.time() - lc[1] < 120:
            self.trusted = st.room                    # the board told us where we are a moment ago

    def on(self) -> bool:
        a = self.a
        return bool(self.active and a.walking and a.path is not None and a.path is self.mp
                    and getattr(a.cfg, "pilot_goto", True))

    def _can_ask(self) -> bool:
        a, st = self.a, self.st
        return bool((a.cfg.locate_cmd or "").strip()) and a._locate_failed < 3 and not st.in_combat \
            and not (a.in_deadly() and st.room)      # no stopping to ask where you drown — unless truly lost

    def _check_before_text(self, step, here, now) -> bool:
        """About to type a room's own command ('go hole') in a room that looks like others: make sure with the
        board first. Revolution, 2026-10-30: five Dragon's Teeth Hills rooms look exactly like 2/487 (the hole
        down to the Stone Tunnel); drifted on plain steps, it typed 'go hole' in 2/193 — 'Your command had no
        effect.' — again and again. True = asked (this tick is taken)."""
        if step.dir or not step.move or not self.w.look_alike(here):
            return False
        lc = getattr(self.st, "located", None)
        moved = self.last["t"] if self.last else 0
        if lc and lc[0] == here and lc[1] >= moved:
            return False                              # the board told us this room since the last move
        if not self._can_ask() or self._noask_seq == self.st.view_seq:
            return False                              # no 'pro' on this board: go by the tracker
        self._ask(f"about to '{step.move}' in {here[0]}/{here[1]}, which looks like other rooms")
        return True

    def _ask(self, why):
        a = self.a
        if a.locate_now(why):
            self.asked = {"t": time.time(), "ok": self.st.locate_ok}
            a.log(f"Go to: {why} — asking the board ({a.cfg.locate_cmd.strip()})")
            a.why("pilot_ask", why=why, room=self.st.room)
        else:
            a.status = "Checking location"           # asked a moment ago: that answer first

    def _route(self, frm, to):
        a, w = self.a, self.w
        r = a.plan_route(frm, to)
        if r is None and (a.cfg.auto_get_items or a.cfg.bash_key_doors):
            # the same 'as if you had every key' plan goto() falls back on (the door gets picked / bashed)
            r = a.keyed_route(frm, to)                # (keeps out of avoided areas — they get asked about)
        if r and any(w.stuck_door(ex) for ex in r):
            # (a '1000' door back in the plan when goto() had found a way round it — the Dark-Elf Castle's moat: the
            #  first re-plan put 8/559 S back and it sent 'open' for 2 minutes, m58 bug 0)
            try:
                alt = a._round_stuck(frm, to, r, None)
            except Exception:
                alt = None
            if alt:
                r = alt
        return r

    # ------------------------------------------------------------ planning
    def _one(self, cur, ex, at):
        """One exit as a path step (megamud_files.path_from_route's rules)."""
        w = self.w
        pre, move, flags = [], ex.dir, 0
        if ex.kind == "hidden" and "search" in ex.etype.lower():
            pre = [f"search {ex.dir.lower()}"]
        elif ex.kind in ("hidden", "door") and ex.action_cmds() and not (at and at != cur):
            pre = ex.action_cmds()                    # 'pull lever' / 'ask sphinx fire' in this room
        elif ex.kind == "text" and ex.text_command:
            move = ex.text_command
        elif ex.kind == "trap":
            flags |= STEPF["DISARM"]
        if getattr(w, "segments", None):
            from .board_fixes import pre_for
            pre = pre_for(w, cur, ex) + list(pre)
        st_ = Step(w.room(cur).mega_hash, flags, move, pre, cur, ex.to)
        if getattr(ex, "scatter", None):
            st_._scatter = ex.scatter                 # a random drop: landing anywhere in its range is expected
        return st_

    @staticmethod
    def _stops(gate, ex):
        """Each action the exit needs, in order, with the room it's done in: [(room, command)]."""
        return [(tuple(a["at"]) if a.get("at") else gate, (a.get("cmds") or ["pull lever"])[0])
                for a in ex.steps_needed()]

    def _tour(self, pos, det, start=0, depth=0):
        """From pos round the exit's actions still to do, each in its own room and in order, then back to the
        gate: (steps, [(i, command)] still to do in the gate room itself, index of the first action step) or None.
        Each command goes out on the first step out of its room. 17/2068's way down needs the hand twisted in
        17/2094 and THEN the sword in 17/2076 — the old detour went to the first room only and typed both there
        (Ozrinom, 2026-11-06).
        A leg that itself goes through a wall opened from somewhere else gets its own tour (0.8.189, realm walk
        sweep: the Treetops' 16/551 north wall is opened by 'tear bark' in 16/569, and 16/569 is behind a wall
        'push knot' in 16/567 opens, itself behind 'pull vine' in 16/556 — the tour gave up, so the walk typed 'n'
        into the wall and stopped)."""
        w, gate, stops = self.w, det["key"][0], det["stops"]
        gr = w.room(gate)
        gx = gr.exits.get(det["key"][1]) if gr else None
        behind = gx.to if gx is not None else None
        out, pend, first = [], [], None
        for i in range(start, len(stops) + 1):
            room = gate if i == len(stops) else stops[i][0]
            if room != pos:
                # (never through the gate itself to reach its levers — 0.8.214: 15/477 N's lever at 15/604 is
                #  nearest through 15/478, so the tour failed and Buddy stopped at 15/335: "no way there from here")
                leg = w.route(pos, room, max_nodes=20000, avoid={behind} if behind and room != behind else None)
                if leg is None:
                    leg = self._leg_past_failed(pos, room)
                if leg is None:
                    return None
                if any(w.action_at(x) for x in leg):
                    if depth >= 4 or self._crosses(pos, leg, det["key"]):
                        return None
                    sub = self._steps(pos, leg, depth=depth + 1)
                else:
                    sub = path_from_route(w, pos, leg).steps
                if not sub:
                    return None
                if pend:
                    sub[0].pre = [c for _, c in pend] + list(sub[0].pre or [])
                    sub[0]._pilot_action = (det["key"], pend[-1][0] + 1)
                    if first is None:
                        first = len(out)
                    pend = []
                for s in sub:
                    if getattr(s, "_pilot_detour", None) is None:
                        s._pilot_detour = det     # (a nested tour's steps keep their own)
                out += sub
                pos = room
            if i < len(stops):
                pend.append((i, stops[i][1]))
        return out, pend, first

    def _gate(self, cur, ex, det, tour, base):
        """The tour's steps plus the step through the gate; for a timed gate, notes the run (no fighting from the
        first action on — megamud_files.path_from_route's lever gates) in self._rush."""
        out, pend, first = tour
        s = Step(self.w.room(cur).mega_hash, 0, ex.dir, [c for _, c in pend], cur, ex.to)
        s._pilot_exit = det["key"]
        if pend:
            s._pilot_action = (det["key"], len(det["stops"]))
            if first is None:
                first = len(out)
        out = out + [s]
        if first is not None and det["key"] in TIMED_GATES and getattr(self.w, "paradigm", True):   # (pMUD's; 0.8.201)
            for x in out[first:]:
                x.flags |= STEPF["NOATTACK"]
            self._rush.append({"begin": base, "first": base + first, "gate": base + len(out) - 1,
                               "room": cur, "dir": ex.dir})
        return out

    def _leg_past_failed(self, a_, b_):
        """A tour leg through exits that failed us a while ago (a door whose bashes kept missing): those are 'another
        way first', and the lever this leg goes to is only up there. 0.8.192 (Spectral Knight sweep: twenty missed
        bashes at the 6/885 iron door 'went round' it — but the lever opening the alcove is behind it, so the walk then
        typed 'd' into 6/861's wall). Walls stay walls."""
        w = self.w
        fe = getattr(w, "failed_edges", None)
        if not fe:
            return None
        # (M14B-3: the Temple Control Room's lever behind '[80]' doors a strength-75 mage can't open — each re-plan's
        #  tour un-failed the door and went back to it, 3,958 rooms in 15 min. At most REDO_MAX times per leg in 30
        #  minutes, and never through a door nobody in the party can open)
        import time as _t
        cnt = w.__dict__.setdefault("_leg_past_failed_n", {})
        now = _t.time()
        n, t0 = cnt.get((a_, b_), (0, now))
        if now - t0 > 1800:
            n, t0 = 0, now
        if n >= REDO_MAX:
            return None
        cnt[(a_, b_)] = (n + 1, t0)
        saved = dict(fe)
        fe.clear()
        w.forget_routes()
        try:
            leg = w.route(a_, b_, max_nodes=20000)
        finally:
            fe.update(saved)
            w.forget_routes()
        if leg and any(ex.kind == "door" and w.door_hopeless(ex) for ex in leg):
            return None
        return leg

    @staticmethod
    def _crosses(cur, route, key) -> bool:
        """Does this route go through exit `key` (room, dir)?"""
        for ex in route:
            if (cur, ex.dir) == key:
                return True
            cur = ex.to
        return False

    def _steps(self, cur, route, assume=(), base=0, depth=0):
        w = self.w
        out = []
        for ex in route:
            at = w.action_at(ex)
            key = (cur, ex.dir)
            if at and at != cur and at in w.rooms:
                if key in self.done or key in assume:
                    s = Step(w.room(cur).mega_hash, 0, ex.dir, [], cur, ex.to)
                    s._pilot_exit = key               # opened already this trip: straight through
                    out.append(s)
                    cur = ex.to
                    continue
                # walk round the rooms it's opened from, do each there, come back, go through
                det = {"key": key, "stops": self._stops(cur, ex)}
                tour = self._tour(cur, det, depth=depth)
                if tour is not None:
                    out += self._gate(cur, ex, det, tour, base + len(out))
                    cur = ex.to
                    continue
                if depth:
                    return None                       # (a nested tour that can't be walked: the outer one can't either)
                # 0.8.192: no way round to where it's opened from — walking on would type the move into a wall
                # (Revolution's 'didn't even try the commands' at the Spectral Knight's stairwell, 6/861 down)
                self._untourable = (cur, ex.dir, det["stops"][0][0] if det["stops"] else at)
                return None
            out.append(self._one(cur, ex, at))
            cur = ex.to
        return out

    def _build(self, here):
        """Steps from here to the target, or None (no way)."""
        now = time.time()
        self.done = {k: t for k, t in self.done.items() if now - t < DONE_SECS}
        self.prog = {k: v for k, v in self.prog.items() if now - v[1] < DONE_SECS and k not in self.done}
        self._rush = []
        self._untourable = None
        steps, cur, pend, assume, gate_pre = [], here, self.pending, set(), []
        if pend and pend["key"] in self.done:
            pend = self.pending = None
        if pend:
            # partway round a remote action's rooms when we got knocked about: carry on from the next one
            tour = self._tour(cur, pend, self.prog.get(pend["key"], (0, 0))[0])
            if tour is None:
                pend = self.pending = None
            else:
                steps, gate_pre, _ = tour
                cur, assume = pend["key"][0], {pend["key"]}
        route = self._route(cur, self.target)
        if not pend and getattr(self.a.cfg, "route_tokens", False):
            # 0.8.201 (Dan): a teleport token you carry, when it saves a lot of walking (tokens.py)
            from .tokens import router
            tr = router(self.a)
            tok = tr.shortcut(cur, self.target, route)
            if tok is not None:
                num, info, on = tok
                after = self._steps(tuple(info["to"]), on, (), 1)
                if after is not None:
                    return [tr.step(cur, num, info)] + after
        if route is None:
            return None
        rest = self._steps(cur, route, assume, len(steps))
        if rest is None:
            return None                               # (an exit on the way whose levers can't be reached)
        if pend and gate_pre and rest:
            first = rest[0]
            first.pre = [c for _, c in gate_pre] + list(first.pre or [])
            first._pilot_action = (pend["key"], len(pend["stops"]))
        return steps + rest

    def redo_remote(self, room, d) -> bool:
        """A door opened from another room (the Grand Stair's south-east door, 7/150, by the lever in 7/152) is shut
        when we get to it — it closed again, or the lever was pulled a few minutes ago on another walk: go back round
        and do it again, at most REDO_MAX times. 0.8.189, realm walk sweep: the door handler typed 'pull lever' in
        7/150, where there's no lever, tried 'open' and gave up ("the door southeast is locked"). True = re-planning."""
        key = (tuple(room), d)
        if not self.on() or self.redo.get(key, 0) >= REDO_MAX:
            return False
        self.done.pop(key, None)
        self.prog.pop(key, None)
        self.redo[key] = self.redo.get(key, 0) + 1
        self.a.log(f"Go to: the door {d} in {room[0]}/{room[1]} is shut — going round to open it again")
        self.need_plan = True
        self.given = None
        return True

    # ------------------------------------------------------------ each tick
    def _absorb(self):
        """What went out since we last handed walk() a step."""
        a = self.a
        if a.detour:
            # one of walk()'s helpers (the 'no such exit' check) sent a map exit of its own
            ex = a.detour[0]
            self.last = {"frm": a._detour_from, "dest": ex.to, "plain": self._predictable(ex),
                         "step": None, "t": a._step_sent_at}
            a.detour, self.given = None, None
            return
        g = self.given
        if g is None or a.idx != g + 1 or g >= len(self.mp.steps):
            return
        s = self.mp.steps[g]
        self.given = None
        r = self.w.room(s.room) if s.room else None
        ex = next((e for e in (r.exits.values() if r else []) if e.to == s.dest
                   and (e.dir == s.move or e.accepts(str(s.move)))), None)
        self.last = {"frm": s.room, "dest": s.dest, "step": s, "t": a._step_sent_at,
                     "plain": bool(s.dir) if ex is None else self._predictable(ex)}
        det = getattr(s, "_pilot_detour", None)
        if det and det["key"] not in self.done:
            self.pending = det
        act = getattr(s, "_pilot_action", None)
        if act:
            key, n = act
            total = len(det["stops"]) if det else n
            if n >= total:
                self.done[key] = time.time()
                self.prog.pop(key, None)
                if self.pending and self.pending["key"] == key:
                    self.pending = None
            else:
                self.prog[key] = (n, time.time())     # this many of its actions done, in order

    @staticmethod
    def _predictable(ex) -> bool:
        """A move the room tracker can follow: a direction, or a text exit that always goes to the same room
        ('go path'). A teleport (a vortex) or a boat can put you anywhere that looks the same."""
        req = getattr(ex, "req", None) or {}
        return "(teleport)" not in (ex.etype or "").lower() and not req.get("voyage") and not getattr(ex, "scatter", None)
        # (a random drop — the Padded Cells — lands in any of its look-alikes: not trusted without 'pro', m149 N2)

    def _where(self, now):
        """The room we're in for sure, or None (asked the board / lost — this tick is taken)."""
        a, st, w = self.a, self.st, self.w
        here = st.room
        lc = getattr(st, "located", None)
        moved = self.last["t"] if self.last else 0
        if here and lc and lc[0] == here and lc[1] >= moved:
            self.trusted, self.asked = here, None    # the board said so: nothing guesses over that
            return here
        if self.asked:
            if st.locate_ok > self.asked["ok"]:
                self.asked = None
            elif now - self.asked["t"] < ASK_SECS:
                a.status = "Checking location"
                return None
            else:
                self.asked = None
                self._noask_seq = st.view_seq
                a._locate_failed += 1
                a.log(f"'{a.cfg.locate_cmd.strip()}' didn't give a room number — going by the room tracker")
        ask_ok = self._can_ask() and self._noask_seq != st.view_seq
        last = self.last
        if here is None:
            cands = list(st.candidates or [])
            if cands and ask_ok:
                self._ask(f"not sure which of {len(cands)} rooms this is")
                return None
            exp = last["dest"] if last else None
            if exp and exp in cands:
                # no room number to be had: the room the move should have reached, if the tracker allows it
                st.candidates = [exp]
                a.log(f"Placed by the path at {exp[0]}/{exp[1]} (the tracker had {len(cands)} look-alikes)")
                self.trusted = exp
                return exp
            if a.ready("lost", 3):
                a.status = "Lost — looking around"
                a.send("")
            if now - a._last_progress > 60:
                a.stop("Stopped: couldn't tell where we are for 60s")
            return None
        if here == self.trusted:
            return here
        plain = bool(last and last["plain"] and here == last["dest"] and last["frm"] == self.trusted)
        if plain or not ask_ok or not w.look_alike(here):
            self.trusted = here
            return here
        # a look-alike room we didn't reach by a plain predicted step (a text exit, a teleport, somewhere the
        # move shouldn't have taken us, or the start): the board's room number before we act on it
        self._ask(f"{here[0]}/{here[1]} looks like other rooms")
        return None

    def prepare(self, now=None) -> bool:
        """Called by walk() before it picks a step. True = this tick is taken (waiting for 'pro', lost,
        re-routed through goto()). False = path.steps[idx] starts in the room we're in: take it."""
        a, st = self.a, self.st
        now = now or time.time()
        self._absorb()
        if st.locate_until > now:
            a.status = "Checking location"
            return True                               # a 'pro' answer is on its way
        here = self._where(now)
        if here is None:
            return True
        steps, i = self.mp.steps, a.idx
        if here == self.target:
            if not (i >= len(steps) and (not steps or steps[-1].dest == here)):
                steps[:] = []                         # got here early (or by a way round): that's arriving
                a.idx = 0
            self.given = None
            return False                              # walk() finishes the Go to
        if not self.need_plan and i < len(steps) and steps[i].room == here:
            if getattr(steps[i], "_token", None) is not None:
                # a teleport token works from any room — no need to be sure which look-alike this is first
                from .tokens import router
                hold = router(a).hold(steps[i], here)  # (room clear, out of combat, not the round of a spell)
                if hold == "wait":
                    return True
                if hold == "walk":
                    return self._replan(here, False)
                return self._go(i)
            if self._check_before_text(steps[i], here, now):
                return True
            return self._go(i)                        # where the plan expects us
        last = self.last
        if not self.need_plan and last and last["step"] is not None and here == last["frm"] \
                and 0 < i <= len(steps) and steps[i - 1] is last["step"]:
            # the move didn't happen (a shut door, 'no exit', the game ate it): that step again
            if getattr(last["step"], "_token", None) is not None:
                from .tokens import router
                if router(a).no_move(last["step"], here) == "walk":
                    return self._replan(here, False)  # out of uses / a no-token room / short of cash: walk it
                a.idx = i - 1
                self.last = None                      # (again next tick, through the round / room-clear check)
                return True
            key = getattr(last["step"], "_pilot_exit", None)
            if key and key in self.done and self.redo.get(key, 0) < REDO_MAX:
                # through a wall a remote action opens — it may have shut again: go and do it again
                self.done.pop(key, None)
                self.prog.pop(key, None)
                self.redo[key] = self.redo.get(key, 0) + 1
                a.log(f"Go to: the way {last['step'].move} from {here[0]}/{here[1]} is still shut — "
                      "doing its action again")
                return self._replan(here, False)
            a.idx = i - 1
            return self._go(i - 1)
        unexpected = bool(last) and not self.need_plan and here not in (last["dest"], last["frm"])
        sc = getattr(last["step"], "_scatter", None) if last and last.get("step") is not None else None
        if unexpected and sc and here[0] == sc[0] and sc[1] <= here[1] <= sc[2]:
            # the random drop landed somewhere else in its range (the asylum, the uninvited portal): not being
            # knocked off the path — plan on from here (Dan: 'n s n s… until we see the old man')
            a.log(f"Go to: the drop landed in {here[0]}/{here[1]} — planning on from there")
            unexpected = False
        return self._replan(here, unexpected)

    def _go(self, i) -> bool:
        self.given = i
        self.need_plan = False
        return False

    def _replan(self, here, unexpected) -> bool:
        a = self.a
        if unexpected:
            exp = self.last["dest"] if self.last else None
            a.log(f"Go to: at {here[0]}/{here[1]}" + (f", not {exp[0]}/{exp[1]}" if exp else "")
                  + " — planning from here")
            a.why("pilot_replan", here=here, expected=exp)
            if exp is not None and self.target and tuple(exp) == tuple(self.target) and tuple(here) != tuple(exp) \
                    and time.time() - getattr(a, "_flee_at", 0) > 30:
                # (not when we ran — attacked at the target and fled twice isn't the target throwing us out: fight3 #1)
                # (0.8.201, walk check: the step INTO the target landed somewhere else — 17/2978's room spell throws
                #  you to 17/2980. Each bounce was an 18-room lap back, 5 laps before the drift guard paused. The
                #  same throw twice in 10 minutes: stop and say why)
                now_ = time.time()
                bn = {k: v for k, v in (getattr(self, "_bounces", None) or {}).items() if now_ - v[1] < 600}
                key_ = (tuple(self.target), tuple(here))
                n_ = bn.get(key_, (0, now_))[0] + 1
                bn[key_] = (n_, now_)
                self._bounces = bn
                if n_ >= 2:
                    w_ = a.s.world
                    sp_ = (getattr(w_, "room_spells", None) or {}).get(tuple(self.target))
                    spn = ((w_.spells.get(sp_) or {}).get("Name") if sp_ else None)
                    if spn:
                        a.stop(f"Stopped: {self.target[0]}/{self.target[1]} sends you back out to {here[0]}/{here[1]}"
                               f" (its room spell '{spn}') — tried twice, not looping round again")
                    else:
                        # (no room spell: the step into it took you somewhere else — 'go alley' at 2/2519 is a command
                        #  two exits share, and the game picks the other one: flags2 #7)
                        a.stop(f"Stopped: the step into {self.target[0]}/{self.target[1]} took you to {here[0]}/{here[1]}"
                               " instead — tried twice, not looping round again")
                    return True
            if a._drifted("detour"):
                self.need_plan = True
                return True
        plan = self._build(here)
        if plan is None and a.parked():
            return True                               # goto() is waiting on 'i' / 'abil' / 'who': it carries on then
        if plan is None and getattr(self, "_untourable", None):
            room, d, at = self._untourable
            a.stop(f"Stopped: the {d} exit of {room[0]}/{room[1]} is opened from {at[0]}/{at[1]}, and there's no way "
                   f"there from here")
            return True
        if plan is None:
            if time.time() - self._fallback_at > 5:
                # goto() knows more ways to find one (forget failed exits, read the keys, ask 'abil')
                self._fallback_at = time.time()
                a.log(f"Go to: no way on from {here[0]}/{here[1]} — planning the trip again")
                fb = self._fallback_at
                if a.goto(self.target, then=a.after_goto):
                    self._fallback_at = fb
                    return True
            a.stop(f"Stopped: no route from {here[0]}/{here[1]} to {self.target[0]}/{self.target[1]}")
            return True
        self.mp.steps[:] = plan
        self.mp.rush = self._rush                     # (the old plan's step numbers would point anywhere)
        a.idx = 0
        a.detour = None
        return self._go(0)
