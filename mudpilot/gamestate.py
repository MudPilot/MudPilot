"""Parses MajorMUD output line by line: prompt (HP/MA), room displays, combat,
experience, cash/items, and keeps track of exactly which MME room you are in.

Room tracking works like MegaMUD but uses the full MME exit graph:
  * every movement command you (or the bot) send is queued;
  * each room display is matched against the room the queued move should lead to;
  * if that fails (teleport, flee, death, desync) it falls back to name+exits lookup,
    preferring rooms close to where you were, and narrows ties with later moves.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from .ansi import plain
from .worlddb import WorldDB, norm_dir, DIRS

PROMPT_RE = re.compile(r"\[HP=(-?\d+)(?:/(MA|KAI)=(-?\d+))?\s*(?P<rin>\((?:Resting|Meditating)\))?\s*\]:?\s*"
                       r"(?P<rest>\((?:Resting|Meditating)\))?", re.I)
# (0.8.200: a class with no mana prints its rest inside the brackets — '[HP=91 (Resting) ]:' — MudPlay's notes)


def leading_prompts(text: str) -> list:
    """The prompts at the start of a line ('[HP=684/MA=473]:[HP=684/MA=473]:'), and only those. A prompt
    quoted later in the line — 'Vel gossips: [HP=5/MA=0]:' — is someone talking, not your HP."""
    out, pos = [], len(text) - len(text.lstrip())
    while True:
        m = PROMPT_RE.match(text, pos)
        if not m or m.end() == pos:
            break
        out.append(m)
        pos = m.end()
        while pos < len(text) and text[pos] == " ":
            pos += 1        # '[HP=..]: (Resting) [HP=..]: (Resting) X telepaths: @ok' — keep going past the gap
    if out or not text:
        return out
    # a prompt glued onto the end of game text ("Sneaking...[HP=684]:") still counts — unless the line
    # is somebody talking, where anything after the name is their words
    if _TALK_RE.search(text):
        return []
    return list(PROMPT_RE.finditer(text))


_TALK_RE = re.compile(r"^\s*\S+(?: \S+)? (?:gossips|says|telepaths|gangpaths|broadcasts|auctions|yells|whispers|"
                      r"shouts|tells you|says to|exclaims)\b|^\s*\S+ (?:said|asks)\b|--- Telepath|"
                      r"^\s*From \S+ \(Yelling\):|^\s*You (?:say|exclaim|ask|yell)\b", re.I)
EXITS_RE = re.compile(r"^\s*Obvious exits?:\s*(.*)$", re.I)
ALSO_RE = re.compile(r"^\s*Also here:\s*(.*)$", re.I)
NOTICE_RE = re.compile(r"^\s*You notice\s+(.*?)\s*(?:here\.?)?\s*$", re.I)
EXP_RE = re.compile(r"^\s*You gain ([\d,]+) experience", re.I)
HITS_RE = re.compile(r"Hits:\s*(\d+)\s*/\s*(\d+)", re.I)
MANA_RE = re.compile(r"(?:Mana|Kai):\s*\*?\s*(\d+)\s*/\s*(\d+)", re.I)   # ("Mana: * 336/346" too)
DARK_RE = re.compile(r"too dark to see|very dark.*can'?t see|pitch black", re.I)
# blind, the game answers a move (or Enter) with this instead of the room — the move still happened (Dan,
# 2026-11-09: blind in the pyramid, 's s e e s s' left the map on the room 'pro' had just set)
BLIND_SEE_RE = re.compile(r"(?:^|\]:)\s*you are blind\.\s*$", re.I)
GATE_REFUSE = (r"do not have enough to cover the toll|alignment prevents you from entering|"
               r"you are too (?:good|evil) to go through|you may not go through this exit|"
               r"have not progressed far enough|have progressed too far|need to cast a spell to go that way|"
               r"do not have the appropriate item")
MOVE_FAIL_RE = re.compile(
    r"no exit in that direction|can'?t go that way|you cannot go that way|door is closed|is locked|"
    r"gate is closed|blocks your (?:way|path)|path is blocked|too exhausted|can'?t move|"
    r"you are held|you are engulfed|unable to move|a strange power holds you back|"
    r"you can(?:not|'t) go (?:there|any further|in that direction)|portal is closed|you fumble in confusion|"
    r"you are too afraid|you look around stupidly|may not do that while you are mortally wounded|"
    # 0.8.200, from MudPlay's notes: refusals the step used to sit waiting on until it timed out
    r"can'?t seem to move anywhere|too heavy to move|too scared to flee|flat on your back|convulse violently|"
    r"closed door in that direction|portal is shut|"
    # 0.8.202: the game ate the move (asleep, paralyzed, too stunned, drunk, stone, limbo, retching) — Wayfarer
    r"you are too stunned to move|you are fast asleep|you are paralyzed|you cannot move a muscle|you reel drunkenly|"
    r"you shake and shiver|you struggle, but you are solid stone|you are in limbo|you retch\b|" + GATE_REFUSE, re.I)
# can't act for now (not a wall): the walk waits a moment, then tries again — never counted against the exit
CANT_ACT_RE = re.compile(r"^you (?:are too stunned to move|are fast asleep|are paralyzed|cannot move a muscle|"
                         r"reel drunkenly|shake and shiver|struggle, but you are solid stone|are in limbo)", re.I)
# a gate that won't let us through however often we try: toll money, alignment, quest progress, a spell or an item
GATE_REFUSE_RE = re.compile(GATE_REFUSE, re.I)
# pMUD: confusion / fear eats the command — it isn't a wall, just try again
CONFUSED_FAIL_RE = re.compile(r"^you (?:fumble (?:around )?in confusion|look around stupidly|are too afraid|retch|drool|"
                              r"convulse|struggle for breath|are too stunned to move|are fast asleep|are paralyzed|"
                              r"cannot move a muscle|reel drunkenly|shake and shiver|struggle, but you are solid stone|"
                              r"are in limbo)", re.I)
# "-- Following your Party leader north --": a follower moved without sending anything
FOLLOW_RE = re.compile(r"--\s*following\s+(?:your\s+)?party\s+leader(?:\s+([a-z]+))?\s*--", re.I)
CHAT_LINE_RE = re.compile(r"^\w+ (?:gossips|telepaths|says|gangpaths|auctions|yells|broadcasts|exclaims|asks)\b|"
                          r"^Broadcast from |^From \w+ \(Yelling\):|"
                          r"^You (?:say|gossip|telepath|gangpath|auction|yell|exclaim|ask)\b")
# (0.8.202, Wayfarer: 'From Bob (Yelling): "…' and 'You exclaim/ask' weren't chat, so a yell padded to wrap as
#  'Revolution telepaths: @do drop all"' on its second line read as a real telepath, and a yelled 'You have been
#  killed!' as your death)
# a quoted chat line whose quote isn't closed yet: the next piece is still their words, however short this one is
CHAT_QUOTE_OPEN_RE = re.compile(r'^(?:\w+ (?:says|exclaims|asks|yells)(?: \(to [^)]*\))?|'
                                r'You (?:say|exclaim|ask|yell)(?: \(to [^)]*\))?|From \w+ \(Yelling\):|'
                                r'Broadcast from \w+) "(?!.*"\s*$)')
EXITS_CONT_RE = re.compile(r"^(?:(?:open|closed|locked)?\s*(?:secret\s+)?(?:trap\s+)?(?:door|gate|passage)?\s*"
                           r"(?:north|south|east|west|northeast|northwest|southeast|southwest|up|down|above|below)"
                           r"[\s,.]*)+$", re.I)
# 'secret passage below', 'closed trap door above': MajorMUD's words for up / down in an exits list
EXIT_WORD_DIRS = {"above": "up", "below": "down"}
JAIL_RE = re.compile(r"dragged off to jail|you are let out of jail", re.I)
SNEAK_BANNER_RE = re.compile(r"^\s*sneaking\.\.\.\s*$", re.I)
SNEAK_FAIL_RE = re.compile(r"you don't think you're sneaking|you are no longer sneaking|you make a sound as you enter", re.I)
DOOR_CLOSED_RE = re.compile(r"(?:door|gate) is closed|closed door in that direction", re.I)
COMBAT_ON_RE = re.compile(r"\*Combat Engaged\*", re.I)
COMBAT_OFF_RE = re.compile(r"\*Combat Off\*", re.I)
DEATH_RE = re.compile(r"you (?:are|have been) (?:dead|killed|slain)|you die\b(?! (?:down|off)\b)", re.I)
# ('The flames enveloping you die down!' / 'The insects biting and stinging you die off.' are spells wearing off)
REST_ON_RE = re.compile(r"you are now (?:resting|meditating)|you begin (?:resting|meditating)", re.I)
ARRIVE_RE = re.compile(r"into the room|just arrived|arrives? from|enters? the room|"
                       r"(?:leaves|moves|runs|wanders) (?:to the )?(?:north|south|east|west|up|down)|"
                       r"\b(?:thunders|storms|bursts|rushes|stumbles|shambles|ambles|creeps|scuttles|slithers|crawls|"
                       r"flies|hops|lopes|strides|glides|charges|walks|wanders|sneaks|limps|steps)\s+(?:in(?:to)?\b)"
                       r"(?:\s+the\s+room)?\s+from|out of the room to the|just left to the|"
                       r"\b[a-z]+s (?:itself |you |their way )?in from\b|"     # 0.8.202: any 'runs / stalks / stomps / floats … in from the west'
                       r"\b(?:materializes|appears|forms beside you)\b|"
                       r"\brises (?:up )?(?:from|out of) the (?:ground|earth|floor|water|grave)|\bmoves into the\b", re.I)
AWAKE_RE = re.compile(r"\b(?:animates|comes? to life|springs? to life|awakens|stirs to life|takes? shape)\b.*(?:attacks?|!)$|\band attacks!$", re.I)   # "The statue animates, and attacks!"
# a monster we can't see (dark room) that's in the fight: "Revolution moves to attack tall dark-elf sentry.",
# "The angry dark-elf sentry swings at Revolution with their falchion!", "The obsidian statue slashes Buddy for 2 damage!"
JOIN_ATTACK_RE = re.compile(r"^([A-Z][a-z]+) moves to attack (?:the |an? )?([a-z][\w' -]*?)[.!]?$")
MON_HITS_RE = re.compile(r"^The ([a-z][\w' -]*?) [a-z]+(?: at)? (you|[A-Z][a-z]+)r?\b")   # ('your feet': 0.8.200)
# a monster being friendly at you, not attacking: smiles, nods, gives… (the bishop, Justice Darkbane)
FRIENDLY_VERBS = {"smiles", "grins", "nods", "waves", "winks", "bows", "looks", "glances", "stares", "peers",
                  "gazes", "beams", "chuckles", "laughs", "giggles", "sighs", "shrugs", "points", "gestures",
                  "beckons", "says", "exclaims", "asks", "whispers", "gives", "hands", "thanks", "greets",
                  "blinks", "frowns", "scowls", "nudges", "pats", "hugs", "smirks", "squints", "eyes", "arches",
                  "speaks", "tells", "bids", "salutes", "regards", "studies", "watches", "considers", "ponders"}
# "Spellcasting: +100", "Anti-Magic +30", "Flux -30" (several per line allowed)
ABIL_RE = re.compile(r"([A-Za-z][A-Za-z.'\- ]{1,28}?)\s*(?::|=)?\s*([+-]\d{1,4})\b(?!\s*/)")
ABIL_COLON_RE = re.compile(r"([A-Za-z][A-Za-z.'\- ]{1,28}?)\s*:\s*(\d{1,4})\b(?!\s*/)")
# Board-style ability table:  "ManaRegen(145)             0188"
#   or single-ability form:   "spells:  ManaRegen(145)             0188"
ABIL_ROW_RE = re.compile(r"^\s*(?:(granted|worn|spells|race|class)\s*:\s*)?([A-Za-z][^():]*?(?:\([^)\d][^)]*\))?[^():]*?)"
                         r"\((\d+)\)\s+([-+]?\d+)\s*$", re.I)
ABIL_SECTIONS = {"race": "race", "class": "class", "worn items": "worn", "worn": "worn",
                 "spell effects": "spells", "spells": "spells", "grantedabilities": "granted",
                 "granted abilities": "granted", "granted": "granted"}
ABIL_SOURCES = ("spells", "worn", "granted", "race", "class", "total")
EXPLINE_RE = re.compile(r"Exp:\s+(\d+)\s+Level:\s+(\d+)\s+Exp needed for next level:\s+(\d+)\s+\((\d+)\)\s+\[(\d+)%\]")
STAT_LEVEL_RE = re.compile(r"\bLevel:\s+(\d+)")
LIVES_RE = re.compile(r"\bLives/CP:\s+(\d+)/(\d+)")
WEALTH_RE = re.compile(r"^\s*Wealth:\s+(\d+)\s+copper farthings?", re.I)
ENC_RE = re.compile(r"^\s*Encumbrance:\s+(\d+)/(\d+)\s+-\s+(\w+)\s+\[(\d+)%\]", re.I)
# "skull mask (Face)", "vortex staff (Weapon Hand)", stock "(Worn)"/"(Wielded)" — any slot tag counts as worn
WORN_PART_RE = re.compile(r"^(?:an?\s+|the\s+|\d+\s+)?(.+?)\s*\(([A-Z][A-Za-z -]{1,18})\)\s*$")
WIELD_SLOTS = {"wielded", "wielding", "weapon hand", "weapon", "two hands", "two-handed", "both hands"}


def worn_list(carrying: str) -> list:
    """[(item, slot)] for everything worn or wielded in a 'You are carrying …' listing."""
    out = []
    for part in re.split(r",\s*", carrying or ""):
        m = WORN_PART_RE.match(part.strip().rstrip("."))
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def wielded(carrying: str) -> str:
    return next((n for n, slot in worn_list(carrying) if slot.lower() in WIELD_SLOTS), "")


CARRY_RE = re.compile(r"^\s*You are carrying\s+(.*)$", re.I)
KEYS_RE = re.compile(r"^\s*You have (?:no keys|the following keys:\s*(.*))", re.I)
SPELLS_HEAD_RE = re.compile(r"^\s*Level\s+(?:Mana|Kai)\s+Short\s+Spell Name", re.I)
SPELL_ROW_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$")
NO_SPELLS_RE = re.compile(r"you have no (?:spells|powers)", re.I)
LOCATE_RES = [re.compile(r"\blocation\s*:\s*(\d{1,3})\s*[,/]\s*(\d{1,5})", re.I),     # Paradigm 'pro'
              re.compile(r"map\s*#?\s*:?\s*(\d{1,3})\D{1,16}room\s*#?\s*:?\s*(\d{1,5})", re.I),
              re.compile(r"(?<![\d/])(\d{1,3})\s*/\s*(\d{1,5})(?![\d/])"),
              re.compile(r"(?<![\d,])(\d{1,3})\s*,\s*(\d{1,5})(?![\d,])")]
NOT_LOCATION_RE = re.compile(r"lives\s*/\s*cp|\d+/\d+/\d{4}|\bexp\s*:|hits\s*:|mana\s*:", re.I)
# chat is never the board's answer: Evolution (Dan, 2026-11-03) asked 'pro', and the echo of his own reply to Buddy —
# "/Buddy {walking to Dragon's Teeth Hills (2/873)}" — came back first: "arrived", 134 rooms short
SENT_ECHO_RE = re.compile(r"^\s*/\w+\s|\{.*\}")
PARTY_HEAD_RE = re.compile(r"following people are in your travel party", re.I)
# "  Miserable Par   (Mage)   [M: 69%] [H: 96%]M - Frontrank" · "  Phrixas  (Mystic)  [H:100%]  - Frontrank"
# (no mana bar for Kai classes) · "[H: -5%]" · "[H:100%]RMP - Backrank" · "  Deacon  (Priest)  [Invited]"
# 0.8.200: a Kai class (Mystic, Monk…) shows "[K: 40%]" there once it has any kai — the row didn't match and they
# dropped out of the party (no heals, no party blesses). Kai isn't mana: they count as full.
PARTY_ROW_RE = re.compile(r"^\s{1,4}(\w+)(?:\s+\w+)?\s+\((\w[\w ]*)\)\s+(?:\[M:\s*(-?\d+)%\]\s*|\[K:\s*-?\d+%\]\s*)?"
                          r"(?:\[H:\s*(-?\d+)%\]|\[(Invited)\])(?:\s*([A-Za-z]*)\s*-\s*(\w+))?")
PARTY_NONE_RE = re.compile(r"not in a (?:travel )?party|You are no longer in a party|has (?:been )?disbanded", re.I)
PARTY_LEFT_RE = re.compile(r"^(\w+) is no longer following you\.?\s*$")
COINS = ["copper farthing", "silver noble", "gold crown", "platinum piece", "runic coin"]
COIN_VALUE = {"copper farthing": 1, "silver noble": 10, "gold crown": 100,
              "platinum piece": 10000, "runic coin": 1000000}


@dataclass
class RoomView:
    name: str
    exits: set | None          # None = unknown (dark)
    monsters: list = field(default_factory=list)   # list[(shown_name, monster_rec or None)]
    items: list = field(default_factory=list)      # list[(qty, name)]
    players: list = field(default_factory=list)
    t: float = 0.0
    closed: set = field(default_factory=set)       # "closed door east" → {"E"}


def _split_list(text: str) -> list[str]:
    text = text.strip().rstrip(".")
    return [p.strip() for p in re.split(r",\s*|\s+and\s+", text) if p.strip()]


def parse_item_list(text: str) -> list[tuple[int, str]]:
    """Items are split on commas; ' and ' only when another item starts after it
    ('a sword and 2 daggers'), so 'rope and grapple' stays one item."""
    out = []
    text = text.strip().rstrip(".")
    parts = [x.strip() for x in re.split(r",\s*|\s+and\s+(?=(?:an?|the|some|\d+)\s)", text, flags=re.I) if x.strip()]
    for p in parts:
        m = re.match(r"^(\d+)\s+(.*)$", p)
        if m:
            out.append((int(m.group(1)), m.group(2)))
        else:
            out.append((1, re.sub(r"^(?:an?|the|some)\s+", "", p, flags=re.I)))
    return out


def coin_kind(name: str) -> str | None:
    n = name.lower()
    for c in COINS:
        if c in n:
            return c
    return None


class GameState:
    def __init__(self, world: WorldDB, log=None):
        self.world = world
        self.log = log or (lambda *a: None)
        # vitals
        self.hp = self.max_hp = 0
        self.max_hp_read = False     # (True once 'st' / a Hits: line gave the real max — not the best prompt seen)
        self.ma = self.max_ma = 0
        self.resting = False
        self.in_combat = False
        self.meditating = False
        self.sneaking = False
        self._exp_since_line = 0
        self.last_prompt = 0.0
        self.dead = False
        self._chat_open = False          # the last line was somebody talking (a wrapped piece may follow)
        self.continuation = False        # this line is the wrapped end of their words, not game text
        # location
        self.candidates: list = []          # possible MME rooms (ideally exactly 1)
        self.view: RoomView | None = None   # last room display
        self.view_seq = 0                   # increments on each room display
        self.history: deque = deque(maxlen=200)
        self.pending: deque = deque()       # queued ("move", dir|cmd, room_before) / ("look",) / ("peek",)
        self.door_closed_dir: str | None = None
        self.need_refresh = False
        self.move_failed = 0                # counter
        self.gate_refused = None            # (room, dir, the game's line, when) — a gate that said no
        self.confused_fail_at = 0.0         # last 'you fumble / retch / look around stupidly' (command eaten)
        self.cant_act_at = 0.0              # last 'You are fast asleep.' / 'You are paralyzed!' … (0.8.202)
        self.sick = False                   # 'You feel nauseous!' till 'You feel less sick.'
        self.abilities: dict = {}           # lower-case ability name -> (value, time seen)
        self.abil_capture_until = 0.0       # while > now, colon-style "Name: 100" values also count
        self.abil_probe = None              # (key, until, cmd_numbers) for single-ability checks like "abil 145"
        self.level = 0
        self.race = ""
        self.char_class = ""
        self.strength = 0
        self.exp_total = 0
        self.exp_needed = 0
        self.lives = None
        self.wealth = None
        self.enc = None                     # (cur, max, word, pct)
        self.carrying = ""
        self.coins: dict = {}               # coin kind -> how many you carry (from 'i', pickups and drops)
        self.keys = ""
        self.inv_seq = 0                    # bumps each time a full inventory listing is read
        self.inv_at = 0.0                   # …and when
        self._inv_part = None               # "carry" / "keys" while a listing wraps over lines
        self.party: dict = {}
        self.party_seq = 0               # given name -> {"class", "ma", "hp", "t"}
        self.known_spells: list | None = None   # shorts from the game's `spells` list (None = not read yet)
        self._spell_reading = False
        self._spell_buf: list = []
        self.known_spell_rows: list = []
        self.on_spells = []                 # callbacks(list_of_shorts)
        self.agility = 0
        self.mana_tick = 0
        self.lag = 0.0
        self.lag_samples: list = []          # (time, seconds the board took to answer) — the lag meter
        self._sent_at = 0.0
        self.lag_pending_done = True
        self.ac = self.dr = 0
        self.intellect = self.willpower = self.health = self.charm = 0
        self.magic_res = self.perception = self.stealth = self.spellcasting = 0
        self.stealth_read = False           # 'st' showed a Stealth figure (it can be below 0: a raft, -17)
        self.sneak_fails, self.sneak_fail_at = 0, 0.0   # "You don't think you're sneaking" in a row
        self.picklocks = 0
        self.alignment = ""                 # your own, from your line in 'who' (exit gates)
        self.traps = 0
        self.locate_until = 0.0             # while > now, look for "map/room" in the reply to `pro`
        self.locate_ok = 0                  # times a locate reply was understood
        self.on_located = []
        self.peek_view = None
        self.on_peek = []
        self._party_reading = False
        self.abil_rows: dict = {}           # (source, ability id) -> (value, time seen)
        self.abil_names: dict = {}          # ability id -> name as the board prints it
        self._abil_section = None
        # session stats
        self.reset_stats()
        # listeners
        self.on_room = []
        self.on_exp = []
        self.on_event = []                  # (kind, data)
        self._block: list = []              # lines since last prompt/room

    # ------------------------------------------------------------ stats
    def reset_stats(self):
        self.stat_start = time.time()
        self.exp_gained = 0
        self.kills = 0
        self.copper_looted = 0
        self.deaths = 0
        self.steps_walked = 0

    def exp_per_hour(self) -> float:
        hrs = max((time.time() - self.stat_start) / 3600, 1e-6)
        return self.exp_gained / hrs

    # ------------------------------------------------------------ location helpers
    @property
    def room(self):
        return self.candidates[0] if len(self.candidates) == 1 else None

    @property
    def room_label(self) -> str:
        if not self.candidates:
            return "Unknown"
        r = self.world.room(self.candidates[0])
        if len(self.candidates) == 1:
            return f"{r.key[0]}/{r.key[1]}  {r.name}"
        return f"{r.name}  ({len(self.candidates)} possible)"

    def hp_pct(self) -> float:
        return 100.0 * self.hp / self.max_hp if self.max_hp else 100.0

    def ma_pct(self) -> float:
        return 100.0 * self.ma / self.max_ma if self.max_ma else 100.0

    def set_room(self, key):
        self.candidates = [key]
        self._emit_room()

    def _emit_room(self):
        for cb in self.on_room:
            cb(self)

    def _event(self, kind, data=None):
        for cb in self.on_event:
            cb(kind, data)

    # ------------------------------------------------------------ outgoing
    def note_command(self, cmd: str):
        """Called for every command sent to the game, so moves can be tracked."""
        c = cmd.strip()
        low = c.lower()
        self._sent_at = time.time()
        self.lag_pending_done = False
        before = list(self.candidates)
        if low == "" or low in ("l", "lo", "loo", "look"):
            self.pending.append(("look", None, before))
            return
        m = re.match(r"^(?:l|lo|loo|look)\s+(\w+)$", low)
        if m and norm_dir(m.group(1)):
            self.pending.append(("peek", None, before))
            return
        m = re.match(r"^(?:go\s+)?(\w+)$", low)
        if m and norm_dir(m.group(1)):
            self.pending.append(("move", norm_dir(m.group(1)), before))
            self._sneak_banner = False
            self._sneak_move = True
            return
        if low and not low.startswith(("/", "@", "gos ", "tel ", "say ", ".", "par", "i", "st", "stat", "exp")):
            self._last_raw = (c, time.time(), list(self.candidates))   # maybe a way MME doesn't know ('enter pyramid')
        # text exits ("go path", "climb rope") — only queue if MME knows one here
        for key in self.candidates[:50]:                  # any room we might be in (not just the first guess)
            r = self.world.room(key)
            if r:
                for ex in r.exits.values():
                    if ex.accepts(low):
                        self.pending.append(("move", c, before))
                        return
        if low in ("rest", "sit"):
            pass

    # ------------------------------------------------------------ incoming
    @staticmethod
    def strip_prompt(segs):
        """Drop a leading '[HP=..]:' (plus echoed command) the server left on the line."""
        text = plain(segs)
        ms = leading_prompts(text)
        if not ms:
            return segs
        cut = ms[-1].end()
        out, pos = [], 0
        for t, st in segs:
            if pos + len(t) <= cut:
                pos += len(t)
                continue
            out.append((t[max(0, cut - pos):], st))
            pos += len(t)
        return out

    WRAP_AT = 72          # a chat line this long has likely been wrapped by the game (80 columns, word wrap)

    def feed_line(self, segs):
        # A long chat line the game wraps: the second piece is their words, not game text. Padded on purpose it can
        # read 'Evolution telepaths: @do …', 'Zed hits you for 5 damage!' or '[HP=99999]:'. Paradigm tidies the line
        # (ESC[79D ESC[K) before every new message; a wrapped piece has none (ansi.Line.fresh).
        fresh = getattr(segs, "fresh", None)
        if self._chat_open and fresh is False and plain(segs).strip():
            self.continuation = True
            if getattr(self, "_chat_by_len", False) and len(plain(segs).rstrip()) < self.WRAP_AT:
                self._chat_open = False      # opened by length (no ESC[K to end it): a short piece is the last one
            return
        self.continuation = False
        # (0.8.201, bug hunt: a chat line that came without ESC[K — glued after a prompt, another server — left this
        #  False, and its padded second half 'Evolution telepaths: @do …' was read as a real telepath. A chat line
        #  long enough to have wrapped opens it too)
        said = plain(self.strip_prompt(segs)).strip()
        self._chat_open = (bool(fresh) or len(plain(segs).rstrip()) >= self.WRAP_AT or
                           bool(CHAT_QUOTE_OPEN_RE.match(said))) and bool(CHAT_LINE_RE.match(said))
        # (0.8.202: or a quote left open — 'Bob says "…' with no closing quote goes on on the next line)
        self._chat_by_len = self._chat_open and not fresh
        self._check_prompt(plain(segs))
        segs = self.strip_prompt(segs)
        text = plain(segs)
        stripped = text.strip()
        if not stripped and getattr(self, "_exits_hold", None) is None:
            self._block.append((segs, text))
            return
        held = getattr(self, "_exits_hold", None)
        if held is not None:
            self._exits_hold = None
            if stripped and EXITS_CONT_RE.match(stripped):
                self._room_display(held + " " + stripped)    # "…, southeast," / "southwest"
                return
            self._room_display(held)
            if not stripped:
                self._block.append((segs, text))
                return
        if EXITS_RE.match(text):
            if re.search(r"(?:,|\b(?:door|gate|open|closed|locked|passage|trap|secret))\s*$", text.strip(), re.I):
                self._exits_hold = text.rstrip()               # the list goes on on the next line
                return
            self._room_display(text)
            return
        self._block.append((segs, text))
        if len(self._block) > 60:
            self._block = self._block[-60:]
        if CHAT_LINE_RE.match(stripped):
            return                         # "Bob gossips: you have been killed" isn't your death
        self._scan_misc(text)

    def feed_partial(self, text: str):
        """Prompt usually arrives without a newline."""
        self._check_prompt(text)

    def flush_exits(self):
        held = getattr(self, "_exits_hold", None)
        if held is not None:
            self._exits_hold = None
            self._room_display(held)

    def _check_prompt(self, text: str):
        ms = leading_prompts(text)
        if not ms:
            return
        self.flush_exits()                    # a prompt ends any exits list waiting for its wrapped line
        m = ms[-1]
        now = time.time()
        if self._sent_at and not self.lag_pending_done:
            self.lag = now - self._sent_at
            self.lag_pending_done = True
            if 0 <= self.lag < 60:
                self.lag_samples.append((now, self.lag))
                if len(self.lag_samples) > 4000:
                    del self.lag_samples[:2000]
        self.hp = int(m.group(1))
        if m.group(3):
            new_ma = int(m.group(3))
            d = new_ma - (self.ma or 0)
            # a regen tick: mana went up by a small amount without us casting a heal/regen
            if 0 < d <= max(30, (self.max_ma or 0) // 3) and self.ma:
                self.mana_tick = d
            self.ma = new_ma
        self.max_hp = max(self.max_hp, self.hp)
        if m.group(3):
            kind = (m.group(2) or "MA").upper()
            if getattr(self, "_ma_kind", kind) != kind:
                self.max_ma = self.ma                # MA ↔ KAI: a different pool, start its max over
            self._ma_kind = kind
            self.max_ma = max(self.max_ma, self.ma)
        elif getattr(self, "_ma_kind", None) == "KAI":
            # a board can drop '/KAI=' from the prompt at 0 kai (as 'par' drops [K:]): no pool shown is 0, not
            # the last value (0.8.201, bug hunt: stale kai)
            self.ma = 0
        rest_ = m.group("rest") or m.group("rin")
        self.resting = bool(rest_)
        self.meditating = bool(rest_) and "medit" in rest_.lower()
        self.last_prompt = time.time()
        self._abil_section = None
        self._party_reading = False
        if self._spell_reading:
            self._finish_spells(self._spell_buf)
        self.dead = False
        self._block = []

    def _scan_abil_table(self, text: str) -> bool:
        t = text.strip()
        sec = ABIL_SECTIONS.get(t.lower())
        if sec:
            self._abil_section = sec
            return True
        m = ABIL_ROW_RE.match(text)
        if not m:
            return False
        src = (m.group(1) or self._abil_section or "total").lower()
        aid = int(m.group(3))
        self.abil_names[aid] = m.group(2).strip()
        self.abil_rows[(src, aid)] = (int(m.group(4)), time.time())
        self.abil_seen_at = time.time()          # the board answered an abil check (any row)
        return True

    def abil_id(self, ability) -> int | None:
        a = str(ability).strip()
        m = re.match(r"^\D*?(\d+)\)?$", a)
        if a.isdigit() or (m and "(" in a):
            return int(m.group(1))
        low = a.lower()
        for aid, nm in self.abil_names.items():
            if nm.lower() == low:
                return aid
        return None

    def abil_value(self, ability, source="spells", since: float = 0.0):
        """Value of an ability from the board's ability table. source: spells/worn/granted/
        race/class/total. Rows older than `since` are ignored (count as not present).
        Returns (value, newest_time) or None if nothing seen since then."""
        aid = self.abil_id(ability)
        if aid is None:
            return None
        if source == "total":
            rows = [v for (src, i), v in self.abil_rows.items() if i == aid and v[1] >= since]
            if not rows:
                return None
            return sum(v for v, _t in rows), max(t for _v, t in rows)
        v = self.abil_rows.get((source, aid))
        return v if v and v[1] >= since else None

    def _scan_abilities(self, text: str):
        now = time.time()
        if self._scan_abil_table(text):
            return
        pr = self.abil_probe
        if pr and now < pr[1]:
            body = text.replace(pr[3], " ") if pr[3] and pr[3] in text else text
            nums = [int(n) for n in re.findall(r"(?<![\w/.])[-+]?\d+(?![\w/])", body)]
            nums = [n for n in nums if n not in pr[2]] or nums
            if nums:
                self.abilities[pr[0]] = (nums[-1], now)
                self.abil_probe = None
                return
        elif pr:
            self.abil_probe = None
        found = ABIL_RE.findall(text)
        if now < self.abil_capture_until:
            found += ABIL_COLON_RE.findall(text)
        for name, val in found:
            n = name.strip().lower()
            if n.startswith(("you ", "the ", "a ")) or len(n) < 2:
                continue
            self.abilities[n] = (int(val), now)

    def ability(self, name: str):
        """Latest value for an ability (matches 'ntap' to 'nightmare tap' style prefixes too)."""
        n = name.strip().lower()
        if n in self.abilities:
            return self.abilities[n]
        for k, v in self.abilities.items():
            if k.endswith(n) or n in k:
                return v
        return None

    def _scan_status_lines(self, text: str):
        m = EXPLINE_RE.search(text)
        if m:
            self.exp_total, self.level, self.exp_needed = int(m.group(1)), int(m.group(2)), int(m.group(3))
            self._exp_since_line = 0
            self.exp_line_at = time.time()          # (0 needed = ready to level, not 'unknown')
            self.exp_line_new = True                 # (the session tells a waiting @level)
        low = text.lower()
        if "attempting to sneak" in low and "don't think you're sneaking" not in low:
            self.sneaking = True
            self.sneak_fails = 0
        elif SNEAK_FAIL_RE.search(text) or "*combat engaged*" in low:
            self.sneaking = False
            if "don't think you're sneaking" in low:
                self.sneak_fails += 1
                self.sneak_fail_at = time.time()
        if SNEAK_BANNER_RE.match(text):
            self._sneak_banner = True
        mf = FOLLOW_RE.search(text)
        if mf:
            d = norm_dir(mf.group(1) or "")
            # we were moved by the party leader: the next room shown is one step that way
            self.pending.append(("move", d, list(self.candidates)) if d else ("look", None, list(self.candidates)))
            self._sneak_banner = True             # following moves don't print a sneak banner of their own
        m = LIVES_RE.search(text)
        if m:
            self.lives = int(m.group(1))
            self.stat_new = True                 # (a waiting @lives answers now)
            m2 = STAT_LEVEL_RE.search(text)
            if m2:
                self.level = int(m2.group(1))
        elif "Level:" in text and "Exp needed" not in text and re.search(r"\bName:|\bRace:|\bClass:", text):
            m2 = STAT_LEVEL_RE.search(text)
            if m2:
                self.level = int(m2.group(1))
        m = re.search(r"\bRace:\s+([A-Za-z-]+)", text)
        if m:
            self.race = m.group(1)
        m = re.search(r"\bClass:\s+([A-Za-z-]+)", text)
        if m:
            self.char_class = m.group(1)
        m = re.search(r"\bStrength:\s+(\d+)", text)
        if m:
            self.strength = int(m.group(1))
        m = re.search(r"\bAgility:\s+(\d+)", text)
        if m:
            self.agility = int(m.group(1))
        m = re.search(r"\bArmou?r Class:\s+(-?\d+)\s*/\s*(-?\d+)", text)
        if m:
            self.ac, self.dr = int(m.group(1)), int(m.group(2))
        for k, rx in (("intellect", r"\bIntellect:\s+(\d+)"), ("willpower", r"\bWillpower:\s+(\d+)"),
                      ("health", r"\bHealth:\s+(\d+)"), ("charm", r"\bCharm:\s+(\d+)"),
                      ("magic_res", r"\bMagicRes:\s+(\d+)"), ("perception", r"\bPerception:\s+(\d+)"),
                      ("stealth", r"\bStealth:\s+(-?\d+)"), ("spellcasting", r"\bSpellcasting:\s+(\d+)"),
                      ("picklocks", r"\bPicklocks:\s+(\d+)"), ("traps", r"\bTraps:\s+(\d+)")):
            m = re.search(rx, text)
            if m:
                setattr(self, k, int(m.group(1)))
                if k == "stealth":
                    self.stealth_read = True
        # the game's spell list ("spells" command)
        if SPELLS_HEAD_RE.match(text):
            self._spell_reading, self._spell_buf = True, []
            return
        if NO_SPELLS_RE.search(text):
            self._finish_spells([])
            return
        if self._spell_reading:
            m = SPELL_ROW_RE.match(text)
            if m:
                self._spell_buf.append([m.group(3).lower(), m.group(4).strip().lower(),
                                        int(m.group(1)), int(m.group(2))])
                return
            self._finish_spells(self._spell_buf)
        m = WEALTH_RE.match(text)
        if m:
            self.wealth = int(m.group(1))
        m = ENC_RE.match(text)
        if m:
            self.enc = (int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)))
            # the inventory listing is complete: recount the coins you carry
            self.coins = {}
            for qty, name in parse_item_list(self.carrying or ""):
                ck = coin_kind(name)
                if ck:
                    self.coins[ck] = self.coins.get(ck, 0) + qty
        m = re.match(r"^You (picked up|dropped|hid|stashed|deposited) (\d+) (.+?)\.?$", text.strip(), re.I)
        if m:
            ck = coin_kind(m.group(3))
            if ck:
                n = int(m.group(2)) * (1 if m.group(1).lower() == "picked up" else -1)
                self.coins[ck] = max(0, self.coins.get(ck, 0) + n)
                if n > 0:
                    # copper looted counts what the game says you got (0.8.201, bug hunt: it counted the 'get' as
                    # sent — refused and partial pickups too)
                    self.copper_looted += n * COIN_VALUE.get(ck, 0)
        m = CARRY_RE.match(text)
        if m:
            self.carrying, self._inv_part = m.group(1).strip(), "carry"
            return
        m = KEYS_RE.match(text)
        if m:
            self.keys, self._inv_part = (m.group(1) or "").strip(), "keys"
            return
        if self._inv_part and text.strip() and not WEALTH_RE.match(text) and not ENC_RE.match(text) \
                and not PROMPT_RE.search(text):
            if self._inv_part == "carry":
                self.carrying += " " + text.strip()     # long lists wrap onto more lines
            else:
                self.keys += (" " if self.keys else "") + text.strip()
            return
        if WEALTH_RE.match(text) or ENC_RE.match(text):
            self._inv_part = None
        if ENC_RE.match(text):
            self.inv_seq += 1                    # encumbrance closes the listing
            self.inv_at = time.time()
            self.inv_new = True                  # (a waiting @have / @inv answers now)
        if PARTY_HEAD_RE.search(text):
            self.party = {}
            self._party_reading = True
            return
        if PARTY_NONE_RE.search(text):
            self.party = {}
        ml = PARTY_LEFT_RE.match(text.strip())
        if ml:
            self.party.pop(ml.group(1), None)
        mj = re.match(r"^(\w+) started to follow you\.?\s*$", text.strip())
        if mj and mj.group(1) not in self.party:
            # in the party now — don't wait for the next 'par' (or something invites them again)
            self.party[mj.group(1)] = {"class": "", "ma": 100, "hp": 100, "rank": "", "t": time.time(), "flags": ""}
            self.party_seq += 1
        if self._party_reading:
            m = PARTY_ROW_RE.match(text)
            if m:
                if not m.group(5):                         # invited, not in yet
                    self.party[m.group(1)] = {"class": m.group(2).strip(), "ma": int(m.group(3)) if m.group(3) else 100,
                                              "hp": int(m.group(4)), "rank": m.group(7) or "", "t": time.time(),
                                              "flags": m.group(6) or ""}
                    self.party_seq += 1
            elif not text.strip() or PROMPT_RE.search(text) or not text.startswith(" "):
                self._party_reading = False                # one odd row doesn't end the list; a blank line does

    def _finish_spells(self, rows):
        """rows: [short, name, level, mana] as the game lists them."""
        self._spell_reading = False
        seen, out = set(), []
        for r in rows:
            if r[0] not in seen:
                seen.add(r[0])
                out.append(r)
        self.known_spells = [r[0] for r in out]
        self.known_spell_rows = out
        for cb in self.on_spells:
            cb(out)

    def _scan_locate(self, text: str) -> bool:
        if time.time() > self.locate_until:
            return False
        # never a number pair off another reply that came back alongside: 'st' ("Lives/CP: 9/5"), the deaths list
        # ("10/21/2026 … 13/323"), regen times
        if CHAT_LINE_RE.search(text.strip()) or SENT_ECHO_RE.search(text):
            return False
        other = NOT_LOCATION_RE.search(text)
        for rx in LOCATE_RES:
            if other and rx is not LOCATE_RES[0]:
                continue
            for m in rx.finditer(text):
                key = (int(m.group(1)), int(m.group(2)))
                if key in self.world.rooms:
                    self.locate_until = 0.0
                    self.locate_ok += 1
                    self._last_raw = None                 # a relocation by 'pro' is never a way to learn
                    self.located = (key, time.time())     # the board said so: nothing guesses over this
                    self.candidates = [key]
                    self.history.append(key)
                    self.pending.clear()
                    for cb in self.on_located:
                        cb(key)
                    self._emit_room()
                    return True
        return False

    def _kill_credit(self) -> str | None:
        """Which monster this exp line was for: the one named in a death line just above it, taken off the
        room list (so an area spell's three kills land on three monsters); else the current target."""
        v = self.view
        mons = list(v.monsters) if v else []
        recent = self._recent[-9:-1]
        for entry in reversed(recent):
            line, used = entry
            low = line.lower()
            if used or ("for " in low and " damage" in low) or EXP_RE.search(line):
                continue
            for i, (shown, rec) in enumerate(mons):
                nm = (rec["name"] if rec else shown).lower()
                if shown.lower() in low or nm in low:
                    del v.monsters[i]               # it's dead: not a target any more
                    entry[1] = True                 # each death line pays for one exp line
                    self.last_kill_rec = rec        # the boss tracker needs which one (it's off the list now)
                    return rec["name"] if rec else shown
        return None

    INV_GOT_RE = re.compile(r"^You (?:took|picked up|get|receive[sd]?) (?:(\d+) )?(.+?)\.?$", re.I)
    INV_LOST_RE = re.compile(r"^You (?:dropped|drop|gave|give|sold|sell|hid|hide|put) (?:(\d+) )?(.+?)"
                             r"(?: (?:to|in|into|on) .+?)?(?: for .+)?\.?$", re.I)
    INV_WEAR_RE = re.compile(r"^You are now (?:wearing|holding|wielding) (?:an? |the )?(.+?)\.?$", re.I)
    INV_REMOVE_RE = re.compile(r"^You have removed (?:an? |the )?(.+?)\.?$", re.I)

    def _inv_delta(self, text):
        """pMUD: keep 'what you carry' current between 'i's — picked up, dropped, sold, worn, removed."""
        t = text.strip()
        if not self.carrying or len(t) > 120:
            return
        items = [n for _q, n in [(0, p.strip()) for p in re.split(r",\s*", self.carrying) if p.strip()]]
        m = self.INV_GOT_RE.match(t)
        if m and not re.search(r"\b(?:copper farthings?|silver nobles?|gold crowns?|platinum pieces?|runic coins?)\b",
                               m.group(2), re.I):
            items.append(((m.group(1) + " ") if m.group(1) and m.group(1) != "1" else "") + m.group(2))
        else:
            m = self.INV_LOST_RE.match(t)
            if m:
                name = m.group(2).lower()
                for i, it in enumerate(items):
                    base = re.sub(r"^\d+\s+|\s*\([^)]*\)\s*$", "", it).lower()
                    if base == name or base.rstrip("s") == name.rstrip("s"):
                        items.pop(i)
                        break
                else:
                    return
            else:
                m = self.INV_WEAR_RE.match(t) or self.INV_REMOVE_RE.match(t)
                if not m:
                    return
                name, wearing = m.group(1).lower(), bool(self.INV_WEAR_RE.match(t))
                # 0.8.224.3 (R: logs — PVEREV's divine intervention failed 217 of 221 times): the slot names from the
                # last 'i' are remembered, so a wear line puts "(Off-Hand)" / "(Weapon Hand)" back, not a generic
                # "(Worn)" — item spells, wielded() and gear modes need to know which hand holds what
                so = self.__dict__.setdefault("_slot_of", {})
                for it in items:
                    ms = re.match(r"^(?:\d+\s+)?(.*?)\s*\(([^)]*)\)\s*$", it)
                    if ms and ms.group(2).strip().lower() not in ("worn", ""):
                        so[ms.group(1).strip().lower()] = ms.group(2).strip()
                for i, it in enumerate(items):
                    base = re.sub(r"\s*\([^)]*\)\s*$", "", it)
                    if base.lower().lstrip("anthe ").endswith(name) or base.lower() == name:
                        items[i] = f"{base} ({so.get(base.strip().lower()) or 'Worn'})" if wearing else base
                        break
                else:
                    return
        self.carrying = ", ".join(items)

    def _scan_misc(self, text: str):
        if self._scan_locate(text):
            return
        self._recent = (getattr(self, "_recent", []) + [[text.strip(), False]])[-10:]
        self._scan_abilities(text)
        self._scan_status_lines(text)
        self._inv_delta(text)
        ml = re.match(r"^\s*You lose ([\d,]+) experience", text, re.I)
        if ml:
            self.exp_gained -= int(ml.group(1).replace(",", ""))     # a death or a drain (pMUD)
        if re.match(r"^\s*You don'?t see (?!any|anything|that)\S.* here[.!]?\s*$", text, re.I) and self.view:
            # the target's gone (dead, fled, someone else killed it): look again rather than attack thin air
            self.need_refresh = True
        m = EXP_RE.search(text)
        if m:
            n = int(m.group(1).replace(",", ""))
            self.exp_gained += n
            self._exp_since_line += n
            self.last_kill_rec = None
            self.last_kill_name = self._kill_credit() if n > 0 else None
            if n > 0:
                self.kills += 1
            self.need_refresh = True               # something died: look before acting (combat may go on)
            for cb in self.on_exp:
                cb(n)
            self._event("exp", n)
        m = HITS_RE.search(text)
        if m:
            self.hp, self.max_hp = int(m.group(1)), int(m.group(2))
            self.max_hp_read = True
        m = MANA_RE.search(text)
        if m:
            self.ma, self.max_ma = int(m.group(1)), int(m.group(2))
        if COMBAT_ON_RE.search(text):
            self.in_combat = True
            self.combat_on_at = time.time()
            self.resting = False
            self._event("combat", True)
        if COMBAT_OFF_RE.search(text):
            self.in_combat = False
            self.need_refresh = True
            if self.view is not None:
                self.view.monsters = []        # what we saw is stale (it just died) — look again before acting
            self._event("combat", False)
        if REST_ON_RE.search(text):
            self.resting = True
        md = DEATH_RE.search(text)
        if md and '"' not in text[:md.start()]:      # (0.8.202: never words inside quotes — someone's speech)
            self.dead = True
            self.deaths += 1
            self.in_combat = False
            self.candidates = []
            self.pending.clear()              # (0.8.201, bug hunt: moves typed before dying aren't the respawn's)
            self._event("death")
        if CONFUSED_FAIL_RE.search(text.strip()):
            self.confused_fail_at = time.time()
        if CANT_ACT_RE.search(text.strip()):
            self.cant_act_at = time.time()       # asleep / paralyzed / too stunned: the walk gives it a moment
        if re.match(r"^you feel (?:nauseous|sick|ill)\b", text.strip(), re.I):
            self.sick = True                  # the rotting beholder's stench: commands get eaten for a while
        elif re.match(r"^you feel less sick|^you no longer feel (?:sick|nauseous)", text.strip(), re.I):
            self.sick = False
        if MOVE_FAIL_RE.search(text):
            self._move_failed(text)
        if DARK_RE.search(text):
            self.dark_at = time.time()           # can't see the room: 'pro' says where we are (automation)
            self._dark_room()
        elif BLIND_SEE_RE.search(text):
            self._dark_room("(blind)")
        if JAIL_RE.search(text):
            self.pending.clear()              # carried off: wherever we land isn't one step from here
            self.candidates = []
            self._event("jail", text)
        if ARRIVE_RE.search(text):
            who = (text.strip().split() or [""])[0].lower()
            if who not in {n.split()[0].lower() for n in (self.party or {}) if n}:
                self.need_refresh = True
            # (our own party walking in behind us shows us nothing new: looking again for them held every step
            # ~0.33 s — MudPilot-led steps took 2.2 s where MegaMUD's took 1.75, 2026-11-01)
            self._event("arrival", text)
        self._unseen_monster(text.strip())
        if AWAKE_RE.search(text):
            self.need_refresh = True              # "The statue animates, and attacks!" — a monster just appeared
            self._event("arrival", text)

    def _unseen_monster(self, t):
        """Dan, 2026-10-28: Buddy in a dark room while the party fought a sentry — it can't see the room, so it never
        saw the monster and stood there. A monster that attacks you or the party, or that a party member moves to
        attack, is in this room: put it on the room's list so the fight logic takes it on. (Combat Off clears it.)"""
        if not t or not t[0].isupper():
            return
        m = JOIN_ATTACK_RE.match(t)
        if m:
            who, mon = m.group(1), m.group(2)
        else:
            m = MON_HITS_RE.match(t)
            if not m:
                return
            mon, who = m.group(1), m.group(2)
            if re.search(r"dying|\bdies\b|death|collapses|falls dead|flees|runs away|vanishes|shatters", t, re.I):
                return                               # "The sentry insults you with his dying breath."
            # talking or a gesture isn't an attack: "The ghost gives you a stern look, "Be wary…"" put a 'ghost' (an
            # evil one) on the list and Miserable PVE cast at Justice Darkbane (2026-11-06)
            verb = t[len("The ") + len(mon):].split()[0].lower() if len(t) > len("The ") + len(mon) else ""
            if '"' in t or verb in FRIENDLY_VERBS:
                return
        v0 = self.view
        if v0 is not None and any(re.search(rf"\b{re.escape(mon.lower())}\b", sh.lower()) for sh, _r in v0.monsters):
            return                                   # 'the ghost' = the Ghost of Justice Darkbane that's already here
        party = {n.split()[0].lower() for n in (self.party or {})}
        if who.lower() != "you" and who.lower() not in party:
            return
        w = getattr(self, "world", None)
        rec = w.identify_monster(mon) if w is not None and getattr(w, "loaded", False) else None
        if not rec:
            return                                   # only real monsters ("The door slams shut" isn't one)
        v = self.view
        if v is None:
            v = self.view = RoomView("(dark)", None, t=time.time())
        if any(sh.lower() == mon.lower() for sh, _r in v.monsters):
            return
        v.monsters = list(v.monsters) + [(mon, rec)]
        self.view_seq += 1
        self._event("unseen_monster", mon)

    def _pop_display_entry(self, kinds=("move", "look", "peek")):
        while self.pending:
            e = self.pending.popleft()
            if e[0] in kinds:
                return e
        return None

    def _move_failed(self, text):
        # the oldest pending move (or a look into a direction that isn't there) did not happen
        for i, e in enumerate(self.pending):
            if e[0] == "peek" and "no exit" in text.lower():
                del self.pending[i]
                return
            if e[0] == "move":
                del self.pending[i]
                self.move_failed += 1
                if GATE_REFUSE_RE.search(text):
                    self.gate_refused = (tuple(self.room) if self.room else None, e[1], text.strip(), time.time())
                if DOOR_CLOSED_RE.search(text) and norm_dir(str(e[1])):
                    self.door_closed_dir = e[1]
                self._event("move_failed", e[1])
                return

    def _dark_room(self, label="(dark)"):
        # one answer per command, oldest first: Enter's answer isn't a move's (taking the next move for it put
        # the map a room ahead, then the move's own answer found nothing)
        e = self._pop_display_entry()
        if e and e[0] == "move" and self.candidates:
            # typed ahead ('s s' faster than the game answers): from where the step before landed, not from
            # where we were when it was typed (both steps landed on the same room — two rooms off on level 2)
            nxt = self._predict(self.candidates, e[1]) or (self._predict(e[2], e[1]) if e[2] else [])
            if nxt:
                self.candidates = nxt
                self.steps_walked += 1
                self.view = RoomView(label, None, t=time.time())
                self.view_seq += 1
                self._emit_room()

    # ------------------------------------------------------------ room display
    def _room_display(self, exits_line: str):
        block = self._block
        self._block = []
        exits_text = EXITS_RE.match(exits_line).group(1)
        shown, closed = set(), set()
        if "none" not in exits_text.lower():
            for part in _split_list(exits_text):
                w = part.split()[-1] if part.split() else ""
                d = norm_dir(EXIT_WORD_DIRS.get(w.lower(), w))   # 'secret passage below' = down (0.8.202)
                if d:
                    shown.add(d)
                    if re.search(r"\b(?:closed|locked)\b", part, re.I):
                        closed.add(d)
        self._closed_now = closed
        # collect Also here / You notice (may wrap onto several lines)
        monsters, players, items = [], [], []
        name, name_idx = None, -1
        joined = []
        for segs, text in block:
            if joined and not joined[-1][1].rstrip().endswith(".") and \
                    (joined[-1][1].lower().lstrip().startswith(("also here", "you notice"))) and text.strip():
                joined[-1] = (joined[-1][0] + segs, joined[-1][1] + " " + text.strip())
            else:
                joined.append((segs, text))
        for i, (segs, text) in enumerate(joined):
            m = ALSO_RE.match(text)
            if m:
                for who in _split_list(m.group(1)):
                    who = who.rstrip("*").strip()          # "Deacon*" = a party member
                    # 'Bob(Hidden)', 'giant rat (Charmed)': the name without the tag (0.8.202)
                    who = re.sub(r"(?<=\S)\s*\([A-Za-z ]+\)$", "", who).rstrip("*").strip()
                    rec = self.world.identify_monster(who)
                    if rec:
                        monsters.append((who, rec))
                    elif who[:1].isupper():
                        players.append(who)
                    else:
                        monsters.append((who, None))
                continue
            m = NOTICE_RE.match(text)
            if m:
                items = parse_item_list(m.group(1))
        # room name: nearest line above the exits that is a known MME room name;
        # prefer bright-cyan lines (MajorMUD colours room names that way)
        for i in range(len(joined) - 1, -1, -1):
            segs, text = joined[i]
            t = text.strip()
            if not t or ALSO_RE.match(text) or NOTICE_RE.match(text):
                continue
            cyan = any(st.fg == 6 and st.bold for s, st in segs if s.strip())
            if self.world.is_room_name(t) and (cyan or name is None):
                name, name_idx = t, i
                if cyan:
                    break
        if name is None and any(DARK_RE.search(t) for _sg, t in joined):
            # "The room is very dark - you can't see anything" + exits: the dark arrival already moved us
            self.view = RoomView("(dark)", shown, monsters, items, players, time.time())
            self.view_seq += 1
            self._emit_room()
            return
        if name is None:
            # unknown room: still record the view but can't place it
            for segs, text in reversed(joined):
                if text.strip() and not ALSO_RE.match(text) and not NOTICE_RE.match(text):
                    name = text.strip()
                    break
        view = RoomView(name or "?", shown, monsters, items, players, time.time(), closed)
        entry = self._pop_display_entry()
        if entry and entry[0] == "peek":
            # looking into the next room: keep it apart, it isn't where we are
            self.peek_view = view
            for cb in self.on_peek:
                cb(view)
            return
        self.view = view
        self.view_seq += 1
        self._locate(entry, name or "", shown)
        self._resolve_monsters(view)
        self._emit_room()

    def _resolve_monsters(self, view):
        """pMUD: several MME monsters share a name (zombie 70 vs 500 exp) — once we know the room, take the one
        that lives here (its lair list), else one that lairs on this map."""
        w = self.world
        if not getattr(w, "dup_names", None) or not view.monsters:
            return
        cands = list(self.candidates or [])
        room = cands[0] if len(cands) == 1 else None
        mp = cands[0][0] if cands and all(c[0] == cands[0][0] for c in cands) else None
        if room is None and mp is None:
            return
        out = []
        for who, rec in view.monsters:
            if rec and rec["name"].lower() in w.dup_names:
                rec = w.identify_monster(who, room=room, map_=mp) or rec
            out.append((who, rec))
        view.monsters = out

    def _predict(self, cands, move):
        out = []
        for c in cands:
            if norm_dir(str(move)) and str(move) in DIRS:
                n = self.world.neighbor(c, move)
            else:
                n = None
                r = self.world.room(c)
                for ex in (r.exits.values() if r else []):
                    if ex.accepts(str(move)):
                        # (every exit that takes it, not just the last: 2/2519's two 'go alley' exits — loopsA LA4)
                        if ex.to and ex.to not in out:
                            out.append(ex.to)
            if n and n not in out:
                out.append(n)
        return out

    def _moved_in(self, key):
        """0.8.223 (Dan, m1018 #2b): our own move landed in another room. Moving away ends the fight, but the game
        (the practice server at least) doesn't always print *Combat Off* — a stale 'in combat' ran the run check over
        and over with nothing hitting (81 runs in 4 minutes). Cleared here when nothing's in the new room; with
        monsters here the bot clears it a few seconds on if none of them hits us (Automation._stale_combat)."""
        self.moved_at = (key, time.time())
        if self.in_combat and not (self.view and self.view.monsters):
            self.in_combat = False
            self._event("combat", False)

    def _locate(self, entry, name, shown):
        if entry and entry[0] == "move" and getattr(self, "_sneak_move", False):
            self._sneak_move = False
            if self.sneaking and not getattr(self, "_sneak_banner", True) and norm_dir(str(entry[1] or "")):
                self.sneaking = False             # a normal move that arrived without "Sneaking..." = sneak lost
        w = self.world
        prev = list(self.candidates)
        if entry and entry[0] == "peek":
            return  # looking into an adjacent room doesn't move us
        if entry and entry[0] == "move":
            # typed ahead ('n n e e n' faster than the game answers): each move goes from where the one
            # before it landed — not from where we were when it was typed
            pred = [k for k in self._predict(prev, entry[1]) if w.match_room(k, name, shown)] if prev else []
            if not pred and entry[2]:
                pred = [k for k in self._predict(entry[2], entry[1]) if w.match_room(k, name, shown)]
            if pred:
                self.candidates = self._narrow(pred, prev)
                self.steps_walked += 1
                if not prev or pred[0] not in prev:
                    self._moved_in(pred[0])
                self.history.append(pred[0])
                return
        # look / unexpected display / failed prediction: did we stay put?
        stay = [k for k in prev if w.match_room(k, name, shown)]
        if stay and not entry:
            # (0.8.201, bug hunt: a room shown with nothing asked for — a summon, a teleport trap, being dragged —
            # into a look-alike next door (the Rocky Trail chains) read as "never moved". Keep both: here, and the
            # look-alikes one step away; the next room that tells them apart picks one)
            step = self._near(prev, set(w.candidates(name, shown)), 1)
            self.candidates = stay + [k for k in step if k not in stay]
            return
        if stay and entry[0] == "look":
            self.candidates = stay
            return
        glob = w.candidates(name, shown)
        if not glob:
            glob = [k for k in w.by_name.get(name.lower(), [])]  # exits mismatch: name only
        if not glob:
            self.candidates = []
            return
        if stay:
            self.candidates = stay
            return
        unique = len(glob) == 1
        if len(glob) > 1 and prev:
            near = self._near(prev, set(glob), 4)
            if near:
                glob = near
        self.candidates = self._narrow(glob, prev)[:500]
        if len(self.candidates) == 1:
            self.history.append(self.candidates[0])
            lr = getattr(self, "_last_raw", None)
            if not entry and lr and time.time() - lr[1] < 5 and len(lr[2]) == 1 and lr[2][0] != self.candidates[0] \
                    and len(prev) == 1 and prev[0] == lr[2][0] and unique \
                    and not self.world.look_alike(lr[2][0]):
                # (only when both ends are rooms nothing else looks like — in the pyramid a guess between
                # twins once 'learned' that asking the sphinx in a dead end teleports you)
                # you typed something and ended up somewhere MME has no exit to: learn the way
                self._last_raw = None
                for cb in getattr(self, "on_learn", []):
                    cb(lr[2][0], lr[0], self.candidates[0])

    def _narrow(self, cands, prev):
        """Look-alike rooms (48 'Rocky Trail's): keep the one(s) the evidence points at — pMUD's tie-breaks.
        1. an exit back to the room we were sure of a moment ago;  2. the monsters standing here are ones
        MME says live in that room (its lair list / NPC). Never narrows to nothing."""
        if len(cands) < 2:
            return list(cands)
        w = self.world
        out = list(cands)
        if len(prev) == 1:
            back = [c for c in out if any(ex.to == prev[0] for ex in (w.room(c).exits.values() if w.room(c) else []))]
            if back and len(back) < len(out):
                out = back
        v = self.view
        if v and v.closed and len(out) > 1:
            # a closed / locked door on screen: keep the look-alikes that have a door that way (pMUD)
            doors = [c for c in out if all((w.room(c).exits.get(d) is not None and
                                            w.room(c).exits[d].kind in ("door", "key")) for d in v.closed if w.room(c))]
            if doors and len(doors) < len(out):
                out = doors
        if len(out) > 1 and not prev:
            lr = getattr(self, "last_known", None)       # where you were when MudPilot last closed
            if lr in out:
                out = [lr]
        nums = {rec["num"] for _sh, rec in (v.monsters if v else []) if rec and rec.get("num") is not None}
        if nums and len(out) > 1:
            def lives_here(c):
                r = w.room(c)
                if not r:
                    return False
                ids = {int(x) for x in re.findall(r"\d+", (r.lair or "").split(":")[-1])} if r.lair else set()
                try:
                    ids.add(int(r.npc or 0))
                except (TypeError, ValueError):
                    pass
                return bool(ids & nums)
            fit = [c for c in out if lives_here(c)]
            if fit and len(fit) < len(out):
                out = fit
        return out

    def _near(self, origins, targets, depth):
        """Rooms in `targets` reachable from any origin within `depth` steps."""
        seen = set(origins)
        frontier = list(origins)
        hits = []
        for _ in range(depth):
            nxt = []
            for c in frontier:
                r = self.world.room(c)
                if not r:
                    continue
                for ex in r.exits.values():
                    if ex.to not in seen:
                        seen.add(ex.to)
                        nxt.append(ex.to)
                        if ex.to in targets:
                            hits.append(ex.to)
            if hits:
                return hits
            frontier = nxt
        return hits
