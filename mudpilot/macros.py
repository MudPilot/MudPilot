"""Macros, MegaMUD style.

A macro is text bound to a key (F1-F12 with Shift/Ctrl, or the number pad). In the
text, ^M means "press Enter": "n^Ml n^M" walks north then looks north. Text after the
last ^M is left in the input box for you to finish ("ask rod trade " + you type).

"Def" macros are shared by every character (data/macros.json); "Char" macros belong to
one character (its settings) and override a Def macro on the same key.
"""
from __future__ import annotations

import json
import os

from . import config

MACRO_FILE = os.path.join(config.DATA_DIR, "macros.json")

# MegaMUD's default number-pad layout
DEFAULT_MACROS = {
    "Keypad 8": "n^M", "Keypad 2": "s^M", "Keypad 4": "w^M", "Keypad 6": "e^M",
    "Keypad 7": "nw^M", "Keypad 9": "ne^M", "Keypad 1": "sw^M", "Keypad 3": "se^M",
    "Keypad 0": "u^M", "Keypad .": "d^M", "Keypad 5": "^M", "Keypad +": "rest^M",
}

FKEYS = [f"F{i}" for i in range(1, 13)]
KEYPAD_KEYS = [f"Keypad {c}" for c in "0123456789"] + ["Keypad .", "Keypad +", "Keypad -", "Keypad *", "Keypad /"]
ALL_KEYS = FKEYS + [f"Shift+{k}" for k in FKEYS] + [f"Ctrl+{k}" for k in FKEYS] + KEYPAD_KEYS + \
    ["Insert", "Home", "End", "Page Up", "Page Down", "Pause", "Delete"]

# Tk keysyms (Linux/Mac, and Windows with NumLock off) and Windows keycodes (NumLock on)
_KP_SYMS = {"KP_0": "0", "KP_1": "1", "KP_2": "2", "KP_3": "3", "KP_4": "4", "KP_5": "5", "KP_6": "6",
            "KP_7": "7", "KP_8": "8", "KP_9": "9", "KP_Insert": "0", "KP_End": "1", "KP_Down": "2",
            "KP_Next": "3", "KP_Left": "4", "KP_Begin": "5", "KP_Right": "6", "KP_Home": "7", "KP_Up": "8",
            "KP_Prior": "9", "KP_Decimal": ".", "KP_Delete": ".", "KP_Add": "+", "KP_Subtract": "-",
            "KP_Multiply": "*", "KP_Divide": "/"}
_WIN_CODES = {96: "0", 97: "1", 98: "2", 99: "3", 100: "4", 101: "5", 102: "6", 103: "7", 104: "8", 105: "9",
              110: ".", 107: "+", 109: "-", 106: "*", 111: "/"}
_WIN_NAV = {45: "0", 35: "1", 40: "2", 34: "3", 37: "4", 12: "5", 39: "6", 36: "7", 38: "8", 33: "9", 46: "."}


# pMUD: macros on any key — Ctrl+letter/digit (Ctrl+Shift too) and the keys nothing types with
SPECIAL_KEYS = {"Insert": "Insert", "Home": "Home", "End": "End", "Prior": "Page Up", "Next": "Page Down",
                "Pause": "Pause", "Scroll_Lock": "Scroll Lock", "Delete": "Delete"}
_NO_MACRO = {"Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+A", "Ctrl+Z"}      # copy / paste / cut / select / undo stay theirs
# 0.8.201: keys MudPilot itself already uses (app.py binds) — the macro editor won't hand them out
RESERVED_KEYS = {"F1": "the help book", "Ctrl+S": "Settings", "Ctrl+Shift+D": "Copy diagnostics",
                 "Page Up": "scrolling the game screen", "Page Down": "scrolling the game screen",
                 "Ctrl+Home": "the top of the game screen", "Ctrl+End": "the bottom of the game screen"}
FREE_KEYS = [k for k in ALL_KEYS if k not in RESERVED_KEYS]


