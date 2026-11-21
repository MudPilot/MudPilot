"""Help → Copy diagnostics: everything needed to see why MudPilot isn't doing what you expect,
as plain text you can paste into a chat. No passwords (the screen copy is scrubbed, the BBS
password and ntfy topic live in Credential Manager and are never read here).
"""
from __future__ import annotations

import os
import platform
import time

from . import __version__


def why_not_moving(s) -> list:
    """Plain-English reasons the bot isn't walking right now, most likely first."""
    b, st, cfg = s.bot, s.state, s.settings
    now = time.time()
    out = []
    if not s.telnet.connected:
        return ["Not connected."]
    if not s._entered:
        out.append("Not in the realm yet (MudPilot waits for the first HP prompt / room before doing anything).")
    if b.paused:
        out.append("Everything is paused (@auto-all off or the pause switch).")
    if st.dead:
        out.append("Dead.")
    pg = getattr(b, "_pending_goto", None)
    if pg:
        out.append(f"Go to is waiting for your inventory (sent 'i' {now - pg[4]:.0f}s ago) before planning the route.")
    aw = getattr(b, "_await_inv", None)
    if aw:
        out.append(f"Path start is waiting for your inventory (needed-items check, {now - aw[3]:.0f}s).")
    if not b.walking:
        msg = getattr(b, "no_route_msg", "")
        out.append(f"Not walking. Status: '{b.status}'." + (f" Last route problem: {msg}" if msg else ""))
        if b.errands.active:
            out.append(f"An errand is active (fetching an item): {b.errands.active.get('todo')}")
        return out
    out.append(f"Walking: {b.path.title if b.path else '?'} — step {b.idx + 1}/{len(b.path.steps) if b.path else 0}, "
               f"{'loop' if b.loop else 'path'}.")
    try:
        for src, why in b.walk_holds().items():
            out.append(f"HELD by {src}: {why}.")
    except Exception:
        pass
    if b.x.waiting_on:
        out.append(f"Waiting for party members below the wait %: {', '.join(b.x.waiting_on)}.")
    try:
        if b.x.blocked_by_ailment():
            out.append(f"Blocked by an ailment: {', '.join(b.x.ailments)}.")
    except Exception:
        pass
    if getattr(b, "_boss_hold", None):
        out.append(f"Stopped before a boss room {b._boss_hold} (Alt+R walks in).")
    if st.pending:
        out.append(f"Waiting for the last move's result ({now - getattr(b, '_step_sent_at', now):.0f}s; times out after "
                   f"{cfg.step_timeout}s).")
    if getattr(b, "detour", None):
        out.append(f"On a detour back to the path ({len(b.detour)} steps left).")
    if st.in_combat:
        out.append("In combat.")
    elif st.view and st.view.monsters and cfg.auto_combat:
        out.append(f"Monsters here: {', '.join(m for m, _r in st.view.monsters)} (fights before moving on).")
    if st.resting:
        out.append(f"Resting (HP {st.hp_pct():.0f}%, MA {st.ma_pct() if st.max_ma else 100:.0f}%; up at "
                   f"{cfg.rest_until_hp}% HP / {cfg.rest_until_ma}% MA).")
    elif st.max_hp and (st.hp_pct() < cfg.rest_below_hp or (cfg.rest_below_ma and st.max_ma and st.ma_pct() < cfg.rest_below_ma)):
        out.append("Low enough to rest (rest settings).")
    if getattr(b, "_danger_hp", 0):
        out.append(f"Danger check: resting to {b._danger_hp:.0f}% HP before the next lair.")
    if getattr(b, "_pace_until", 0) > now:
        out.append(f"Lair pacing: waiting {b._pace_until - now:.0f}s for the next lair to refill.")
    if getattr(b, "_rest_full", False):
        out.append("Auto-tune: topping up to full before a trial.")
    if getattr(b, "_lair_wait_at", None):
        out.append("Waiting in an empty lair for it to fill (lair wait).")
    if st.need_refresh:
        out.append("Refreshing the room view before acting.")
    if len(out) == 1:
        out.append("Nothing holding it — if it still isn't stepping, the screen lines below show what the game answered.")
    return out


