"""Import a MegaMUD character file (Chars\\<Name>\\*.ini or Chars\\<Name>.ini).

MegaMUD's INI keys aren't publicly documented, so every key is read and matched
against known/likely names. The UI shows a preview of each mapping before it is
applied; anything not recognised is kept in settings.megamud_extra so nothing is lost
and the mapping can be extended later."""
from __future__ import annotations

import os
import re

# (pattern on normalised key, setting, kind)  kind: pct|int|str|bool|spell1|spell2|list|bless
RULES = [
    (r"^mana(rest|low)%?$", "rest_below_ma", "pct"),
    (r"^mana(full|high|max)%?$", "rest_until_ma", "pct"),
    (r"^(hp|hit|hits|health)?(rest|low)%$|^rest(hp|hits|health)%?$|^(hp|hits|health)rest%?$", "rest_below_hp", "pct"),
    (r"^(hp|hit|hits|health|rest)(full|high|max)%?$", "rest_until_hp", "pct"),
    (r"^(hp|hits|health)?run%?$|^run(hp|hits|health)%?$|^flee%?$", "run_pct", "pct"),
    (r"^(hp|hits|health)?heal%$|^heal(hp|hits|health)%?$", "heal_pct", "pct"),
    (r"^heal(spell|cmd|command)$", "heal_cmd", "str"),
    (r"^(attack|atk)(spell|cmd)1?$|^spell(attack|atk)1?$|^primary(attack)?spell$", "attack_spells", "spell1"),
    (r"^(secondary|second|2nd|alt)(attack)?spell$|^(attack|atk)spell2$", "attack_spells", "spell2"),
    (r"^pre(attack)?spell$|^opener(spell)?$", "pre_attack_spell", "str"),
    (r"^(multi|area|group)(attack)?spell$", "multi_spell", "str"),
    (r"^(multi|area|group)(attack)?(min|count|mobs|monsters)$", "multi_min_mobs", "int"),
    (r"^(min|minimum)(mobs|monsters|monst)$|^attackmin$", "min_mobs", "int"),
    (r"^(max|maximum)(mobs|monsters|monst)$|^attackmax$", "max_mobs", "int"),
    (r"^(melee|attack)(cmd|command)$", "attack_cmd", "str"),
    (r"^(party|group)(bless|buff)(spell)?\d*$", "party_blesses", "pbless"),
    (r"^(self)?bless(spell)?\d*$|^buff\d*$", "buffs", "bless"),
    (r"^(char)?level$", "char_level", "int"),
    (r"^spellcasting$|^sc$", "spellcasting", "int"),
    (r"^auto(combat|attack)$", "auto_combat", "bool"),
    (r"^auto(rest)$", "auto_rest", "bool"),
    (r"^(use)?meditate$", "use_meditate", "bool"),
    (r"^pre(rest)(cmd|command|cmds)?$", "pre_rest_cmd", "str"),
    (r"^post(rest)(cmd|command|cmds)?$", "post_rest_cmd", "str"),
    (r"^pre(med|meditate)(cmd|command|cmds)?$", "pre_med_cmd", "str"),
    (r"^post(med|meditate)(cmd|command|cmds)?$", "post_med_cmd", "str"),
    (r"^(hang|hangup)(below|if)?(hp|hits|health)?%?$", "hangup_hp_pct", "pct"),
    (r"^auto(get|loot|pickup)$", "auto_loot", "bool"),
    (r"^(get|pickup)(cash|coins|money)$", "loot_cash", "bool"),
    (r"^(dont|donot|no|never)attack$|^ignore(mobs|monsters)?$", "ignore_mobs", "list"),
    (r"^(user|userid|bbsuser|login|username)$", "username", "str"),
    (r"^(host|bbs|bbshost|address|ipaddress|server)$", "host", "str"),
    (r"^(port|bbsport)$", "port", "int"),
]


