"""Control folder (data\\control): lets the desktop restart and update MudPilot on the mini PC with nobody there.

Only these names mean anything; what's inside a request file is never run or obeyed:
  restart.request  stop at a safe moment, note the loop and party, close for the launcher (mudpilot.launcher),
                   which installs a newer MudPilot-*.zip from Downloads, waits on 'hold', and opens MudPilot again
  hold             the launcher doesn't reopen MudPilot while this exists (settings being edited)
  resume.json      written here on the way out; the next start logs back in and carries on with that loop
  status.json      written every 30 s: version, connected, what the bot is doing (for whoever's watching)
  launcher.log     the launcher's own notes
  update-soon      (0.8.201) a restart for an update is about to come: tell the party first, so a player at the
                   keys (Revolution's) knows it's coming. The message is fixed here; the file's contents are ignored
A restart request only works when MudPilot was opened by the launcher — otherwise nothing would reopen it.
"""
from __future__ import annotations

import json
import os
import time

from . import __version__
from . import config

CONTROL_DIR = os.path.join(config.DATA_DIR, "control")
RESTART_EXIT = 3                    # exit code that tells the launcher "reopen me"
SAFE_WAIT_MAX = 120                 # never wait longer than this for a fight to end
RESUME_MAX_AGE = 30 * 60
STATUS_SECS = 10                    # status.json this often (0.8.201: was 30; the All characters window reads it)


def path(name: str) -> str:
    return os.path.join(CONTROL_DIR, name)


def by_launcher() -> bool:
    return os.environ.get("MUDPILOT_LAUNCHER") == "1"


