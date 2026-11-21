"""Full-screen pages (train stats / character editor) are kept as an 80×25 screen, not scrambled lines."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
a = s.ansi
for segs in a.feed("[HP=682/MA=453]:\x1b[79D\x1b[KRevolution casts nature tap on Revolution!\r\n"):
    s._line(segs)
check("the game tidying its prompt line isn't a full-screen page", not a.screen.active)
page = ("\x1b[2J\x1b[1;1H/ P A R A D I G M      Char. Creation /"
        "\x1b[4;5H\x1b[36m» Given Name\x1b[4;30H\x1b[0mMiserable\x1b[5;5H\x1b[36m» Family Name\x1b[5;30H\x1b[7mRevolution\x1b[0m"
        "\x1b[9;5H» Strength\x1b[9;22H(  40 to  140)\x1b[9;40H  80")
for segs in a.feed(page):
    s._line(segs)
rows = a.screen.text_rows()
check("cursor-drawn page is a screen", a.screen.active)
check("fields land on their rows", rows[3].strip().startswith("» Given Name") and rows[3].rstrip().endswith("Miserable"))
check("…and columns", rows[8][21:35] == "(  40 to  140)" and rows[8].rstrip().endswith("80"))
check("the field you're on is highlighted", any(c[3] for c in a.screen.cells[4][29:39]))
for segs in a.feed("\x1b[2J\r\n[HP=682/MA=453]:Ancient Keep, Throne Room\r\n"):
    s._line(segs)
check("back at a game prompt: normal screen again", not a.screen.active)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
