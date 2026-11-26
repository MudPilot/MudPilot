"""Session: owns the connection, ANSI stream, game state and bot. UI-independent so
it can run headless (tests) or under the Tk window."""
from __future__ import annotations

import os
import shutil
import re
import time

from . import config
from .ansi import AnsiStream, plain
from .automation import Automation
from .gamestate import GameState
from .spells import SpellBook
from .megamud_files import read_mp, resolve_path, find_mp_files, MPath, write_mp
from .telnet import TelnetClient
from .worlddb import WorldDB


RESOLVER_VERSION = 2       # bump when path matching changes (2: bridges moves MME doesn't have)


PARTY_HOLD_SECS = 300         # after a disband you meant: no automatic invites / joins for this long (0.8.224, Dan:
                              # "it shouldn't regroup for a few minutes" — it was 60 s, invites only)
# 0.8.200 (auto-train, Dan: CP can't be unspent): the train stats form holds every automatic command — par, telepath
# replies, triggers, all of it — from the moment 'train stats' goes out (MudPlay: a 'par' typed into the Family Name
# box made a character's last name "par"). Not seen yet after FORM_HOLD_WAIT → no form came; seen → never longer
# than FORM_HOLD_CAP (a missed exit once left MudPlay's keyboard held and the loop's first move was dropped).
FORM_HOLD_WAIT = 12.0
FORM_HOLD_CAP = 180.0


# a party MudPilot's "@mpsync" (rest / level / spell-tune sync) and ours going out — not for the game screen
MPSYNC_SCREEN_RE = re.compile(r"^(?:\w+ telepaths: @mpsync\b|/\w+ @mpsync\b)", re.I)