class ControlBox:
    def __init__(self, session, folder: str = CONTROL_DIR):
        self.s = session
        self.dir = folder
        self.started = time.time()
        self.on_restart = None              # the app: save everything and close with RESTART_EXIT
        self.resuming = None                # what resume.json asked for at start-up
        self._next_check = 0.0
        self._next_status = 0.0
        self._asked_at = 0.0
        self._refused = 0.0
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:
            pass

    def _p(self, name):
        return os.path.join(self.dir, name)

    # ------------------------------------------------------------ start-up
    def load_resume(self):
        """resume.json from the last restart: log back in and carry on with the loop, re-invite the party."""
        f = self._p("resume.json")
        try:
            with open(f, encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            return None
        try:
            os.remove(f)
        except OSError:
            pass
        if not isinstance(r, dict) or time.time() - float(r.get("t") or 0) > RESUME_MAX_AGE:
            return None
        s = self.s
        want = os.path.basename(str(r.get("path_file") or "")).lower()
        mp = next((p for p in s.paths if want and os.path.basename(p.filename or "").lower() == want), None)
        party = [str(n) for n in r.get("party") or [] if str(n).isalnum()][:6]
        fl = str(r.get("follow") or "")
        if fl.isalpha():
            # a follower doesn't gather a party of its own (Buddy, 2026-10-30, invited Revolution — then
            # 'join Revolution' was 'You must disband your own party first!' every time)
            party = []
            # we stopped our leader before the restart: ask for an invite, join, then @rego them
            s._rejoin = {"leader": fl, "t": time.time(), "asked": 0, "tries": 0, "joined": False}
            s.log(f"Restarted — will ask {fl} for an @invite, join, then @rego")
        if party:
            # Dan, 2026-10-28: after a restart Miserable looped off without Buddy. Hold the loop and re-invite the
            # party we had, until they're back (up to comeback_wait_mins), instead of running solo.
            now_ = time.time()
            s._regroup = {"names": party, "t": now_, "asked": 0,
                          "until": now_ + float(s.settings.comeback_wait_mins or 5) * 60}
        self.resuming = {"title": r.get("title"), "loop": bool(r.get("loop")), "connect": bool(r.get("connected"))}
        # (0.8.201, bug hunt: the hang-up comes back too — held at the menu, and no connect till the stay-offline
        #  time is up; 'hold_off' is the seconds still to wait, -1 = until you connect yourself)
        if r.get("hold_realm"):
            s.hold_realm = True
        try:
            hu = float(r.get("hung_up_until") or 0)
        except (TypeError, ValueError):
            hu = 0.0
        if hu < 0 or hu > time.time():
            s.safety.hung_up_until = float("inf") if hu < 0 else hu
            self.resuming["hold_off"] = -1 if hu < 0 else hu - time.time()
            s.log("Hung up before the restart — " + ("staying off until you connect" if hu < 0 else
                                                      f"staying off {int((hu - time.time()) / 60) + 1} more min"))
        if str(r.get("hunt") or "").isdigit():
            # 'hunt this boss, then this loop' (written by hand while held — Dan, 2026-11-03: 'finish the hunt then
            # loop' across an update): the hunt starts once we're back in and regrouped (bosshunt.tick)
            s._hunt_resume = {"num": int(r["hunt"]), "back": mp, "t": time.time()}
            mon = s.world.monsters.get(int(r["hunt"])) or {}
            s.log(f"Restarted by the control folder — will hunt {mon.get('name', 'the boss')}"
                  + (f", then {mp.title}" if mp else "") + (f"; will invite {', '.join(party)}" if party else ""))
            if party:
                s._reinvite = party
            self._hold_for_leader(s)
            return self.resuming
        goto = tuple(r["goto"]) if isinstance(r.get("goto"), list) and len(r["goto"]) == 2 else None
        if goto and r.get("walking"):
            from types import SimpleNamespace
            s._drop_resume = {"path": SimpleNamespace(title=f"Go to {goto[0]}/{goto[1]}"), "loop": False,
                              "after": mp, "target": goto}
            s._drop_started = time.time()
            s.log(f"Restarted by the control folder — logging back in to carry on to {goto[0]}/{goto[1]}"
                  + (f", then {mp.title}" if mp else "") + (f"; will invite {', '.join(party)}" if party else ""))
            if party:
                s._reinvite = party
            self._hold_for_leader(s)
            return self.resuming
        if mp and r.get("walking"):
            s._drop_resume = {"path": mp, "loop": bool(r.get("loop")), "after": None, "target": None}
            s._drop_started = time.time()   # comes back in like a dropped line: carry on, re-invite
        if party:
            s._reinvite = party
        s.log("Restarted by the control folder" + (f" — logging back in to carry on with {mp.title}" if mp and
                                                     r.get("walking") else "") +
              (f"; will invite {', '.join(party)}" if party else ""))
        if mp and not r.get("walking") and r.get("stopped"):
            # stopped when the restart came (Revolution @stop'd us for its own restart, 2026-10-29: its @rego
            # afterwards found nothing to carry on with and the party sat idle) — @rego / Rego still works
            s.bot.resume = {"path": mp, "loop": bool(r.get("loop")), "after": None}
            s.log(f"Stopped before the restart — Rego (or @rego) carries on with {mp.title}")
        if r.get("died"):
            s.bot.dead_hold = float(r["died"])     # still dead-held after the restart: nothing walks till you say
            s.log("Died before the restart — nothing walks until you start it yourself")
        sg = r.get("stopped_goto")
        if isinstance(sg, list) and len(sg) == 2:
            sg = tuple(sg)
            s.bot.resume = {"path": None, "loop": False, "after": mp, "target": sg}
            s.bot.stop_note = "before the restart"
            s.log(f"Stopped before the restart on the way to {sg[0]}/{sg[1]} — Rego (or @rego) carries on")
        if r.get("walking") and not mp:
            s.log(f"Couldn't find the path '{r.get('title')}' to carry on with — logging in only")
        self._hold_for_leader(s)
        return self.resuming

    @staticmethod
    def _hold_for_leader(s):
        """A follower doesn't walk off on its own after a restart: what it was walking waits until it's back in its
        leader's party (Dan, 2026-10-30: Miserable came back while Revolution was dead in the temple, couldn't get
        to him, and went off looping the Glades solo — 'he'll die again naked and solo'). Never back in → it stays
        put, and Rego carries on when you say."""
        rj = getattr(s, "_rejoin", None)
        dr = getattr(s, "_drop_resume", None)
        if rj and dr:
            rj["then"], s._drop_resume = dr, None
            s.log(f"Not carrying on with {dr['path'].title} until I'm back with {rj['leader']}")

    UPDATE_NOTICE = "{MudPilot update coming - this party restarts in about a minute, back in 2-3}"

    def _update_notice(self):
        """rollout.py's heads-up before it restarts a party (Dan, 2026-11-16: "if revo's at keys he knows it's gonna
        happen"). Telepaths each party member a fixed line — in braces like every bot answer, so no MudPilot treats
        it as a command — and shows it here too."""
        p = self._p("update-soon")
        if not os.path.exists(p):
            return
        self._drop(p)
        s = self.s
        me = (s.settings.my_name or "").lower()
        members = [n for n in (s.state.party or {}) if n and n.lower() != me]
        s.log("Update coming: this party restarts in about a minute" +
              (f" — told {', '.join(members)}" if members else ""))
        try:
            s.on_banner("MudPilot update coming — restarting in about a minute", "down")
        except Exception:
            pass
        if s.telnet.connected and getattr(s, "_entered", False):
            for m in members:
                s.send(f"/{m} {self.UPDATE_NOTICE}", from_bot=True)

    # ------------------------------------------------------------ per poll
    def tick(self):
        now = time.time()
        if now >= self._next_status:
            self._next_status = now + STATUS_SECS
            self.write_status()
        if now < self._next_check:
            return
        self._next_check = now + 2
        self._update_notice()
        req = self._p("restart.request")
        try:
            mt = os.path.getmtime(req)
        except OSError:
            self._asked_at = 0.0
            return
        if mt < self.started - 5:
            self._drop(req)                 # left over from before this start
            return
        if not by_launcher():
            if not self._refused:
                self._refused = now
                self.s.log("Control folder asked for a restart, but this MudPilot wasn't opened by the launcher "
                           "(nothing would reopen it) — ignored. Open MudPilot from its shortcut to allow it.")
            self._drop(req)
            return
        if not self._asked_at:
            self._asked_at = now
            self._leader_stopped = None
            self.s.log("Control folder: restart asked for — stopping at a safe moment")
        st, bot = self.s.state, self.s.bot
        busy = st.in_combat or (getattr(bot, "in_deadly", None) and bot.in_deadly())
        if busy and now - self._asked_at < SAFE_WAIT_MAX:
            return
        r = self.s.world.room(st.room) if st.room else None
        if getattr(self.s.settings, "pvp_realm", False) and r is not None and r.lair and bot.walking \
                and now - self._asked_at < SAFE_WAIT_MAX * 3:
            # (only while walking: standing still we'd never leave it — the wait just ran its 6 minutes)
            # PvP: don't log out in a regen room (Dan, 2026-10-30) — the loop walks on; close once it's out of one
            if self.ready_note():
                self.s.log("Control folder: restart waits till we're out of this lair room (PvP)")
            return
        ld = self._leader()
        if ld and self.s.telnet.connected and not getattr(self, "_leader_stopped", None):
            # following someone else's party: stop them, or they walk off and leave us behind while we restart
            # (@invite + @rego when we're back). Only now — asked first, the stopped leader kept us in a PvP lair
            # room and the lair wait above ran its full 6 minutes (Revolution, 2026-10-30)
            self.s.send(f"/{ld} @stop", from_bot=True)
            self.s.log(f"Restart: asked {ld} to @stop until I'm back")
            self._leader_stopped = ld
            return                              # close on the next check (2 s): let the telepath go out first
        self._drop(req)
        self.write_resume()
        self.s.log("Control folder: closing for a restart")
        if self.on_restart:
            self.on_restart()

    def ready_note(self) -> bool:
        """Say the PvP lair wait once a minute, not every check."""
        now = time.time()
        if now - getattr(self, "_lair_note_at", 0) > 60:
            self._lair_note_at = now
            return True
        return False

    def _leader(self):
        """The party leader we follow, if it isn't us."""
        b = self.s.bot
        if getattr(b, "walking", False) and getattr(b, "loop", False) and getattr(b, "path", None) is not None:
            # walking a loop of our own: we follow nobody, whoever's party we're still in. Dan, 2026-11-13: Miserable
            # PVE, still in Evolution's party from a relog, looped Tidepool alone — its restart @stopped Evolution's
            # whole party and then walked off to Rotting Glade to rejoin them
            return None
        x = getattr(b, "x", None)
        ld = getattr(x, "_following", None) if x else None
        rj = getattr(self.s, "_rejoin", None)
        if not ld and rj:
            ld = rj.get("leader")             # still on our way back to them: a restart carries that on (2026-10-30)
        if not ld and x is not None and getattr(x, "_followed", None) and (
                time.time() - float(getattr(x, "_followed_t", 0) or 0) < 300):
            # following them up to a few minutes ago: the leader logged off just before our own restart (a rollout
            # closes the party one by one) and the game cleared 'following'. Dan, 2026-11-16: Buddy came back
            # thinking he led, invited everyone, and Evolution's party re-formed under him without its loop
            ld = x._followed
        if not ld:
            # we @stopped them for this restart and they logged off first (a rollout closes every follower): they're
            # still who we rejoin (Buddy, 2026-11-02, came back with no leader and got left)
            ld = getattr(self, "_leader_stopped", None)
        me = (self.s.settings.my_name or "").lower()
        return ld if ld and ld.lower() != me and ld.isalpha() else None

    def _drop(self, f):
        # a file the desktop just made over the network can be locked for a moment: try again, don't just shrug
        # (Evolution, 2026-11-03: the request outlived the close, and the rollout waited 7 minutes for him)
        for i in range(8):
            try:
                os.remove(f)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.25)
        try:
            os.remove(f)
        except OSError as ex:
            self.s.log(f"Control folder: couldn't remove {os.path.basename(f)} ({ex})")

    # ------------------------------------------------------------ files
    def write_resume(self):
        s, bot = self.s, self.s.bot
        mp = bot.path if bot.walking and bot.path and not bot.path.title.startswith("Go to ") else None
        if mp is None and bot.walking and bot.after_goto is not None:
            mp = bot.after_goto                 # on the way to the loop: carry on to it
        if mp is None:
            r = getattr(bot, "resume", None) or getattr(s, "_drop_resume", None)
            mp = (r or {}).get("path") if (r or {}).get("path") and not r["path"].title.startswith("Go to ") else None
            # (0.8.201, bug hunt: a restart while the line was down — outage, mid-reconnect — found walking False
            #  (the drop clears it) and forgot the loop; what the drop kept to carry on with is still walking)
            walking = bool(mp and not getattr(bot, "resume", None) and getattr(s, "_drop_resume", None))
        else:
            walking = True
        try:
            s.remember_party()
        except Exception:
            pass
        # a Go to (or the errand fetching a key for one) carries on to where you were going — the errand starts
        # again by itself when the Go to finds the key still missing
        goto, after = None, None
        er = getattr(getattr(bot, "errands", None), "active", None)
        if er and er.get("target"):
            goto, after = er["target"], er.get("after")
        elif bot.walking and bot.path and bot.path.title.startswith("Go to ") and getattr(bot, "_goto_target", None):
            goto, after = bot._goto_target, bot.after_goto
        elif not bot.walking and not getattr(bot, "resume", None) and (getattr(s, "_drop_resume", None) or {}).get("target"):
            goto, after = s._drop_resume["target"], s._drop_resume.get("after")   # (0.8.201, bug hunt: as above)
        stopped_goto = None
        rs = getattr(bot, "resume", None) or {}
        if not goto and not bot.walking and rs.get("target"):
            # stopped on a Go to (a follower's @stop before its own restart): keep it for Rego / @rego.
            # Revolution, 2026-10-30: stopped on the way to the Bank of Godfrey, restarted, and sat 'Idle'
            stopped_goto = rs["target"]
            mp = rs.get("after") if getattr(rs.get("after"), "filename", "") else None
        if goto:
            walking = True
            mp = after if after is not None and getattr(after, "filename", "") else None
        # (0.8.201, bug hunt: down and waiting to reconnect by itself counts as connected — the next start gets back
        #  in instead of sitting offline unless auto_connect happened to be on)
        on = bool(s.telnet.connected) or bool(getattr(s, "_want_connected", False) and s.settings.auto_reconnect)
        r = {"t": time.time(), "version": __version__, "connected": on,
             "walking": walking, "loop": bool(mp and (bot.loop if bot.path is mp else mp.is_loop)),
             "title": mp.title if mp else None, "path_file": os.path.basename(mp.filename) if mp else None,
             "goto": list(goto) if goto else None,
             "stopped_goto": list(stopped_goto) if stopped_goto else None,
             "died": getattr(bot, "dead_hold", 0) or 0,
             "party": list(getattr(s, "_reinvite", None) or []),
             # walking a loop of our own (or a Go to on the way to one) means we're not following anybody, whatever
             # party we were in last — a follower's walking is its leader's. Dan, 2026-11-10: Buddy left
             # Evolution's party to loop Crimson Fort on his own; after a restart he stood there waiting for an
             # invite from Evolution
             "follow": None if walking and mp is not None and not getattr(s, "_rejoin", None) else self._leader(),
             # stopped (a follower's @stop before its own restart): kept so their @rego still carries on with it
             "stopped": bool(not walking and mp and getattr(bot, "resume", None))}
        # (0.8.201, bug hunt: a hang-up lived only in memory — a restart inside the stay-offline time logged straight
        #  back into the room it had just fled. -1 = stay off until you connect yourself; older files lack these keys)
        hu = float(getattr(getattr(s, "safety", None), "hung_up_until", 0) or 0)
        r["hung_up_until"] = -1 if hu == float("inf") else (hu if hu > time.time() else 0)
        r["hold_realm"] = bool(getattr(s, "hold_realm", False))
        self._write("resume.json", r)

    def write_status(self):
        s = self.s
        st, bot = s.state, s.bot
        try:
            rate = s.stats.exp_rate()
        except Exception:
            rate = None
        d = {"t": time.time(), "version": __version__, "by_launcher": by_launcher(),
             "connected": bool(s.telnet.connected), "in_game": bool(getattr(s, "_entered", False)),
             "walking": bool(bot.walking), "path": bot.path.title if bot.path else None,
             "status": str(getattr(bot, "status", ""))[:160], "room": list(st.room) if st.room else None,
             "hp_pct": round(st.hp_pct()) if st.max_hp else None,
             "ma_pct": round(st.ma_pct()) if st.max_ma else None,
             "in_combat": bool(st.in_combat), "exp_hr": round(rate) if rate else None,
             "hands_off": bool(getattr(s.settings, "hands_off", False)),
             # which settings profile is running: the next start opens this one even if app.json says otherwise
             # (Dan, 2026-11-13: after Revolution's PC lost power, PVEREV came up on a two-week-old profile)
             "profile": getattr(s.settings, "profile", None)}
        d.update(self._overview_fields())
        try:
            d["follows"] = self._leader()      # (0.8.204: rollout.py closes followers before the in-game leader)
        except Exception:
            d["follows"] = None
        self._write("status.json", d)
        if getattr(s.settings, "status_broadcast", False):
            try:                            # (0.8.201) optional LAN packet for the All characters window; off by default
                from . import overview
                overview.send_status(d, int(getattr(s.settings, "status_broadcast_port", 0) or overview.UDP_PORT))
            except Exception:
                pass

    def _overview_fields(self) -> dict:
        """(0.8.201) What the All characters window (overview.py) shows besides the above: who, where, level. Never a
        password, chat or screen text — just names and numbers the window prints. Anything that fails is left out."""
        s = self.s
        st, bot, cfg = s.state, s.bot, s.settings
        out = {}
        try:
            r = s.world.room(st.room) if st.room else None
            hu = float(getattr(getattr(s, "safety", None), "hung_up_until", 0) or 0)
            out.update({
                "name": cfg.my_name or "", "board": cfg.board or "", "pvp_realm": bool(getattr(cfg, "pvp_realm", False)),
                "level": int(st.level or cfg.char_level or 0),
                "cls": str(getattr(st, "char_class", "") or cfg.char_class or "")[:20],
                "room_name": (r.name if r else "")[:80],
                "hp": st.hp, "max_hp": st.max_hp, "ma": st.ma, "max_ma": st.max_ma,
                "loop": bool(getattr(bot, "loop", False)),
                "hung_up": hu > time.time(), "dead": bool(getattr(bot, "dead_hold", 0)),
                "status_every": STATUS_SECS})
        except Exception:
            pass
        return out

    def _write(self, name, data):
        tmp = self._p(name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, self._p(name))
        except OSError:
            pass
