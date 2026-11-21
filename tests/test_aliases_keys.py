"""0.8.201: aliases (Game Data → Aliases) and key bindings (Game Data → Macros).
Typed 'bs' → 'bash door', $1/$* args, a macro key can send an alias, MudPilot's own keys (F1 help, Ctrl+S…)
aren't handed out, and a remote '@do bs' from a party member is never expanded (only what you type)."""
import os, sys
import tkinter as tk
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamedata import GameData
from mudpilot.ansi import Style
from mudpilot import aliases as A
from mudpilot import macros as M
from mudpilot.app import App

ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


# ---------------------------------------------------------------- expansion
al = {"bs": "bash door", "k": "kill $1", "gp": "get all^Mput all in sack;wear $*", "x2": "bs;k $1",
      "me": "me", "loopy": "loopy2", "loopy2": "loopy", "nothing": "  "}
cases = [("bs", ["bash door"]), ("BS north", ["bash door north"]), ("k orc", ["kill orc"]), ("k", ["kill"]),
         ("gp ring of fire", ["get all", "put all in sack", "wear ring of fire"]), ("x2 orc", ["bash door", "kill orc"]),
         ("me", ["me"]), ("loopy", ["loopy"]), (".@do bs", [".@do bs"]), ("/revolution bs", ["/revolution bs"]),
         ("hello  there", ["hello  there"]), ("", [""]), ("nothing", [])]
for typed, want in cases:
    got = A.expand(typed, al, ";")
    check(f"expand {typed!r} -> {got}", got == want)
check("no aliases = as typed", A.expand("bs", {}, ";") == ["bs"] and A.expand("bs", None) == ["bs"])
check("never more than MAX_STEPS", len(A.expand("many", {"many": ";".join(["n"] * 50)})) == A.MAX_STEPS)
check("reserved name refused", A.name_problem("gos", {}) is not None and A.name_problem("say", {}) is not None)
check("two words / symbols refused", A.name_problem("b s", {}) and A.name_problem("@do", {}) and A.name_problem(".x", {}))
check("duplicate refused, renaming itself fine", A.name_problem("BS", al) and A.name_problem("bs", al, old="bs") is None)
check("a fresh name is fine", A.name_problem("bd", al) is None)

# ---------------------------------------------------------------- Game Data → Aliases tab
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
root = tk.Tk(); root.withdraw()
app = type("A", (), {"s": s, "add_log": lambda self, m: None,
                     "_var": lambda self, k: tk.BooleanVar(value=bool(getattr(st, k, False)))})()
gd = GameData(root, app, tab="Aliases")
check("Aliases tab is there, after Macros", "Aliases" in gd.tabs and
      GameData.TABS.index("Aliases") == GameData.TABS.index("Macros") + 1)
check("starts empty (new setting defaults to nothing)", st.aliases == {} and not gd.a_tree.get_children())
check("add bs", gd.a_save(None, "bs", "bash door") is None and st.aliases == {"bs": "bash door"}
      and gd.a_tree.set("bs", "Sends") == "bash door")
check("refuses a game word", gd.a_save(None, "gos", "hi") and "gos" not in st.aliases)
check("refuses a duplicate", gd.a_save(None, "BS", "bash") and st.aliases == {"bs": "bash door"})
check("refuses empty text", gd.a_save(None, "k", "") and "k" not in st.aliases)
check("rename bs -> bd keeps one row", gd.a_save("bs", "bd", "bash door") is None and st.aliases == {"bd": "bash door"}
      and list(gd.a_tree.get_children()) == ["bd"])
gd.a_save(None, "k", "kill $1")
gd.a_tree.selection_set("bd")
gd.a_remove()
check(f"remove ({st.aliases})", st.aliases == {"k": "kill $1"} and list(gd.a_tree.get_children()) == ["k"])
check("aliases follow the character, not a config slot", "aliases" in config.Settings.CONFIG_SHARED)

# ---------------------------------------------------------------- typed + macro keys go through the aliases
st.aliases = {"bs": "bash door", "k": "kill $1"}
sent = []
s.telnet.sock = object()
real_send = s.send
s.send = lambda c, from_bot=False: sent.append(c)


class Ent:
    def __init__(self): self.v = ""
    def get(self): return self.v
    def delete(self, a, b=None): self.v = ""
    def insert(self, i, t): self.v = t
    def icursor(self, i): pass
    def focus_set(self): pass


fake = type("F", (), {})()
fake.s, fake.entry, fake.add_log = s, Ent(), lambda m: None
fake.send_typed = lambda c: App.send_typed(fake, c)
App.send_typed(fake, "k orc")
check(f"typed 'k orc' -> {sent}", sent == ["kill orc"])
sent.clear()
App.run_macro(fake, "bs^Mk rat^Mk ")
check(f"macro 'bs^Mk rat^Mk ' sends {sent}, leaves '{fake.entry.v}'", sent == ["bash door", "kill rat"]
      and fake.entry.v == "k ")
sent.clear()
App.run_macro(fake, "^M")
check(f"a bare Enter macro still sends Enter ({sent})", sent == [""])

# ---------------------------------------------------------------- MudPilot's own keys stay MudPilot's
for k in ("F1", "Ctrl+S", "Ctrl+Shift+D", "Page Up", "Page Down", "Ctrl+Home", "Ctrl+End"):
    check(f"{k} is reserved and not offered", k in M.RESERVED_KEYS and k not in M.FREE_KEYS)
check("F2-F12 / keypad still offered", "F2" in M.FREE_KEYS and "Keypad 8" in M.FREE_KEYS and "Shift+F1" in M.FREE_KEYS)
check("Ctrl+S key event is the reserved name", M.key_name("s", 83, 0x4, True) == "Ctrl+S")
check("Ctrl+B is a macro key", M.key_name("b", 66, 0x4, True) == "Ctrl+B" and "Ctrl+B" not in M.RESERVED_KEYS)
mt = gd.tabs["Macros"]


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


check("Macros tab still builds", any(isinstance(w, ttk.Treeview) for w in walk(mt)))

# ---------------------------------------------------------------- a remote @do is never expanded
s.send = real_send
st.remote_players = {"Miserable": ["query", "location", "move", "settings", "execute"]}
st.aliases = {"bs": "bash door", "look": "bash door"}
wire = []


class FakeTel:
    connected = True
    def send_line(self, x): wire.append(x)
    events = __import__("queue").Queue()
    def close(self): pass


s.telnet = FakeTel()


def feed(*lines):
    for l in lines:
        s._line([(l, Style())])


feed("[HP=650/MA=394]: (Meditating) par", "The following people are in your travel party:",
     "  Evolution Abil                (Mage)       [M: 89%] [H: 92%]M - Frontrank",
     "  Miserable Cunt                (Druid)      [M:100%] [H: 96%]R - Backrank",
     "[HP=650/MA=394]:Town Gates", "Obvious exits: north, south, east, west")
for cmd in ("bs", "look"):
    s.remote._recent.clear(); wire.clear()
    feed(f"Miserable telepaths: @do {cmd}")
    check(f"remote '@do {cmd}' sends {wire} — not the alias", cmd in wire and "bash door" not in wire)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
