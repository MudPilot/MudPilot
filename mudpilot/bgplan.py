"""Route planning off the window's thread.

Dan, 2026-10-30: picking a room in Goto turned the window white ('Not Responding') for up to 15 s while the route
was worked out — it looked like a crash. Now the planning (Bot.goto and everything it calls) runs on a worker
thread; the window keeps drawing and says 'Calculating route — one moment please…'.

While it runs, what the planner would do to the window or the game (send, log, alerts) is queued and played back
on the window's thread, in order; a question for you (take Negative Power Plane?) is asked on the window's thread
and the planner waits for the answer. The bot's own tick sits out until the plan is done."""
from __future__ import annotations

import queue
import threading
import time

DEFERRED = ("send", "log", "on_alert", "on_no_route", "on_paths_changed", "on_settings_changed")


def plan(session, fn, done=None, ask=None, after=None, ask_in_thread=False):
    """Run fn(ask) — fn(ask) returns what Bot.goto returns — then done(result, error) on the window's thread.
    after = Tk's after (root.after); without it (tests, headless) it all runs right here.
    ask_in_thread: ask itself waits for its answer on the planner's thread (a remote @goto asks over telepath)."""
    if after is None or getattr(session.bot, "_planning", False):
        try:
            res = fn(None if ask_in_thread else ask)
        except Exception as e:
            if not done:
                raise
            done(None, e)
            return None
        if done:
            done(res, None)
        return res
    q = queue.Queue()
    saved = {n: getattr(session, n) for n in DEFERRED if hasattr(session, n)}
    own = {n for n in saved if n in session.__dict__}       # a callback the window set, not a method
    for n in saved:
        setattr(session, n, (lambda _n: lambda *a, **k: q.put((_n, a, k)))(n))
    out = {}

    def ask_bg(*a):
        if ask is None:
            return False
        if "end" in out:
            # this plan is over and nobody drains its queue any more (a parked Go to kept this ask and is retried
            # from the tick): waiting would freeze the window for 120 s. Ask straight away on the window's thread.
            return bool(ask(*a)) if threading.current_thread() is threading.main_thread() else False
        ev, box = threading.Event(), {}
        q.put(("__ask__", a, {"ev": ev, "box": box}))
        ev.wait(120)
        return box.get("v", False)

    def work():
        try:
            out["res"] = fn(ask if ask_in_thread else (ask_bg if ask is not None else None))
        except BaseException as e:          # handed back to the window's thread
            out["err"] = e
        out["end"] = time.time()

    session.bot._planning = True
    t = threading.Thread(target=work, name="route-plan", daemon=True)
    t.start()

    DRAIN_MAX = 400     # per pass: whatever goes wrong, a played-back call that queues more can't spin the window for good

    def drain():
        for _ in range(DRAIN_MAX):
            try:
                n, a, k = q.get_nowait()
            except queue.Empty:
                return
            if n == "__ask__":
                try:
                    k["box"]["v"] = bool(ask(*a))
                finally:
                    k["ev"].set()
                continue
            try:
                saved[n](*a, **k)
            except Exception:
                pass

    def poll():
        drain()
        if "end" not in out:
            after(40, poll)
            return
        for n, f in saved.items():
            if n in own:
                setattr(session, n, f)
            else:
                session.__dict__.pop(n, None)
        session.bot._planning = False
        for _ in range(25):                 # (the last of it, in passes: nothing queues more now)
            drain()
            if q.empty():
                break
        if done:
            done(out.get("res"), out.get("err"))
    after(40, poll)
    return None
