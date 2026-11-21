"""Dan, 2026-11-01: '@level / @exp answers scroll away — put them in the conversation box' — but not the party-sync
chatter ('@mpsync sk …' every fight, '{mpsync ok}', '@rego', '{AFK}': "this is excessive"). Bot traffic stays hidden
by default; what you asked, and the answers to it, always show."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.chat import ChatLog
from mudpilot.windows import ChatPane
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


check("bot traffic hidden by default", config.Settings().chat_show_bot is False)
c = ChatLog()
shown = lambda: [e[3] for e in c.entries if not ChatPane.is_bot(e[3]) or c.you_asked(e)]
c.note_sent(".@level")
for ln in ['You say "@level"', 'Revolution says (to you) "{level 47, 12% to 48}"', 'Evolution says (to you) "{level 16}"',
           'Revolution telepaths: @mpsync sk 3|25|0|0|nightshade', 'Revolution telepaths: {mpsync ok 0.8.137 tune}',
           'Revolution telepaths: @rego', 'Revolution telepaths: {AFK}']:
    c.feed(ln)
s = shown()
check(f"asked the room: the question and both answers show ({s})",
      "@level" in s and "{level 47, 12% to 48}" in s and "{level 16}" in s)
check("…the party-sync chatter doesn't", not any(x.startswith(("@mpsync", "{mpsync", "@rego", "{AFK")) for x in s))
c.note_sent("/revolution @exp")
c.feed("Revolution telepaths: {exp 1,234,567}")
check(f"telepathed question: its answer shows ({shown()[-1]})", shown()[-1] == "{exp 1,234,567}")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
