"""ANSI SGR parser. Turns a raw stream into lines of (text, style) segments so the
terminal can colour them and the game parser can see plain text + colours."""
from __future__ import annotations

import re

_CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")

COLORS = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


class Style(tuple):
    """(fg 0-7 or None, bold)"""
    __slots__ = ()

    def __new__(cls, fg=None, bold=False):
        return tuple.__new__(cls, (fg, bold))

    @property
    def fg(self):
        return self[0]

    @property
    def bold(self):
        return self[1]

    @property
    def tag(self) -> str:
        return f"c{'x' if self.fg is None else self.fg}{'b' if self.bold else ''}"


class Screen:
    """A small VT100 screen (80×25) kept alongside the line stream. Full-screen BBS pages — MajorMUD's
    train stats / character editor, ANSI menus — draw by moving the cursor around; as lines those come
    out scrambled, so while one is up the window shows this grid instead."""
    def __init__(self, cols=80, rows=25):
        self.cols, self.rows = cols, rows
        self.clear()
        self.active = False           # a page is being drawn with cursor moves
        self.seq = 0                  # bumps on every change (redraw when it moves)
        self.rev = False              # reverse video (the highlighted field)
        self._saved = (0, 0)

    def clear(self):
        self.cells = [[(" ", None, False, False) for _ in range(self.cols)] for _ in range(self.rows)]
        self.r = self.c = 0

    def put(self, text, style):
        for ch in text:
            if ch == "\n":
                self.r = min(self.rows - 1, self.r + 1)
                if self.r == self.rows - 1 and not self.active:
                    self.cells.pop(0)
                    self.cells.append([(" ", None, False, False) for _ in range(self.cols)])
                continue
            if ch == "\r":
                self.c = 0
                continue
            if ch == "\x08":
                self.c = max(0, self.c - 1)
                continue
            if ch < " " and ch != "\t":
                continue
            if self.c >= self.cols:
                self.c = 0
                self.r = min(self.rows - 1, self.r + 1)
            self.cells[self.r][self.c] = (ch, style.fg, style.bold, self.rev)
            self.c += 1
        self.seq += 1

    def csi(self, params, final):
        nums = [int(x) if x.isdigit() else 0 for x in params.split(";")] if params else []
        n = (nums[0] if nums and nums[0] else 1)
        if final in ("H", "f"):
            row = (nums[0] if len(nums) > 0 and nums[0] else 1) - 1
            col = (nums[1] if len(nums) > 1 and nums[1] else 1) - 1
            self.r, self.c = max(0, min(self.rows - 1, row)), max(0, min(self.cols - 1, col))
            if params and (row or col):
                self.active = True        # absolute cursor moves (row;col): a full-screen page
                # (relative moves like ESC[79D ESC[K are just the game tidying its prompt line)
        elif final == "A":
            self.r = max(0, self.r - n)
        elif final == "B":
            self.r = min(self.rows - 1, self.r + n)
        elif final == "C":
            self.c = min(self.cols - 1, self.c + n)
        elif final == "D":
            self.c = max(0, self.c - n)
        elif final == "J":
            if params in ("2", ""):
                self.clear()
        elif final == "K":
            for x in range(self.c, self.cols):
                self.cells[self.r][x] = (" ", None, False, False)
        elif final == "s":
            self._saved = (self.r, self.c)
        elif final == "u":
            self.r, self.c = self._saved
        elif final == "m":
            codes = [int(c) if c.isdigit() else 0 for c in params.split(";")] if params else [0]
            for c in codes:
                if c == 0 or c == 27:
                    self.rev = False
                elif c == 7:
                    self.rev = True
        self.seq += 1

    def text_rows(self):
        return ["".join(ch for ch, *_ in row).rstrip() for row in self.cells]


class Line(list):
    """A finished line of (text, Style) pieces. `fresh` is True when the game tidied the line first (ESC[79D ESC[K):
    Paradigm does that before every new message. A wrapped piece of a long chat line has none, which is how a
    message padded to wrap as 'Evolution telepaths: @do …' on its second line is told apart from the real thing."""
    fresh = False


class AnsiStream:
    """Feed raw text; get back completed lines [(text, Style), ...] and the current
    partial line. Also reports screen clears."""

    def __init__(self):
        self.style = Style()
        self.cur: list = []
        self._cur_fresh = False
        self._pending = ""
        self.clear_requested = False
        self.screen = Screen()

    def feed(self, data: str) -> list:
        data = self._pending + data
        self._pending = ""
        # keep an incomplete escape for next time
        esc = data.rfind("\x1b")
        if esc != -1 and not _CSI.match(data, esc) and len(data) - esc < 16:
            self._pending = data[esc:]
            data = data[:esc]
        lines = []
        pos = 0
        for m in _CSI.finditer(data):
            self._text(data[pos:m.start()], lines)
            self.screen.put(data[pos:m.start()].replace("\x1b", ""), self.style)
            self._csi(m.group(1), m.group(2), lines)
            self.screen.csi(m.group(1), m.group(2))
            pos = m.end()
        self._text(data[pos:], lines)
        self.screen.put(data[pos:].replace("\x1b", ""), self.style)
        return lines

    def partial_text(self) -> str:
        return "".join(t for t, _ in self.cur)

    def _text(self, s: str, lines: list):
        if not s:
            return
        s = s.replace("\r\n", "\n").replace("\r", "")
        parts = s.split("\n")
        for i, p in enumerate(parts):
            p = p.replace("\x07", "").replace("\x1b", "")
            p = "".join(ch for ch in p if ch == "\t" or ch == "\x08" or ch >= " ")   # (0.8.200: keep backspaces —
            # Stock boards hide one inside direction words, 'n' 'Q' BS 'orth'; dropped here, exits read 'nQorth')
            if p:
                if p.endswith("\x08") or "\x08" in p:
                    for ch in p:
                        if ch == "\x08":
                            self._backspace()
                        else:
                            self._append(ch)
                else:
                    self._append(p)
            if i < len(parts) - 1:
                self._finish(lines)

    def _append(self, t: str):
        if self.cur and self.cur[-1][1] == self.style:
            self.cur[-1] = (self.cur[-1][0] + t, self.style)
        else:
            self.cur.append((t, self.style))

    def _backspace(self):
        if self.cur:
            t, st = self.cur[-1]
            t = t[:-1]
            if t:
                self.cur[-1] = (t, st)
            else:
                self.cur.pop()

    def _csi(self, params: str, final: str, lines: list):
        if final == "m":
            fg, bold = self.style
            codes = [int(c) if c.isdigit() else 0 for c in params.split(";")] if params else [0]
            for c in codes:
                if c == 0:
                    fg, bold = None, False
                elif c == 1:
                    bold = True
                elif c == 22:
                    bold = False
                elif 30 <= c <= 37:
                    fg = c - 30
                elif 90 <= c <= 97:
                    fg, bold = c - 90, True
                elif c == 39:
                    fg = None
            self.style = Style(fg, bold)
        elif final == "J" and params in ("2", ""):
            self.clear_requested = True
        elif final == "K":
            self._cur_fresh = True      # erase line: nothing to remove here, but it marks a new message (Line.fresh)
        elif final in ("H", "f") and self.cur:
            # cursor home on BBS screens: break line so text doesn't run together
            self._finish(lines)

    def _finish(self, lines: list):
        ln = Line(self.cur)
        ln.fresh = self._cur_fresh
        lines.append(ln)
        self.cur = []
        self._cur_fresh = False


def plain(segs) -> str:
    return "".join(t for t, _ in segs)
