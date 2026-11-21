"""Aliases (0.8.201): a short word you type expands to one or more commands.

  bs        -> bash door
  k $1      -> kill $1           ("k orc" sends "kill orc")
  gp        -> get all^Mput all in sack   (^M or ; = next command)

$1..$9 are the words typed after the alias, $* is all of them. With no $ in the expansion, whatever
you typed after the alias goes on the end of the last command ("k orc" with k -> kill = "kill orc").

Only what YOU type (the command line, a macro key) expands. Remote commands from other players
(@do and friends) go straight to session.send() and never come through here.
Saved per character in settings.aliases ({name: expansion}); Game Data → Aliases edits them.
"""
from __future__ import annotations

import re

# words that already mean something to the game's chat / MudPilot's remote: an alias with one of these names
# would swallow what you meant to say (MudPlay refuses them too)
RESERVED = {"gos", "gossip", "say", "br", "broadcast", "auc", "auction", "bg", "gangpath", "tele", "telepath",
            "yell", "sys", "who", "top", "quit", "pro"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,19}$")
MAX_DEPTH = 4            # an alias may use another alias, this many deep (and never itself)
MAX_STEPS = 20           # one typed word never sends more than this many commands


def name_problem(name: str, aliases: dict | None = None, old: str | None = None) -> str | None:
    """Why this can't be an alias name, or None if it's fine."""
    n = (name or "").strip()
    if not NAME_RE.match(n):
        return "An alias is one word: letters first, then letters / digits / - / _ (up to 20)."
    if n.lower() in RESERVED:
        return f"'{n}' is a game command (chat, who, quit…) — pick another word."
    if any(k.lower() == n.lower() and (old is None or k.lower() != old.lower()) for k in (aliases or {})):
        return f"There's already an alias called '{n}'."
    return None


def _split(text: str, splitter: str = ";") -> list:
    """'get all^Mput all in sack' / 'a;b' -> steps. ';;' is a real ';'."""
    out = []
    for part in (text or "").replace("^m", "^M").split("^M"):
        if splitter and splitter in part:
            esc = "\x00"
            out += [p.replace(esc, splitter) for p in part.replace(splitter + splitter, esc).split(splitter)]
        else:
            out.append(part)
    return [p.strip() for p in out if p.strip()]


def _find(aliases: dict, word: str):
    w = word.lower()
    for k, v in (aliases or {}).items():
        if k.lower() == w:
            return k, v
    return None, None


def substitute(expansion: str, rest: str) -> str:
    args = rest.split()
    if not re.search(r"\$(\d|\*)", expansion):
        return expansion + (" " + rest if rest else "")

    def one(m):
        if m.group(1) == "*":
            return rest
        i = int(m.group(1))
        return args[i - 1] if 0 < i <= len(args) else ""
    return re.sub(r"\$(\d|\*)", one, expansion)


def expand(cmd: str, aliases: dict | None, splitter: str = ";", _depth: int = 0, _seen: tuple = ()) -> list:
    """One typed command -> the commands to send (the command itself if it isn't an alias)."""
    if not aliases or not cmd or not cmd.strip():
        return [cmd]
    m = re.match(r"^\s*(\S+)\s*(.*?)\s*$", cmd)
    name, body = _find(aliases, m.group(1))
    if name is None or name.lower() in _seen or _depth > MAX_DEPTH:
        return [cmd]
    steps = _split(substitute(body or "", m.group(2)), splitter)
    out = []
    for st in steps:
        out += expand(st, aliases, splitter, _depth + 1, _seen + (name.lower(),))
        if len(out) >= MAX_STEPS:
            break
    out = [re.sub(r" {2,}", " ", x).strip() for x in out[:MAX_STEPS]]
    return [x for x in out if x]          # (an alias that expands to nothing sends nothing)
