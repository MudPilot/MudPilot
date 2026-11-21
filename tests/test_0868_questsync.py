"""0.8.168 (Dan, 2026-11-09): party MudPilots tell each other their quest flags - all of them once a session, then
each change ("Revolution's quest flag: DaoLordQuest 12 -> 13"). The leader's quest-style command (say / ask / give...)
has the party check theirs for 10 minutes. And the first 'abil' of a session waits for a quiet moment: not straight
after a hang-up on PvP, or getting in hurt."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def mk(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    s.sent, s.logs = [], []
    s.send = lambda c, from_bot=False, s=s: s.sent.append(c)
    s.log = lambda m, *a, **k: s.logs.append(m)
    s.bot.log = s.log
    s.notify.send = lambda kind, msg, force=False, s=s: s.logs.append(f"NOTIFY {kind}: {msg}")
    return s

lead, fol = mk("Miserable"), mk("Revolution")
lead.state.party = {"Miserable": {}, "Revolution": {}}
fol.state.party = {"Miserable": {}, "Revolution": {}}
lead.partysync.peers["Revolution"] = {"rest": 0, "hp": 100, "ma": 100, "t": time.time()}
fol.partysync.peers["Miserable"] = {"rest": 0, "hp": 100, "ma": 100, "t": time.time()}
fol.bot.x._following = "Miserable"
dao = 134
fol.state.abil_names[dao] = "DaoLordQuest"
lead.state.abil_names[dao] = "DaoLordQuest"

def deliver(src, dst):
    """The telepaths src sent to dst's name: run them through dst's party sync."""
    out = [c for c in src.sent if c.lower().startswith(f"/{dst.settings.my_name.lower()} @mpsync ")]
    src.sent[:] = [c for c in src.sent if c not in out]
    for c in out:
        dst.partysync.command(src.settings.my_name, c.split("@mpsync ", 1)[1])
    return out

# ---- the first read of the session: all flags go to the teammate once
fol.settings.known_abils = {str(dao): 12}
fol.partysync.quest_read({str(dao): 12, "145": 5})        # 145 = ManaRegen: not a quest flag
sent = deliver(fol, lead)
check(f"first read: quest flags told once ({sent})", sent == ["/Miserable @mpsync q 134=12"])
check(f"…the leader logs them ({lead.logs[-1:]})", lead.logs and "DaoLordQuest 12" in lead.logs[-1])
fol.partysync.quest_read({str(dao): 12})
check("…not again on the next read", not deliver(fol, lead))

# ---- a flag goes up: the leader's MudPilot says so and alerts
fol.bot._new_quest_flags({str(dao): 13}, {str(dao): 12})
sent = deliver(fol, lead)
check(f"flag up: told by party sync ({sent})", sent == ["/Miserable @mpsync q 134=13"])
check(f"…no old-style '{{Quest flag:}}' telepath to a MudPilot leader ({fol.sent})", not fol.sent)
check(f"…the leader logs who went up ({lead.logs[-2:]})",
      any("Revolution's quest flag: DaoLordQuest 12" in m and "13" in m for m in lead.logs))
check("…and alerts (kind 'quest')", any(m.startswith("NOTIFY quest:") for m in lead.logs))
check(f"…kept: quest_flags() {lead.partysync.quest_flags()}", lead.partysync.quest_flags().get("Revolution", {}).get("134") == 13)

# a MegaMUD leader (no party sync): the old telepath
fol.partysync.peers.clear()
fol.bot._new_quest_flags({str(dao): 14}, {str(dao): 13})
check(f"MegaMUD leader: '{{Quest flag: ...}}' as before ({fol.sent})", fol.sent and "{Quest flag:" in fol.sent[-1])
fol.sent.clear()
fol.partysync.peers["Miserable"] = {"rest": 0, "hp": 100, "ma": 100, "t": time.time()}

# ---- the leader's quest-style command: the party checks for a while
lead.bot.note_quest_cmd("ask sphinx stars")
sent = deliver(lead, fol)
check(f"leader's 'ask': the party is asked to watch ({sent})", sent == ["/Revolution @mpsync qwatch 600"])
check("…the follower watches for 10 min", fol.bot._quest_watch_until > time.time() + 590)
lead.bot.note_quest_cmd("say hello")
check("…not asked again within the minute", not deliver(lead, fol))
fol.bot.note_quest_cmd("ask sphinx stars")
check("following: our own 'ask' doesn't send a watch", not [c for c in fol.sent if "qwatch" in c])

# ---- reading 'abil': quiet moments only; the first one not straight after getting in
b, g = fol.bot, fol.state
now = time.time()
fol._connected_at = now - 5
b._abil_read = None
b.ready = lambda *a, **k: True
g.hp, g.max_hp, g.last_prompt = 700, 700, now
g.in_combat, g.resting = False, False
g.pending.clear()
g.view = RoomView("Great Pyramid", {"N"}, [], [], [], now)
check("just logged in (5 s): no 'abil' yet", not b._read_quest_flags() and "abil" not in fol.sent)
fol._connected_at = now - 60
g.hp = 300
check("in a minute, but hurt (43%): not yet", not b._read_quest_flags() and "abil" not in fol.sent)
g.hp = 700
g.view = RoomView("Great Pyramid", {"N"}, [], [], ["Badguy"], now)
check("a stranger in the room: not yet", not b._read_quest_flags() and "abil" not in fol.sent)
g.view = RoomView("Great Pyramid", {"N"}, [], [], ["Revolution", "Miserable"], now)
fol._connected_at = now - 400
check("quiet (only the party here): reads it", b._read_quest_flags() and fol.sent[-1:] == ["abil"])
# ...and while watching, again every 30 s
b._abil_read = ("done", time.time() - 31)
b._quest_poke = 0
b._quest_watch_until = time.time() + 300
fol.sent.clear()
check("watching: read again after 30 s", b._read_quest_flags() and fol.sent[-1:] == ["abil"])
b._abil_read = ("done", time.time() - 31)
b._quest_watch_until = 0
fol.sent.clear()
check("not watching: not every 30 s", not b._read_quest_flags() and not fol.sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
