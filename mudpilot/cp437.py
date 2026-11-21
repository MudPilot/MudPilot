"""IBM code page 437 — how BBS screens (box lines, blocks, ANSI art) reach the MUD window (0.8.201).

Bytes become text in exactly one place: telnet.TelnetClient._reader → decode() below. That has always been CP437
(bytes 0-127 are plain ASCII, so every game line the parsers see is the same text whatever this module does;
128-255 become the IBM PC glyphs: 0xC4 '─', 0xB3 '│', 0xDB '█', 0xB0 '░' …).

What Settings → Other → "BBS art (CP437)" switches is the drawing: the MUD window (and the full-screen page view)
uses a font that really has those glyphs at the same width as a letter, so boxes and block art line up instead of
drawing in a substitute font with gaps. Off (the default) = the MUD window font exactly as picked in Font….

`import encodings.cp437` is explicit so the compiled (Nuitka) build always carries the codec."""
from __future__ import annotations

import encodings.cp437  # noqa: F401  (explicit: the compiled build must keep this codec)

CODEC = "cp437"

# glyphs a BBS draws with: box lines (single/double), corners, tees, shades, blocks
SAMPLE = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬░▒▓█▀▄▌▐■"

# IBM PC fonts first when installed (the real DOS look), then common monospace fonts that carry the glyphs
FALLBACKS = ("Mx437 IBM VGA 8x16", "Px437 IBM VGA 8x16", "Perfect DOS VGA 437", "Perfect DOS VGA 437 Win",
             "Consolas", "Lucida Console", "Cascadia Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New")


def decode(data: bytes) -> str:
    """Raw bytes from the BBS → text. CP437 has a character for every byte, so nothing is ever replaced."""
    return data.decode(CODEC, errors="replace")


def lines_up(root, family: str, size: int = 12) -> bool:
    """True when this font draws every SAMPLE glyph exactly as wide as a letter (no fallback-font gaps)."""
    try:
        import tkinter.font as tkfont
        f = tkfont.Font(root=root, family=family, size=size)
        if f.actual("family").lower() != family.lower():
            return False                       # not installed: Tk swapped in something else
        cell = f.measure("M")
        return cell > 0 and all(f.measure(ch) == cell for ch in SAMPLE)
    except Exception:
        return False


_picked: dict = {}


def pick_font(root, family: str, size: int = 12) -> str:
    """The MUD-window font for CP437 mode: an IBM PC font if one is installed, else your own font when it already
    lines the glyphs up, else the first fallback that does. Never fails — worst case it's your own font."""
    key = (family, size)
    if key in _picked:
        return _picked[key]
    out = None
    for fam in FALLBACKS[:4]:
        if lines_up(root, fam, size):
            out = fam
            break
    if out is None and family and lines_up(root, family, size):
        out = family
    if out is None:
        out = next((fam for fam in FALLBACKS[4:] if lines_up(root, fam, size)), None) or family or "Consolas"
    _picked[key] = out
    return out
