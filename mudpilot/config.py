"""Settings persisted as JSON in the app's data folder. Passwords are never written
here — they go to Windows Credential Manager through `keyring`."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field

# the compiled build (Nuitka): the code is ...\MudPilot\app\0.8.160\mudpilot\, its exe beside that folder, and the
# install two folders further up (sys.executable isn't the exe there)
FROZEN = "__compiled__" in globals()


def long_path(p: str) -> str:
    """'…\\08E0B8~1.159\\…' → '…\\0.8.159\\…': the compiled build is handed its folder in 8.3 short names."""
    if os.name != "nt":
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    return buf.value if ctypes.windll.kernel32.GetLongPathNameW(p, buf, 32768) else p


APP_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if FROZEN:
    APP_HOME = long_path(APP_HOME)                  # (a folder that exists: config.py itself doesn't, compiled)
APP_DIR = os.path.dirname(os.path.dirname(APP_HOME)) if FROZEN else APP_HOME
EXE_NAME = "MudPilot.exe" if os.name == "nt" else "MudPilot.bin" if sys.platform == "darwin" else "MudPilot"   # (Linux: no .exe; Mac: .bin — its disks ignore case, so "MudPilot" would clash with the mudpilot/ folder)
APP_EXE = os.path.join(APP_HOME, EXE_NAME) if FROZEN else sys.executable


def open_path(path) -> bool:
    """Open a file or folder the way a double-click would: Explorer / the file's program on Windows,
    xdg-open on Linux, open on a Mac."""
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except (AttributeError, OSError):
        return False
# one install, a data folder per character set: the launcher's --data PVE runs MudPilot on data-PVE\
DATA_DIR = os.environ.get("MUDPILOT_DATA_DIR") or os.path.join(APP_DIR, "data")
BOARDS_DIR = os.path.join(DATA_DIR, "boards")
DEFAULT_BOARD = os.environ.get("MUDPILOT_DEFAULT_BOARD", "Paradigm")   # Paradigm ships with MudPilot
LEGACY_BOARD = "Main"                     # where v0.2-0.7 single-board data was migrated to
BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundled")   # (beside the code, either way)
BUNDLED_BOARDS = {"Paradigm": "Paradigm.db", "Stock": "Stock.db"}   # MME data that comes with MudPilot
LEGACY_WORLD_DB = os.path.join(DATA_DIR, "world.db")      # single-board layout (v0.2 and older)
LEGACY_PATHS_DIR = os.path.join(DATA_DIR, "paths")


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " -_.").strip() or DEFAULT_BOARD


def board_dir(board: str) -> str:
    return os.path.join(BOARDS_DIR, _safe(board))


def world_path(board: str) -> str:
    return os.path.join(board_dir(board), "world.db")


def paths_dir(board: str) -> str:
    return os.path.join(board_dir(board), "paths")


def list_boards() -> list:
    os.makedirs(BOARDS_DIR, exist_ok=True)
    out = sorted(d for d in os.listdir(BOARDS_DIR) if os.path.isdir(os.path.join(BOARDS_DIR, d)))
    return out or [DEFAULT_BOARD]


def install_bundled_boards():
    """First run: set up the boards whose MME data ships with MudPilot (Paradigm, Stock).
    Never overwrites a board you've imported yourself."""
    import shutil
    import sqlite3

    def ver(path):
        """The map data's version: SQLite keeps 'user_version' at bytes 60-63 of the file header.
        Read it straight from the file — no database connection, so Windows paths with spaces
        ('Claude projects') or a busy file can't make it come back as 0 and skip the upgrade."""
        try:
            with open(path, "rb") as f:
                head = f.read(64)
            if len(head) >= 64 and head[:16] == b"SQLite format 3\x00":
                return int.from_bytes(head[60:64], "big")
        except OSError:
            pass
        try:
            con = sqlite3.connect(path)
            try:
                return con.execute("PRAGMA user_version").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            return 0
    for board, fn in BUNDLED_BOARDS.items():
        src = os.path.join(BUNDLED_DIR, fn)
        dst = world_path(board)
        if os.path.exists(src) and os.path.exists(dst) and ver(dst) < ver(src):
            # newer MME import ships with this version (same game data, more detail) — keep a backup,
            # then swap the new one in atomically (the file is never missing, even for a moment)
            try:
                shutil.copy2(dst, dst + ".old")
                tmp = f"{dst}.{os.getpid()}.tmp"
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
            except OSError:
                pass
            continue
        if os.path.exists(src) and not os.path.exists(world_path(board)):
            os.makedirs(paths_dir(board), exist_ok=True)
            tmp = f"{world_path(board)}.{os.getpid()}.tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, world_path(board))


