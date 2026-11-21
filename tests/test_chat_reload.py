"""Dan, 2026-11-15: after an update the chat box started empty, halfway through a gossip conversation.
The last few hours from data/chat go back in at startup, with a 'restarted' line under them."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import chat
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

d = tempfile.mkdtemp()
now = time.time()
def stamp(secs_ago):
    return time.strftime("%H:%M:%S", time.localtime(now - secs_ago))
today = os.path.join(d, time.strftime("%Y-%m-%d", time.localtime(now)) + ".log")
lines = [f"{stamp(20 * 3600)} [gossip] Oldtimer: from long ago",
         f"{stamp(600)} [gossip] Phrixas: anyone seen the dark phoenix?",
         f"{stamp(300)} [telepath] You → Revolution: on my way",
         f"{stamp(120)} [say] Revolution: @ok"]
if time.localtime(now - 20 * 3600).tm_mday != time.localtime(now).tm_mday:
    lines = lines[1:]                     # (20 h ago was yesterday: leave it out of today's file)
with open(today, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

c = chat.ChatLog()
n = c.load_recent(folder=d)
whos = [e[2] for e in c.entries]
check(f"the last 12 hours come back ({n}: {whos})", n == 2 and "Phrixas" in whos and "Oldtimer" not in whos)
check("…without the party's @ok chatter", "Revolution" not in whos)
check("…the telepath keeps its 'You → Revolution'", any(e[2] == "You → Revolution" and e[3] == "on my way"
                                                        for e in c.entries))
check("…in order, with the restart line under them", c.entries[-1][1] == "restart" and
      [e[0] for e in c.entries[:-1]] == sorted(e[0] for e in c.entries[:-1]))
before = open(today, encoding="utf-8").read()
c2 = chat.ChatLog(); c2.load_recent(folder=d)
check("…and nothing written to the log again", open(today, encoding="utf-8").read() == before)
check("no chat folder: nothing, no error", chat.ChatLog().load_recent(folder=os.path.join(d, "none")) == 0)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
