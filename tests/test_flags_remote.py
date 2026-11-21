"""Dan, 2026-11-04: '@flags' — ask a character for its quest flags by telepath (Window → Quest guide only before)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
r, b = s.remote, s.bot
st.known_abils = {}
out = r.c_flags("Dan", "")
check(f"none known: says it's reading them ({out})", "reading them now" in out and b._quest_poke > 0)
st.known_abils = {"134": 9, "145": 5}                    # 145 = ManaRegen, not a quest flag
s.state.abil_names[134] = "DaoLordQuest"
b._abil_read = ("done", time.time() - 600)
b._quest_poke = 0
out = r.c_flags("Dan", "")
check(f"lists the quest flags only, with how old ({out})", out.startswith("quest flags (read 10m")
      and "DaoLordQuest (134) = 9" in out and "145" not in out)
check("…and asks for 'abil' again", b._quest_poke > 0)
out = r.c_flags("Dan", "dao")
check(f"one by name ({out})", out[0].startswith("DaoLordQuest (134) = 9"))
out = r.c_flags("Dan", "126")
check(f"one not set, with MME's next step ({out})", "not set" in out[0] and "next step" in out[0] and "—" not in out[0])
check(f"unknown name ({r.c_flags('Dan', 'zzqq')})", "no quest flag" in r.c_flags("Dan", "zzqq"))
# Dan, 2026-11-04: at 9 it said Orfeo (who wants 11); the pharaoh and the dao were missing (death spells)
w = s.world
check(f"9 -> the pharaoh ({w.quest_hint(134, None, 9)})", "Pharaoh Rastep" in w.quest_hint(134, None, 9))
check(f"10 -> the Dao Lord ({w.quest_hint(134, None, 10)})", "Dao Lord" in w.quest_hint(134, None, 10))
check("11 -> Orfeo", "Orfeo" in w.quest_hint(134, None, 11))
check("12 -> finished: no next step", w.quest_hint(134, None, 12) == "")
st.known_abils = {"134": 12}
check(f"@flags at 12 says done, one line ({r.c_flags('Dan', '134')})",
      r.c_flags("Dan", "134") == ["DaoLordQuest (134) = 12 - done"])
st.known_abils = {"134": 11}
check("…and an answer fits one telepath line (no '{= 11}' tail)", all(len(x) <= 115 for x in r.c_flags("Dan", "134")))
# AFK: never answer a bot's '{…}' (three AFK characters bounced '{AFK}' around)
sent = []
s.send = lambda c, **k: sent.append(c)
st.afk, st.afk_message = True, "{AFK}"
s.remote.feed_line("Revolution telepaths: {= 11}")
s.remote.feed_line("Evolution telepaths: {AFK}")
check(f"AFK: no reply to a '{{…}}' answer ({sent})", not any("AFK" in c for c in sent))
s.remote.feed_line("Roadkill telepaths: you there?")
check(f"…but a person still gets one ({sent})", any(c.startswith("/Roadkill") and "AFK" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