def migrate_single_board():
    """Move a v0.2 data/world.db + data/paths into data/boards/Main (once, no data lost)."""
    import shutil
    install_bundled_boards()
    main = board_dir(LEGACY_BOARD)
    if os.path.exists(LEGACY_WORLD_DB) and not os.path.exists(world_path(LEGACY_BOARD)):
        os.makedirs(main, exist_ok=True)
        shutil.move(LEGACY_WORLD_DB, world_path(LEGACY_BOARD))
    if os.path.isdir(LEGACY_PATHS_DIR):
        os.makedirs(paths_dir(LEGACY_BOARD), exist_ok=True)
        for f in os.listdir(LEGACY_PATHS_DIR):
            src, dst = os.path.join(LEGACY_PATHS_DIR, f), os.path.join(paths_dir(LEGACY_BOARD), f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.move(src, dst)
    legacy_boss = os.path.join(DATA_DIR, "bosses.json")
    if os.path.exists(legacy_boss) and not os.path.exists(os.path.join(main, "bosses.json")):
        os.makedirs(main, exist_ok=True)
        shutil.move(legacy_boss, os.path.join(main, "bosses.json"))


WORLD_DB = world_path(LEGACY_BOARD)
PATHS_DIR = paths_dir(LEGACY_BOARD)
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
APP_STATE = os.path.join(DATA_DIR, "app.json")
SETTINGS = os.path.join(DATA_DIR, "settings.json")   # legacy single-profile file
KEYRING_SERVICE = "MudPilot"


@dataclass
class Settings:
    profile: str = "Default"
    board: str = DEFAULT_BOARD           # which BBS this character plays on (its own MME data, paths, boss timers)
    # connection
    host: str = ""
    port: int = 23
    username: str = ""
    save_password: bool = True
    auto_reconnect: bool = True
    reconnect_delay: int = 60              # a dropped line: try again this often, for as long as MudPilot is open
    leader_watch: bool = True              # following: notice the leader dropping / us being left behind
    leader_gone_wait_cmd: str = "/{name} @wait"   # sent once when left behind ("" = don't)
    attack_on_entry: bool = True           # walk into hostile monsters → attack before anything else
    mana_throttle: bool = True             # near the mana rest line: cheaper spells, keep going instead of meditating
    mana_throttle_band: int = 15           # starts this many % above 'rest below' mana
    rest_up_on_tick: bool = True          # end a rest on the regen tick when it's only a sliver short
    rest_smart_full: bool = True          # solo: take one more tick if it fills you completely
    smart_rest: bool = False              # quickest way back: rest / meditate + heals / rgen + meditate (smartrest.py)
    smart_rest_safe_hp: int = 50          # under this HP %, heal straight away whatever the plan says
    smart_rest_rates: dict = field(default_factory=dict)   # learned: rest / meditate HP and mana per second, heal size
    reconnect_max_delay: int = 300         # not used since 0.8.120 (retries are every reconnect_delay, no back-off)
    resume_after_reconnect: bool = True    # back in after a dropped line: carry on with the loop/path
    reinvite_after_reconnect: bool = True  # back in after a drop/hang-up: invite whoever was in your party
    dead_line_secs: int = 90               # sent something and heard nothing this long = the line is dead
    triggers: list = field(default_factory=lambda: [
        {"match": r"type it in and press ENTER|Enter your User-?ID|^\s*User-?ID:", "send": "{user}", "once": True},
        {"match": r"Enter your password|^\s*Password:", "send": "{password}", "once": True},
    ])
    # remote (@) commands — MegaMUD compatible, default deny
    remote_enabled: bool = True
    remote_channels: dict = field(default_factory=lambda: {"telepath": True, "say": True, "gangpath": True,
                                                           "broadcast": False})
    remote_players: dict = field(default_factory=dict)   # name -> [categories]
    remote_warn_denied: bool = True
    divert_to: str = ""
    my_name: str = ""
    # engine switches (the @auto-* toggles)
    auto_nuke: bool = True               # area attack spells (the Nuke button)
    auto_cast: bool = True               # retired 0.8.185: single-target spells follow auto_combat
    auto_heal: bool = True
    auto_bless: bool = True
    auto_preattack: bool = True
    auto_light: bool = False
    light_cmd: str = ""                  # e.g. "light torch"
    auto_light_items: bool = False       # 0.8.200: ready a carried torch/lantern before dark rooms, rem it in lit ones (lights.py)
    auto_sneak: bool = False
    sneak_mode: str = "smart"           # always | smart (only into lair rooms, or when solo)
    safe_rest_steps: int = 3            # on a loop, walk up to this many steps to rest outside a lair (0 = rest anywhere)
    lair_wait_secs: int = 0             # on a loop, wait this long in an empty lair for a spawn (0 = don't)
    sneak_cmd: str = "sn"
    auto_hide: bool = False
    hide_cmd: str = "hide"
    auto_search: bool = False
    # MegaMUD-style manual / auto mode defaults (auto = walking a path or loop)
    ignore_mode_defaults: bool = False
    mode_defaults: dict = field(default_factory=dict)   # {"manual": {flag: bool}, "auto": {...}}
    default_task: str = "nothing"        # "nothing" | "loop"
    default_loop: str = ""
    auto_connect: bool = False
    # combat
    auto_combat: bool = False
    attack_cmd: str = "a {target}"
    min_mobs: int = 1
    max_mobs: int = 99
    defend_out_of_range: bool = True     # fight back if attacked even outside min/max
    skip_zero_exp: bool = True           # don't attack shopkeepers/NPCs worth 0 exp
    attack_neutral: bool = False         # MME alignment Neutral (shopkeepers, slaves) — not hostile
    attack_good: bool = False            # Good / Lawful good (guards, the mayor) — you get evil points
    ignore_mobs: list = field(default_factory=list)
    # Game Data → Monsters attitude (MegaMUD's Enemy / Neutral / Friend), by monster name: overrides MME's alignment
    # — 'enemy' fights it (non-hostile amazon shamans for nature tap, Dan 0.8.208), 'neutral' / 'friend' leave it
    # alone unless it starts it. Not listed = MME's alignment, as before
    monster_attitude: dict = field(default_factory=dict)
    monster_order: dict = field(default_factory=dict)   # Game Data → Monsters: "monster" → "first" | "last" (attack order)
    only_mobs: list = field(default_factory=list)   # if non-empty, attack only these
    # spells (damage calc + auto-switch)
    attack_spells: list = field(default_factory=list)   # short names, e.g. ["bliz", "fbal", "lbol"]
    cast_cmd: str = "{short} {target}"
    char_level: int = 0                  # 0 = assume spell cap level
    spellcasting: int = 0                # your Spellcasting stat (0 = assume 100% cast chance)
    spell_dmg_bonus: int = 0
    spell_min_pct: int = 75              # skip spells doing < this % of rated damage on the target
    spell_mana_reserve: int = 0
    spell_round_secs: float = 4.5
    spell_cheap_below_exp: int = 0           # monsters worth less than this get the cheapest spell that works (0 = off)
    spell_fallback_melee: bool = True
    auto_spells: bool = True             # pick from every attack spell the character knows
    spell_pick: str = "damage"           # "damage" or "damage per mana"
    aoe_safety: bool = True              # no area spells with a non-party player in the room / room unknown
    spell_eff_floor_pct: int = 50        # a weaker spell has to do at least this % of the hardest one's damage
    spell_eff_max_steps: int = 2         # never more than this many steps below the hardest spell
    spell_efficiency: bool = True        # start on the hardest spell, dial back when you're overkilling alone
    auto_deposit_on: bool = False        # end of a lap: carrying this much → bank, deposit, back
    deposit_at_copper: int = 100000
    deposit_cmd: str = "deposit {copper}"
    last_worn: list = field(default_factory=list)   # what you had on (put back on after a corpse recovery)
    swap_owed: list = field(default_factory=list)   # rest-swap commands still owed (sent at the next login; 0.8.201)
    recover_corpse: bool = True          # 'recover corpse <you>' when your corpse is in the room
    item_rules: list = field(default_factory=list)   # Loot tab → Item rules: "rope and grapple: max 1" …
    withdraw_cmd: str = "withdraw {copper}"   # short of a toll or a boat fare: fetch the difference from the bank
    toll_bank_run: bool = True
    bank_room: str = ""                  # "17/2435"; blank = the nearest bank
    auto_sell_on: bool = False
    auto_sell_items: list = field(default_factory=list)
    # 0.8.227.7 (Dan: "pile up and sell when the party's full"): the sell trip waits till nobody in the party has room
    # for another of the sell list, then walks the whole party there whatever the distance, and the MudPilot followers
    # sell theirs too (down to each one's own 'keep')
    auto_sell_party_full: bool = False
    # 0.8.201 (Dan): chest / floor loot a shop pays under this many gold for isn't worth the walk — don't pick it up,
    # drop it when a chest hands it over; the valuable chest loot goes on the sell trip (chestloot.py). Off by default
    loot_drop_cheap: bool = False
    loot_drop_below_gold: int = 100
    # 0.8.201 (Dan): count the uses of charged items (wands die after N, per-day items refill at cleanup) and stop
    # using one that's out until cleanup (itemcharges.py). Blank cleanup time = refill 24 h after it ran out
    item_charges_on: bool = True
    cleanup_time: str = ""               # the realm's daily cleanup, this PC's clock, "HH:MM"
    auto_buy_on: bool = False
    auto_buy: str = ""                   # "healing potion 3-10; torch 2-5" = keep at least 3, buy up to 10
    trip_max_steps: int = 60
    auto_scrolls: bool = False           # 0.8.200: after a level-up, buy and read scrolls for spells you can now learn (scrolls.py)
    auto_train: bool = False             # 0.8.200: a level banked → the nearest trainer at the end of a lap (training.py)
    train_keep_levels: int = 0           # …but keep this many levels banked
    train_max_level: int = 0             # …and never train above this level (0 = no cap)
    train_stats: bool = False            # 0.8.200: after training, spend CP by the plan below with 'train stats'
    train_stats_plan: str = ""           # "10: STR 60 AGL 50; 20: STR 70" — target stats by level (cumulative)
    party_train: bool = False            # 0.8.200: leader takes its MudPilot members training too (@ptrain)
    char_alignment: str = ""             # blank = from the who list (exit gates like "Alignment: Saint to Seedy")
    char_race: str = ""
    route_pay_tolls: bool = True         # route through toll exits you can afford
    route_spell_traps: bool = False      # route through spell-trap exits (only when much shorter)
    route_tokens: bool = False           # 0.8.201: Go to may 'use' a teleport token you carry (token of Silvermere…)
    route_token_min_save: int = 40       # …only when it saves at least this many rooms of walking
    route_token_dest: dict = field(default_factory=dict)  # token name (lower) → "map/room" where it lands (beats MME's)
    hazard_counters: bool = False        # 0.8.201: buy a cheap item that stops a route's room damage (cold, magma…)
    hazard_counter_cap: int = 300        # …never one costing more than this many gold
    gear_modes_on: bool = False          # swap gear by itself (Loot tab → Gear modes)
    gear_modes: dict = field(default_factory=dict)       # mode → {slot: item}
    monster_spells: dict = field(default_factory=dict)   # Game Data → Monsters: "monster" → {"spell": short | "" (melee), "variants": bool}
    known_spells: list = field(default_factory=list)    # read from the game's `spells` list
    known_spells_at: float = 0.0
    known_spell_rows: list = field(default_factory=list)  # [short, name, level, mana] as the game lists them
    char_class: str = ""                 # from the stat screen (for spell / gear fallbacks)
    pre_attack_spell: str = ""           # cast once as a fight starts (e.g. a debuff/opener)
    use_area_min: bool = True          # area spells only (and first) when mobs >= multi_min_mobs
    multi_spell: str = ""                # area spell when enough mobs are in the room
    multi_min_mobs: int = 3
    megamud_extra: dict = field(default_factory=dict)   # unmapped keys kept from a MegaMUD import
    # bless / buff upkeep (MegaMUD "bless spells" + ability checks)
    buffs: list = field(default_factory=list)   # see Buff fields in automation.py
    abil_check_cmd: str = "abil"             # your board's ability command (blank = only per-rule checks)
    abil_check_secs: int = 60
    heal_cmd: str = ""                  # minor heal (Spells tab), cast below heal_pct
    heal_pct: int = 50
    major_heal_cmd: str = ""            # major heal, cast below major_heal_pct
    major_heal_pct: int = 35
    heal_min_ma_fight: int = 0          # heal in a fight only while mana is at or above this % (0 = any mana)
    heal_min_ma_rest: int = 0           # out of a fight (resting, walking) only at or above this % (0 = any mana)
    hp_regen_cmd: str = ""              # cast when you start resting (HP low)
    ma_regen_cmd: str = ""              # cast when you start meditating/resting for mana
    hp_full_cmd: str = ""               # cast once when HP tops out
    ma_full_cmd: str = ""               # cast once when mana tops out
    max_off_casts: int = 0              # attack-spell casts per fight before melee (0 = no limit)
    # cures — the bot casts these when the game says you're poisoned/blind/diseased/held
    cure_poison_cmd: str = ""
    cure_blind_cmd: str = ""
    cure_disease_cmd: str = ""
    freedom_cmd: str = ""
    ignore_poison: bool = False
    ignore_blindness: bool = False
    ignore_confusion: bool = False
    cures_first: bool = False           # prioritise cures over minor heal
    party_cures: bool = True            # cast your cures on party members too (poison from 'par', '@blind' etc. said)
    report_conditions: bool = True      # in a party, say '@blind' / '@held' / '@diseased' when you can't cure it yourself
    bless_margin_secs: int = 15         # timer blesses recast this long before they wear off
    run_pct: int = 0                    # 0 = never run (running just drags a pile of mobs along)
    # resting
    auto_rest: bool = True
    rest_cmd: str = "rest"
    use_meditate: bool = False           # meditate (not rest) when only mana is low
    # gear swaps (MegaMUD Health tab Pre-rest/Post-rest/Pre-med/Post-med); ^M separates commands
    auto_regen_gear: bool = False        # put on the best HP / mana regen gear in your pack to rest, fighting gear after
    rest_swap_on: bool = False
    pre_rest_cmd: str = ""
    post_rest_cmd: str = ""
    med_swap_on: bool = False
    pre_med_cmd: str = ""
    post_med_cmd: str = ""
    party_check_secs: float = 5         # send 'par' this often while in a party (0 = off); solo: every 5 min
    # party healing
    party_heal: bool = False            # heal the party member with the lowest HP %
    party_heal_pct: int = 70            # ...when they're below this
    party_heal_cmd: str = ""            # e.g. "mihe {name}" (blank = heal command + name)
    party_heal_priority: list = field(default_factory=list)   # names healed first (e.g. whoever attacks last)
    party_priority_bonus: int = 15      # priority players count as this many % lower
    party_major_cmd: str = ""           # major heal for party members ({name}); below party_major_pct
    party_major_pct: int = 50
    party_area_cmd: str = ""            # area heal when party_area_count members are below party_area_pct
    party_area_count: int = 3
    party_area_pct: int = 80
    area_over_major: bool = False
    heal_party_over_self: bool = True   # heal a party member before yourself if they're lower
    rest_heal_party: bool = True        # keep healing the party while you rest
    request_heal_pct: int = 0           # ask for healing below this HP % (0 = off)
    request_heal_cmd: str = "gangpath heal me please ({hp}%)"
    party_blesses: list = field(default_factory=list)   # [{"cast": "prot", "secs": 0 (auto)}] cast for the party
    par_after_round: bool = False       # send 'par' after each combat round
    attack_reverse: bool = False        # attack the last monster listed first
    no_wait: bool = False               # NoWait: ignore @wait and don't wait for hurt members (timed lairs) — dangerous
    hands_off: bool = False             # Hands off: nothing automatic at all (hang-up safety still on)
    no_hang: bool = False               # NoHang: overrides every automatic hang-up (PvP, low HP, enemies, rules)
    target_priority: str = "first"      # which monster in the room list to attack: first / second / third / last
    target_biggest: bool = True         # the biggest threat (most exp) first — the prismatic dragon, not its serpents
    attack_leaders_target: bool = True  # attack what the leader attacks
    party_leader: str = ""              # who leads (blank = whoever's first in 'par')
    defend_party_pvp: bool = True       # attack a player who attacks your party (when not hanging up)
    share_cash: bool = False            # share coins you pick up
    share_cmd: str = "share {qty} {item}"
    help_bash: bool = True              # bash the door the leader is bashing
    say_panic: bool = True              # gangpath @panic when you run while leading
    ignore_panic_following: bool = False
    ignore_party_following: bool = False
    ignore_wait_leading: bool = False
    party_max_mobs: int = 0             # max monsters when in a party (0 = Combat tab's)
    party_max_mob_exp: int = 0          # skip monsters worth more than this in a party (0 = no limit)
    party_wait_pct: int = 70            # leading: wait for members below this HP % to rest (Dan: 70 by default)
    party_wait_mins: float = 2          # ...for at most this long
    party_teleport_bring: bool = True
    party_say_cmds: list = field(default_factory=list)   # typed exits followers don't follow: '@party <cmd>' first (learned)   # leading through a command exit: '@party <cmd>' first, then wait for them
    aid_party: bool = True              # 'aid <name>' when a party member drops to the ground bleeding
    party_wait_until_pct: int = 0       # ...and once waiting, until they're back to this HP % (0 = the wait line).
    # Not 90: that's the healer's minor-heal line, which heals on the move — the party mustn't stand for it
    party_wait_ma_pct: int = 20         # leading: also wait for a member below this mana % (0 = off)…
    party_wait_ma_until: int = 60       # …until they're back to this
    party_wait_msg: str = "@wait"
    party_resume_msg: str = "@ok"
    # PvP spells: cast in order each round while fighting a player
    pvp_spells: list = field(default_factory=list)   # [{"cast": "mist", "rounds": 25}, {"cast": "slep", "rounds": 0}]
    pvp_target_cmd: str = "{cast} {name}"
    pvp_auto_fight: bool = False        # fight back a player who attacks you (instead of only hanging up)
    # routing (Go to, events, stash runs)
    avoid_names: list = field(default_factory=lambda: ["Negative Power Plane"])   # rooms whose name has this
    avoid_rooms: list = field(default_factory=list)       # map/room numbers to never walk through
    avoid_mode: str = "ask"             # ask (when you click Go to) | avoid | allow
    bash_key_doors: bool = True         # a key door you have no key for: try to pick/bash it instead of refusing
    auto_get_items: bool = True         # missing a key? go kill the monster that drops it / buy it, then walk
    check_needed_items: bool = True     # before a path: keys / rope and grapple / idol the exits need
    arrive_auto_on: bool = True         # Go to arrived → turn these on
    arrive_turn_on: list = field(default_factory=lambda: ["auto_combat", "auto_nuke", "auto_rest", "auto_heal"])
    boss_stop_pct: int = 40             # …only when it's expected to do at least this % of your max HP (0 = always)
    stop_before_boss: bool = True       # stop before walking into a boss's room (MegaMUD style)
    boss_route_round: bool = True       # Go to / trips / the way back: round any boss's room when there's a way about as short
    boss_hunt_on: bool = True           # bosses ticked "Hunt": leave the loop to kill them when due, then come back
    boss_hunt_max_steps: int = 80
    boss_farm_on: bool = False          # also when idle (not walking): go kill ticked bosses, loot, come back
    boss_loot_cmd: str = "get all"       # after a hunted boss dies (; between commands)
    boss_no_stop: list = field(default_factory=list)   # boss names you just walk in on and mow down
    eco_travel: bool = True              # Eco: on the way somewhere, don't stop for small fry
    eco_min_exp: int = 0                 # …still fight anything worth at least this (0 = auto: level × 50, or half a minute of exp/hr)
    eco_max_hit: int = 0                 # …or that hits harder than this (0 = auto: 8% of max HP, at least 25)
    eco_pack_pct: int = 5                # …or the ones walked past hit you for this % of max HP in a round: clear the room
    eco_hp_pct: int = 60                 # …and fight back whatever's on you below this HP %
    start_maximized: bool = True
    last_room: str = ""                  # where you were last (a hint for placing you after a restart)
    known_abils: dict = field(default_factory=dict)   # your quest flags / abilities from the last full 'abil'
    backstab_weapon: str = ""            # wield this for a backstab…
    main_weapon: str = ""                # …and this again after (blank = what you had)         # open the main window maximised, after the loading screen
    auto_weapon_swap: bool = True        # a monster your weapon can't hurt: wield a carried one magical enough, then back (0.8.201)
    disarm_traps: bool = False           # 'disarm trap <dir>' before a trapped exit (a thief's skill)
    disarm_tries: int = 2
    record_sessions: bool = True         # keep a recording of each session in data\traces (passwords removed)
    show_recover_password: bool = False  # 'pro' prints your recover password — masked on screen unless this is on
    mpsync_not: dict = field(default_factory=dict)   # party members who answered @mpsync hi from MegaMUD: name → when
    mpsync_peers: dict = field(default_factory=dict)  # teammates' last '@mpsync me' / level: name → {me, lvl, t}
    talk_slow: int = -1                  # 'set talk slow' on the board: 1 = say needs a leading '.', 0 = not, -1 = not seen yet
    invite_join_cmd: str = "/{name} @join"   # sent right after inviting someone, so they join now ("" = off)
    party_reset_on_loop: bool = True       # arriving on a new loop telepaths each party member @reset
    party_reset_cmd: str = "/{name} @reset"
    party_rank: str = ""                # "front" | "mid" | "back" — set it whenever you're in a party
    rank_cmd: str = "{rank}rank"        # frontrank / midrank / backrank ({rank} = front/mid/back)
    attack_last: bool = False           # attack at once, and again after each party member joins in (be the last)
    attack_last_wait: float = 8         # (not used any more) ...but attack anyway after this many seconds
    # MegaMUD "Other" options
    pick_locks: bool = False            # pick locks instead of bashing
    bash_cmd: str = "bash {dir}"
    pick_cmd: str = "pick {dir}"
    bash_doors_first: bool = True        # a closed door: bash it straight away (they're nearly always locked)
    attempt_bash: int = 20              # (Dan, 2026-10-30: 3 gave up on a bashable door — bashing is a roll)
    party_bash_help: bool = True        # leading: the party's MudPilots bash the door with you
    attempt_pick: int = 3
    relog_instead_of_hang: bool = False
    afk: bool = False                   # Away From Keyboard (Alt+K)
    allow_hangup_not_afk: bool = True   # remote @hangup works when you're not AFK
    allow_hangup_all_off: bool = False  # ...and when every auto switch is off
    hangup_if_naked: bool = True        # hang up if your inventory shows nothing worn or wielded
    bless_while_resting: bool = False
    bless_in_combat: bool = True
    spell_mana: dict = field(default_factory=dict)   # spell number -> your own mana cost (Game Data → Spells)
    late_round_spells: str = "slep"     # partial-round spells: cast in the last seconds of the round (Dan, 2026-10-30)
    late_round_secs: float = 2.0
    late_cast_guard: float = 1.6
    heal_window_secs: float = 2.5       # mid-fight heals: only in the first this-many seconds of a round (Dan)        # mid-fight blesses/minor heals: not this close before the next round (pMUD)
    stall_secs: float = 8.0             # being hit but no attack of ours this long: attack again (0 = off)
    bless_st_timers: bool = True        # read bless time-left from 'st' (Paradigm shows "(216s)")
    go_back_if_running: bool = True     # run back the way you came
    break_before_running: bool = False
    break_cmd: str = "bre"
    manual_override: bool = True        # an attack / targeted spell you type: that fight's yours until you stop
    manual_round_secs: float = 5        # one combat round
    manual_idle_rounds: int = 2         # combat off this many rounds with no attack from you → MudPilot takes over
    manual_max_rounds: int = 4          # …and never longer than this since your last attack
    run_distance: int = 1               # rooms to run
    light_dim_rooms: bool = False       # light up dimly lit rooms too
    dont_move_unless_sneaking: bool = False
    search_count: int = 1               # searches per room (auto Search: hidden gold and items, every room)
    command_splitter: str = ";"         # split what you type into several commands
    scrollback_lines: int = 20000
    delete_players_days: int = 90       # forget Unknown players not seen for this long (0 = never)
    game_entry_cmd: str = ""            # sent once you're in the game
    game_exit_cmd: str = ""             # sent before a normal Disconnect / relog
    meditate_cmd: str = "medi"
    rest_below_hp: int = 60
    route_danger_pct: int = 60          # routes keep out of lairs whose full spawn would cost this % of your HP (0 = off)
    drain_heal: bool = True             # last weak monster + HP under the rest line: drain it back up (dtch)
    drain_spell: str = "dtch"
    stash_rafts: bool = True            # a loop that doesn't cross water: hide the rafts there, pick them up leaving
    raft_stash: dict = field(default_factory=dict)   # where this character's rafts are hidden (stash.py)
    rest_until_hp: int = 100
    rest_below_ma: int = 0
    rest_until_ma: int = 100
    # loot
    auto_loot: bool = False
    loot_cash: bool = True
    loot_items: list = field(default_factory=list)
    # cash rules (Loot tab): pick each coin up or not, and stop once you're past a level
    cash_rules: dict = field(default_factory=lambda: {
        "copper farthing": {"get": True, "skip_at": 5}, "silver noble": {"get": True, "skip_at": 10},
        "gold crown": {"get": True, "skip_at": 0}, "platinum piece": {"get": True, "skip_at": 0},
        "runic coin": {"get": True, "skip_at": 0}})
    drop_small_coins: bool = True       # getting heavy? drop cheaper coins to make room for better ones
    drop_coins_enc: int = 50            # ...once encumbrance reaches this %
    drop_unwanted_coins: bool = False   # drop coins you no longer collect at your level
    coins_not_heavy: bool = False       # don't pick up coins once you're Heavy (encumbrance ≥ coins_heavy_pct)
    coins_heavy_pct: int = 66           # ...this % (MajorMUD says Heavy somewhere between 59 and 70)
    drop_cmd: str = "drop {qty} {item}"
    loot_never: list = field(default_factory=list)       # never pick these up even if they match
    # stash (each lap): leave valuable coins / items in a room
    stash_room: str = ""                # default stash (map/room, e.g. 3/606) for loops without their own
    party_stash_room: str = ""          # set by a member's '@stash' here: auto-stash items get hidden in it too
    loop_stash: dict = field(default_factory=dict)   # loop file name -> its own stash room "map/room"
    loop_runthru: dict = field(default_factory=dict)  # loop file name -> ["map/room"…] crossed between two rounds
    stash_max_steps: int = 40           # never walk further than this from a loop to stash
    stash_coins: list = field(default_factory=lambda: ["gold crown", "platinum piece", "runic coin"])
    stash_items: list = field(default_factory=list)
    stash_cmd: str = "drop {qty} {item}"
    stash_hide: bool = True             # hide it after dropping
    stash_hide_cmd: str = "hide {qty} {item}"   # hides it from your pack (instead of dropping it)
    stash_looted: bool = True           # (not used any more) also stash every item the Get button picks up (weapons that sell, etc.)
    stash_each_lap: bool = True         # walk to the stash room at the end of each lap if you're carrying any
    stash_min_copper: int = 500         # ...but only when it's worth this much (copper value) or more
    get_cash_cmd: str = "get {qty} {item}"
    get_item_cmd: str = "get {item}"
    # PvP / awareness
    hangup_on_pvp: bool = True           # drop the line when a player attacks you or your party (@pvp off)
    pvp_loot_cmds: str = "get all"       # party member killed by a player: grab this first (; between)
    hangup_on_player: bool = False       # drop the line when any player shows up
    pvp_friends: list = field(default_factory=list)   # never hang up for these (party is always ignored)
    hangup_low_hp: bool = True           # hang up when HP drops below hangup_hp_pct
    hangup_hp_pct: int = 25
    hangup_stay_offline: float = 0       # minutes to stay off before auto-reconnect (0 = until you reconnect)
    # 0.8.201 (Dan): hang-up item pickup (hangupitems.py). Off and 0 until you set them: only boards whose sysop set
    # items to drop on a penalised hang-up (Stock option #38 / #60) need it; Paradigm never drops items, only HP
    hangup_items_drop: bool = False      # this board drops items on a hang-up: pick them back up after logging in
    hangup_items_count: int = 0          # how many items the board drops (its option #60); the pickup never takes more
    look_on_sound: bool = True           # "You hear movement to the northeast" -> look northeast
    look_ignore_secs: float = 3          # ignore the same direction for this long after looking
    macros: dict = field(default_factory=dict)        # this character's macros (key -> text with ^M)
    keypad_macros: bool = True                        # number pad runs macros (n/s/e/w...) instead of typing digits
    aliases: dict = field(default_factory=dict)       # 0.8.201: typed word -> commands (aliases.py; Game Data → Aliases)
    chat_alerts_on: bool = False                      # 0.8.201: chat keyword alerts (chatalerts.py), off unless ticked
    chat_alert_words: list = field(default_factory=list)   # words that flag a chat line (whole word, any case)
    # players
    learn_players: bool = True           # look at players once to learn their gear
    look_player_hours: float = 24        # ...and not again for this many hours
    hangup_on_enemy: bool = True
    hangup_monsters: list = field(default_factory=list)   # monsters that make you hang up the moment they show up
    pvp_tell_party: bool = True          # telepath the party "*Attacked* … hanging up!" before a PvP hang-up
    safe_rooms: list = field(default_factory=list)        # "map/room": never start a fight here (towns, quest NPCs)
    info_cmd_rules: dict = field(default_factory=dict)    # pMUD gather: {"par": {"gap": 10, "no_combat": True, …}}
    tick_cmds: list = field(default_factory=list)         # "0.3 resting look" — sent at that point of every tick
    enter_on_tick: bool = True                            # enter the realm just after the server tick
    stop_on_danger: bool = True                           # a low-HP hang-up doesn't relog by itself
    banks_safe: bool = True                               # banks count as safe rooms too (pMUD's defaults)
    deadly_rooms: list = field(default_factory=lambda: ["Muddy Underwater Passage"])  # never stand still in these
    stop_on_typed_move: bool = True      # you typed a move while it walked a path: it stops until you click Rego
    pilot_goto: bool = True              # New Go to walker (plans every step from where you really are)
    pause_on_typed_move: int = 6         # you typed a move yourself: the bot keeps its hands off for this many s         # hang up when a player marked Enemy is seen
    exp_formula: str = "stock"           # "stock" MajorMUD or "greatermud"
    # config profiles 1-4 (Alt+1..4): each holds a full set of options
    config_profiles: dict = field(default_factory=dict)  # "1".."4" -> {"name": str, "values": {...}}
    active_config: str = "1"
    settings_version: int = 20            # bumped when a default changes so old saves can be migrated once
    ntfy_on: bool = False               # phone alerts via ntfy (topic kept in Credential Manager)
    ntfy_server: str = "https://ntfy.sh"
    ntfy_kinds: list = field(default_factory=lambda: ["hangup", "pvp", "death", "track", "stop", "drop", "leader"])
    rotate_on: bool = False               # loop rotation (Paths → More → Loop rotation…)
    rotate_loops: list = field(default_factory=list)   # loop keys, in order
    rotate_mode: str = "empty"            # "empty" = when a lap's lairs were mostly empty · "laps" = every N laps
    rotate_empty_pct: int = 50
    rotate_laps: int = 3
    sounds_on: bool = False
    sound_events: dict = field(default_factory=lambda: {"hangup": "", "death": "", "pvp": "", "telepath": ""})
    schedules: list = field(default_factory=list)   # [{"at": "06:30" | "every": mins, "action", "arg", "on"}]
    track_cmd: str = "trac"
    track_max_steps: int = 40
    track_max_fails: int = 3
    leaderboard_on: bool = False          # 'top 200' every hour, exp/hr for everyone (Window → XP leaderboard)
    leaderboard_mins: int = 60
    eightball_on: bool = False            # answer "(8) question" on gossip
    message_rules_on: bool = True         # MegaMUD-style Messages (Game Data → Messages)
    party_comeback: bool = True           # leader waits for a dropped member and fetches them; follower asks @comeback
    comeback_wait_mins: float = 5
    party_missing_secs: int = 30          # leading: a member still in the party but not with us this long → @where, fetch
    party_sync: bool = True               # MudPilot party members: share rest/HP/mana, rest together
    gear_watch: bool = True               # alert when armour better than yours shows up
    gear_watch_weapons: bool = True       # …and weapons that hit harder per round (alert only, never wielded; 0.8.201)
    gear_goal: str = "Armour class (AC)"  # what "better" means (inventory calculator goals)
    gear_min_gain: float = 0.5
    gear_grab_upgrades: bool = False      # pick up upgrades lying in a room
    gear_auto_wear: bool = False          # …and put them on
    danger_opener_spell: str = ""         # dangerous fight: cast this first (e.g. mist = mystic mist)
    danger_opener_pct: int = 50           # dangerous = expected damage ≥ this % of your current HP…
    danger_opener_mobs: int = 3           # …or this many monsters (0 = ignore), or a boss
    danger_big_spells: bool = True        # dangerous fight: hardest-hitting spells, mana throttle off
    danger_check: bool = True             # before a lair: rest up if a full spawn could hurt too much
    danger_stop: bool = False             # …and stop the loop if even full HP isn't enough
    lair_pace: bool = True                # rest while the next lair refills instead of walking in on it empty
    lair_pace_max: int = 45               # …only if it's due within this many seconds
    # 0.8.201 (Dan): Camp lairs (lair_camp.py) — the lairs you marked, and how the next one is picked. Camping only
    # runs when you start it (Paths → Camp lairs, or @camp start); nothing here turns it on
    lair_camp_rooms: list = field(default_factory=list)   # ["map/room", …]
    lair_camp_throughput: bool = False    # pick the lair we'd be least late for, not the closest one that's back
    scripter_wait: bool = True            # another player clearing the lairs just ahead: let them come round
    scripter_wait_max: int = 240          # …for at most this many seconds
    scripter_trail: bool = False          # …or trail them round the loop's rooms (never out of them) to take the kills
    ac_cmd: str = "stat all"              # what @ac types to read AC/DR (Paradigm shows vs evil/good here)
    death_action: str = "stay"            # after dying: "stay" (stop, alert) or "hangup"
    death_hangup_secs: int = 8
    tune_mins: int = 30                    # auto-tune resting: minutes of looping per setting tried
    tune_rounds: int = 1
    tune_baseline: dict = field(default_factory=dict)   # your settings while a test runs (restored if it's cut short)
    ntfy_control: bool = False            # accept status / stop / hang up typed in the ntfy app
    web_on: bool = False                  # phone page over Headscale/Tailscale (watch-only; key in Credential Manager)
    status_broadcast: bool = False        # 0.8.201: send a small status packet (UDP broadcast, this LAN only) for the All characters window
    status_broadcast_port: int = 47870
    web_bind: str = ""                    # blank = this PC's Headscale/Tailscale address
    web_port: int = 0                     # 0 = first free from 8770
    watchdog_on: bool = False             # stuck for a while → try to get going again, then tell the phone
    watchdog_mins: int = 5
    summary_on: bool = False              # morning summary to the phone
    summary_time: str = "07:00"
    boss_warn_mins: int = 10              # "boss due back in N min" (when the Boss alert is ticked)
    auto_enter_realm: bool = True       # at the MajorMUD menu, enter the realm by itself…
    enter_realm_prompt: str = "[MAJORMUD]:"
    enter_realm_cmd: str = "E"          # …except right after you (or MudPilot) hung up: then you choose
    logon_steps: list = field(default_factory=list)   # BBS logon: [{"match": "Please enter your selection:", "send": "P", "every": False}]
    user_prompt: str = ""                # BBS tab: the board's "enter your username" line (blank = recognise the usual ones)
    pass_prompt: str = ""                # ...and its password line
    hide_password: bool = False
    # Messages / Responses (PvP team commands) + track alerts
    responses_on: bool = True
    responses: list = None               # None = MudPilot's starter set (nuke, bs *, sneak, hide, hold, track…)
    track_alert: bool = True             # tell the team when tracking turns up players
    track_alert_channel: str = "broadcast"   # broadcast | gangpath | say | party
    track_alert_msg: str = "Tracks: {names} near {room}"
    track_pattern: str = ""              # blank = MudPilot's built-in patterns
    track_hangup: bool = False           # also hang up yourself
    # Talk / AFK
    log_chat: bool = True
    greet_players: bool = False
    greet_cmd: str = "wave {name}"
    disallow_remote: bool = False
    disallow_gangpath_remote: bool = False
    chat_keep_lines: int = 200
    auto_afk_mins: float = 5            # go AFK after this long with no typing (0 = never)
    afk_when_minimized: bool = True
    input_cancels_afk: bool = True
    afk_message: str = "{AFK}"
    remote_fail_msg: str = "{command invalid or not allowed}"
    # Auto-roam
    roam_dirs: list = field(default_factory=lambda: ["N", "S", "E", "W", "NE", "NW", "SE", "SW"])
    roam_open_dirs: list = field(default_factory=list)
    roam_rooms: list = field(default_factory=list)      # [{"room": "3/606", "cmd": "..."}]
    # General / toolbar
    backup_settings: bool = True
    show_toolbar: bool = True
    update_check: bool = True           # ask GitHub for a newer release when MudPilot opens (nothing about you is sent)
    update_skip: str = ""               # a version you said Skip to
    window_colour: str = ""             # title bar colour (Win 11) + strip: "" = picked from the data folder, or a name
    toolbar_order: list = field(default_factory=list)   # the toolbar's buttons as you dragged them ([] = default)
    toolbar_icons: bool = True           # MegaMUD-style icon buttons (hover for the name); off = text buttons          # the lock on the BBS tab's password box
    # layout + fonts
    term_font: str = "Consolas"
    term_font_size: int = 12
    cp437_terminal: bool = False         # (0.8.201) BBS art: MUD window in a font that draws CP437 box/block glyphs
    chat_font: str = "Arial"            # MegaMUD's conversation window look
    chat_font_size: int = 12
    layout_main: float = 0.667          # MUD window share of the width (right column = the rest)
    layout_right: float = 0.4           # conversations share of the right column's height (map gets the rest)
    map_minimized: bool = False
    pvp_realm: bool = False              # this game allows PvP (seen 'PVP' at the menu / a Server PvP message)
    chat_filters: dict = field(default_factory=dict)     # channel → shown
    chat_colors: dict = field(default_factory=dict)      # channel → #rrggbb (blank = MegaMUD's)
    chat_timestamps: bool = True
    chat_split: bool = True
    chat_show_bot: bool = False         # conversations: show every @command and bots' {auto answers} (party sync,
    #                                     spell tuning…). Your own @commands and their answers always show.
    map_window_rooms: str = "Zoom"      # pop-out map: Zoom | 20×20 | 30×30 | 50×50
    window_geom: dict = field(default_factory=dict)     # "main" / "Map" / "Party" / … -> "WxH+X+Y"
    open_windows: list = field(default_factory=list)    # pop-outs to bring back next start
    dock_chat: bool = True               # conversations pane top-right
    locate_cmd: str = "pro"              # board command that prints your room number (blank = off)
    # events (timers, text triggers, boss hunts)
    events: list = field(default_factory=list)
    # walking
    refresh_secs: int = 6
    step_timeout: int = 10
    last_path: str = ""

    # ------------------------------------------------------------ config profiles 1-4
    # Each character has four sets of options (MegaMUD's Config Profile 1-4, Alt+1..4),
    # e.g. 1 = solo with PvP hang-ups on, 2 = grouped with hang-ups off.
    # Who the character is, where it connects, learned data and macros are shared.
    CONFIG_SHARED = {"profile", "board", "host", "port", "username", "save_password", "triggers", "my_name",
                     "known_spells", "known_spells_at", "known_spell_rows", "char_level", "char_class",
                     "megamud_extra", "config_profiles", "active_config", "macros", "dock_chat", "events",
                     "remote_players", "pvp_friends", "last_path", "spellcasting", "window_geom", "open_windows",
                     "layout_main", "layout_right", "map_minimized", "raft_stash",
                     "lair_camp_rooms", "aliases"}   # (0.8.201: the marked lairs are the character's, not a config slot's)

    def _config_values(self) -> dict:
        import copy
        return {k: copy.deepcopy(v) for k, v in asdict(self).items() if k not in self.CONFIG_SHARED}

    def config_name(self, slot: str) -> str:
        return (self.config_profiles.get(slot) or {}).get("name") or f"Config Profile {slot}"

    def rename_config(self, slot: str, name: str):
        self.config_profiles = dict(self.config_profiles)
        self.config_profiles[slot] = dict(self.config_profiles.get(slot) or {}, name=name.strip())

    def switch_config(self, slot: str) -> bool:
        """Store the current options in the active slot and load `slot` (an empty slot
        starts as a copy of the current options). Returns True if anything changed."""
        slot = str(slot)
        if slot == self.active_config:
            return False
        profs = dict(self.config_profiles)
        cur = dict(profs.get(self.active_config) or {})
        cur["values"] = self._config_values()
        profs[self.active_config] = cur
        target = dict(profs.get(slot) or {})
        vals = target.get("values")
        if vals:
            fresh = Settings()
            for k in self._config_values():
                setattr(self, k, vals[k] if k in vals else getattr(fresh, k))
        target["values"] = self._config_values()
        profs[slot] = target
        self.config_profiles = profs
        self.active_config = slot
        return True

    @staticmethod
    def profile_path(name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "Default"
        return os.path.join(PROFILES_DIR, safe + ".json")

    @staticmethod
    def list_profiles() -> list:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        return sorted(f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith(".json")) or ["Default"]

    @classmethod
    def load(cls, profile: str | None = None) -> "Settings":
        if profile is None:
            try:
                with open(APP_STATE, "r", encoding="utf-8") as f:
                    profile = json.load(f).get("profile", "Default")
            except (OSError, ValueError):
                # app.json missing or damaged (a power cut left 25 zero bytes on Revolution's PC, 2026-10-30, and he
                # came up on a blank Default — no login, no realm): open the profile saved most recently instead
                profile = cls._last_saved_profile() or "Default"
            ran = cls._profile_last_running()
            if ran and ran != profile:
                cls._profile_note = (f"app.json said '{profile}', but '{ran}' was the one running last — "
                                     f"opening '{ran}'")
                profile = ran
        s = cls()
        s.profile = profile
        path = cls.profile_path(profile)
        if not os.path.exists(path) and profile == "Default" and os.path.exists(SETTINGS):
            path = SETTINGS   # migrate old single settings file
        try:
            # (0.8.201, Dan: a fresh install — no settings saved at all yet — asks which board it plays on instead
            #  of quietly routing on Paradigm's map; any install with a profile is left as it is)
            s._first_run = not os.path.exists(path) and not any(
                f.endswith(".json") for f in (os.listdir(PROFILES_DIR) if os.path.isdir(PROFILES_DIR) else []))
        except OSError:
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(s, k) and k != "profile":
                    setattr(s, k, v)
            if s.board == LEGACY_BOARD and not os.path.exists(world_path(LEGACY_BOARD)) \
                    and os.path.exists(world_path(DEFAULT_BOARD)):
                s.board = DEFAULT_BOARD         # never imported anything: use the bundled Paradigm data
            if int(data.get("settings_version") or 0) < 8 and data.get("term_font_size", 10) == 10:
                s.term_font_size = 12               # 0.8.x shipped a small MUD-window font
            if data.get("party_check_secs") == 20 and int(data.get("settings_version") or 0) < 7:
                s.party_check_secs = 5          # 0.6 default was 20 s; MegaMUD's is 5
            if int(data.get("settings_version") or 0) < 15 and data.get("attempt_bash", 3) == 3:
                s.attempt_bash = 20             # 0.8.119 and older gave up after 3 bashes
            if int(data.get("settings_version") or 0) < 9 and data.get("run_pct", 20) == 20:
                s.run_pct = 0                   # 0.8.7 and older ran at 20% HP by default
            for bf in (s.buffs or []) if int(data.get("settings_version") or 0) < 10 else []:
                if (bf.get("cast") or "").strip().lower() in ("flux", "ntap", "nity") and "while_resting" not in bf:
                    bf["while_resting"] = True      # mana regen is most useful while you rest
                if (bf.get("cast") or "").strip().lower() in ("flux", "ntap", "nity") and bf.get("min_mana_pct", 25) == 25:
                    bf["min_mana_pct"] = 5          # don't hold the mana-regen spell back when mana is low
            if data.get("stash_hide_cmd") == "hide {item}":
                s.stash_hide_cmd = "hide {qty} {item}"   # hide from the pack, don't drop first
            if data.get("rank_cmd") == "rank {rank}":
                s.rank_cmd = "{rank}rank"       # 0.8.x default was wrong: MajorMUD uses frontrank/midrank/backrank
            if int(data.get("settings_version") or 0) < 12 and not (data.get("command_splitter") or "").strip():
                s.command_splitter = ";"        # MegaMUD's ';' = Enter on the command line
            if int(data.get("settings_version") or 0) < 11 and isinstance(s.ntfy_kinds, list):
                for k in ("drop", "leader"):     # new alerts that matter overnight: on for everyone
                    if k not in s.ntfy_kinds:
                        s.ntfy_kinds.append(k)
            if int(data.get("settings_version") or 0) < 13:
                # 'Users' (hang up on any player) came on with the mode defaults — off for everyone; hang
                # up only on players marked Enemy (Game Data → Players, or right-click their name)
                s.hangup_on_player = False
                s.hangup_on_enemy = True
                for md in (s.mode_defaults or {}).values():
                    if isinstance(md, dict):
                        md["hangup_on_player"] = False
            if int(data.get("settings_version") or 0) < 14:
                # 0.8.51 put NoHang into the mode defaults (on!) — every Go to switched hang-ups off. Take it
                # out; and Eco on for trips (Dan: on by default)
                for md in (s.mode_defaults or {}).values():
                    if isinstance(md, dict):
                        md.pop("no_hang", None)
                        md.setdefault("eco_travel", True)
                        md["eco_travel"] = True
                s.eco_travel = True
                s.hangup_on_pvp = True if data.get("hangup_on_pvp") is None else s.hangup_on_pvp
            if int(data.get("settings_version") or 0) < 16 and data.get("reconnect_delay", 20) == 20:
                s.reconnect_delay = 60       # Dan: retry every 60 s, forever (was 20 s doubling up to 5 min)
            if int(data.get("settings_version") or 0) < 17:
                # Dan, 2026-10-30: wait for a member below 70% (was 80) and walk on once they're back over it — not
                # stand till 90%, the healer's minor-heal line (it heals on the move). Your own numbers stay.
                if data.get("party_wait_pct", 80) == 80:
                    s.party_wait_pct = 70
                if data.get("party_wait_until_pct", 90) == 90:
                    s.party_wait_until_pct = 0
            if int(data.get("settings_version") or 0) < 20:
                s.chat_show_bot = False         # 0.8.137 showed all the party-sync chatter (Dan: "excessive"); your own
                #                                 @ questions and their answers show anyway
            if int(data.get("settings_version") or 0) < 18 and float(data.get("layout_right", 0.4) or 0) < 0.3:
                s.layout_right = 0.4         # saved squeezed (Dan: the conversations box opened at two lines)
            s.settings_version = Settings.settings_version     # migrations above run once
        except (OSError, ValueError):
            pass
        s.no_wait = s.hands_off = False   # same for NoWait / Hands off
        s.no_hang = False            # NoHang is for the moment you switch it on — never left on from last time
        return s

    def save(self):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        path = self.profile_path(self.profile)
        if self.backup_settings and os.path.exists(path):
            _backup(path)
        _write_safely(path, json.dumps(asdict(self), indent=2))
        # which profile to open next time: only when it changed, and never half-written (a power cut mid-write
        # left app.json as zero bytes)
        state = json.dumps({"profile": self.profile})
        try:
            with open(APP_STATE, "r", encoding="utf-8") as f:
                same = f.read() == state
        except OSError:
            same = False
        if not same:
            _write_safely(APP_STATE, state)

    def save_quietly(self, log=None) -> bool:
        """save(), but a failure doesn't raise: it's logged (at most once every 10 minutes) so a locked or full disk
        isn't silent any more. 0.8.225, bug hunt #28."""
        try:
            self.save()
            return True
        except Exception as ex:
            import time as _t
            now = _t.time()
            if log is not None and now - (self._save_warned_at or 0) >= 600:
                self._save_warned_at = now
                try:
                    log(f"Couldn't save your settings ({ex}) — changes since then won't survive a restart")
                except Exception:
                    pass
            return False

    _save_warned_at = 0.0       # (not a field: never saved) when save_quietly last logged a failure
    _profile_note = ""
    _first_run = False          # (0.8.201) set by load() on a fresh install: the app asks which board

    @staticmethod
    def _profile_last_running() -> str | None:
        """The profile the last run had open (control/status.json, written every 30 s), when its file is still here.
        Dan, 2026-11-13: Revolution's PC lost power and PVEREV came back on 'PVEREV' (last saved Oct 30) instead of
        'Revolution', the profile it had run on for two weeks — no blesses, no @ players."""
        sp = os.path.join(DATA_DIR, "control", "status.json")
        try:
            if os.path.exists(APP_STATE) and os.path.getmtime(sp) <= os.path.getmtime(APP_STATE):
                return None          # (app.json is newer: a character picked on purpose since — that one stands)
            with open(sp, "r", encoding="utf-8") as f:
                name = json.load(f).get("profile")
        except (OSError, ValueError, AttributeError):
            return None
        if not name or not isinstance(name, str):
            return None
        return name if os.path.exists(Settings.profile_path(name)) else None

    def describe(self) -> str:
        """'Revolution (saved 13 Nov 19:59)' — for the log at start-up."""
        import time as _t
        try:
            when = _t.strftime("%d %b %H:%M", _t.localtime(os.path.getmtime(self.profile_path(self.profile))))
            return f"{self.profile} (saved {when})"
        except OSError:
            return f"{self.profile} (not saved yet)"

    @staticmethod
    def _last_saved_profile() -> str | None:
        try:
            names = [f for f in os.listdir(PROFILES_DIR) if f.endswith(".json") and f != "Default.json"]
        except OSError:
            return None
        good = []
        for f in names:
            p = os.path.join(PROFILES_DIR, f)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    if json.load(fh).get("username"):
                        good.append((os.path.getmtime(p), f[:-5]))
            except (OSError, ValueError):
                continue
        return max(good)[1] if good else None


def _write_safely(path: str, text: str):
    """Write to a temp file, flush it to the disk, then swap it in: a power cut leaves the old file or the new one,
    never zero bytes."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _backup(path: str, keep: int = 10):
    """One backup per profile per day in data/profiles/backups (last `keep` days)."""
    import shutil
    import time as _t
    try:
        bdir = os.path.join(os.path.dirname(path), "backups")
        os.makedirs(bdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        dest = os.path.join(bdir, f"{base}-{_t.strftime('%Y-%m-%d')}.json")
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
            olds = sorted(f for f in os.listdir(bdir) if f.startswith(base + "-") and f.endswith(".json"))
            for f in olds[:-keep]:
                os.remove(os.path.join(bdir, f))
    except OSError:
        pass


def _pw_key(user: str, host: str = "") -> str:
    return f"{host.strip().lower()}|{user or 'default'}" if host and host.strip() else (user or "default")


def get_password(user: str, host: str = "") -> str | None:
    """Per BBS + user (the same user-ID on two boards can have different passwords);
    falls back to the older user-only entry."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, _pw_key(user, host)) or \
            (keyring.get_password(KEYRING_SERVICE, user or "default") if host else None)
    except Exception:
        return None


def set_password(user: str, pw: str | None, host: str = "") -> bool:
    try:
        import keyring
        if pw:
            keyring.set_password(KEYRING_SERVICE, _pw_key(user, host), pw)
        else:
            for k in {_pw_key(user, host), user or "default"}:
                try:
                    keyring.delete_password(KEYRING_SERVICE, k)
                except Exception:
                    pass
        return True
    except Exception:
        return False
