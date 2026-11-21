"""0.8.201: CP437 / BBS art. Bytes become text in one place (telnet → cp437.decode); 128-255 are the IBM PC glyphs
(box lines, blocks), 0-127 plain ASCII, so every game line the parsers see is the same text whatever the setting.
The setting (Settings → Other → BBS art (CP437), default off) only changes the MUD window's font."""
import os, sys, socket, time, queue
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, cp437, telnet
from mudpilot.ansi import AnsiStream, plain
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

check("codec imported explicitly (compiled build keeps it)", "encodings.cp437" in sys.modules)

# ---- decoding: the glyphs
box = bytes([0xC9, 0xCD, 0xCD, 0xBB, 0x0D, 0x0A, 0xBA, 0x20, 0x20, 0xBA, 0x0D, 0x0A, 0xC8, 0xCD, 0xCD, 0xBC])
check("double box → ╔══╗ ║  ║ ╚══╝", cp437.decode(box) == "╔══╗\r\n║  ║\r\n╚══╝")
check("single lines, tees, cross", cp437.decode(bytes([0xDA, 0xC4, 0xC2, 0xBF, 0xB3, 0xC3, 0xC5, 0xB4, 0xC0, 0xC1, 0xD9]))
      == "┌─┬┐│├┼┤└┴┘")
check("shades and blocks", cp437.decode(bytes([0xB0, 0xB1, 0xB2, 0xDB, 0xDF, 0xDC, 0xDD, 0xDE, 0xFE])) == "░▒▓█▀▄▌▐■")
check("accents / symbols (0x80-0xAF)", cp437.decode(bytes([0x80, 0x81, 0x9B, 0x9C, 0xE1, 0xF8])) == "Çü¢£ß°")
every = cp437.decode(bytes(range(256)))
check("every byte is one character, none replaced", len(every) == 256 and "�" not in every)
check("unchanged from before 0.8.201 (same as bytes.decode('cp437'))",
      all(cp437.decode(bytes([b])) == bytes([b]).decode("cp437", "replace") for b in range(256)))
check("0-127 is plain ASCII", cp437.decode(bytes(range(128))) == bytes(range(128)).decode("ascii"))

# ---- through the real telnet reader (IAC handling included)
a, b = socket.socketpair()
t = telnet.TelnetClient()
t.adopt(a)
game = (b"\x1b[0;32mObvious exits: north, south, east, west\x1b[0m\r\n"
        b"[HP=806/MA=588]: (Meditating)\r\n"
        b"\x1b[1;33mYou notice 12 gold crowns here.\x1b[0m\r\n")
art = b"\x1b[1;34m\xc9\xcd\xcd\xcd\xbb\r\n\xba \xdb\xb2 \xba\r\n\xc8\xcd\xcd\xcd\xbc\x1b[0m\r\n"
b.sendall(game + b"\xff\xff" + art)       # (IAC IAC = a literal 0xFF byte: CP437's non-breaking space)
got, end = "", time.time() + 5
while time.time() < end and not ("╝" in got and got.endswith("\r\n")):
    try:
        k, d = t.events.get(timeout=0.2)
        if k == "data":
            got += d
    except queue.Empty:
        pass
t.close(); b.close()
check("telnet: ASCII game text comes through byte for byte", got.startswith(game.decode("ascii")))
check("telnet: box art comes through as glyphs", "╔═══╗" in got and "║ █▓ ║" in got and "╚═══╝" in got)
check("telnet: IAC IAC → 0xFF (CP437 nbsp)", " " in got)

# ---- the parsers see the same plain text for game lines (the setting never touches this path)
for setting in (False, True):
    st = config.Settings(); st.save = lambda: None
    st.cp437_terminal = setting
    a2 = AnsiStream()
    lines = [plain(x) for x in a2.feed(got)]
    check(f"setting {'on' if setting else 'off'}: game lines parse to the same plain text",
          lines[:3] == ["Obvious exits: north, south, east, west", "[HP=806/MA=588]: (Meditating)",
                        "You notice 12 gold crowns here."] and lines[3] == " ╔═══╗" and lines[4] == "║ █▓ ║")
    segs = AnsiStream().feed(got)
    check(f"setting {'on' if setting else 'off'}: colours kept on the art (bold blue)",
          any("╔" in tx and sty.fg == 4 and sty.bold for ln in segs for tx, sty in ln))

# ---- the setting: default off, font only
st = config.Settings(); st.save = lambda: None
check("BBS art (CP437) is off by default", st.cp437_terminal is False)
import tkinter as tk
from mudpilot import app as A
root = tk.Tk(); root.withdraw()
o = A.App.__new__(A.App)
o.root = root
class _S: pass
o.s = _S(); o.s.settings = st
st.term_font, st.term_font_size = "Courier New", 13
check("off: the MUD window font is exactly the one picked", o._term_font() == ("Courier New", 13))
st.cp437_terminal = True
fam, size = o._term_font()
check(f"on: a font that lines the glyphs up ({fam} {size})", size == 13 and (cp437.lines_up(root, fam, size)
      or not any(cp437.lines_up(root, f, size) for f in cp437.FALLBACKS)))
check("on: junk font name never breaks it", isinstance(cp437.pick_font(root, "No Such Font 123", 12), str))
st.cp437_terminal = False
check("off again: back to the picked font", o._term_font() == ("Courier New", 13))
root.destroy()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
