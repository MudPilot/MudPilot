"""MudPilot on a Mac: the Windows monospace fonts its windows ask for, swapped for the Mac's own.

MudPilot asks for Consolas all over (the MUD window, the log, Conversations …). A Mac doesn't have it, and Tk on macOS
then draws in the system font, whose letters are different widths, so the game's columns and boxes go crooked
(Spuzzy, 2026-11-25: the character-creation screen and the 'who' list misaligned). Linux has the same swap done by
fontconfig (assets/fonts-linux.conf); on a Mac it's done here, when a font reaches Tk: a font asked for by a Windows
monospace name that this Mac doesn't have is drawn in Menlo, which every Mac has. Your saved font choice is
never changed; a font you do have (Courier New, or anything you pick in Font…) is used as it is."""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont

# Windows / Linux monospace names MudPilot (or a settings file brought over from Windows) may ask for
WINDOWS_MONO = ("Consolas", "Cascadia Mono", "Cascadia Code", "Lucida Console", "Terminal", "Fixedsys",
                "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono", "Noto Sans Mono")
# the Mac's own monospace fonts, best first (Menlo has been on every Mac since 10.6)
MAC_MONO = ("Menlo", "SF Mono", "Monaco", "Andale Mono", "PT Mono", "Courier New", "Courier")

_swap: dict = {}          # lower-case missing family -> the Mac font drawn instead


def mono_fallback(families) -> str:
    have = {f.lower() for f in families}
    return next((f for f in MAC_MONO if f.lower() in have), "Menlo")


def swap_family(fam):
    """The family to draw for `fam` (itself unless it's a Windows monospace font this Mac doesn't have)."""
    if isinstance(fam, str):
        return _swap.get(fam.strip("{}").lower(), fam)
    return fam


def swap_font(v):
    """A Tk font value ('Consolas', ('Consolas', 12, 'bold'), '{Consolas} 12') with the family swapped."""
    if not _swap:
        return v
    if isinstance(v, (tuple, list)) and v:
        new = swap_family(v[0])
        return v if new is v[0] else (new,) + tuple(v[1:])
    if isinstance(v, str) and v:
        if v.startswith("{"):
            fam, _, rest = v[1:].partition("}")
        else:
            fam, _, rest = v.partition(" ")
            if fam.lower() not in _swap:
                # 'Lucida Console 10' — a two-word name written without braces
                for k in _swap:
                    if v.lower().startswith(k + " ") or v.lower() == k:
                        fam, rest = v[:len(k)], v[len(k):]
                        break
        new = swap_family(fam)
        if new is fam:
            return v
        return "{%s}%s" % (new, (" " + rest.strip()) if rest.strip() else "")
    return v


def install(root):
    """Call once on a Mac, right after tk.Tk() and before any window is built."""
    if sys.platform != "darwin" or getattr(tk.Misc, "_mp_macfonts", False):
        return
    try:
        fams = set(tkfont.families(root))
    except Exception:
        return
    have = {f.lower() for f in fams}
    to = mono_fallback(fams)
    for name in WINDOWS_MONO:
        if name.lower() not in have:
            _swap[name.lower()] = to
    if not _swap:
        return

    orig_options = tk.Misc._options

    def _options(self, cnf, kw=None):
        # every widget's create / configure / tag / canvas-item options pass through here on their way to Tk
        if kw and "font" in kw:
            kw = {**kw, "font": swap_font(kw["font"])}
        if isinstance(cnf, dict) and "font" in cnf:
            cnf = {**cnf, "font": swap_font(cnf["font"])}
        return orig_options(self, cnf, kw)

    tk.Misc._options = _options

    orig_set = tkfont.Font._set

    def _set(self, kw):
        if "family" in kw:
            kw = {**kw, "family": swap_family(kw["family"])}
        return orig_set(self, kw)

    tkfont.Font._set = _set
    tk.Misc._mp_macfonts = True
