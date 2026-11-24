"""What you clicked: every button, checkbox, menu item, shortcut key and setting you change goes into the log
(and the session trace), marked "You:", so a Report a problem bundle shows what you did as well as what
MudPilot did. Passwords are never written."""
from __future__ import annotations

import sys
import time
import tkinter as tk

SECRET_KEYS = ("password", "save_password", "show_recover_password", "ntfy_token", "phone_token")
_session = None
_last = {"msg": None, "t": 0.0}


def you(msg: str):
    """Log one thing you did (a repeat within a second is dropped — a double-click is one click)."""
    s = _session
    if s is None or not msg:
        return
    now = time.time()
    if _last["msg"] == msg and now - _last["t"] < 1.0:
        return
    _last.update(msg=msg, t=now)
    try:
        s.log(f"You: {msg}")
    except Exception:
        pass


def _text_of(w) -> str:
    for opt in ("text", "label"):
        try:
            t = str(w.cget(opt) or "").strip()
            if t:
                return t.replace("\n", " ")[:60]
        except (tk.TclError, AttributeError):
            pass
    tip = getattr(w, "_tiptext", None)
    if tip:
        return str(tip).split("(")[0].strip()[:60]
    return ""


def _where(w) -> str:
    try:
        top = w.winfo_toplevel()
        if top is w._root():
            return ""                            # the main window
        t = top.title()
        return f" ({t})" if t and not t.startswith(("MudPilot", "Miserable")) else ""
    except (tk.TclError, AttributeError):
        return ""


def _clicked(ev):
    w = ev.widget
    try:
        if str(w.cget("state")) == "disabled":
            return
    except (tk.TclError, AttributeError):
        pass
    t = _text_of(w)
    if not t:
        return
    cls = w.winfo_class()
    if cls in ("Label", "TLabel"):
        try:
            if str(w.cget("cursor")) != "hand2":
                return                           # plain text, not something you click
        except tk.TclError:
            return
    if cls in ("Checkbutton", "TCheckbutton", "Radiobutton", "TRadiobutton"):
        return                                   # the setting it changes is logged (with old → new) instead
    you(f"clicked '{t}'{_where(w)}")


def _key(ev):
    st = ev.state or 0
    # (on Windows 0x8 is Num Lock, not Alt: with Num Lock on every key logged as 'Alt+…' — Buddy, 2026-11-04)
    ctrl, alt = bool(st & 0x4), bool(st & 0x20000) if sys.platform == "win32" else bool(st & 0x20000 or st & 0x8)
    k = ev.keysym
    if k in ("Escape",) or k.startswith("F") and k[1:].isdigit() or ((ctrl or alt) and len(k) <= 8
                                                                     and k not in ("Control_L", "Control_R",
                                                                                   "Alt_L", "Alt_R", "c", "v", "x",
                                                                                   "a", "z")):
        you("pressed " + ("Ctrl+" if ctrl else "") + ("Alt+" if alt else "") + (k.upper() if len(k) == 1 else k))


def _wrap_menu():
    """Every menu item you pick, by its label."""
    if getattr(tk.Menu, "_mp_wrapped", False):
        return
    orig = tk.Menu.add

    def add(self, itemType, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        cmd, label = kw.get("command"), kw.get("label")
        if cmd and label:
            def run(*a, _c=cmd, _l=label, _m=self):
                try:
                    you(f"menu '{_l}'")
                except Exception:
                    pass
                if sys.platform == "darwin":
                    # macOS 27 runs a menu pick inside the menu-bar agent's callback and beachballs the app until it
                    # returns; a box opened straight from the pick (New character...) waits there forever. So run the
                    # pick just after the menu has closed instead.
                    _m.after(1, lambda: _c(*a))
                    return None
                return _c(*a)
            kw["command"] = run
        return orig(self, itemType, kw)
    tk.Menu.add = add
    tk.Menu._mp_wrapped = True


def install(app):
    """Hook the whole app (call once, after the main window exists)."""
    global _session
    _session = app.s
    root = app.root
    for cls in ("Button", "TButton", "Label", "TLabel"):
        root.bind_class(cls, "<ButtonRelease-1>", _clicked, add="+")
    root.bind_all("<KeyPress>", _key, add="+")
    _wrap_menu()


def setting_changed(key, old, new):
    if any(s in key for s in SECRET_KEYS):
        you(f"changed {key}")
        return
    if isinstance(old, str) and len(old) > 60 or isinstance(new, str) and len(new) > 60:
        you(f"changed {key}")
        return
    you(f"set {key}: {old!r} → {new!r}")