class Session:
    def __init__(self, settings: config.Settings | None = None, world_path: str | None = None):
        from .splash import progress
        config.migrate_single_board()
        progress(8, "Reading your settings…")
        self.settings = settings or config.Settings.load()
        world_path = world_path or config.world_path(self.settings.board)
        progress(15, f"Unrolling the map of {self.settings.board or 'the Realm'}…")
        self.world = self._open_world(world_path)
        progress(48, f"{len(self.world.rooms):,} rooms, {len(getattr(self.world, 'monsters', {}) or {}):,} monsters "
                     "— waking the bot…")
        self.world_path = world_path
        self.telnet = TelnetClient()
        self.ansi = AnsiStream()
        self.state = GameState(self.world)
        self.state.on_learn = [self.learn_exit]
        from .recorder import Recorder
        self.recorder = Recorder(self)
        from collections import deque
        self.decisions = deque(maxlen=300)       # the bot's recent decisions ("why did it do that")
        self.spellbook = SpellBook(self.world)
        self.spellbook.carrying = lambda: self.state.carrying or ""
        self.spellbook.known = self.known_spell_dicts       # 'fury' = the fury you know (find)
        try:
            wp = os.path.abspath(self.world_path or "")
            if wp.startswith(os.path.abspath(config.BOARDS_DIR) + os.sep):      # (a character's board, not test data)
                self.spellbook.load_memory(os.path.join(os.path.dirname(wp), "spell_memory.json"))
        except Exception:
            pass
        from .spells import apply_mana_overrides
        apply_mana_overrides(self.world, getattr(self.settings, "spell_mana", None))   # your own mana costs
        self._load_unfindable()                       # hidden exits searching never found (24 h)
        self.bot = Automation(self)
        from .remote import RemoteControl
        from .bosses import BossTracker
        from .chat import ChatLog
        self.remote = RemoteControl(self)
        self.bosses = BossTracker(self)
        from .bosshunt import BossHunt
        self.bosshunt = BossHunt(self)
        from .gearmodes import GearModes
        self.gearmodes = GearModes(self)
        from .shoptrips import ShopTrips
        self.trips = ShopTrips(self)
        from .scrolls import ScrollErrand
        self.scrolls = ScrollErrand(self)        # spell scrolls after a level-up (0.8.200, scrolls.py)
        from .training import Training
        self.training = Training(self)           # auto-train: levels, CP plan, party (0.8.200, training.py)
        self._form_hold = None                   # the train stats hold (begin_form_hold)
        from .comeback import Comeback
        self.comeback = Comeback(self)
        from .routerec import RouteRecorder
        self.routerec = RouteRecorder(self)      # the map's Record Path / Record Loop
        from .messagerules import MessageRules
        self.msgrules = MessageRules(self)
        from .extrafeatures import Sounds, Scheduler, Tracker, Leaderboard, EightBall, Quests
        self.sounds, self.scheduler, self.tracker = Sounds(self), Scheduler(self), Tracker(self)
        self.leaderboard, self.eightball, self.quests = Leaderboard(self), EightBall(self), Quests(self)
        self.on_bell = lambda: None
        self.chat = ChatLog(self.settings)
        self.state.on_room.append(self.bosses.on_room)
        self.state.on_exp.append(self.bosses.on_exp)
        from .combatlog import CombatLog
        self.combatlog = CombatLog(self)
        self.state.on_room.append(self.combatlog.on_room)
        self.state.on_exp.append(self.combatlog.on_exp)
        self.state.on_spells.append(self._got_spells)
        self.state.on_located.append(lambda k: self.log(
            f"Location confirmed by '{self.settings.locate_cmd}': {k[0]}/{k[1]} {self.world.room(k).name}"))
        self.spellbook.on_refused = lambda sp: self.log(
            f"The game won't let you cast {sp['Name'] if sp else 'that spell'} — dropped it for this session")
        from .safety import Safety
        self.safety = Safety(self)
        from .notify import Notifier
        self.notify = Notifier(self)
        from .chatalerts import ChatAlerts
        self.chatalerts = ChatAlerts(self)                 # chat keyword alerts (0.8.201, off unless ticked)
        self.chat.listeners.append(self.chatalerts.on_chat)
        from .notify import PhoneControl
        self.phone = PhoneControl(self)
        from .webremote import WebRemote
        self.web = WebRemote(self)               # the phone page (off unless ticked)
        from .loopstats import LoopStats
        self.loopstats = LoopStats(self)
        from .danger import Danger
        self.danger = Danger(self)
        from .spelltune import SpellTune
        self.spelltune = SpellTune(self)
        from .loopbuild import LoopBuilder
        self.loopbuilder = LoopBuilder(self)
        from .analyzer import LoopAnalyzer
        self.analyzer = LoopAnalyzer(self)
        from .spots import SpotFinder
        self.spots = SpotFinder(self)
        from .advisor import Advisor
        self.advisor = Advisor(self)
        from .sync import Sync
        self.sync = Sync(self)
        self.chat.room_name = lambda key: (self.world.room(key).name if self.world.room(key) else "")
        from .timeline import Timeline
        self.timeline = Timeline(self)
        from .partysync import PartySync
        self.partysync = PartySync(self)
        from .pathshare import PathShare
        self.pathshare = PathShare(self)             # send / take paths over telepath
        from .gearwatch import GearWatch
        self.gearwatch = GearWatch(self)
        self.state.on_room.append(self.gearwatch.on_room)
        from .chestloot import ChestLoot
        self.chestloot = ChestLoot(self)             # drop cheap chest loot, sell the valuable (0.8.201)
        from .itemcharges import ItemCharges
        self.itemcharges = ItemCharges(self)         # wand / per-day item charges (0.8.201)
        from .autotune import AutoTune
        self.autotune = AutoTune(self)
        from .history import History
        self.history = History(self)
        from .lairclock import LairClock
        self.lairclock = LairClock(self)
        from .lair_camp import LairCamp
        self.lair_camp = LairCamp(self)          # Camp lairs: off until you start it (0.8.201, lair_camp.py)
        from .hangupitems import HangupItems
        self.hangup_items = HangupItems(self)    # pick up what a penalised hang-up dropped (0.8.201, hangupitems.py)
        from .watchdog import Watchdog
        self.watchdog = Watchdog(self)
        from .control import ControlBox
        self.control = ControlBox(self)
        self.state.on_event.append(lambda kind, data: kind == "death" and self.bot.on_death())
        from .combatclock import CombatClock
        self.clock = CombatClock(os.path.join(config.DATA_DIR, "round_clock.json")
                                 if not os.environ.get("MUDPILOT_NO_RECORD") else None)   # tests: no saved beat
        from .tick import ServerTick
        self.servertick = ServerTick(self)
        self.state.on_room.append(self.safety.on_room)
        from .players import PlayerDB
        self.players = PlayerDB(self)
        self.state.on_room.append(self.players.on_room)
        from .scripters import Scripters
        self.scripters = Scripters(self)              # someone else scripting our loop
        self.state.on_room.append(self.scripters.on_room)
        self.state.on_room.append(lambda st: self.bot.walking and self.bot.loop and
                                  self.loopstats.note_room(st.room, st.view))
        from .responses import Responses
        self.responses = Responses(self)
        from .macros import Macros
        self.macros = Macros(self.settings)
        from .events import EventManager
        self.events = EventManager(self)
        from .stats import SessionStats
        self.stats = SessionStats(self)
        _reset = self.state.reset_stats

        def reset_all():
            # (0.8.224, real logs — Buddy x2: "Reset session stats" mid-lap saved "Lap 3: 9.4 min, 0 exp, 0 kills"
            #  into the loop stats. The lap's progress so far is carried over the reset)
            ls = getattr(self, "loopstats", None)
            lap = getattr(ls, "_lap", None) if ls is not None else None
            done = None
            if lap:
                try:
                    done = (self.state.exp_gained - lap["exp"], self.state.kills - lap["kills"],
                            self.stats.rests - lap["rests"])
                except Exception:
                    done = None
            _reset()
            self.stats.reset()
            if lap and done:
                lap["exp"] = self.state.exp_gained - done[0]
                lap["kills"] = self.state.kills - done[1]
                lap["rests"] = self.stats.rests - done[2]
        self.state.reset_stats = reset_all
        self.practice = False            # connected to the local practice server
        self.paths: list[MPath] = []
        self.password: str | None = None
        self._fired_once: set = set()
        self._want_connected = False
        self._entered = False
        self._connected_at = 0.0
        self._closed_at = 0.0
        self.logs: list = []
        self._task_done = False
        # UI hooks
        self.on_line = lambda segs: None
        self.on_partial = lambda text: None
        self.on_log = lambda msg: None
        self.on_status = lambda: None
        self.on_clear = lambda: None
        self.on_sent = lambda cmd, from_bot: None
        self.on_settings_changed = lambda: None
        self.on_alert = lambda msg: None
        self.on_no_route = lambda msg: None       # the app pops this up (goto / loop couldn't find a way)
        self.on_paths_changed = lambda: None
        self.on_banner = lambda text, kind: None   # big notice on the MUD screen (connected / disconnected)
        self._down_shown = True
        import queue as _q
        self._bg = _q.Queue()              # work finished on background threads, applied in poll()
        self.paths_busy = None             # (done, total, label) while paths are being matched
        self._match_cache = {}
        m_ = re.match(r"^(\d+)/(\d+)$", self.settings.last_room or "")
        if m_:
            self.state.last_known = (int(m_.group(1)), int(m_.group(2)))
        for k, v in (self.settings.known_abils or {}).items():
            try:
                self.state.abil_rows[("granted", int(k))] = (int(v), 0.0)   # known before the first 'abil'
            except (TypeError, ValueError):
                pass
        self._load_learned()
        self._board_fixes()
        progress(62, "Laying out your paths and loops…")
        self.load_saved_paths()
        self._world_note()
        progress(72, "Lighting the torches…")

    # ------------------------------------------------------------ logging
    def log(self, msg: str):
        stamp = time.strftime("%H:%M:%S")
        if not hasattr(self, "logs"):
            self.logs = []                 # something logged while the session is still being built
        if not hasattr(self, "on_log"):
            self.logs.append(f"{stamp}  {msg}")
            return
        last = getattr(self, "_last_log", None)
        now = time.time()
        if last and last[0] == msg and now - last[1] < 3:
            return                         # the same line twice in a row ("Eco: walking past…" ×2) — once is enough
        self._last_log = (msg, now)
        if hasattr(self, "recorder"):
            self.recorder.log(msg)
        self.logs.append(f"{stamp}  {msg}")
        self.logs = self.logs[-3000:]
        self._log_file(f"{stamp}  {msg}")
        self.on_log(f"{stamp}  {msg}")

    LOG_KEEP_DAYS = 14

    def _log_file(self, line):
        """MudPilot's log, one file a day in data\\logs (kept two weeks) — so a night's run can be looked
        at in the morning. Never has passwords: those are shown as (password) everywhere."""
        if getattr(self, "_no_log_file", False):
            return
        try:
            d = os.path.join(config.DATA_DIR, "logs")
            day = time.strftime("%Y%m%d")
            if getattr(self, "_log_day", None) != day:
                os.makedirs(d, exist_ok=True)
                self._log_day = day
                cutoff = time.time() - self.LOG_KEEP_DAYS * 86400
                for fn in os.listdir(d):
                    fp = os.path.join(d, fn)
                    if fn.startswith("mudpilot-") and os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
            with open(os.path.join(d, f"mudpilot-{day}.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            self._no_log_file = True

    # ------------------------------------------------------------ connection
    def connect(self, host=None, port=None, sock=None):
        self._enter_pending = None
        if host is None:
            self.practice = False
        host = host or self.settings.host
        port = int(port or self.settings.port)
        if not host:
            raise ValueError("No host set")
        self._last_addr = (host, port)
        self.recorder.mark("connect", practice=bool(getattr(self, "practice", False)))
        self._fired_once.clear()
        self._task_done = False
        self._entered = False
        self._menu_seen = False
        self._held_said = False
        self._login_failed = False
        self._connected_at = time.time()
        try:
            # an ailment from before the drop (or before a death) isn't known to still be on: the next line about
            # it says (0.8.201, bug hunt: ailments never cleared)
            self.bot.x.ailments.clear()
            self.bot.x.care._reported.clear()    # (0.8.224.2, review: or release_hold never says @ok again)
        except Exception:
            pass
        if hasattr(self, "safety"):
            self.safety.hung_up_until = 0.0
        self.ansi = AnsiStream()
        if sock is not None:
            self.telnet.adopt(sock)
        else:
            self.telnet.connect(host, port)
        self._want_connected = True
        self._await_reply_since = None
        self._down_shown = False
        self.log(f"Connected to {host}:{port}")
        self.on_banner(f"*** Connected to {host}:{port} at {time.strftime('%I:%M:%S %p').lstrip('0')} ***", "up")

    def _check_echo(self, text):
        """Does the board echo what we type (Paradigm does)? Then don't echo it a second time ourselves —
        every 'par' / 'abil 145' was showing twice."""
        if getattr(self, "server_echoes", False):
            return
        t = text.strip()
        now = time.time()
        for at, cmd in getattr(self, "_recent_sent", []):
            if cmd and len(cmd) >= 2 and now - at < 3 and t == cmd:
                self._echo_hits = getattr(self, "_echo_hits", 0) + 1
                if self._echo_hits >= 3:
                    self.server_echoes = True
                    self.log("The board echoes your commands — MudPilot stops echoing them a second time")
                break

    EDITOR_RE = re.compile(r"Char\. Creation|CP Left:|Point Cost Chart|SAVE your character", re.I)

    # ---- the train stats hold (0.8.200)
    def begin_form_hold(self, why="train stats"):
        self._form_hold = {"t": time.time(), "seen": False, "why": why, "dropped": 0, "t_seen": 0.0}

    def note_form_seen(self):
        h = getattr(self, "_form_hold", None)
        if h and not h["seen"]:
            h["seen"], h["t_seen"] = True, time.time()

    def form_seen(self) -> bool:
        h = getattr(self, "_form_hold", None)
        return bool(h and h["seen"])

    def form_held(self) -> bool:
        """True while automatic commands are held for the train stats form."""
        h = getattr(self, "_form_hold", None)
        if not h:
            return False
        now = time.time()
        if (not h["seen"] and now - h["t"] > FORM_HOLD_WAIT) or (h["seen"] and now - h["t_seen"] > FORM_HOLD_CAP):
            self.end_form_hold("timed out" if h["seen"] else "no form came")
            return False
        return True

    def end_form_hold(self, why=""):
        h, self._form_hold = getattr(self, "_form_hold", None), None
        if h:
            self.log(f"Train stats: automatic commands go out again ({why})"
                     + (f" — {h['dropped']} held back and dropped" if h["dropped"] else ""))

    def form_key(self, data: str):
        """One keystroke for the train stats form, straight out (digits + CR, a bare CR, or a Space — the form is
        driven with CR alone, as MudPlay found live). Goes past the hold: it's what the hold is for."""
        if not self.telnet.connected:
            return
        self.telnet.send_raw(data.encode("cp437", errors="replace"))
        shown = data.rstrip("\r")
        self.recorder.tx(shown if shown.strip() else ("(Space)" if data == " " else "(Enter)"), True)
        self.on_sent(shown, True)

    def leave_realm(self, why):
        """Off in a full-screen menu (train stats, the character editor…): the bot stays quiet until a
        room shows again — otherwise its par/abil/flux land in the editor's boxes."""
        if self._entered:
            self._entered = False
            self._left_at = time.time()
            self.log(f"Paused: {why} — waiting until you're back in the realm")

    def show_down(self, why):
        """Say so on the MUD screen, once per connection."""
        if not self._down_shown:
            self._down_shown = True
            self.on_banner(f"*** {why} at {time.strftime('%I:%M:%S %p').lstrip('0')} ***", "down")

    def hangup_now(self):
        """Alt+H: drop the line immediately, no prompt, and stay off."""
        self.hold_realm = True                  # next connect stops at the MajorMUD menu
        self._want_connected = False
        self.bot.stop("Hung up (Alt+H)")
        self.telnet.close()
        self.log("Hung up (Alt+H)")
        self.show_down("HUNG UP (Alt+H)")

    def send_exit_cmd(self):
        cmd = (self.settings.game_exit_cmd or "").strip()
        if cmd and self.telnet.connected:
            self.bot.send_macro(cmd)

    def disconnect(self):
        if (self.settings.game_exit_cmd or "").strip() and self.telnet.connected:
            self.hangup_items.note_clean_exit()      # quitting with the game's exit command drops nothing (0.8.201)
        self.send_exit_cmd()
        self._want_connected = False
        self._drop_resume = None
        self._drop_started = 0
        self.bot.stop("Disconnected")
        self.telnet.close()

    DUP_PARTY_RE = re.compile(r"^\s*\.?(?:invite\s+\S+|/\S+\s+@join|@party\s+.+|/\S+\s+@do\s+.+|/\S+\s+@where)\s*$", re.I)

    def _dup_party_cmd(self, cmd) -> bool:
        """Regroup, Game Data's 'invite if seen', comeback and the reconnect re-invite can all decide to invite
        the same member in the same second. One invite (one @join, one @party…) is enough: repeats within 8 s
        are dropped — the spam only confuses MegaMUD followers."""
        c = (cmd or "").strip().lower().lstrip(".")
        if not self.DUP_PARTY_RE.match(c):
            return False
        now = time.time()
        sent = getattr(self, "_party_sent", {})
        sent = {k: t for k, t in sent.items() if now - t < 8}
        if c in sent:
            self._party_sent = sent
            return True
        sent[c] = now
        self._party_sent = sent
        return False

    LEADER_MEMORY = 1800

    def my_leader(self) -> str:
        """Who leads me: the one I follow, the one I'm rejoining after a restart — or, when the party has just broken
        and I'm not running a loop of my own, the one I followed in the last half hour. (0.8.212, Dan 2026-11-19: the
        PvP party broke at 23:39, Miserable's 'invite if seen' invited Revolution, its @join pulled Revolution into
        Miserable's party, and both stood there — and not for the first time.)"""
        x, b = self.bot.x, self.bot
        lead = getattr(x, "_following", "") or (getattr(self, "_rejoin", None) or {}).get("leader") or ""
        recent = time.time() - getattr(x, "_followed_t", 0) < self.LEADER_MEMORY
        if not lead and not (b.walking and b.loop) and recent:
            lead = getattr(x, "_followed", "") or ""
        return lead

    def send(self, cmd: str, from_bot: bool = False):
        if not self.telnet.connected:
            return
        if (cmd or "").startswith("/"):
            self._last_tp = (cmd, time.time())       # '--- Telepath Not Sent ---' resends it (0.8.200)
        if from_bot and getattr(self.settings, "hands_off", False):
            return                                   # Hands off: nothing goes out unless you type it
        if from_bot and self.form_held():
            # the train stats form is up (or coming): nothing automatic may land in its boxes
            h = self._form_hold
            h["dropped"] += 1
            if h["dropped"] == 1:
                self.log(f"Train stats: holding automatic commands while the form is up ('{(cmd or '')[:30]}' "
                         "and anything after it)")
            return
        # a member asked for it ('@invite', '@do invite …'): not held back by the disband pause, the repeat filter or
        # an old idea of who leads (0.8.208, Dan 2026-11-19: Revolution's own blocked auto-invite filled the repeat
        # filter, and Miserable's '@invite' 4 s later was dropped without a word — then '@do invite' hit the pause)
        asked = bool(getattr(self.remote, "_asked_invite", False) or getattr(self.remote, "_in_do", False))
        if from_bot and not asked and self._dup_party_cmd(cmd):
            return                                   # the same invite / @join a moment ago (two parts asked)
        if re.match(r"^\s*(?:disband|leave(?:\s+party)?)\b", cmd or "", re.I) and \
                (not from_bot or getattr(self.remote, "_in_do", False)):
            # a disband you (or a friend's @do) meant: someone else is going to lead for a bit — no automatic
            # invites for a minute, or they'd be pulled straight back (Dan, 2026-11-01: "with MegaMUD you gotta be
            # quick as fuck and sometimes try it 2 times")
            self._party_hold_until = time.time() + PARTY_HOLD_SECS
            self._party_hold_from = time.time()
            self.log(f"Disbanded — no automatic invites or joins for {PARTY_HOLD_SECS // 60} minutes, so nobody "
                     "regroups straight away (type invite / join yourself to)")
            try:
                self.partysync.tell_disband()
            except Exception:
                pass
        if not from_bot and re.match(r"^\s*(?:invite|join)\s+\w+", cmd or "", re.I) and \
                time.time() < getattr(self, "_party_hold_until", 0):
            # (0.8.224.3, loops hunt) the party is being re-formed on purpose: the pause is over — comeback and
            # regrouping look after the new party again (it ignored @comeback and never fetched a straggler)
            self._party_hold_until = 0
            if hasattr(self, "comeback"):
                self.comeback._self_left = min(self.comeback._self_left, time.time() - 11)
        mjh = re.match(r"^\s*join\s+(\w+)", cmd or "", re.I) if from_bot else None
        if mjh and time.time() < getattr(self, "_party_hold_until", 0) and not asked:
            if self.bot.ready("party_hold_join_note", 15):
                self.log(f"Not joining {mjh.group(1)} — automatic regrouping paused "
                         f"({int(self._party_hold_until - time.time())} s) after the disband")
            return
        mi = re.match(r"^\s*invite\s+(\w+)", cmd or "", re.I) if from_bot else None
        if mi and time.time() < getattr(self, "_party_hold_until", 0) and not asked:
            if self.bot.ready("party_hold_note", 15):
                self.log(f"Not inviting {mi.group(1)} — auto-invite paused "
                         f"({int(self._party_hold_until - time.time())} s) after the disband")
            return
        if mi:
            self.__dict__.setdefault("_invited_at", {})[mi.group(1).lower()] = time.time()
            lead = self.my_leader().lower()
            if lead and mi.group(1).lower() == lead and not asked:
                self.log(f"Not inviting {mi.group(1)} — they lead; I join them")
                return
        if not from_bot and re.search(r"(?<![a-z0-9])@ok\b", cmd or "", re.I):
            self.remote.release_all("you sent @ok")
        if not from_bot:
            self._own_auto(cmd)
        mj = re.match(r"^\s*join\s+(\w+)", cmd or "", re.I)
        if mj:
            self._join_sent = (mj.group(1), time.time())
        summons = (cmd or "").strip().lower() in getattr(self.world, "summon_triggers", ())
        mu = re.match(r"^\s*use\s+(.+?)\s*$", cmd or "", re.I) if from_bot and not getattr(self, "_expanding", False) else None
        if mu and self.state.carrying:
            # 'use longsword' (a bless made while it was in hand) with the longbow out now: "You do not have
            # shimmering longsword equipped." — swap it in, use it, swap back, like '#sl' (Dan, 2026-10-30, Buddy)
            from .itemspells import table, alias
            from .gamestate import worn_list, parse_item_list
            want = mu.group(1).lower()
            have = [re.sub(r"\s*\([^)]*\)\s*$", "", n).strip() for _q, n in parse_item_list(self.state.carrying)]
            worn = {n.lower() for n, _s in worn_list(self.state.carrying)}
            # (only when the shortcut really is this item's: '#w' is Windblade's — 'use waterskin' went out as
            # 'use Windblade' and nobody drank in the Scorching Desert, Buddy 2026-11-04)
            tb = table(self.world)
            hit = next((n for n in have if (n.lower() == want or n.lower().split()[-1] == want.split()[0])
                        and n.lower() not in worn
                        and any((i.get("name") or "").lower() == n.lower() for i in tb.get(alias(n)) or [])), None)
            if hit:
                cmd = alias(hit) + cmd[mu.end(1):]
        if (cmd or "").lstrip().startswith("#"):
            # '#etc' / '#lsc orc': an item's spell — take off the off-hand item, equip it, use it, put things back
            from .itemspells import expand
            seq = expand(self.world, cmd, self.state.carrying or "")
            if seq:
                self._expanding = True               # (its own 'use …' goes out as it is)
                try:
                    for c in seq:
                        # straight out, not through self.send: while a Go to is planned in the background, bgplan
                        # swaps self.send for a queue — the swap's 'use crozier' came back out after _expanding was
                        # cleared, was expanded again, and so on for ever: 130,000 'eq' lines and a crash
                        # (Revolution PVE, 2026-11-21)
                        type(self).send(self, c, from_bot)
                finally:
                    self._expanding = False
                return
        ic = getattr(self, "itemcharges", None)
        if ic is not None and ic.blocked(cmd, from_bot):
            return                                   # a charged item that's out until cleanup (itemcharges.py)
        if ic is not None:
            ic.note_send(cmd)
        if getattr(self, "chestloot", None) is not None:
            self.chestloot.note_send(cmd)            # 'open <chest>': read the pack before and after (chestloot.py)
        self.state.note_command(cmd)
        self.chat.note_sent(cmd, from_bot)
        self.stats.note_command(cmd)
        ms = re.match(r"^\s*/([A-Za-z][\w'-]*)\s+@(summon|comeback)\s*$", cmd or "", re.I)
        if ms:
            # summoning (or calling back) another MudPilot: tell them where we are, so they don't have to ask
            # (Dan, 2026-11-02: '@comeback' alone got "needs map and room")
            if ms.group(2).lower() == "summon":
                self.remote._summon_sent = {**getattr(self.remote, "_summon_sent", {}), ms.group(1).lower(): time.time()}
            if self.state.room:
                cmd = f"{cmd.strip()} {self.state.room[0]} {self.state.room[1]}"
        cmd = self._talk_slow_out(cmd)
        lc = (getattr(self.settings, "locate_cmd", "") or "").strip().lower()
        if lc and (cmd or "").strip().lower() == lc:
            # the room-number command, whoever typed it: its answer is believed (it used to count only when
            # MudPilot asked — you typed 'pro', it said 12,2031, and the map stayed on 12/2032)
            self.state.locate_until = time.time() + 5
        if not from_bot:
            self._user_sent_at = time.time()
            self.bot.manual.note_cmd(cmd)            # an attack / targeted spell you typed: your fight now
            c0 = (cmd or "").strip().lower()
            if c0 in ("n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d", "north", "south", "east", "west",
                      "northeast", "northwest", "southeast", "southwest", "up", "down") or c0.startswith("go "):
                self.bot._user_moved_at = time.time()      # you're driving: the bot waits a moment
                if getattr(self.settings, "stop_on_typed_move", True):
                    if self.bot.walking and self.bot.path:
                        # you took over: no more steps until you click Rego (which carries on from wherever you are)
                        self.bot.stop("Paused: you moved by hand — click Rego to carry on")
                    # …and nothing that was going to pick the trip up again by itself does (fetching a member
                    # and then 'carrying on to' the Go to dragged you back to the room you'd just walked out of)
                    f = getattr(self.comeback, "fetch", None)
                    if f and f.get("back"):
                        f["back"] = None
                        self.log("Comeback: you're driving — won't carry on with the trip afterwards")
                    self.bot._regoto_at = 0
                    self.bot.drop_parked()
                    self.bot._watchdog_rego_at = 0
        if re.match(r"^\s*train\s+stat", cmd or "", re.I):
            # the hold starts as it goes out (yours or auto-train's), not when the form's marker shows — Paradigm's
            # cursor-drawn box may never send its marker as a line (0.8.200)
            self.begin_form_hold()
            self.leave_realm("training stats")
        self.telnet.send_line(cmd)
        self.recorder.tx(cmd, from_bot)
        self.routerec.note_sent(cmd)
        if hasattr(self, "comeback"):
            self.comeback.note_sent(cmd)
        if summons:
            # 'touch statue' / 'touch hammer' calls a monster up and it attacks: look now, don't stand there while it
            # works Buddy over (Dan, 2026-10-28 — it sent i, abil and par first and waited for Enter)
            self.send("", from_bot=True)
            self.quests.note_sent(cmd)
            self.bot.note_quest_cmd(cmd)
        if hasattr(self, "timeline"):
            self.timeline.note_sent(cmd)
        if getattr(self, "_await_reply_since", None) is None:
            self._await_reply_since = time.time()      # cleared by the next thing the board sends
        self._recent_sent = (getattr(self, "_recent_sent", []) + [(time.time(), (cmd or "").strip())])[-8:]
        self.on_sent(cmd, from_bot)
        m = re.match(r"^\s*inv(?:ite)?\s+([A-Za-z][\w'-]*)\s*$", cmd or "", re.I)
        if m and (self.settings.invite_join_cmd or "").strip():
            # typed or automatic: once the game says who it really was ("invite re" → Revolution),
            # tell them to @join — by their full name, so a short name can't hit the wrong player
            self._invite_pending = time.time()

    def decide(self, what: str, **info):
        """Note a decision (spell picked, step sent, route changed…) for Copy diagnostics and the recording."""
        rec = {"t": round(time.time(), 2), "what": what, **info}
        self.decisions.append(rec)
        self.recorder.decision(rec)

    OWN_AUTO_RE = re.compile(r"^\s*\.?@(auto-[a-z]+|attack-last)\s+(on|off)\s*$", re.I)

    def _own_auto(self, cmd):
        """'.@auto-combat off' / '@auto-combat on' typed yourself: still said to the party, and now switches
        your own character too (Dan, 2026-11-20: it only reached the others - what you say comes back as
        'You say', never as a remote command)."""
        m = self.OWN_AUTO_RE.match(cmd or "")
        if not m:
            return
        name, val = m.group(1).lower(), m.group(2).lower()
        fn = getattr(self.remote, "c_" + name.replace("-", "_"), None)
        if fn is None:
            return
        try:
            out = fn(getattr(self.settings, "my_name", "") or "you", val)
        except Exception as ex:
            self.log(f"@{name} {val}: {ex}")
            return
        if out:
            self.log(f"{out} (you typed it)")

    # ------------------------------------------------------------ set talk slow
    SAY_RE = re.compile(r'^You say "(.*)"\s*$')

    def _talk_slow_out(self, cmd):
        """'@party go portal' said in the room. With 'set talk slow' on, anything said needs a leading '.',
        or the game answers 'Your command had no effect.' — so once we've seen that, add the '.'."""
        c = (cmd or "").strip()
        if c.startswith("@") and int(getattr(self.settings, "talk_slow", -1)) == 1:
            cmd = "." + c
            c = cmd
        if c.startswith(("@", ".@")):
            self._said = (time.time(), c, False)
        return cmd

    def _mask_secret(self, segs):
        """'pro' prints 'Recover Password: …' — show it as (hidden) on screen too, so it can't end up in a
        screenshot or a pasted log. (Settings → Other: 'Show the recover password' turns this off.)"""
        if getattr(self.settings, "show_recover_password", False):
            return segs
        from .timeline import SECRET_RE
        txt = plain(segs)
        if not SECRET_RE.search(txt):
            return segs
        col = segs[0][1] if segs else None
        return [(SECRET_RE.sub(lambda m: (m.group(1) or m.group(3)) + "(hidden)", txt), col)]

    def _save_quietly(self):
        self.settings.save_quietly(self.log)
        try:
            self.hangup_items.snapshot("save")         # the profile saves: so does the hang-up item list (0.8.201)
        except Exception:
            pass

    def _talk_slow_line(self, text):
        mt = re.match(r"^Talking speed:\s+(\w+)", text.strip())
        if mt:                                       # 'pro' says it outright
            v = 1 if mt.group(1).lower() == "slow" else 0
            if int(getattr(self.settings, "talk_slow", -1)) != v:
                self.settings.talk_slow = v
                self.log(f"Talk speed is {mt.group(1).lower()} — " +
                         ("saying things with a '.' in front" if v else "saying things as typed"))
                self._save_quietly()
            return
        said = getattr(self, "_said", None)
        if not said or time.time() - said[0] > 5 or said[2]:
            return
        t, c, _ = said
        line = text.strip()
        if line == "Your command had no effect." and c.startswith("@"):
            self._said = (t, c, True)
            self.settings.talk_slow = 1
            self.log("Talk is set slow here — saying it with a '.' in front from now on")
            self._save_quietly()
            self.send("." + c, from_bot=True)
            return
        m = self.SAY_RE.match(line)
        if m:
            self._said = (t, c, True)
            if m.group(1).startswith(".@") and c.startswith(".@"):
                self.settings.talk_slow = 0
                self.log("Talk isn't set slow — the '.' was said out loud; saying it again without it")
                self._save_quietly()
                self.telnet.send_line(c[1:])
                self._said = (time.time(), c[1:], True)
            elif c.startswith(".@") and int(getattr(self.settings, "talk_slow", -1)) != 1:
                self.settings.talk_slow = 1

    # ------------------------------------------------------------ main loop
    def poll(self):
        """Drain network events, parse, run the bot. Call ~20x per second."""
        got = False
        now = time.time()
        lp = getattr(self, "_last_poll", 0)
        self._last_poll = now
        if lp and now - lp > 45:
            self._woke_up(now - lp)
        while not self._bg.empty():
            try:
                self._bg.get_nowait()()
            except Exception as ex:
                self.log(f"Background job: {ex}")
        while True:
            try:
                kind, data = self.telnet.events.get_nowait()
            except Exception:
                break
            if kind == "data":
                got = True
                self.recorder.rx(data)
                self._await_reply_since = None
                self._last_data_at = time.time()
                self._probe_at = 0
                for segs in self.ansi.feed(data):
                    self._line(segs)
                if self.ansi.clear_requested:
                    self.ansi.clear_requested = False
                    self.on_clear()
                    self.web.clear()
                part = self.ansi.partial_text()
                if self.ansi.screen.active and part.lstrip().startswith("[HP="):
                    self.ansi.screen.active = False
                self.state.feed_partial(part)
                self._triggers(part, partial=True)
                self.on_partial(self.ansi.cur)
            elif kind == "closed":
                self._on_closed(data)
        self._reconnect_tick()
        self._dead_line_tick()
        self._quiet_line_tick()
        self.safety.tick()
        self.hangup_items.tick()             # (every poll: it also notices a new connection before its first 'i')
        try:
            self.control.tick()
        except Exception as ex:
            self.log(f"Control folder: {ex}")
        try:
            self.web.tick()
        except Exception as ex:
            self.log(f"Phone page: {ex}")
        left = getattr(self, "_left_at", 0.0)
        if self.telnet.connected and not self._entered and (
                (not left and self.state.last_prompt > self._connected_at) or
                (self.state.view is not None and self.state.view.t > max(self._connected_at, left))):
            if left:
                self.log("Back in the realm — carrying on")
            if getattr(self, "_form_hold", None) and self._form_hold["seen"] and not self.training.me:
                self.end_form_hold("back in the realm")   # (your own train stats; auto-train ends its own)
            self._left_at = 0.0
            self._entered = True             # first HP prompt = we're in the game
            self._entered_at = time.time()
            # every time into the realm: read the quest flags again, in the first quiet moment (Dan, 2026-11-09)
            self.bot._abil_read = None
            self.bot._abil_late_said = 0
            menu = getattr(self, "_menu_realms", set())
            if menu == {"PVP"} and not self.settings.pvp_realm:
                # the menu only ever said PVP. One listing both ("Game 1 PVE", "Game 2 PVP") says nothing
                # about the realm you picked: the setting stays as it is
                self.settings.pvp_realm = True
                self.settings.save()
                self.log("This looks like a PvP realm — MudPilot will remind you if PvP hang-up is off")
            self._menu_realms = set()
            self.recorder.mark("entered", room=list(self.state.room) if self.state.room else None)
            self._back_in()
            self.hangup_items.on_entered()   # items a penalised hang-up dropped: hold the walk and look (0.8.201)
            self.hold_realm = False          # you went in: the next drop can come back in by itself
            self._held_said = False
            if (self.settings.game_entry_cmd or "").strip():
                self.log(f"Game entry command: {self.settings.game_entry_cmd}")
                self.bot.send_macro(self.settings.game_entry_cmd)
        # nothing game-side (blesses, abil checks, looks, par, events…) until you're in the realm —
        # at the BBS login those words would land in the username / password prompts
        hands_off = getattr(self.settings, "hands_off", False)
        if hands_off and not getattr(self, "_hands_off_said", False):
            self._hands_off_said = True
            self.lair_camp.note_stop("Hands off")    # camping never walks with Hands off (0.8.201)
            if self.bot.walking:
                self.bot.stop("Hands off — nothing automatic until you switch it back on")
            self.log("Hands off: MudPilot does nothing by itself (low-HP / PvP hang-ups still work)")
        elif not hands_off and getattr(self, "_hands_off_said", False):
            self._hands_off_said = False
            self.log("Hands off ended — automation back on")
        if hands_off and self.bot.walking:
            # a walk started while Hands off is on: nothing goes out — say so, it isn't stuck
            self.bot.status = "Hands off is on — nothing moves till you switch it off (the orange button)"
            if self.bot.ready("hands_off_walk", 60):
                self.log("Walking with Hands off on: no step goes out until you switch Hands off off")
        if hands_off:
            tme = getattr(self.training, "me", None)
            if tme and tme.get("phase") in ("form_wait", "form_read", "typing", "verify", "backout", "closing",
                                            "left_open"):
                # Hands off switched on mid train-stats form: finish (it's checked before SAVE) or back it out —
                # never leave the form half-typed with the keyboard held (0.8.201, bug hunt)
                try:
                    self.training._form_tick(time.time())
                except Exception as e:
                    self.log(f"Train stats: {e}")
            self.stats.tick()
            self.history.tick()
            self.phone.tick()
            self.timeline.tick()
            self.on_status()
            return got
        if self._entered or not self.telnet.connected:
            self.players.tick()
            self.responses.tick()
            self._default_task()
            self.remote.tick()
            self.events.tick()
        self.bosses.tick()
        self.bosshunt.tick()
        self.lair_camp.tick()
        self.gearmodes.tick()
        self.trips.tick()
        self.scrolls.tick()
        self.training.tick()
        self.comeback.tick()
        self.scheduler.tick()
        if self.state.last_prompt != getattr(self, "_tick_prompt_seen", None):
            self._tick_prompt_seen = self.state.last_prompt
            self.servertick.on_prompt()
        ep = getattr(self, "_enter_pending", None)
        if ep and now >= ep[0]:
            self._enter_pending = None
            if self.telnet.connected and not self._entered and not getattr(self, "hold_realm", False) \
                    and not self.form_held():
                parts = ep[1].replace("^m", "^M").split("^M")
                if len(parts) > 1 and parts[-1] == "":
                    parts = parts[:-1]
                for part in parts or [""]:
                    self.telnet.send_line(part)
                    self.recorder.tx(part, True)
                    self.on_sent(part, True)
        if self.telnet.connected and self._entered:
            self.servertick.tick()
            self.tracker.tick()
            self.leaderboard.tick()
            self.quests.tick()
        self.stats.tick()
        self.watchdog.tick()
        self.watchdog.after_tick()
        self.history.tick()
        self.phone.tick()
        self.partysync.tick()
        self.pathshare.tick()
        try:
            self.chestloot.tick()
            self.itemcharges.tick()
        except Exception as ex:
            if self.bot.ready("chest_charge_err", 300):
                self.log(f"Chest loot / item charges: {ex}")
        if getattr(self.state, "exp_line_new", False):
            self.state.exp_line_new = False
            self.remote.level_answer()                 # an @level that was waiting on 'exp'
        if getattr(self.state, "inv_new", False):
            self.state.inv_new = False
            self.remote.inv_answer()                   # an @have / @inv that was waiting on 'i'
            self.hangup_items.snapshot("i")            # what we carry, for after a hang-up (0.8.201)
            try:
                from .itemspells import carried
                got = carried(self.world, self.state.carrying or "")
                if got and got != getattr(self, "_item_spells_told", None):
                    self._item_spells_told = got
                    self.log("Item spells you carry (use them like any spell): "
                             + ", ".join(f"{a} = {sp} ({it})" for a, sp, it in got))
            except Exception:
                pass
        if getattr(self.state, "stat_new", False):
            self.state.stat_new = False
            self.remote.stat_answer()                  # an @lives that was waiting on 'st'
        self.timeline.tick()
        self.sync.tick()
        self.autotune.tick()
        r = self.state.room
        if r and r != getattr(self, "_saved_room", None) and time.time() - getattr(self, "_room_saved_at", 0) > 30:
            self._saved_room, self._room_saved_at = r, time.time()
            self.settings.last_room = f"{r[0]}/{r[1]}"
            self._save_quietly()
        if self.telnet.connected and self._entered:
            self._resume_tick()
            self._reinvite_tick()
            self._rejoin_tick()
            self._join_watch_tick()
            self.bot.tick()
        self.on_status()
        return got

    # ------------------------------------------------------------ dropped lines
    def _on_closed(self, why):
        """The line went down. If it wasn't us (hang-up, Disconnect), remember what the bot was doing
        so it can pick up again once auto-reconnect gets back in."""
        if not getattr(self, "_down_logged", False):
            self._down_logged = True
            self.log(f"Connection closed: {why}")
        self.show_down(f"Disconnected — {why}" if why else "Disconnected")
        if self.telnet is not None and hasattr(self, "timeline"):
            self.timeline.event("drop", why or "disconnected")
        if time.time() > getattr(self, "_closed_at_kept_until", 0):
            # (0.8.201, bug hunt: a hang-up sets _closed_at itself just before this event arrives — relog in 5 s /
            #  stay off N minutes; overwriting it made the relog wait a whole reconnect_delay)
            self._closed_at = time.time()
        self.recorder.mark("closed", why=why)
        self._await_reply_since = None
        if hasattr(self, "hangup_items"):
            self.hangup_items.note_drop()            # HP / fight as the line went (before in_combat is cleared)
        self.state.in_combat = False
        bot = self.bot
        self.remember_party()
        if self._want_connected and bot.walking and bot.path:
            self._drop_resume = {"path": bot.path, "loop": bot.loop, "after": bot.after_goto,
                                 "target": getattr(bot, "_goto_target", None) if bot.path.title.startswith("Go to ") else None}
        bot.walking = False
        if self._want_connected and self.settings.auto_reconnect and self.safety.may_reconnect():
            if not getattr(self, "_drop_started", 0):
                self._drop_started = time.time()
                self.watchdog.drops += 1
                self.history.note_drop()
                self._drop_alerted_long = False
                self.notify.send("drop", f"Line dropped ({why or 'closed'}) — reconnecting automatically")

    def _retry_delay(self):
        """Every reconnect_delay seconds (60), for as long as MudPilot is open — no back-off: when the internet
        comes back after an outage we want to be in within a minute, not up to 5 later."""
        return max(10, int(self.settings.reconnect_delay or 60))

    def _reconnect_tick(self):
        if not (self._want_connected and not self.telnet.connected and self.settings.auto_reconnect
                and self._closed_at and not getattr(self, "_reconnecting", False)
                and time.time() - self._closed_at > self._retry_delay() and self.safety.may_reconnect()):
            return
        addr = getattr(self, "_last_addr", None)
        if not addr:
            return
        self._reconnecting = True
        self._reconnect_tries = getattr(self, "_reconnect_tries", 0) + 1
        started = getattr(self, "_drop_started", 0)
        if started and time.time() - started > 600 and not getattr(self, "_drop_alerted_long", False):
            self._drop_alerted_long = True
            self.notify.send("drop", f"Still can't get back in after {int((time.time() - started) / 60)} min — "
                                     f"keeps trying every {self._retry_delay()} s")
        self.log(f"Auto-reconnecting (try {self._reconnect_tries})…")
        import socket
        import threading
        host, port = addr

        def work():
            try:
                sk = socket.create_connection((host, int(port)), timeout=15)   # off the UI thread: no freeze
                self._bg.put(lambda: self._reconnected(sk, host, port))
            except OSError as e:
                self._bg.put(lambda e=e: self._reconnect_failed(e))
        threading.Thread(target=work, daemon=True).start()

    def _reconnected(self, sk, host, port):
        self._reconnecting = False
        if not self._want_connected or self.telnet.connected:      # you disconnected meanwhile / already on
            try:
                sk.close()
            except OSError:
                pass
            return
        self._down_logged = False
        try:
            self.connect(host, port, sock=sk)
        except OSError as e:
            self._reconnect_failed(e)

    def _reconnect_failed(self, e):
        self._reconnecting = False
        self._closed_at = time.time()
        self.log(f"Reconnect failed: {e} — next try in {self._retry_delay()} s")

    def _quiet_line_tick(self):
        """pMUD's lesson: a line can die while nothing is being sent (idle at a rest spot), and a
        login can stall at the menu. Quiet for a minute in the realm → send a bare Enter; no answer
        in 20 s → drop and reconnect. Stuck at the menu/login with no progress for 45 s → reconnect."""
        if not self.telnet.connected or not self.settings.auto_reconnect:
            return
        now = time.time()
        last = max(getattr(self, "_last_data_at", 0), self._connected_at)
        if self._entered:
            if not getattr(self, "_probe_at", 0) and now - last > 60 and not self.state.pending:
                self._probe_at = now
                self.telnet.send_line("")
            elif getattr(self, "_probe_at", 0) and now - self._probe_at > 20 and last < self._probe_at:
                self._probe_at = 0
                self.log("No answer to a quiet-line check in 20 s — dropping it to reconnect")
                self.telnet.close()
                self._on_closed("quiet line, no answer")
        elif not getattr(self, "hold_realm", False) and now - last > 45 and now - self._connected_at > 45 \
                and not getattr(self, "_left_at", 0) and self.settings.auto_enter_realm \
                and now - getattr(self, "_user_sent_at", 0) > 120:
            # only a login that's stuck on its own: not you in train stats / the character editor (left on
            # purpose), not you browsing the BBS menus yourself, and not with auto-enter off
            self.log("Stuck at the login / menu for 45 s with nothing coming in — reconnecting")
            self._connected_at = now
            self.telnet.close()
            self._on_closed("login stalled")

    def _woke_up(self, gap):
        """The PC slept (or MudPilot was frozen) for a while: whatever's on screen is old news and the
        line is probably dead. Drop it and come back in fresh rather than act on a stale room."""
        self.log(f"MudPilot was paused for {gap / 60:.1f} min (the PC slept?) — reconnecting fresh")
        self.state.pending.clear()
        if self.telnet.connected and self.settings.auto_reconnect:
            self.telnet.close()
            self._on_closed("woke up after sleep")

    def _dead_line_tick(self):
        """Sent something and the board has said nothing for a long time: the line is dead even if
        Windows hasn't noticed (Wi-Fi blip, router reboot). Drop it so auto-reconnect can kick in.
        In a fight that's 20 s (pMUD) — rounds come every 5, so 20 s of nothing means you can't see the hits."""
        if self.state.in_combat and self.telnet.connected and self._entered and self.settings.auto_reconnect:
            last = getattr(self, "_last_data_at", 0)
            if last and time.time() - last > 20:
                self.log("Nothing from the board for 20 s in the middle of a fight — reconnecting")
                self.state.in_combat = False
                self.telnet.close()
                self._on_closed("silent during a fight")
                return
        t = getattr(self, "_await_reply_since", None)
        lim = int(self.settings.dead_line_secs or 0)
        if not (t and lim and self.telnet.connected and self._entered) or time.time() - t < lim:
            return
        why = f"no reply from the board for {lim} s"
        self.log(f"The line looks dead ({why}) — dropping it to reconnect")
        self.telnet.close()
        self._on_closed(why)

    def _back_in(self):
        """In the realm again. After a dropped line: tell your phone, then carry on."""
        self._reconnect_tries = 0
        if getattr(self, "_reinvite", None):
            self._reinvite_at = time.time() + 3      # let the room and prompt settle first
        started = getattr(self, "_drop_started", 0)
        self._drop_started = 0
        r = getattr(self, "_drop_resume", None)
        if started:
            mins = (time.time() - started) / 60
            what = f" — carrying on with {r['path'].title}" if r and self.settings.resume_after_reconnect else ""
            self.log(f"Back in after a dropped line ({mins:.0f} min){what}")
            self.notify.send("drop", f"Back in after {mins:.0f} min{what}", force=False)
        if r and self.settings.resume_after_reconnect:
            self._resume_at = time.time() + 4        # let the room and stats show first
        else:
            self._drop_resume = None

    def route_char(self):
        """Tell the map who's walking: class / race / alignment / abilities / cash (exit gates and tolls),
        and the party's classes and races when you lead (a gate has to let everyone through)."""
        w, st, cfg = self.world, self.state, self.settings
        def num(table, name):
            name = (name or "").lower()
            return next((k for k, v in (table or {}).items() if (v.get("Name") or "").lower() == name), None)
        me = (cfg.my_name or "").lower()
        p = self.players.data.get(me) if hasattr(self, "players") else None
        align = (cfg.char_alignment or getattr(st, "alignment", "") or (p or {}).get("alignment") or "").strip()
        party = [v for n, v in st.party.items() if n.lower() != me]
        leading = bool(party) and not getattr(self.bot.x, "_following", None)
        pdata = getattr(getattr(self, "players", None), "data", None) or {}
        pinfo = [pdata.get(n.lower()) or {} for n in st.party if n.lower() != me]
        w.danger_fn = self.bot.danger_room if int(getattr(cfg, "route_danger_pct", 60) or 0) > 0 else None
        pf = getattr(self.bot, "partyflags", None)
        w.char = {"class": num(w.classes, st.char_class or cfg.char_class),
                  "race": num(w.races, st.race or cfg.char_race),
                  "align": align, "abil": lambda a: (st.abil_value(a, "total") or (None,))[0],
                  # the party's answers to '@flags': quest gates have to let them through too (Evolution,
                  # 2026-11-21: 'ask Jorah transport' with three followers who'd said NeutralQuest not set)
                  "party_abil": pf.party_values if (leading and pf is not None) else None,
                  "party_abil_sig": pf.known_sig() if (leading and pf is not None) else (),
                  # every quest flag's value, for the route memory: a route worked out at DaoLordQuest 8 (the
                  # pyramid's arches throw you about) isn't the answer at 9 (Buddy, 2026-11-04)
                  "abil_sig": tuple(sorted((aid, v) for (src, aid), (v, _t) in st.abil_rows.items()
                                           if src == "granted")),
                  "wealth": (10 ** 12 if getattr(self.bot, "_bank_plan", False) else st.wealth),
                  "tolls": cfg.route_pay_tolls, "spell_traps": cfg.route_spell_traps,
                  "party_classes": [num(w.classes, v.get("class")) for v in party] if leading else [],
                  "party": bool(party),
                  # 0.8.201, bug hunt: race and alignment gates only checked the leader — a Seedy or half-ogre
                  # follower was refused and left behind. From Game Data → Players ('who' / look); unknown = skipped
                  "party_races": [num(w.races, m.get("race")) for m in pinfo] if leading else [],
                  "party_aligns": [m.get("alignment") or ("Neutral" if m.get("last_who") else "")
                                   for m in pinfo] if leading else [],
                  # (who those are, in the same order: a refusal names the member a gate stops — partyA D4, partyB P5)
                  "party_names": [str(n).split()[0] for n in st.party if n.lower() != me] if leading else []}
        # 0.8.190 (Dan): traps weighed by the weakest member's HP down to the hang-up line, locked doors by the
        # party's best picker / basher, guarded portals only with Combat on, the idol teleport only when every
        # follower is known to carry one
        b = self.bot
        try:
            w.char.update({"top_level": b.route_top_level() if leading else None,
                           "max_hp": b._weakest_hp(read_only=True) or None,
                           "max_hp_who": b._weakest_name(read_only=True) if leading else None,   # (partyA D4)
                           # (leading: only what every member carries counts against a room's damage — a 50-HP
                           #  follower was walked through 23 rooms of magma on the leader's phoenix feather: partyB P2)
                           "carried": (frozenset(b.held_items() or ()) & frozenset(b.party_carry() or ())) if leading
                                      else frozenset(b.held_items() or ()),
                           "hangup_pct": int(cfg.hangup_hp_pct or 0) if cfg.hangup_low_hp else 0,
                           "door_power": b.door_power(leading),
                           "combat": bool(cfg.auto_combat),
                           "party_have": b.party_carry() if leading else None})
        except Exception as ex:
            self.log(f"Routing: couldn't read the party's HP / doors / kit ({ex})")

    def remember_party(self):
        """Line dropping or hanging up: note who was following you, to invite them again once back in."""
        if getattr(self, "_reinvite", None):
            return                                   # already noted (hang-up, then the close)
        x = self.bot.x
        me = (self.settings.my_name or "").lower()
        names = [n for n in self.state.party if n.lower() != me]
        leading = getattr(x, "_own_party", False) or (names and not getattr(x, "_following", None))
        self._reinvite = names if (leading and names) else []

    def _join_watch_tick(self):
        """After inviting someone, resend @join if they haven't joined (up to 5 times, every 8 s). Dan: Revolution
        had no remotes when first invited, so the one @join did nothing and was never resent."""
        jw = getattr(self, "_join_watch", None)
        if not jw:
            return
        jc = (self.settings.invite_join_cmd or "").strip()
        now = time.time()
        for name in list(jw):
            if any(name.lower() == p.lower() for p in (self.state.party or {})):
                del jw[name]                             # joined — done
                continue
            w = jw[name]
            if now - w["t"] < 8:
                continue
            if w["tries"] >= 5 or not jc:
                self.log(f"{name} hasn't joined after {w['tries']} @join {'try' if w['tries'] == 1 else 'tries'} "
                         "— leaving it")
                del jw[name]
                continue
            w["tries"] += 1
            w["t"] = now
            self.log(f"{name} hasn't joined — @join again (try {w['tries']})")
            self.send(jc.replace("{name}", name), from_bot=True)

    def _late_joiner(self, text):
        """0.8.224 (Dan): an invite still pending when you disbanded — they accept it afterwards and the party you
        meant to break up is back. Someone joining from an invite sent before the disband, inside the pause: disband
        again (once)."""
        if time.time() >= getattr(self, "_party_hold_until", 0):
            return
        m = re.match(r"^(\w+) started to follow you\.?\s*$", text.strip())
        if not m:
            return
        t = getattr(self, "_invited_at", {}).get(m.group(1).lower(), 0)
        if not t or t >= getattr(self, "_party_hold_from", 0):
            return                               # (invited since — by you or an @invite: that one's meant)
        self._invited_at.pop(m.group(1).lower(), None)
        self.log(f"{m.group(1)} took an invite from before the disband — disbanding again")
        self.send("disband party", from_bot=True)

    DISBAND_FIRST_RE = re.compile(r"^You must disband your own party first", re.I)

    def _disband_then_join(self, text) -> bool:
        """'join Revolution' → "You must disband your own party first!": we'd started one (invited someone) —
        disband it and join (Buddy and Revolution kept inviting each other)."""
        js = getattr(self, "_join_sent", None)
        if js and time.time() - js[1] <= 6 and re.match(r"^You must be invited first", text.strip(), re.I):
            # the join didn't happen: their invite (a second later) has to be able to join (0.8.208, Buddy: 'join
            # Miserable' before the invite, then the invite and the @join were taken as 'joined just now')
            getattr(self.remote, "_joined", {}).pop(js[0].lower(), None)
            self._join_sent = None
            return False
        if not js or time.time() - js[1] > 6 or not self.DISBAND_FIRST_RE.match(text.strip()):
            return False
        self._join_sent = None
        if time.time() - getattr(self, "_disbanded_at", 0) < 15:
            return True                              # (did that a moment ago — 18 disband/joins in a second)
        self._disbanded_at = time.time()
        self.log(f"Disbanding my own party to join {js[0]}")
        self.send("disband party", from_bot=True)
        self.send(f"join {js[0]}", from_bot=True)
        return True

    def _rejoin_tick(self):
        """Back from a restart that stopped our leader (control.py): '/Leader @invite' every 15 s until we're in
        their party (players.py joins on their invite), then '/Leader @rego'. Gives up after 5 minutes."""
        rj = getattr(self, "_rejoin", None)
        if not rj:
            return
        now, ld = time.time(), rj["leader"]
        me = (self.settings.my_name or "").lower()
        others = [n.split()[0].lower() for n in (self.state.party or {}) if n.split()[0].lower() != me]
        moved_on = getattr(self.bot, "_user_goto_at", 0) > rj["t"] or \
            (now - rj["t"] > 60 and others and ld.lower() not in others and self.bot.x.leading())
        if moved_on:
            # you parted ways with them on purpose: your own Go to, or your own party now (Miserable PVE, 2026-11-06:
            # Skittles relogged after they'd split up — 10 minutes of '@where Skittles', then a walk off to 17/1773
            # right after your Go to Chancellor Annora)
            self._rejoin = None
            cb = getattr(self, "comeback", None)
            if cb is not None:
                cb.missing.pop(ld, None)
                if (getattr(cb, "fetch", None) or {}).get("name", "").lower() == ld.lower():
                    cb.fetch = None
                    if self.bot.walking and self.bot.path and self.bot.path.title.startswith("Go to ") \
                            and getattr(self.bot, "_user_goto_at", 0) < rj["t"]:
                        self.bot.stop(f"Not going after {ld}")
            self.log(f"Not rejoining {ld} — you've gone your own way")
            return
        if rj.get("ask_first") and not rj["tries"]:
            pass                                      # (the party list may be from before they dropped: ask first)
        elif any(n.split()[0].lower() == ld.lower() for n in (self.state.party or {})) or \
                (getattr(self.bot.x, "_following", "") or "").lower() == ld.lower():
            self._rejoin = None
            if rj.get("no_rego"):
                self.log(f"Back in {ld}'s party")
                return
            rs = getattr(self.bot, "resume", None) or {}
            if rs.get("target") and not rs.get("after"):
                # the walk to them was only to get back to them: nothing of our own to Rego (an @rego for us
                # would otherwise send us off to where they were — 0.8.115, Buddy: 'Rego carries on to 1/2342')
                self.bot.resume, self.bot.stop_note = None, ""
            self.send(f"/{ld} @rego", from_bot=True)
            self.log(f"Back in {ld}'s party — @rego sent")
            if rj.get("then"):
                self._drop_resume, self._resume_at = rj["then"], time.time() + 3   # now carry on with it
            return
        cb = getattr(self, "comeback", None)
        f = getattr(cb, "fetch", None) if cb else None
        if f and f.get("name", "").lower() == ld.lower():
            rj["t"] = max(rj["t"], now - 240)          # on our way to them: the clock waits
            return
        v = self.state.view
        here = {p.split()[0].lower() for p in (v.players if v else []) if p}
        can_walk = not getattr(self.bot, "dead_hold", 0) and not getattr(self.settings, "hands_off", False)
        if v and self.state.room and ld.lower() not in here and now - getattr(self, "_connected_at", now) > 6 \
                and can_walk and now - rj.get("went", 0) > 180 and not self.bot.walking and cb is not None:
            # (no @where at all while we can't walk to them — dead in the temple, Hands off — and once per 3 min
            # otherwise: Buddy, dead, @where'd Revolution every minute, 2026-10-30)
            # they're not in this room — 'invite' only works in the same room ("You don't see buddy here."):
            # ask where they are and walk there first (Buddy and Evolution, 2026-10-30, logged back in at 8/899
            # with Revolution at 8/16 and asked for an invite 22 times)
            rj["went"] = now
            self.log(f"{ld} isn't here — asking where they are and going to them before asking for an invite")
            cb._ask_where(ld)
            cb.fetch["no_invite"] = True
            return
        if now - rj["t"] > 300:
            self._rejoin = None
            if rj.get("then"):
                self.bot.resume = rj["then"]           # staying put: Rego (or @rego) carries on when you say
                self.log(f"Staying put — not walking {rj['then']['path'].title} without {ld} (Rego carries on)")
            self.log(f"{ld} didn't invite me back in 5 minutes — giving up (they're still stopped: @rego them)")
            self.on_alert(f"{ld} didn't invite me back — they may still be stopped")
            return
        if ld.lower() not in here:
            return          # an invite only works in the same room: ask only when they're here (Buddy, dead in the
                            # temple, asked Revolution every 15 s from a map away, 2026-10-30)
        if (not rj["tries"] or now - rj["asked"] >= 30) and now - getattr(self, "_connected_at", now) > 6:
            rj["asked"], rj["tries"] = now, rj["tries"] + 1
            self.send(f"/{ld} @invite", from_bot=True)
            if rj["tries"] % 4 == 1:
                self.send("par", from_bot=True)            # maybe we're already in (the leader re-invited)

    def _reinvite_tick(self):
        at = getattr(self, "_reinvite_at", 0)
        if not at or time.time() < at:
            return
        names = getattr(self, "_reinvite", None) or []
        if not names or not self.settings.reinvite_after_reconnect:
            self._reinvite, self._reinvite_at = [], 0
            return
        n = names.pop(0)
        self.log(f"Back in — inviting {n} again")
        self.send(f"invite {n}", from_bot=True)
        self._reinvited = {**getattr(self, "_reinvited", {}), n.lower(): (n, time.time())}   # (not in yet: comeback)
        self._reinvite_at = time.time() + 2.5 if names else 0

    def _resume_tick(self):
        hu = getattr(self, "_comeback_hp_until", 0)
        if hu:
            st = self.state
            if time.time() > hu or not st.max_hp or (st.hp_pct() >= int(self.settings.rest_below_hp or 0)
                                                     and not st.resting):
                self._comeback_hp_until = 0
                self.bot.release("reconnect")
        at = getattr(self, "_resume_at", 0)
        if not at or time.time() < at:
            return
        self._resume_at = 0
        r, self._drop_resume = getattr(self, "_drop_resume", None), None
        if not r or self.bot.walking or getattr(self, "hold_realm", False):
            return                                   # you've taken over, or a hang-up is holding us out
        self.bot.resume = r
        if self.bot.rego():
            self.bot.set_mode("auto")
            self._comeback_hold()

    def _comeback_hold(self):
        """(0.8.201, Dan — reconnect #5: back in after a drop, the loop walked on 4 s later at whatever HP the fight
        left, before the re-invited members were back.) The walk waits — resting meanwhile — until HP is over the
        rest line and the re-invited party is back in, for up to comeback_wait_mins; then it carries on."""
        cfg, st, now = self.settings, self.state, time.time()
        until = now + float(cfg.comeback_wait_mins or 5) * 60
        names = [n for n, t in (getattr(self, "_reinvited", None) or {}).values() if now - t < 120]
        names += [n for n in (getattr(self, "_reinvite", None) or []) if n not in names]
        if names and cfg.reinvite_after_reconnect and not getattr(self, "_regroup", None):
            self._regroup = {"names": names, "t": now, "asked": 0, "until": until}    # automation.regroup_hold
        if cfg.auto_rest and st.max_hp and st.hp_pct() < int(cfg.rest_below_hp or 0):
            self.bot.hold("reconnect", f"HP {st.hp_pct():.0f}% after a reconnect — resting first")
            self._comeback_hp_until = until

    def _line(self, segs):
        self.state.feed_line(segs)
        if self.state.continuation:
            # the wrapped end of somebody's chat line: shown, never read as game text, a command or a prompt
            if hasattr(self, "timeline"):
                self.timeline.line(plain(segs))
            masked = self._mask_secret(segs)
            self.on_line(masked)
            self.web.add_line(masked)
            return
        if self.ansi.screen.active and re.match(r"^\s*\[HP=", plain(segs)):
            self.ansi.screen.active = False          # back at a game prompt: the full-screen page is over
        text = plain(self.state.strip_prompt(segs))
        if hasattr(self, "timeline"):
            self.timeline.line(text)
        self.spellbook.feed_line(text)
        self.spelltune.feed_line(text)
        try:
            self.combatlog.feed_line(text)
        except Exception as ex:
            self.log(f"Combat summary: {ex}")
        self.comeback.feed_line(text)
        self.hangup_items.note_line(text)
        self._disband_then_join(text)
        self._late_joiner(text)
        self.msgrules.feed_line(text)
        for _x in (self.sounds, self.tracker, self.leaderboard, self.eightball, self.quests):
            try:
                _x.feed_line(text)
            except Exception as ex:
                self.log(f"{type(_x).__name__}: {ex}")
        self.bot.note_line(text)
        self._talk_slow_line(text)
        if self.state.char_class and self.state.char_class != self.settings.char_class:
            self.settings.char_class = self.state.char_class
        if re.search(r"you are now level|you have gained a level|attain level \d+", text, re.I):
            self.bot._spells_asked = False      # new spells may be available
        m = re.match(r"^\s*Name:\s+(\w+)", text)
        if m and "Lives/CP" in text and m.group(1) != self.settings.my_name:
            self.settings.my_name = m.group(1)
        self.safety.feed_line(text)
        self.clock.feed(text)
        mf = re.match(r"^(\w+) (?:started to follow|is now following) you\b", text.strip())
        if mf:
            # they joined — the game says so; no 'par' needed (Dan, 2026-10-30)
            self._followed_at = {**getattr(self, "_followed_at", {}), mf.group(1).lower(): time.time()}
            jw = getattr(self, "_join_watch", None)
            if jw:
                jw.pop(mf.group(1), None)
        mi = re.match(r"^You have invited (\w+) to (?:follow you|join)", text.strip())
        if mi and time.time() - getattr(self, "_invite_pending", 0) < 15:
            self._invite_pending = 0
            jc = (self.settings.invite_join_cmd or "").strip()
            fa = (getattr(self, "_followed_at", {}) or {}).get(mi.group(1).lower(), 0)
            if jc and time.time() - fa > 10:
                self.send(jc.replace("{name}", mi.group(1)), from_bot=True)
                # watch for the join; resend @join if they don't (Dan: Revolution had no remotes yet, so the
                # first @join did nothing and was never resent)
                self._join_watch = {**getattr(self, "_join_watch", {}),
                                    mi.group(1): {"t": time.time(), "t0": time.time(), "tries": 1}}
        if not self._entered:
            for tag in re.findall(r"\b(PVP|PVE)\b", text):
                self._menu_realms = getattr(self, "_menu_realms", set()) | {tag}   # decided on entering (above)
        if not self.settings.pvp_realm and re.search(r"^Server PvP Message:", text):
            self.settings.pvp_realm = True        # the game itself says PvP happens here
            self.settings.save()
            self.log("This looks like a PvP realm — MudPilot will remind you if PvP hang-up is off")
        self._check_echo(text)
        if self.EDITOR_RE.search(text) and (self._entered or getattr(self, "_form_hold", None)):
            if getattr(self, "_form_hold", None):
                self.note_form_seen()
            elif self._entered:
                self.begin_form_hold("character editor")   # a form we didn't send for: held all the same
                self.note_form_seen()
            if self._entered:
                self.leave_realm("character editor")
        if not self.telnet.connected:
            return
        self.players.feed_line(text)
        self.scripters.feed_line(text)
        self.gearwatch.feed_line(text)
        self.itemcharges.feed_line(text)
        self.responses.feed_line(text)
        self.chat.feed(text)
        self.remote.feed_line(text)
        self.events.feed_line(text)
        self._triggers(plain(segs))
        if MPSYNC_SCREEN_RE.match(text.strip()):
            return      # MudPilots talking to each other: read above, kept in Conversations, not on the screen (Dan)
        masked = self._mask_secret(segs)
        self.on_line(masked)
        self.web.add_line(masked)

    LOGIN_USER = r'type it in and press ENTER|Enter your User-?ID|^\s*User-?ID:|enter your user ?name|username or "new"|^\s*login:'
    LOGIN_PASS = r"Enter your password|^\s*Password:"

    def _login_triggers(self):
        """The User-ID / password prompts. BBS tab: paste your board's prompt lines to match them exactly;
        blank = MudPilot recognises the usual ones (incl. Paradigm's 'Please enter your username or "new":')."""
        if getattr(self, "_login_failed", False):
            return []                 # a wrong login is never retried by itself (lock-outs, typos in the wrong box)
        st = self.settings
        up = (st.user_prompt or "").strip()
        pp = (st.pass_prompt or "").strip()
        return [("login-user", {"match": re.escape(up) if up else self.LOGIN_USER, "send": "{user}", "once": True}),
                ("login-pass", {"match": re.escape(pp) if pp else self.LOGIN_PASS, "send": "{password}", "once": True})]

    def _realm_trigger(self):
        """Enter the realm at the MajorMUD menu — unless you hung up (Alt+H, low HP, PvP…) since MudPilot
        started; then the next connect stops at the menu so you can look before going in."""
        st = self.settings
        p = (st.enter_realm_prompt or "").strip()
        if not st.auto_enter_realm or not p or not (st.enter_realm_cmd or "").strip():
            return []
        if getattr(self, "hold_realm", False):
            if not getattr(self, "_held_said", False) and getattr(self, "_menu_seen", False):
                self._held_said = True
                self.log("At the MajorMUD menu — not entering by itself because you hung up last time. "
                         f"Type {st.enter_realm_cmd} to go in.")
            return []
        return [("enter-realm", {"match": re.escape(p), "send": st.enter_realm_cmd, "once": True})]

    def _realm_held(self, t) -> bool:
        """A logon step that would enter the realm is held too while hold_realm is on."""
        p = (self.settings.enter_realm_prompt or "").strip().lower()
        return bool(getattr(self, "hold_realm", False) and p and p in (t.get("match") or "").replace("\\", "").lower())

    def _logon_triggers(self):
        """BBS tab logon steps: when this text appears, type that (e.g. 'Please enter your selection:' -> P).
        Each fires once per connection unless 'every time' is ticked (then at most every 5 s)."""
        out = []
        for i, r in enumerate(self.settings.logon_steps or []):
            m = (r.get("match") or "").strip()
            if m and (r.get("send") or "").strip():
                out.append((f"logon-{i}", {"match": re.escape(m), "send": r["send"], "once": not r.get("every"),
                                           "every": bool(r.get("every"))}))
        return out

    def _triggers(self, text: str, partial=False):
        if self.form_held():
            return                     # (a trigger's reply would land in the train stats form's boxes)
        p = (self.settings.enter_realm_prompt or "").strip()
        if p and p.lower() in text.lower():
            self._menu_seen = True
        if not self._entered and not getattr(self, "_login_failed", False) and \
                re.search(r"invalid (?:username|user ?id|login|password)|incorrect password|login incorrect|"
                          r"bad password", text, re.I):
            self._login_failed = True
            st_ = self.settings
            if st_.username and st_.host:
                # a saved password the board says is wrong: forget it, so Connect asks again (Revolution's guess
                # was saved, and ☎ Connect kept logging in with it without showing the box)
                config.set_password(st_.username, None, st_.host)
                self.password = ""
            self.log("Login failed — the saved password was wrong and is forgotten; Connect will ask for it "
                     "(or File → Connect… → Import from MegaMUD).")
            self.on_alert("Login failed")
        trig = list(self._login_triggers()) + [x for x in self._logon_triggers() if not self._realm_held(x[1])] + \
            self._realm_trigger() + [(i, t) for i, t in enumerate(self.settings.triggers)
                                               if not re.search(r"\{user\}|\{password\}", t.get("send", ""))]
        for i, t in trig:
            if t.get("once") and i in self._fired_once:
                continue
            if t.get("every"):
                last = self._every_at.get(i, 0) if hasattr(self, "_every_at") else 0
                if time.time() - last < 5:
                    continue
            elif partial and not t.get("once"):
                continue  # repeating triggers only on complete lines
            try:
                if not re.search(t["match"], text, re.I | re.M):
                    continue
            except re.error:
                continue
            send = t.get("send", "")
            if i == "enter-realm":
                d = self.servertick.enter_delay()
                if d is not None and d > 0.05:
                    # pMUD's Enter on Tick: go in just after the server tick — a whole round before anything acts
                    self._fired_once.add(i)
                    self._enter_pending = (time.time() + d, send)
                    self.log(f"Entering the realm on the tick (in {d:.1f} s)")
                    continue
            if "{password}" in send:
                pw = self.password or config.get_password(self.settings.username, self.settings.host)
                if not pw:
                    continue
                send = send.replace("{password}", pw)
            if "{user}" in send:
                if not self.settings.username:
                    continue
                send = send.replace("{user}", self.settings.username)
            if t.get("every"):
                self._every_at = getattr(self, "_every_at", {})
                self._every_at[i] = time.time()
            else:
                self._fired_once.add(i)
            # Enter is added automatically; a MegaMUD-style ^M inside splits it into several lines
            parts = send.replace("^m", "^M").split("^M")
            if len(parts) > 1 and parts[-1] == "":
                parts = parts[:-1]
            for part in parts or [""]:
                self.telnet.send_line(part)
                self.recorder.tx("(hidden)" if "{password}" in t.get("send", "") else part, True)
                # show it on the MUD screen like any other command (never the password itself)
                self.on_sent("(password)" if "{password}" in t.get("send", "") else part, True)
            self.log(f"Trigger fired: {t['match'][:30]}… → {'(password)' if '{password}' in t.get('send','') else send}")

    # ------------------------------------------------------------ paths
    # ---- paths: parsed on the spot, matched to MME rooms in the background (cached on disk)
    CACHE_NAME = ".mudpilot-match.json"

    def _cache_path(self):
        return os.path.join(self.paths_dir, self.CACHE_NAME)

    def _load_cache(self) -> dict:
        import json
        try:
            with open(self._cache_path(), "r", encoding="utf-8") as f:
                c = json.load(f)
            wm = os.path.getmtime(self.world_path) if os.path.exists(self.world_path) else 0
            ok = abs(c.get("world_mtime", 0) - wm) < 1 and c.get("resolver") == RESOLVER_VERSION
            return c.get("files", {}) if ok else {}
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        import json
        try:
            wm = os.path.getmtime(self.world_path) if os.path.exists(self.world_path) else 0
            tmp = self._cache_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"world_mtime": wm, "resolver": RESOLVER_VERSION, "files": self._match_cache}, f)
            os.replace(tmp, self._cache_path())
        except OSError:
            pass

    @staticmethod
    def _sig(fn):
        try:
            st = os.stat(fn)
            return [int(st.st_mtime), st.st_size]
        except OSError:
            return [0, 0]

    def _apply_cached(self, mp) -> bool:
        c = self._match_cache.get(os.path.basename(mp.filename))
        if not c or c.get("sig") != self._sig(mp.filename) or len(c.get("rooms", [])) != len(mp.steps) and c.get("ok"):
            return False
        mp.resolved, mp.resolve_note = bool(c.get("ok")), c.get("note", "")
        if mp.resolved:
            for stp, (r0, r1, d0, d1) in zip(mp.steps, c["rooms"]):
                stp.room, stp.dest = (r0, r1), (d0, d1)
                self._learn_step(stp)
        return True

    def _learn_step(self, stp):
        """A path step MME has no exit for (the path bridged it): put it on the map."""
        r = self.world.room(stp.room)
        if not r or not stp.dest:
            return
        if any(ex.to == stp.dest for ex in r.exits.values()):
            return
        self.world.add_learned(stp.room, stp.move, stp.dest)

    def _remember_match(self, mp):
        rooms = [[s.room[0], s.room[1], s.dest[0], s.dest[1]] for s in mp.steps] \
            if mp.resolved and all(s.room and s.dest for s in mp.steps) else []
        self._match_cache[os.path.basename(mp.filename)] = {"sig": self._sig(mp.filename), "ok": bool(rooms),
                                                            "note": mp.resolve_note, "rooms": rooms}

    def load_saved_paths(self):
        """Read every saved path; reuse cached room matches, match the rest in the background."""
        self.paths = []
        os.makedirs(self.paths_dir, exist_ok=True)
        self._match_cache = self._load_cache()
        todo = []
        for f in find_mp_files(self.paths_dir):
            try:
                mp = read_mp(f)
            except (OSError, ValueError):
                continue
            mp.filename = f
            self.paths.append(mp)
            if self.world.loaded and not self._apply_cached(mp):
                todo.append(mp)
        if todo:
            self._match_in_background(todo, "Matching paths to MME rooms")

    def _match_in_background(self, mps, label, then=None):
        import threading
        self.paths_busy = (0, len(mps), label)
        world = self.world

        def work():
            for i, mp in enumerate(mps, start=1):
                try:
                    resolve_path(world, mp)
                except Exception:
                    mp.resolved = False
                self.paths_busy = (i, len(mps), label)
            self._bg.put(lambda: self._matched(mps, then))
        threading.Thread(target=work, daemon=True).start()

    def _matched(self, mps, then=None):
        for mp in mps:
            self._remember_match(mp)
        self._save_cache()
        self.save_learned()
        self.paths_busy = None
        self.on_paths_changed()
        if then:
            then()

    def import_paths(self, files: list[str], on_done=None):
        """Copy .mp files into this board's paths folder and match them to MME rooms in the
        background. on_done(imported, matched, errors) runs on the main thread when finished."""
        import shutil
        import threading
        os.makedirs(self.paths_dir, exist_ok=True)
        world, dest_dir = self.world, self.paths_dir
        self.paths_busy = (0, len(files), "Importing paths")

        def work():
            import filecmp
            done, errs, used = [], [], {}
            for i, f in enumerate(files, start=1):
                try:
                    mp = read_mp(f)
                    base = os.path.basename(f)
                    # MegaMUD folders can hold two different files with the same name (Default\ and a
                    # character's own folder): keep both instead of the second overwriting the first
                    prev = used.get(base.lower())
                    if prev and os.path.abspath(prev) != os.path.abspath(f):
                        try:
                            same = filecmp.cmp(prev, f, shallow=False)
                        except OSError:
                            same = False
                        if same:
                            self.paths_busy = (i, len(files), "Importing paths")
                            continue
                        stem, ext = os.path.splitext(base)
                        n = 2
                        while f"{stem}_{n}{ext}".lower() in used:
                            n += 1
                        base = f"{stem}_{n}{ext}"
                    used[base.lower()] = f
                    dest = os.path.join(dest_dir, base)
                    if os.path.abspath(dest) != os.path.abspath(f):
                        shutil.copy2(f, dest)
                    mp.filename = dest
                    if world.loaded:
                        resolve_path(world, mp)
                    done.append(mp)
                except (OSError, ValueError) as e:
                    errs.append(f"{os.path.basename(f)}: {e}")
                except Exception as e:      # a bad path never stops the rest
                    errs.append(f"{os.path.basename(f)}: {e}")
                self.paths_busy = (i, len(files), "Importing paths")
            self._bg.put(lambda: self._imported(done, errs, on_done))
        threading.Thread(target=work, daemon=True).start()

    def _imported(self, done, errs, on_done):
        names = {os.path.basename(mp.filename).lower() for mp in done}
        self.paths = [p for p in self.paths if os.path.basename(p.filename).lower() not in names] + done
        for mp in done:
            self._remember_match(mp)
        self._save_cache()
        self.paths_busy = None
        res = sum(1 for mp in done if mp.resolved)
        self.log(f"Imported {len(done)} path(s), {res} matched to MME rooms")
        self.on_paths_changed()
        if on_done:
            on_done(len(done), res, errs)

    # ---- MegaMUD's known rooms (Rooms.md) for the Goto window
    @property
    def rooms_md_path(self):
        return os.path.join(config.board_dir(self.settings.board), "Rooms.md")

    def import_rooms_md(self, src) -> int:
        import shutil
        from .megamud_files import read_rooms_md
        rows = read_rooms_md(src)
        if rows:
            os.makedirs(os.path.dirname(self.rooms_md_path), exist_ok=True)
            if os.path.abspath(src) != os.path.abspath(self.rooms_md_path):
                shutil.copy2(src, self.rooms_md_path)
        return len(rows)

    @staticmethod
    def _open_world(path):
        """Open the board's map data — and fix it if the file got damaged (a crash or a power cut mid-write):
        put the damaged one aside, fall back to the last good copy (or the copy MudPilot ships), and carry on."""
        import glob
        import sqlite3
        for junk in glob.glob(glob.escape(path) + ".*.tmp*") + glob.glob(glob.escape(path) + ".*.new"):
            try:
                if time.time() - os.path.getmtime(junk) > 3600:
                    os.remove(junk)                  # left by a re-import that was cut off (MudPilot closed)
            except OSError:
                pass
        for attempt in range(3):
            try:
                return WorldDB(path)
            except sqlite3.DatabaseError as ex:
                msg = str(ex).lower()
                if any(w in msg for w in ("malformed", "not a database", "no such table", "file is encrypted")):
                    break                            # really damaged
                if attempt == 2:
                    raise                            # locked / busy (antivirus, OneDrive): don't throw a good file away
                time.sleep(1.0)
        bad = f"{path}.damaged"
        try:
            os.replace(path, bad)
        except OSError:
            pass
        old = path + ".old"
        if os.path.exists(old):
            try:
                shutil.copy2(old, path)
                return WorldDB(path)
            except (OSError, sqlite3.DatabaseError):
                pass
        try:
            config.install_bundled_boards()
            return WorldDB(path)
        except (OSError, sqlite3.DatabaseError):
            return WorldDB(path + ".missing")

    def _world_note(self):
        """Say which map data is in use — and flag one older than this MudPilot."""
        from .worlddb import DATA_VERSION
        w = self.world
        if not getattr(w, "loaded", True) or not w.rooms:
            return
        v = getattr(w, "version", 0)
        self.log(f"Map data: board {self.settings.board}, {len(w.rooms):,} rooms, data v{v}, "
                 f"{getattr(w, 'action_exits', 0)} exit actions (pull lever etc.)")
        if v < DATA_VERSION:
            src = self._mme_source()
            if src and not getattr(self, "_reimporting", False):
                self._reimporting = True
                self.log(f"Map data is older than this MudPilot (v{v}) — re-importing {os.path.basename(src)} in the "
                         "background so routes through hidden exits work")
                import threading
                out = self.world_path

                def work():
                    try:
                        tmp = f"{out}.{os.getpid()}.new"
                        WorldDB.import_mdb(src, tmp)
                        os.replace(out, out + ".old") if os.path.exists(out) else None
                        os.replace(tmp, out)
                        self._bg.put(lambda: (self.log("Map data re-imported — reloading"), self.reload_world()))
                    except Exception as ex:
                        self._bg.put(lambda ex=ex: self.log(f"Re-import failed ({ex}) — use File → Import MME database"))
                    finally:
                        self._reimporting = False
                threading.Thread(target=work, daemon=True).start()
            else:
                self.log(f"Map data is older than this MudPilot (v{v}, needs v{DATA_VERSION}) — some routes won't be "
                         "found. Use File → Import MME database again to update it.")
                self.on_alert("Map data is out of date — File → Import MME database")

    def _mme_source(self):
        """The MME file this board was imported from, if it's still on this PC."""
        import sqlite3
        try:
            con = sqlite3.connect(self.world_path)
            name = (con.execute("SELECT v FROM meta WHERE k='source'").fetchone() or [""])[0]
            con.close()
        except sqlite3.Error:
            return None
        if not name:
            return None
        for d in (os.path.join(config.APP_DIR, "MME data"), config.board_dir(self.settings.board), config.DATA_DIR):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return None

    @staticmethod
    def _rooms_md_fix(w, name, cands, mon_ix):
        """The right room for a Rooms.md entry whose number is missing, glued or disagrees with its hash, or None.
        'Choira Pyromancer-15 1168': the number is the Temple of Fire inside the Crimson Fortress (key 1077), but the
        hash is 15/1165, the Lava Pool Choira stands in. 'Stone Giant Chieftain-1601095': no space in the number, and
        the hash also fits 2/10 Top of Mountain Stair near Annora — that one was walked to (Revolution, 2026-11-20).
        A hash candidate the named monster stands, spawns or lairs in wins; then a glued number that spells one."""
        if not cands:
            return None
        base = re.sub(r"[\s+\-]*\d[\d /]*$", "", name or "").strip()
        nm = re.sub(r"\s*\([^)]*\)\s*$", "", base).strip().lower()
        if nm:
            if not mon_ix:
                for num, m_ in (getattr(w, "monsters", None) or {}).items():
                    mon_ix.setdefault((m_.get("name") or "").strip().lower(), []).append(num)
            lives = set()
            for num in mon_ix.get(nm, ()):
                try:
                    lives |= {tuple(k) for k, _how in w.monster_rooms(num)}
                except Exception:
                    pass
            hit = [k for k in cands if k in lives]
            if hit:
                return hit[0]
        g = re.search(r"(\d{4,9})\s*$", name or "")
        if g:
            d = g.group(1)
            hit = [k for k in cands if d.startswith(str(k[0])) and d[len(str(k[0])):].isdigit()
                   and int(d[len(str(k[0])):]) == k[1]]
            if len(hit) == 1:
                return hit[0]
        return None

    # a Rooms.md name's room number: 'Name-17 377', 'Name - 13 2995', 'Name-16  2268', 'Name-12-1671', 'Name 15/1054'
    MD_NUM = r"[\s+\-]*(\d{1,3})(?:[ /]+|-)(\d{1,5})\s*$"
    MD_STOP = {"of", "the", "and", "a", "an", "to", "in", "outside", "near"}

    @classmethod
    def _md_words(cls, s):
        s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
        return {x for x in re.findall(r"[a-z0-9']+", s) if x not in cls.MD_STOP and not x.isdigit()}

    @classmethod
    def _md_like(cls, a, b):
        A, B = cls._md_words(a), cls._md_words(b)
        return len(A & B) / len(A | B) if A and B else 0.0

    @staticmethod
    def _one_digit(a, b):
        """a and b differ by one digit: changed, added, dropped, or two next to each other swapped."""
        if a == b:
            return False
        if len(a) == len(b):
            d = [i for i in range(len(a)) if a[i] != b[i]]
            return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
        if abs(len(a) - len(b)) != 1:
            return False
        lo, hi = (a, b) if len(a) < len(b) else (b, a)
        return any(hi[:i] + hi[i + 1:] == lo for i in range(len(hi)))

    @classmethod
    def _rooms_md_key(cls, w, raw, h, mon_ix, claimed, group=None, gmaps=None):
        """(name, room, by_number) for one Rooms.md entry, or None. Its number is trusted when the hash or the room's
        name backs it; when neither does, the number is a typo more often than not (an audit of the shared Rooms.md,
        Dan 2026-11-21: 'Outside Master Assassin-8 1262' is 7/1262, 'Diamond Mine (Devil Fiend area)-6 1791' is
        15/1791, 'Crumbling Temple, Sphinx Statue-12 2242' is 12/2442, 'Swamp Ridge Path Crossroads-6 133' is 6/178).
        With no number, the hash room whose name fits best — 'Blue Tower, Weapons (sharp)' is 1/3304, not the
        forest trail 13/130 that shares its hash."""
        if not w.loaded:
            return None
        cands = list(w.by_hash.get(h, []))
        m = re.search(cls.MD_NUM, raw or "")
        name = (raw[:m.start()].strip() if m else raw) or raw
        num = (int(m.group(1)), int(m.group(2))) if m else None
        rm = w.room(num) if num else None

        def free(k):                      # a fix never lands on a room another entry names by number
            return k and not (claimed.get(k, set()) - {name.strip().lower()})

        gm = (gmaps or {}).get(group) or {}

        def order(k):                     # ties: the map the entry's area mostly uses, then the room nearest the number
            return (-gm.get(k[0], 0), abs(k[1] - num[1]) if num and k[0] == num[0] else 10 ** 6)

        def fix(numbered_room):
            named = sorted((k for k in cands if w.room(k) and w.room(k).name.lower() == name.lower()),
                           key=lambda k: (not free(k),) + order(k))
            if named:
                return named[0]
            k = cls._rooms_md_fix(w, raw, cands, mon_ix)
            if free(k):
                return k
            if num:
                typo = [k for k in cands if k[1] == num[1] and free(k)]   # the map number wrong, the room right
                if len(typo) == 1:
                    return typo[0]
                # one digit off on the same map: 12/2242 for 12/2442, 17/569 for 17/1569, 16/1617 for 16/1517
                typo = [k for k in cands if k[0] == num[0] and cls._one_digit(str(k[1]), str(num[1])) and free(k)]
                if len(typo) == 1:
                    return typo[0]
            score = sorted(((cls._md_like(name, w.room(k).name), k) for k in cands if w.room(k) and free(k)),
                           key=lambda x: (-x[0],) + order(x[1]))
            if score:
                best, k = score[0]
                base = cls._md_like(name, numbered_room.name) if numbered_room else -1
                if numbered_room is None and (best > 0 or len(score) == 1):
                    return k
                if numbered_room is not None and best >= 0.5 and best >= base + 0.3:
                    return k
            return None
        if rm:
            if num in cands or rm.name.lower() == name.lower() or not cands:
                return name, num, True
            if cls._rooms_md_fix(w, raw, [num], mon_ix) == num:
                # the named monster lives in the numbered room: that backs it too (0.8.221, bug hunt: 'Thief Spirit
                # (11)-1 2275' went to 1/2272 Marble Chamber by the one-digit rule; the spirit is in 1/2275's tomb)
                return name, num, True
            return name, fix(rm) or num, True
        if not cands:
            return None
        k = fix(None) or min(cands, key=lambda k: (not free(k),) + order(k))
        g = re.search(r"[\s+\-]*(\d{4,9})\s*$", name)
        if g and name[:g.start()].strip() and g.group(1) in (f"{k[0]}{k[1]}", f"{k[0]}0{k[1]}"):
            name = name[:g.start()].strip()   # 'Stone Giant Chieftain-1601095' → the name alone
        return name, k, False

    def known_rooms(self) -> list:
        """[(area, name, (map, room))] — MegaMUD's Rooms.md if imported, plus every path's start/end."""
        from .megamud_files import read_rooms_md
        out, seen, mon_ix = [], set(), {}
        w = self.world
        if os.path.exists(self.rooms_md_path):
            try:
                rows = read_rooms_md(self.rooms_md_path)
            except OSError:
                rows = []
            numbered = {}
            # rooms another entry names by number: a fixed-up entry never lands on one ('Darken Beast Lord-17 831' and
            # 'Outside Darken Beast Lord-17 2812' have each other's hash — moving one would hide the other)
            claimed, gmaps = {}, {}
            for r in rows:
                m_ = re.search(self.MD_NUM, r["name"] or "")
                if m_:
                    claimed.setdefault((int(m_.group(1)), int(m_.group(2))), set()).add(
                        r["name"][:m_.start()].strip().lower())
                    gm_ = gmaps.setdefault(r["group"], {})
                    gm_[int(m_.group(1))] = gm_.get(int(m_.group(1)), 0) + 1
            for r in rows:
                if re.search(self.MD_NUM, r["name"] or ""):
                    got = self._rooms_md_key(w, r["name"], r["hash"], mon_ix, claimed, r["group"], gmaps)
                    if got:
                        numbered[got[0].lower()] = got[1]
            for r in rows:
                got = self._rooms_md_key(w, r["name"], r["hash"], mon_ix, claimed, r["group"], gmaps)
                if not got:
                    continue
                name, key, by_num = got
                if not by_num:
                    cands = list(w.by_hash.get(r["hash"], []))
                    nk = numbered.get(name.lower())
                    if nk and (nk in cands or w.room(nk) and w.room(key) and w.room(nk).name == w.room(key).name):
                        key = nk                     # the same place listed with its number elsewhere: one entry
                if (key, name.lower()) not in seen:
                    seen.add((key, name.lower()))
                    out.append((r["group"] or "Other", name, key))
        have = {k for _g, _n, k in out}
        # one entry per room number: Rooms.md listing the same place twice (two names, or a twin's hash) shows once
        uniq, by_key = [], {}
        for g_, n_, k_ in out:
            if k_ in by_key:
                continue
            by_key[k_] = True
            uniq.append((g_, n_, k_))
        out = uniq
        pl = self.places()
        if out:
            return self._apply_places(out, pl)
        for mp in self.paths:
            for grp, lbl, key in ((mp.start_group, mp.start_label, mp.steps[0].room if mp.steps else None),
                                  (mp.end_group, mp.end_label, mp.steps[-1].dest if mp.steps else None)):
                if not key or not lbl:
                    continue
                mk = re.search(r"[\s+\-]*(\d{1,3})[ /](\d{1,5})\s*$", lbl)
                if mk and (int(mk.group(1)), int(mk.group(2))) in w.rooms:
                    # the label says which room it is ('…(Below Pharoah)-12 2085'): that beats a MegaMUD hash
                    # matched to a look-alike (the pyramid's twins gave 12/1808 and 12/1915 too)
                    key = (int(mk.group(1)), int(mk.group(2)))
                    lbl = lbl[:mk.start()].strip() or lbl
                else:
                    lbl = re.sub(rf"[\s-]*(?:{key[0]}[ /])?{key[1]}\s*$", "", lbl).strip() or lbl   # 'Bank-1 297' → 'Bank'
                if key in have or (lbl.lower(), key) in seen:
                    continue                     # one entry per room (Rooms.md name wins)
                have.add(key)
                seen.add((lbl.lower(), key))
                out.append((grp or "From paths", lbl, key))
        return self._apply_places(out, pl)

    # ---- your own Goto places: renames, removals and rooms you added (on top of MegaMUD's Rooms.md)
    @property
    def places_file(self):
        return os.path.join(config.board_dir(self.settings.board), "goto_places.json")

    def places(self) -> dict:
        import json
        try:
            with open(self.places_file, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        return {"renamed": dict(d.get("renamed") or {}), "removed": list(d.get("removed") or []),
                "added": list(d.get("added") or [])}

    def save_places(self, d):
        import json
        os.makedirs(os.path.dirname(self.places_file), exist_ok=True)
        tmp = self.places_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, self.places_file)

    def _apply_places(self, out, pl):
        rm, rn = set(pl["removed"]), pl["renamed"]
        res, keys = [], set()
        for g_, n_, k_ in out:
            ks = f"{k_[0]}/{k_[1]}"
            if ks in rm:
                continue
            res.append((g_, rn.get(ks, n_), k_))
            keys.add(tuple(k_))
        for a in pl["added"]:
            try:
                g_, n_, m_, r_ = a
            except (TypeError, ValueError):
                continue
            k_ = (int(m_), int(r_))
            if k_ not in keys and f"{m_}/{r_}" not in rm:
                res.append((g_ or "My places", rn.get(f"{m_}/{r_}", n_), k_))
                keys.add(k_)
        return res

    def place_rename(self, key, name):
        d = self.places()
        d["renamed"][f"{key[0]}/{key[1]}"] = name
        self.save_places(d)

    def place_remove(self, key):
        d = self.places()
        ks = f"{key[0]}/{key[1]}"
        if ks not in d["removed"]:
            d["removed"].append(ks)
        d["added"] = [a for a in d["added"] if f"{a[2]}/{a[3]}" != ks]
        self.save_places(d)

    def place_add(self, key, name, group="My places"):
        d = self.places()
        ks = f"{key[0]}/{key[1]}"
        d["removed"] = [x for x in d["removed"] if x != ks]
        d["added"] = [a for a in d["added"] if f"{a[2]}/{a[3]}" != ks] + [[group, name, key[0], key[1]]]
        d["renamed"].pop(ks, None)
        self.save_places(d)

    def save_path(self, mp: MPath, filename: str):
        os.makedirs(self.paths_dir, exist_ok=True)
        dest = os.path.join(self.paths_dir, filename)
        write_mp(mp, dest)
        mp.filename = dest
        self.paths = [p for p in self.paths if p.filename != dest] + [mp]

    def _default_task(self):
        """General tab 'Begin looping at': once per connection, as soon as we know where we are."""
        st = self.settings
        if not self._task_done and st.default_task == "roam" and self.telnet.connected and self.state.room \
                and not self.bot.walking:
            self._task_done = True
            self.log("Default task: begin auto-roaming")
            self.bot.x.start_roam()
            return
        if self._task_done or st.default_task != "loop" or not st.default_loop or not self.telnet.connected:
            return
        if not self.state.room or self.bot.walking:
            return
        self._task_done = True
        mp = next((p for p in self.paths if p.title == st.default_loop), None)
        if not mp:
            self.log(f"Default task: no loop named '{st.default_loop}'")
            return
        self.log(f"Default task: begin looping '{mp.title}'")
        if mp.resolved and mp.steps[0].room and not any(x.room == self.state.room for x in mp.steps):
            self.bot.goto_bg(mp.steps[0].room, then=mp)
        else:
            self.bot.start_path(mp, loop=True)

    # ------------------------------------------------------------ spells
    def _got_spells(self, rows):
        st = self.settings
        self.spellbook.refused.clear()
        shorts = [r[0] for r in rows]
        st.known_spells = shorts
        st.known_spell_rows = rows
        st.known_spells_at = time.time()
        try:
            st.save()
        except OSError:
            pass
        n = len([s for s in self.known_spell_dicts() if self._is_attack(s)])
        missing = self.unknown_spells()
        self.log(f"Spell list read: {len(shorts)} spells, {n} attack spells"
                 + (f" (not in MME data: {', '.join(missing)})" if missing else ""))

    @staticmethod
    def _is_attack(sp):
        from .spells import is_attack_spell, spell_kind
        return is_attack_spell(sp) and spell_kind(sp) is not None

    def known_spell_dicts(self):
        out = []
        rows = self.settings.known_spell_rows or [[s, "", -1, -1] for s in self.settings.known_spells or []]
        for short, name, lvl, mana in rows:
            sp = self.spellbook.resolve(short, name, lvl, mana)
            if sp:
                out.append(sp)
        return out

    def unknown_spells(self):
        """Spells in the game's list that this board's MME data doesn't have."""
        return [r[0] for r in (self.settings.known_spell_rows or []) if not self.spellbook.resolve(*r)]

    def spell_candidates(self):
        """Attack spells the bot may use: the game's spell list (or, until it's read, what
        the class can learn at this level), plus anything listed by hand."""
        from .spells import class_spells
        cands = {sp["Number"]: sp for sp in self.known_spell_dicts()}
        if not cands:
            cls = next((k for k, v in self.world.classes.items()
                        if v.get("Name", "").lower() == (self.state.char_class or self.settings.char_class).lower()), 0)
            if cls:
                for sp in class_spells(self.world, cls, self.state.level or self.settings.char_level):
                    cands[sp["Number"]] = sp
        for short in self.settings.attack_spells or []:
            sp = self.spellbook.find(short)
            if sp:
                cands[sp["Number"]] = sp
        return [sp for sp in cands.values() if self._is_attack(sp) and not self.spell_too_low(sp)]

    # a level-50+ full caster (Mage, Druid, Priest) never casts an attack spell below this level (Dan, 2026-11-14:
    # "A level 50+ caster should never under any circumstance cast a level 2 spell" — Revolution casting vine strike)
    LOW_SPELL_FLOOR, LOW_SPELL_FROM = 30, 50     # (Dan: "even 20 is brutally low")

    def full_caster(self) -> bool:
        """A class with the game's full magic (MageryLVL 3: Mage, Druid, Priest), not a hybrid."""
        cname = (self.state.char_class or self.settings.char_class or "").strip().lower()
        for v in (getattr(self.world, "classes", None) or {}).values():
            if (v.get("Name") or "").lower() == cname:
                return int(v.get("MageryLVL") or 0) >= 3
        return cname in ("mage", "druid", "priest")

    def spell_too_low(self, sp) -> bool:
        """A low-level attack spell a level-50+ full caster has no business casting (vine strike, magic missile)."""
        lvl = int(self.state.level or self.settings.char_level or 0)   # (0.8.201, bug hunt: the game's level wins)
        return bool(sp) and lvl >= self.LOW_SPELL_FROM and self.full_caster() and             int(sp.get("ReqLevel") or 0) < self.LOW_SPELL_FLOOR

    @property
    def paths_dir(self) -> str:
        return config.paths_dir(self.settings.board)

    def switch_board(self):
        """Load the MME data, paths and boss timers for settings.board."""
        self.world_path = config.world_path(self.settings.board)
        self.state.candidates = []
        self.state.view = None
        self.reload_world()               # also reloads this board's paths
        self.bosses.load()
        self.bosses.on_change()
        self.players.load()
        self.players.on_change()

    # ---------------------------------------------------------------- ways MME's map doesn't have
    @property
    def learned_file(self):
        return os.path.join(config.board_dir(self.settings.board), "learned_exits.json")

    def _board_fixes(self):
        """Ways MME gets wrong, from walking them for real (board_fixes.py) — only where they fit this map."""
        try:
            from . import board_fixes
            from .lair_camp import realm_of
            n = board_fixes.apply(self.world, realm_of(self))     # Paradigm's walked fixes, on Paradigm only
            if n:
                self.log(f"Map: {n} fixed way(s) MME gets wrong (pyramid level 3 with the golden lion key)")
        except Exception as ex:
            self.log(f"Map fixes: {ex}")

    @property
    def forgotten_file(self):
        return os.path.join(config.board_dir(self.settings.board), "forgotten_exits.json")

    def _load_forgotten(self):
        """0.8.224 (Dan, logEVO D): wrong learned ways that failed when walked stay forgotten across sessions — path
        bridging re-learned the same 10/179 NE every start, a failed step and a replan (and an 8 s freeze) each time."""
        import json
        try:
            with open(self.forgotten_file, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = []
        got = set()
        for r in rows if isinstance(rows, list) else []:
            try:
                src, mv, dst = r
                got.add((tuple(src), str(mv).lower(), tuple(dst)))
            except (TypeError, ValueError):
                continue
        self.world.forgotten = set(getattr(self.world, "forgotten", set()) or set()) | got
        self._forgotten_saved = len(self.world.forgotten)

    def _save_forgotten(self):
        import json
        fg = getattr(self.world, "forgotten", None) or set()
        if len(fg) == getattr(self, "_forgotten_saved", 0):
            return
        rows = sorted([list(s), m, list(d)] for s, m, d in fg)[-500:]
        os.makedirs(os.path.dirname(self.forgotten_file), exist_ok=True)
        tmp = self.forgotten_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, self.forgotten_file)
        self._forgotten_saved = len(fg)

    def _load_learned(self):
        import json
        try:
            self._load_forgotten()
        except Exception as ex:
            self.log(f"Map: forgotten ways: {ex}")
        try:
            with open(self.learned_file, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = []
        from .worlddb import clean_move
        good = []
        for r in rows:
            try:
                src, mv, dst = r
            except (TypeError, ValueError):
                continue
            mv2 = clean_move(mv)
            if mv2 and self.world.look_alike(src) and self.world.look_alike(dst):
                mv2 = ""                         # learned between two look-alike rooms: a guess, not a fact
            if mv2 and self.world.limited_use_item(mv2):
                mv2 = ""                         # 'use silverm': spends a limited-use item — never a way to walk
            if mv2:                              # '@party go vortex' → 'go vortex'; other @ / chat lines dropped
                good.append([list(src), mv2, list(dst)])
        n = sum(1 for src, mv, dst in good if self.world.add_learned(tuple(src), mv, tuple(dst)))
        self.world.learned = good
        self._learned_saved = len(good)
        if good != rows:
            self._learned_saved = -1
            try:
                self.save_learned()              # write the cleaned list back
            except OSError:
                pass
        if n:
            self.log(f"Map: {n} ways MME doesn't list, learned from your paths and walking")

    def save_learned(self):
        import json
        try:
            self._save_forgotten()
        except OSError:
            pass
        rows = getattr(self.world, "learned", [])
        if len(rows) == getattr(self, "_learned_saved", 0):
            return
        os.makedirs(os.path.dirname(self.learned_file), exist_ok=True)
        uniq = []
        for r in rows:
            if r not in uniq:
                uniq.append(r)
        tmp = self.learned_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(uniq, f)
        os.replace(tmp, self.learned_file)
        self._learned_saved = len(rows)

    def hands_on(self, why):
        """A Go to you started is you saying 'go': Hands off would leave it standing there, the same as Rego (Dan,
        2026-11-09). Turns Hands off off and says so. True = it was on."""
        if not getattr(self.settings, "hands_off", False):
            return False
        self.settings.hands_off = False
        try:
            self.on_settings_changed()
        except Exception:
            pass
        self.log(f"{why} — Hands off is off again")
        return True

    def learn_exit(self, src, cmd, dst):
        lc = (self.settings.locate_cmd or "").strip().lower()
        if lc and (cmd or "").strip().lower().lstrip(".") == lc:
            return                               # 'pro' told us where we are — it didn't take us anywhere
        spent = self.world.limited_use_item(cmd)
        if spent:
            self.log(f"Map: not learning '{cmd}' as a way — the {spent} has limited uses, so Go to never spends it")
            return
        if self.world.add_learned(src, cmd, dst):
            a, b = self.world.room(src), self.world.room(dst)
            self.log(f"Map: learned '{cmd}' from {a.name} ({src[0]}/{src[1]}) to {b.name} ({dst[0]}/{dst[1]})"
                     " — MME doesn't list it; Go to can use it now")
            self.save_learned()

    UNFINDABLE_HOURS = 24

    def _unfindable_path(self):
        return os.path.join(config.board_dir(self.settings.board), "unfindable.json")

    def note_unfindable(self, room, d):
        """A hidden exit you searched for over and over and never found: a wall for a day, on disk (so a restart and
        the next Go to don't send you back up to it)."""
        import json
        self.world.wall(room, d, mins=self.UNFINDABLE_HOURS * 60)
        try:
            data = json.load(open(self._unfindable_path(), encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        now = time.time()
        data = {k: v for k, v in data.items() if v > now}
        data[f"{room[0]}/{room[1]}/{d}"] = now + self.UNFINDABLE_HOURS * 3600
        try:
            os.makedirs(os.path.dirname(self._unfindable_path()), exist_ok=True)
            json.dump(data, open(self._unfindable_path(), "w", encoding="utf-8"))
        except OSError:
            pass

    def _load_unfindable(self):
        import json
        try:
            data = json.load(open(self._unfindable_path(), encoding="utf-8"))
        except (OSError, ValueError):
            return
        now = time.time()
        for k, until in data.items():
            m, r, d = k.split("/")
            if until > now:
                self.world.wall((int(m), int(r)), d, mins=(until - now) / 60)

    def reload_world(self):
        self.world = WorldDB(self.world_path)
        self._world_note()
        self.state.world = self.world
        self._load_learned()
        self._board_fixes()
        self.spellbook.world = self.world
        self._load_unfindable()
        from .spells import apply_mana_overrides
        apply_mana_overrides(self.world, getattr(self.settings, "spell_mana", None))
        self.bosses.on_change()
        self.load_saved_paths()          # re-match against the new MME data (in the background)
