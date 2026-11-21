"""Gear modes: different gear for walking, fighting, resting, meditating and PvP, swapped by itself.

Like pMUD's gear profiles. Capture what you're wearing as a mode (Settings → Loot → Gear modes):
e.g. put your mana-regen ring and robe on, sit down to meditate, Capture → Meditate. From then
on, MudPilot swaps them in when you meditate and back to your Base gear when you stand up.
A slot a mode doesn't mention keeps its Base item. Swaps are best-effort: an item you no longer
carry is skipped (and said once); a swap never holds up walking or fighting. Gear changes in a fight
cost a round in MajorMUD, so Combat gear goes on as the fight starts, not round by round.
"""
from __future__ import annotations

import time

from .gamestate import worn_list, WIELD_SLOTS

MODES = ("base", "combat", "rest", "meditate", "pvp")
LABEL = {"base": "Base (walking)", "combat": "Combat", "rest": "Rest", "meditate": "Meditate", "pvp": "PvP"}
SLOTS = {"finger": 2, "wrist": 2, "worn": 2}    # slots that hold two items
SETTLE = 1.5          # a mode has to hold this long before swapping (no flapping)


class GearModes:
    def __init__(self, session):
        self.s = session
        self.current = "base"
        self._want = None
        self._since = 0.0
        self._applied = None
        self._missing_said: set = set()
        self._sent_at = 0.0

    # ------------------------------------------------------------ which mode
    def mode_now(self) -> str:
        st, x = self.s.state, self.s.bot.x
        if getattr(x, "pvp_target", None):
            return "pvp"
        if st.in_combat:
            return "combat"
        if st.resting:
            return "meditate" if st.meditating else "rest"
        return "base"

    def sets(self) -> dict:
        return dict(self.s.settings.gear_modes or {})

    def capture(self, mode: str) -> dict:
        """What you're wearing now becomes that mode's gear."""
        worn = worn_list(self.s.state.carrying)
        gm = self.sets()
        got: dict = {}
        for item, slot in worn:
            got.setdefault(slot, []).append(item)
        gm[mode] = {slot: items[0] if len(items) == 1 else items for slot, items in got.items()}
        self.s.settings.gear_modes = gm
        self.s.settings.save()
        self.s.log(f"Gear modes: captured {LABEL.get(mode, mode)} — {len(worn)} items")
        return gm[mode]

    def clear(self, mode: str):
        gm = self.sets()
        gm.pop(mode, None)
        self.s.settings.gear_modes = gm
        self.s.settings.save()

    def wanted(self, mode: str) -> dict:
        """slot → item, or [items] for a slot that holds two (Base filled in for slots the mode doesn't set)."""
        gm = self.sets()
        out = dict(gm.get("base") or {})
        if mode != "base":
            out.update(gm.get(mode) or {})
        return out

    # ------------------------------------------------------------ swapping
    def plan(self, mode: str) -> list:
        """Commands to go from what's worn to what the mode wants. Finger, Wrist and Worn hold two: an item comes
        off only if another mode put it on (it's in another mode's set for that slot, not this one's) or a wanted
        item needs its place — never to leave a slot empty. Revolution (2026-11-06): Base kept one item per slot,
        so the second wrist/Worn item looked wrong — the sunstone wristband and the sash of the arch-mage came
        off and 'wear diamond emblem' went to an emblem already on."""
        worn: dict = {}
        for item, slot in worn_list(self.s.state.carrying):
            worn.setdefault(slot, []).append(item)
        want = self.wanted(mode)
        if not want:
            return []
        cmds = []
        carried = (self.s.state.carrying or "").lower()
        for slot, items in want.items():
            items = _items(items)
            have = list(worn.get(slot, []))
            low = [h.lower() for h in have]
            need = []
            for item in items:
                if item.lower() in low:
                    low.remove(item.lower())
                    continue
                if item.lower() not in carried:
                    if item not in self._missing_said:
                        self._missing_said.add(item)
                        self.s.log(f"Gear modes: {item} isn't in your inventory — skipped")
                    continue
                need.append(item)
            if not need:
                continue
            mine = {i.lower() for i in items}
            others = {i.lower() for m, g in self.sets().items() if m != mode for i in _items((g or {}).get(slot))}
            # spare = worn here and not wanted; mode gear (another mode's) goes first
            spare = sorted((h for h in have if h.lower() not in mine), key=lambda h: h.lower() not in others)
            room = max(SLOTS.get(slot.lower(), 1), len(have)) - len(have)
            off = [h for h in spare if h.lower() in others]
            off += spare[len(off):len(off) + max(0, len(need) - room - len(off))]
            verb = "wield" if slot.lower() in WIELD_SLOTS else "wear"
            for k, item in enumerate(need):
                if k < len(off):
                    cmds.append(f"remove {off[k]}")
                elif room <= 0:
                    break                                # nothing we may take off: leave it
                else:
                    room -= 1
                cmds.append(f"{verb} {item}")
        return cmds

    def tick(self):
        s, cfg = self.s, self.s.settings
        if not cfg.gear_modes_on or not s.telnet.connected or not s._entered or not self.sets():
            return
        now = time.time()
        mode = self.mode_now()
        if mode != self._want:
            self._want, self._since = mode, now
            return
        if mode == self._applied or now - self._since < (0.2 if mode in ("combat", "pvp") else SETTLE):
            return
        if now - self._sent_at < 3 or not s.state.carrying:
            return
        cmds = self.plan(mode)
        self._applied = mode
        if not cmds:
            return
        s.log(f"Gear modes: {LABEL.get(mode, mode)} gear — " + "; ".join(cmds))
        for c in cmds:
            s.send(c, from_bot=True)
        s.send("i", from_bot=True)                 # see what's really on now
        self._sent_at = now


def _items(v) -> list:
    """A mode's slot entry as a list: one item (str) or two ([str, str])."""
    if not v:
        return []
    return [v] if isinstance(v, str) else [x for x in v if x]
