"""0.8.201: chat keyword alerts (Settings → Phone alerts → Chat keywords; off by default). A gossip / auction / telepath /
say / broadcast line from another player with one of the words is logged highlighted and sent to ntfy (if set up),
at most one phone alert a minute; your own lines, bot chatter and other text never count."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot import chatalerts as CA
from mudpilot import notify as N

ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
check("off by default, no words", st.chat_alerts_on is False and st.chat_alert_words == [])
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.chat._write = lambda *a: None                        # never writes data\chat
logs = []
s.on_log = lambda m: logs.append(m)
posts = []
N.get_topic = lambda: "test-topic"
real_thread = N.threading.Thread


class NoThread:                                        # never really posts: record what would go
    def __init__(self, target=None, daemon=None): self.t = target
    def start(self): posts.append(time.time())


N.threading.Thread = NoThread


class FakeTel:
    connected = True
    def send_line(self, x): pass
    events = __import__("queue").Queue()
    def close(self): pass


s.telnet = FakeTel()


def feed(*lines):
    for l in lines:
        s._line([(l, Style())])


def hits():
    return [m for m in logs if CA.LOG_MARK in m]


feed("Phrixas gossips: anyone selling a kraken pearl?")
check("default off: nothing flagged", not hits() and not posts)

st.chat_alerts_on = True
st.chat_alert_words = ["kraken pearl", "Raid", "Miserable"]
st.ntfy_on = True
feed("Phrixas gossips: anyone selling a kraken pearl?")
check(f"gossip with a phrase flagged ({hits()[-1:] })", len(hits()) == 1 and "Phrixas (gossip)" in hits()[0])
check(f"…and one phone alert ({len(posts)})", len(posts) == 1)
feed("Bob auctions: RAID at the pyramid tonight")
check("auction, any case: logged", len(hits()) == 2)
check("…but no second phone alert within a minute", len(posts) == 1)
feed("Bob telepaths: are you raiding?")
check("whole words only ('raiding' isn't 'raid')", len(hits()) == 2)
feed("You say \"raid time\"", "You gossip: raid", "Miserable gossips: raid now")
check("your own lines never count", len(hits()) == 2)
feed("Revolution telepaths: @do say raid", "Revolution telepaths: {raid ok}")
check("party bot chatter never counts", len(hits()) == 2)
feed("The raid troll hits you for 5 damage!")
check("plain game text never counts", len(hits()) == 2)
feed('Broadcast from Sysop "Raid event in 5 minutes"', 'Tom says "hey Miserable"')
check("broadcast + say flagged", len(hits()) == 4)
# rate limit: past the minute → another phone alert; same word+player inside 10 min → not again
s.chatalerts._phone_last -= 61
s.notify._last.clear()
feed("Phrixas gossips: still want a kraken pearl")
check("same word, same player within 10 min: logged, not phoned", len(hits()) == 5 and len(posts) == 1)
feed("Zed gossips: kraken pearl for sale")
check("another player after a minute: phoned", len(posts) == 2)
s.chatalerts._phone_last -= 61; s.notify._last.clear()
st.ntfy_on = False
feed("Amy gossips: raid!")
check("ntfy off: logged only", len(hits()) == 7 and len(posts) == 2)
st.chat_alerts_on = False
feed("Amy gossips: raid again")
check("switched off: nothing", len(hits()) == 7)
check("a crashing check never drops the listener", s.chatalerts.on_chat in s.chat.listeners)
check("chat isn't one of the ticked phone kinds (own switch)", "chat" not in N.KINDS and "chat" not in st.ntfy_kinds)
N.threading.Thread = real_thread
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
