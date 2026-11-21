"""who → Game Data players (gang, title, alignment) and the last-10-places log."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.learn_players = False
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T(); s._want_connected = True
s.players.save = lambda: None
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
src = os.path.join(os.path.dirname(__file__), "who_sample.txt")
feed(*open(src).read().splitlines(), "[HP=600/MA=300]:")
s.players._who["t"] -= 2; s.players.tick()
P = s.players.data
check(f"everyone added ({len(P)})", len(P) >= 135)
def g(n): return P[n.lower()]
check("Arlionnica: FIEND, Prestige Worldwide", g("Arlionnica")["gang"] == "Prestige Worldwide" and g("Arlionnica")["alignment"] == "FIEND")
check(f"Danger Ranger: Order of the Bogan ({g('danger')['gang']})", g("danger")["gang"] == "Order of the Bogan" and g("danger")["surname"] == "Ranger")
check(f"Brackle: Master of the Way / No, Vegans Allowed ({g('brackle')})",
      g("brackle")["gang"] == "No, Vegans Allowed" and g("brackle")["title"] == "Master of the Way")
check(f"Jester: Sword of Justice / Flat Moon Society", g("jester")["gang"] == "Flat Moon Society" and g("jester")["title"] == "Sword of Justice")
check(f"Blackath: Whisper of Death ({g('blackath')})", g("blackath")["gang"] == "Prestige Worldwide" and g("blackath")["who_flag"] == "x")
check(f"Dark Rhel: Wizard of ID ({g('dark')['gang']})", g("dark")["gang"] == "Wizard of ID")
check("Astro: no gang, title Sensei", g("astro")["gang"] == "" and g("astro")["title"] == "Sensei")
check("Guntz: Criminal", g("guntz")["alignment"] == "Criminal" and g("guntz")["gang"] == "Wild HoGs")
check("Fenix (line after it is a [updated] note)", g("fenix")["title"] == "Magehunter")
check("Ire I: Mistress of the Way", g("ire")["title"] == "Mistress of the Way" and g("ire")["gang"] == "The Undutchables")
check("Zyxyz last line", g("zyxyz")["title"] == "Cardinal")
# places
w = s.world
rooms = [k for k, r in w.rooms.items() if r.name][:2]
def visit(k, n):
    s.state.candidates = [k]
    s.state.view = type(s.state.view or object)  if False else None
    from mudpilot.gamestate import RoomView
    s.state.view = RoomView(w.room(k).name, {"north"}, players=[n])
    s.players.on_room(s.state)
visit(rooms[0], "Miser")
visit(rooms[0], "Miser")          # same visit
m = P["miser"]
check("standing there counts once", m["places"][0][1] == 1)
m["_place_at"] = time.time() - 3600
visit(rooms[0], "Miser")
check("seen there again later: ×2", m["places"][0][1] == 2)
visit(rooms[1], "Miser")
check("newest place first", m["places"][0][0] == w.room(rooms[1]).name and len(m["places"]) == 2)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