def norm(key: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", key.lower())


def read_ini(path: str) -> list:
    """Return [(section, key, value)] — tolerant of MegaMUD's odd INI quirks."""
    rows, section = [], ""
    with open(path, "r", encoding="latin-1", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith((";", "#")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                rows.append((section, k.strip(), v.strip()))
    return rows


def find_char_files(path: str) -> list:
    """Accept a single .ini or a MegaMUD/Chars folder; return candidate INI files."""
    if os.path.isfile(path):
        return [path]
    out = []
    for root, _d, files in os.walk(path):
        out += [os.path.join(root, f) for f in files if f.lower().endswith(".ini")]
    return sorted(out)


def _bool(v: str):
    return v.strip().lower() in ("1", "true", "yes", "on", "y")


def _int(v: str):
    m = re.search(r"-?\d+", v)
    return int(m.group()) if m else None


def plan_import(rows: list) -> tuple[list, dict]:
    """Return (mappings, extra). mappings: [(section, key, value, setting, new_value, note)]."""
    maps, extra = [], {}
    from .macros import _ini_key
    for sec, key, val in rows:
        mk = _ini_key(key) if "macro" in sec.lower() else None
        if mk and val:
            maps.append((sec, key, val, "macros", (mk, val), "macro"))
            continue
        nk = norm(key)
        hit = None
        for pat, setting, kind in RULES:
            if re.search(pat, nk):
                hit = (setting, kind)
                break
        if not hit or val == "":
            extra[f"{sec}/{key}" if sec else key] = val
            continue
        setting, kind = hit
        note = ""
        if kind == "pct":
            nv = _int(val)
            if nv is None or not 0 <= nv <= 100:
                extra[f"{sec}/{key}" if sec else key] = val
                continue
        elif kind == "int":
            nv = _int(val)
            if nv is None:
                extra[f"{sec}/{key}" if sec else key] = val
                continue
        elif kind == "bool":
            nv = _bool(val)
        elif kind in ("spell1", "spell2"):
            nv = val.split()[0] if val.split() else val
            note = "primary attack spell" if kind == "spell1" else "secondary attack spell"
        elif kind == "list":
            nv = [x.strip() for x in re.split(r"[,;|]", val) if x.strip()]
        elif kind == "bless":
            nv = {"name": val, "cast": val.strip(), "every": 0,
                  "enabled": True, "op": ">=", "value": 0}
            note = "self bless — recast at the spell's MME duration minus the margin"
        elif kind == "pbless":
            nv = {"cast": val.strip(), "secs": 0, "enabled": True}
            note = "party bless"
        else:
            nv = val
        maps.append((sec, key, val, setting, nv, note or kind))
    return maps, extra


def apply_import(settings, maps: list, extra: dict, chosen: set | None = None):
    spells = list(settings.attack_spells or [])
    for i, (sec, key, val, setting, nv, kind) in enumerate(maps):
        if chosen is not None and i not in chosen:
            continue
        if setting == "attack_spells":
            if "secondary" in kind:
                if nv not in spells:
                    spells.append(nv)
            else:
                spells = [nv] + [s for s in spells if s != nv]
        elif setting == "macros":
            settings.macros = dict(settings.macros or {})
            settings.macros[nv[0]] = nv[1]
        elif setting == "buffs":
            if nv["cast"] and not any(b.get("cast") == nv["cast"] for b in settings.buffs):
                settings.buffs.append(nv)
        elif setting == "party_blesses":
            pbs = list(settings.party_blesses or [])
            if nv["cast"] and not any(b.get("cast") == nv["cast"] for b in pbs):
                pbs.append(nv)
            settings.party_blesses = pbs
        else:
            setattr(settings, setting, nv)
            if setting in ("pre_rest_cmd", "post_rest_cmd") and nv:
                settings.rest_swap_on = True
            elif setting in ("pre_med_cmd", "post_med_cmd") and nv:
                settings.med_swap_on = True
            elif setting == "hangup_hp_pct":
                settings.hangup_low_hp = bool(nv)
                if not nv:
                    settings.hangup_hp_pct = 25
    settings.attack_spells = spells
    settings.megamud_extra = dict(settings.megamud_extra or {}, **extra)