def key_name(keysym: str, keycode: int, state: int, windows: bool, extended: bool = True) -> str | None:
    """Turn a Tk key event into a macro key name, or None if it isn't a macro key. On Windows `extended` is
    state & 0x40000, Tk's flag for the arrow / Home / End block (0x20000 is Alt: checking that made the Up arrow
    Keypad 8 — Dan, 0.8.226: "the up arrow just makes me run north" instead of bringing back the last command)."""
    shift, ctrl = bool(state & 0x1), bool(state & 0x4)
    if keysym in FKEYS:
        return ("Ctrl+Shift+" if ctrl and shift else "Ctrl+" if ctrl else "Shift+" if shift else "") + keysym
    if ctrl and len(keysym) == 1 and keysym.isalnum():
        nm = ("Ctrl+Shift+" if shift else "Ctrl+") + keysym.upper()
        return None if nm in _NO_MACRO else nm
    if keysym in SPECIAL_KEYS and not (windows and not extended and keycode in _WIN_NAV):
        return ("Ctrl+" if ctrl else "Shift+" if shift else "") + SPECIAL_KEYS[keysym]
    if keysym in _KP_SYMS:
        return "Keypad " + _KP_SYMS[keysym]
    if windows:
        if keycode in _WIN_CODES:
            return "Keypad " + _WIN_CODES[keycode]
        # NumLock off: number-pad keys arrive as arrows/home/etc. without the "extended" flag
        if not extended and keycode in _WIN_NAV:
            return "Keypad " + _WIN_NAV[keycode]
    return None


def split(text: str) -> tuple[list[str], str]:
    """'n^Ml n^Mask rod ' -> (['n', 'l n'], 'ask rod ')"""
    parts = text.replace("^m", "^M").split("^M")
    return parts[:-1], parts[-1]


def load_default() -> dict:
    try:
        with open(MACRO_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d = {str(k): str(v) for k, v in d.items()}
            if d.pop("_keypad_v", None) != "2":
                if d.get("Keypad 0") == "d^M" and d.get("Keypad .") == "u^M":
                    d["Keypad 0"], d["Keypad ."] = "u^M", "d^M"     # 0 = up, . = down (Dan, 0.8.22)
                try:
                    save_default(d)
                except Exception:
                    pass
            return d
    except (OSError, ValueError):
        pass
    return dict(DEFAULT_MACROS)


def save_default(macros: dict):
    os.makedirs(os.path.dirname(MACRO_FILE), exist_ok=True)
    tmp = MACRO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**macros, "_keypad_v": "2"}, f, indent=2)
    os.replace(tmp, MACRO_FILE)


class Macros:
    def __init__(self, settings):
        self.settings = settings
        self.default = load_default()

    def table(self) -> list:
        """[(key, text, 'Char'|'Def')] for every bound key, in key order."""
        char = self.settings.macros or {}
        keys = [k for k in ALL_KEYS if k in char or k in self.default]
        keys += sorted(k for k in set(char) | set(self.default) if k not in ALL_KEYS)
        return [(k, char[k], "Char") if k in char else (k, self.default[k], "Def") for k in keys]

    def get(self, key: str) -> str | None:
        char = self.settings.macros or {}
        return char.get(key, self.default.get(key))

    def set(self, key: str, text: str, scope: str = "Char"):
        if scope == "Def":
            self.default[key] = text
            save_default(self.default)
            (self.settings.macros or {}).pop(key, None)
        else:
            self.settings.macros = dict(self.settings.macros or {})
            self.settings.macros[key] = text
        self.settings.save()

    def remove(self, key: str, scope: str):
        if scope == "Def":
            self.default.pop(key, None)
            save_default(self.default)
        else:
            self.settings.macros = {k: v for k, v in (self.settings.macros or {}).items() if k != key}
            self.settings.save()


def from_megamud_ini(sections: dict) -> dict:
    """Pick macros out of a MegaMUD .ini if it has a [Macros]-style section:
    keys like F1, ShiftF2, CtrlF3, Num8 / Keypad8 / KP8."""
    out = {}
    for sec, items in sections.items():
        if "macro" not in sec.lower():
            continue
        for k, v in items.items():
            name = _ini_key(k)
            if name and v:
                out[name] = v
    return out


def _ini_key(k: str) -> str | None:
    import re
    k = k.strip()
    m = re.match(r"^(shift|ctrl|control)?[\s+_-]*f(\d{1,2})$", k, re.I)
    if m and 1 <= int(m.group(2)) <= 12:
        mod = {"shift": "Shift+", "ctrl": "Ctrl+", "control": "Ctrl+"}.get((m.group(1) or "").lower(), "")
        return f"{mod}F{int(m.group(2))}"
    m = re.match(r"^(?:num|keypad|kp|key-pad)[\s_-]*([0-9.+*/-]|plus|minus|dot|period|star|slash)$", k, re.I)
    if m:
        c = {"plus": "+", "minus": "-", "dot": ".", "period": ".", "star": "*", "slash": "/"}.get(m.group(1).lower(), m.group(1))
        return f"Keypad {c}"
    return None
