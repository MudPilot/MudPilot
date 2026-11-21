"""Window-freeze watcher (pMUD's UI hang watcher): the window ticks a heartbeat every second; a background
thread notices when it stops for 8 s and writes where every thread was at that moment to
data/ui_freeze.log. When the window comes back, MudPilot says how long it froze. Copy diagnostics and
the debug bundle include the file.

Short stalls (a couple of seconds — Dan, 2026-10-30: 'it locks up for 2 seconds when I click Go') are written
too, at most one every 30 s and without a message in the window, so we can see what holds the window up."""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time

from . import config

STALL = 8.0
CANCEL_AFTER = 15.0      # stuck this long in the game: cancel whatever Windows mode might be holding the window
RECOVER_AFTER = 45.0     # …still stuck with Tk itself waiting (no MudPilot code running): restart through the launcher
RECOVER_BUSY = 300.0     # stuck in MudPilot's own code that long: restart too
SHORT = 1.8              # heartbeat every 1 s: a gap this long is the window stuck for ~1 s or more
SHORT_EVERY = 30


class HangWatch:
    def __init__(self, root, log, session=None):
        self.root, self.log, self.s = root, log, session
        self.beat = time.time()
        self._cancelled = 0.0
        self._main = threading.main_thread()
        try:
            self._hwnd = int(root.wm_frame(), 16)
        except Exception:
            self._hwnd = None
        self.frozen_at = 0.0
        self._short_at = 0.0
        self._short_beat = 0.0
        self.path = os.path.join(config.DATA_DIR, "ui_freeze.log")
        self._stop = False
        self.root.after(1000, self._tick)
        threading.Thread(target=self._watch, daemon=True, name="hangwatch").start()

    def _tick(self):
        now = time.time()
        if self.frozen_at:
            gap = now - self.frozen_at + STALL
            self.frozen_at = 0.0
            self._cancelled = 0.0
            try:
                self.log(f"The window froze for about {gap:.0f} s — where it was stuck is in ui_freeze.log "
                         "(Help → Save debug bundle sends it)")
            except Exception:
                pass
        self.beat = now
        try:
            self.root.after(1000, self._tick)
        except Exception:
            self._stop = True

    def _dump(self, head):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            if os.path.exists(self.path) and os.path.getsize(self.path) > 2_000_000:
                os.replace(self.path, self.path + ".old")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {head} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.flush()
                faulthandler.dump_traceback(file=f, all_threads=True)
        except Exception:
            pass

    def _watch(self):
        while not self._stop:
            time.sleep(0.3)
            now = time.time()
            gap = now - self.beat
            if gap > STALL and not self.frozen_at:
                self.frozen_at = now
                self._dump(f"window not answering for {gap:.0f} s")
            if self.frozen_at and self._in_game():
                self._recover(gap)
            elif SHORT < gap <= STALL and self._short_beat != self.beat and now - self._short_at > SHORT_EVERY:
                # (once per stall, and not too often: where the window is while it's stuck a second or two)
                self._short_beat, self._short_at = self.beat, now
                self._dump(f"short stall: window not answering for {gap:.1f} s")

    # ---- getting a stuck window going again (Dan, 2026-11-13: Miserable PVE's window stopped at 07:59 with nothing of
    # MudPilot's running — Tk itself waiting — and the character stood in a crab fight until it died; the line dropped
    # and nothing came back until he clicked the window at 10:44, 2 h 45 min later)

    def _in_game(self) -> bool:
        s = self.s
        try:
            return bool(s is not None and s.telnet is not None and s.telnet.connected)
        except Exception:
            return False

    def _tk_waiting(self) -> bool:
        """The window's thread is inside Tk's own loop (no MudPilot code on its stack): Windows or Tk holding it."""
        try:
            f = sys._current_frames().get(self._main.ident)
        except Exception:
            return False
        return f is not None and f.f_code.co_name == "mainloop"

    def _cancel_modes(self):
        """WM_CANCELMODE to every window of the window's thread: ends a menu, a move / resize, a captured mouse."""
        if os.name != "nt":
            return 0                                     # (a Windows-only fix; Linux window managers don't hold Tk)
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnds = [self._hwnd] if self._hwnd else []
            cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            cb = cb_t(lambda h, _l: (hwnds.append(h), True)[1])
            u.EnumThreadWindows(self._main.native_id, cb, 0)
            for h in set(hwnds):
                u.PostMessageW(h, 0x001F, 0, 0)          # WM_CANCELMODE
            return len(set(hwnds))
        except Exception:
            return 0

    def _recover(self, gap):
        now = time.time()
        if gap > CANCEL_AFTER and not self._cancelled:
            self._cancelled = now
            n = self._cancel_modes()
            self._note(f"stuck {gap:.0f} s in the game: cancelled any menu / move on {n} window(s)")
            return
        waiting = self._tk_waiting()
        if not (gap > RECOVER_BUSY or (waiting and gap > RECOVER_AFTER)):
            return
        from . import control
        if not control.by_launcher():
            if now - self._cancelled > 60:            # (nothing would reopen us: keep nudging, once a minute)
                self._cancelled = now
                self._cancel_modes()
            return
        self._dump(f"stuck {gap:.0f} s in the game ({'Tk waiting' if waiting else 'busy'}) — restarting through the launcher")
        try:
            self.s.control.write_resume()
        except Exception as ex:
            self._note(f"resume note failed: {ex!r}")
        self._note("restarting: the launcher reopens MudPilot, which logs back in and carries on")
        os._exit(control.RESTART_EXIT)

    def _note(self, msg):
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass
