"""Dan, 2026-11-01: someone moved into the Glades loop. Sharing rooms is fine (Miserable's area spell takes most of a
room); trailing him into lairs he just cleared isn't. Twice in a few minutes → catch him up and share his rooms (0.8.141: never
wait for him to get ahead)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, sc = s.bot, s.state, s.scripters
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


b.walking, b.loop = True, True
b.x.leading = lambda: True
g.max_hp, g.hp, g.max_ma, g.ma = 600, 500, 400, 300
# he's seen walking through two lairs ahead of us
for room in ((17, 1630), (17, 1631)):
    g.candidates = [room]
    g.view = RoomView("Glade", {"N"}, [], [], ["Zimmer"], time.time())
    sc.on_room(g)
g.view = RoomView("Glade", {"N"}, [], [], [], time.time())
sc.seen["Zimmer"] = {k: time.time() - 90 for k in sc.seen["Zimmer"]}     # 90 s ahead: a way off
sc.lair_empty((17, 1630))
check("one empty lair he'd just been in: noted, nothing yet", not sc.hold and not sc.chase)
sc.lair_empty((17, 1631))
check(f"two, 90 s ahead: catch him up, never wait ({sc.chase and sc.chase['name']}, hold {sc.hold})",
      sc.catching_up() and not sc.hold)
sent.clear()
check("…no resting for him", not sc.holding([]) and not sent)
g.candidates = [(17, 1632)]
sc.feed_line("Zimmer walks into the room from the south.")
check("caught up with him: sharing his rooms", not sc.catching_up())
# only just ahead (cleared it under a minute ago): catch up — no pacing stops — instead of waiting a lap
sc.hits, sc._waited, sc.hold = {}, {}, None
for room in ((17, 1650), (17, 1651)):
    g.candidates = [room]
    g.view = RoomView("Glade", {"N"}, [], [], ["Zed"], time.time())
    sc.on_room(g)
g.view = RoomView("Glade", {"N"}, [], [], [], time.time())
sc.seen["Zed"][(17, 1650)] = time.time() - 20
sc.seen["Zed"][(17, 1651)] = time.time() - 20
sc.lair_empty((17, 1650)); sc.lair_empty((17, 1651))
check(f"20 s ahead: catch up, not wait ({sc.chase and sc.chase['name']}, hold {sc.hold})", sc.catching_up() and not sc.hold)
g.candidates = [(17, 1652)]
sc.feed_line("Zed walks into the room from the north.")
check("caught up: sharing his rooms", not sc.catching_up())
# a lair empty that nobody else was in: our own business, no wait
sc.hits, sc._waited, sc.chase = {}, {}, None
sc.lair_empty((17, 1700)); sc.lair_empty((17, 1701))
check("empty lairs nobody else was in: nothing", not sc.hold and not sc.chase)
# party members never count
g.party = {"Miserable": {}, "Revolution": {}}
g.candidates = [(17, 1640)]
g.view = RoomView("Glade", {"N"}, [], [], ["Revolution"], time.time()); sc.on_room(g)
sc.lair_empty((17, 1640)); sc.lair_empty((17, 1640))
check("a party member clearing ahead isn't a scripter", not sc.hold and not sc.chase)
# 0.8.135, Miserable: "Letting Revolution come round" — a MudPilot partner, party list empty after a restart
g.party = {}; sc.hits, sc._waited, sc.hold, sc.chase = {}, {}, None, None
s.partysync.peers = {"Revolution": {"t": time.time()}}
for room in ((17, 1660), (17, 1661)):
    g.candidates = [room]; g.view = RoomView("Glade", {"N"}, [], [], ["Revolution"], time.time()); sc.on_room(g)
sc.lair_empty((17, 1660)); sc.lair_empty((17, 1661))
check("a MudPilot partner is never another scripter", not sc.hold and not sc.chase)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
