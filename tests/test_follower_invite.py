"""Buddy, 2026-10-30, after a restart: invited Revolution (its leader), which started a party of its own — then every
'join Revolution' got "You must disband your own party first!" and they invited each other for minutes. A follower
never invites its leader, its restart gathers no party, and 'disband your own party first' → disband, join."""
import os, sys, time, json, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
sent = []
s.telnet.send_line = lambda c: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


c = s.control
c.dir = tempfile.mkdtemp()
json.dump({"t": time.time(), "connected": True, "walking": False, "party": ["Revolution", "Evolution"],
           "follow": "Revolution"}, open(os.path.join(c.dir, "resume.json"), "w", encoding="utf-8"))
c.load_resume()
check("a follower's restart gathers no party of its own",
      not getattr(s, "_regroup", None) and not getattr(s, "_reinvite", None))
sent.clear()
s.send("invite Revolution", from_bot=True)
check(f"never invites the leader it's rejoining ({sent})", not any(x.startswith("invite") for x in sent))
s.send("join Revolution", from_bot=True)
sent.clear()
s._line([("You must disband your own party first!", Style())])
check(f"'disband your own party first' → disband, join ({sent})", sent[:2] == ["disband", "join Revolution"])
# @join: just join and check the party — no telepath back
s.remote._channel = "telepath"
st.remote_players = {"Revolution": ["query", "location", "invite", "move"]}
sent.clear()
s.remote.feed_line("Revolution telepaths: @join")
check(f"@join: join + par, no '{{joining …}}' telepath ({sent})",
      sent[:2] == ["join Revolution", "par"] and not any(x.startswith("/") for x in sent))
# on the way to the leader, walked into them: stop
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import MPath
b = s.bot
s._rejoin = None
s.comeback.fetch = {"name": "Revolution", "phase": "going", "room": (2, 489), "back": None, "t": time.time(),
                    "no_invite": True}
b.walking, b.path = True, MPath("Go to 2/489", "MudPilot", "", "")
s.state.candidates = [(2, 488)]
s.state.view = RoomView("Dragon's Teeth Hills", {"N"}, [], [], ["Revolution"], time.time())
s.comeback.tick()
check(f"walked into the leader on the way: stops there ({b.walking}, {b.status})", not b.walking)
# leader: invited and not following yet → the walk waits; 'X started to follow you.' = joined, no par needed
lead = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); lead._no_log_file = True
lead.telnet.sock = object(); ls_ = []; lead.telnet.send_line = lambda c: ls_.append(c)
lead.settings.my_name = "Revolution"; lead.settings.invite_join_cmd = "/{name} @join"
lead.state.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
lead.bot.x._following = None
lead.bot.x.leading = lambda: True
lead._invite_pending = time.time()
lead._line([("You have invited Buddy to follow you.", Style())])
lead._invite_pending = time.time()
lead._line([("You have invited Evolution to follow you.", Style())])
lead.bot.walking = True
lead.bot.walk([], True)
check(f"invited, not following yet: the walk waits ({lead.bot.status})", "Waiting for" in lead.bot.status)
lead._line([("Buddy started to follow you.", Style())])
lead._line([("Evolution started to follow you.", Style())])
check(f"both started to follow: nobody left to wait for ({lead._join_watch})", not lead._join_watch)
ls_.clear(); lead._invite_pending = time.time()
lead._line([("You have invited Buddy to follow you.", Style())])
check(f"no @join to someone already following ({ls_})", not any("@join" in c for c in ls_))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
