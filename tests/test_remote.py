"""Remote commands + boss kill + chat, driven by fake game lines (no network)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot import bosses as B
B.BOSS_FILE_OVERRIDE = "/tmp/claude-0/bosses_test.json"
if os.path.exists(B.BOSS_FILE_OVERRIDE): os.remove(B.BOSS_FILE_OVERRIDE)
st = config.Settings(); st.remote_players = {"Miserable": ["query", "location", "move", "settings"]}
st.buffs = [{"name": "Nature tap", "cast": "ntap", "ability": "145", "source": "spells", "check_cmd": "abil 145", "op": ">=", "value": 150, "enabled": True}]
st.save = lambda: None
s = Session(st)
sent = []
class FakeTel:
    connected = True
    def send_line(self, x): sent.append(x)
    events = __import__("queue").Queue()
    def close(self): pass
s.telnet = FakeTel()
s.bosses.load(); s.bosses.data = {}
def feed(*lines):
    for l in lines: s._line([(l, Style())])
feed("[HP=650/MA=394]: (Meditating) par", "The following people are in your travel party:",
     "  Miserable Cunt                (Mage)       [M: 89%] [H: 92%]M - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H: 96%]R - Backrank",
     "[HP=650/MA=394]:Town Gates", "Obvious exits: north, south, east, west")
tests = ["Miserable telepaths: @health", "Miserable telepaths: @where", "Miserable says \"@status\"",
         "Miserable telepaths: @auto-combat on", "Miserable telepaths: @settings", "Miserable telepaths: @bless ntap 120",
         "Miserable telepaths: @do look", "Stranger telepaths: @do drop all", "Stranger telepaths: @health",
         "Miserable telepaths: @do suicide", "Miserable gangpaths: @version", "Miserable telepaths: @wait",
         "Miserable telepaths: @goto 1/3", "Miserable telepaths: @path", "Miserable telepaths: @stop",
         "Miserable telepaths: @timer", "Broadcast from Miserable \"@health\"", "Miserable telepaths: @rego"]
for t in tests:
    s.remote._recent.clear(); sent.clear(); feed(t); print(f"{t:45} -> {sent}")
print("holding:", s.remote.holding(), "| auto_combat:", st.auto_combat, "| ntap target:", st.buffs[0]["value"])
# boss kill: dark phoenix in room, we gain exp, it is gone afterward
feed("[HP=650/MA=394]:Phoenix Nest", "Also here: dark phoenix.", "Obvious exits: north")
feed("*Combat Engaged*", "You gain 3250000 experience.", "*Combat Off*", "[HP=650/MA=394]:Phoenix Nest", "Obvious exits: north")
print("boss:", [(m["name"], s.bosses.status(m["num"])[0]) for m in s.bosses.tracked()])
sent.clear(); feed("Miserable telepaths: @timer phoenix"); print("@timer phoenix ->", sent)
feed("Bob gossips: anyone selling a rope?", "Miserable telepaths: hey you there", "Bob says \"hi\"")
print("chat:", [(c, w, m) for _t, c, w, m in s.chat.entries])