def snapshot(app) -> str:
    s = app.s
    b, st, cfg, w = s.bot, s.state, s.settings, s.world
    lines = [f"=== MudPilot {__version__} diagnostics · {time.strftime('%Y-%m-%d %H:%M:%S')} · "
             f"{platform.platform()} · Python {platform.python_version()}"]
    lines.append(f"Board {cfg.board}: {len(w.rooms):,} rooms, map data v{getattr(w, 'version', '?')}, "
                 f"{getattr(w, 'action_exits', '?')} exit actions")
    r = w.room(st.room) if st.room else None
    lines.append(f"Room: {st.room} {r.name if r else ''} · candidates {list(st.candidates)[:5]} · "
                 f"view: {st.view.name if st.view else None} exits {sorted(st.view.exits or []) if st.view else None}")
    lines.append(f"Connected {s.telnet.connected} · in realm {s._entered} · mode {getattr(b, '_mode', '?')} · "
                 f"walking {b.walking} · paused {b.paused} · status '{b.status}'")
    lines.append(f"HP {st.hp}/{st.max_hp} MA {st.ma}/{st.max_ma} · level {st.level or cfg.char_level} · "
                 f"combat {st.in_combat} · resting {st.resting} · lag {st.lag:.1f}s")
    held = b.held_items()
    lines.append(f"Inventory read: {held is not None} · keys: {st.keys[:120] or '-'} · items known to MME: "
                 f"{len(held or [])}")
    lines.append(f"Party: {dict((k, {kk: v.get(kk) for kk in ('class', 'hp', 'ma')}) for k, v in st.party.items())}")
    lines.append(f"Holds: {s.remote.holds} · waiting_on {b.x.waiting_on} · leader gone {b.x.leader_gone}")
    lines.append("Settings: " + ", ".join(f"{k}={getattr(cfg, k, None)}" for k in (
        "auto_combat", "auto_nuke", "auto_heal", "auto_rest", "auto_bless", "stop_before_boss", "check_needed_items",
        "auto_get_items", "avoid_mode", "danger_check", "lair_pace", "mana_throttle", "rest_below_hp",
        "rest_until_hp", "rest_below_ma", "rest_until_ma", "run_pct", "safe_rest_steps", "lair_wait_secs")))
    lines.append(f"Avoid: {cfg.avoid_names} {cfg.avoid_rooms}")
    try:
        tune = s.spelltune
        lines.append(f"Spell efficiency: {'on' if cfg.spell_efficiency else 'off'} · {tune.role()} · "
                     + (" | ".join(tune.status()) or "nothing learned yet"))
    except Exception as ex:
        lines.append(f"Spell efficiency: ({ex})")
    lines.append("")
    lines.append("--- Why isn't it moving?")
    try:
        lines += ["• " + x for x in why_not_moving(s)]
    except Exception as ex:
        lines.append(f"(couldn't work it out: {ex})")
    if getattr(b, "path", None):
        mp = b.path
        nxt = mp.steps[b.idx] if b.idx < len(mp.steps) else None
        lines.append(f"Next step: {nxt.room}→{nxt.dest} '{nxt.move}' pre={nxt.pre}" if nxt else "Next step: (end)")
    lines.append("")
    lines.append("--- Log (last 60)")
    lines += s.logs[-60:]
    lines.append("")
    lines.append("--- Screen (last 40 lines, passwords hidden)")
    lines += [time.strftime("%H:%M:%S ", time.localtime(t)) + x for t, x in list(s.timeline.screen)[-40:]]
    lines.append("")
    lines.append("--- Sent (last 25)")
    lines += [time.strftime("%H:%M:%S ", time.localtime(t)) + (c if not c.startswith("/") else c[:60])
              for t, c in list(s.timeline.sent)[-25:]]
    dec = list(getattr(s, "decisions", []))[-25:]
    if dec:
        lines.append("")
        lines.append("--- Decisions (last 25: why it did what it did)")
        for d in dec:
            extra = ", ".join(f"{k}={v}" for k, v in d.items() if k not in ("t", "what"))
            lines.append(time.strftime("%H:%M:%S ", time.localtime(d["t"])) + f"{d['what']}: {extra}"[:240])
    rec = getattr(s, "recorder", None)
    if rec and rec.path:
        lines.append(f"Recording: {rec.path}")
    from .report import ERRORS
    if ERRORS:
        lines.append("")
        lines.append("--- Errors (last 3)")
        for t, e in ERRORS[-3:]:
            lines.append(f"{t}\n{e[-1500:]}")
    lines.append("=== end")
    return "\n".join(lines)


def save_bundle(app) -> str:
    """pMUD's 'Save debug bundle': one zip with the session recording(s), today's log, errors, a window-freeze
    report if there is one, the diagnostics and your settings (passwords and tokens removed). For when
    a problem is too big to paste."""
    import json
    import zipfile
    from . import config
    from .report import clean_settings
    s = app.s
    out_dir = os.path.join(config.DATA_DIR, "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"debug-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    manifest = {"version": __version__, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "included": [], "missing": []}
    rec = getattr(s, "recorder", None)
    if rec:
        rec.flush_now()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        def add(fp, arc):
            if fp and os.path.exists(fp):
                z.write(fp, arc)
                manifest["included"].append(arc)
            else:
                manifest["missing"].append(arc)
        for i, fp in enumerate(rec.recent_files(2) if rec else []):
            add(fp, "traces/" + os.path.basename(fp))
        add(os.path.join(config.DATA_DIR, "logs", f"mudpilot-{time.strftime('%Y%m%d')}.log"), "log-today.log")
        add(os.path.join(config.DATA_DIR, "errors.log"), "errors.log")
        add(os.path.join(config.DATA_DIR, "ui_freeze.log"), "ui_freeze.log")
        try:
            z.writestr("diagnostics.txt", snapshot(app))
            manifest["included"].append("diagnostics.txt")
        except Exception as ex:
            z.writestr("diagnostics.txt", f"couldn't build: {ex}")
        z.writestr("settings.json", json.dumps(clean_settings(s.settings), indent=1, default=str))
        manifest["included"].append("settings.json")
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    return path
