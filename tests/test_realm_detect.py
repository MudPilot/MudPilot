"""PvP realm detection: a BBS menu listing both realms (Paradigm: 'Game 1 PVE', 'Game 2 PVP') doesn't mark the
character PvP; a menu that only says PVP does, and so does a 'Server PvP Message' in the game."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.ansi import Style
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def enter(menu_lines, then=()):
    st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.pvp_realm = False
    s = Session(st)
    class T:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): pass
        def send_raw(self, x): pass
        def close(self): self.connected = False
    s.telnet = T()
    s._entered = False
    for l in menu_lines:
        s._line([(l, Style())])
    s._connected_at = time.time() - 5
    s.state.last_prompt = time.time()
    s.poll()
    for l in then:
        s._line([(l, Style())])
    return s

s = enter(["1. Paradigm Game 1 PVE", "2. Paradigm Game 2 PVP", "Please select a realm:"])
check("menu listing PVE and PVP: not marked PvP", s._entered and not s.settings.pvp_realm)
s = enter(["Welcome to Some Game PVP", "Please select a character:"])
check("menu saying only PVP: PvP realm", s.settings.pvp_realm)
s = enter(["1. Paradigm Game 1 PVE", "2. Paradigm Game 2 PVP"], ["Server PvP Message: Vexx has slain Bob!"])
check("a Server PvP Message in the game: PvP realm", s.settings.pvp_realm)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
