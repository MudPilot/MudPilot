"""Messages/Responses (team PvP commands) and track alerts."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None
st.my_name = "Tester"; st.auto_spells = True; st.char_level = 45; st.char_class = "Druid"
st.hangup_on_pvp = True
s = Session(st)
sent, closed = [], []
class FakeTel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): closed.append(1); self.connected = False
s.telnet = FakeTel(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
feed("[HP=600/MA=300]:Town Gates", "Also here: Bob.", "Obvious exits: north, south")
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 600, 600, 300, 300
s.state.party = {"Tester": {"hp": 100, "ma": 100, "t": time.time()}, "Miserable": {"hp": 100, "ma": 100, "t": time.time()}}
st.known_spell_rows = [["esto", "eldritch storm", 37, 45], ["magm", "magma blast", 30, 20], ["mete", "meteor swarm", 41, 60]]
def heard(line):
    sent.clear(); feed(line)
    s.responses._pending_at -= 2; s.responses.tick()
    return list(sent)
out = heard('Broadcast from Miserable "nuke"')
check(f"br nuke from party -> biggest area spell ({out})", out and out[0] in ("esto", "mete"))
check("stranger can't trigger", heard('Broadcast from Stranger "nuke"') == [])
out = heard('Broadcast from Miserable "bs Bob"')
check(f"bs Bob -> backstab ({out})", out == ["bs Bob"])
check("sneak", heard("Miserable gangpaths: sneak") == ["sn"])
check("hide by telepath", heard("Miserable telepaths: hide") == ["hide"])
check("odd text never passed through", heard('Broadcast from Miserable "bs Bob;suicide"') == [])
heard('Broadcast from Miserable "attack Bob"')
check("attack Bob -> PvP target", s.bot.x.pvp_target == "Bob")
s.bot.x.stop_pvp()
s.bot.walking = True
heard('Broadcast from Miserable "hold"')
check("hold stops and holds for Miserable", not s.bot.walking and "Miserable" in s.remote.holds)
# track alert
st.track_alert = True; st.track_alert_channel = "broadcast"
out = heard("You notice the tracks of Lexxy heading north.")
check(f"track alert broadcast ({out})", any(c.startswith("br Tracks: Lexxy") for c in out))
check("no repeat within a minute", not any(c.startswith("br ") for c in heard("You notice the tracks of Lexxy heading north.")))
check("party member's tracks ignored", not heard("You notice the tracks of Miserable heading west."))
st.track_alert_channel = "party"
out = heard("You notice the tracks of Mirage heading east.")
check(f"party alert by telepath ({out})", any(c.startswith("/Miserable Tracks: Mirage") for c in out))
# Paradigm's real track output (2026-10-25): one line per trail, gathered into one alert
st.track_alert_channel = "broadcast"
sent.clear()
feed("Imani went southeast from here.", "Imani went north from here.")
s.responses._pending_at -= 2; s.responses.tick()
check(f"Paradigm 'went ... from here' lines -> one alert with directions ({sent})",
      sent == ["br Tracks: Imani (southeast/north) near ?"])
print("ALL PASS" if ok else "SOME FAILED")
