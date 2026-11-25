# MudPilot

A MegaMUD-style client for MajorMUD with MME (MajorMUD Explorer) built in. It always knows your exact map/room number, walks MegaMUD paths and loops, fights, casts the right spell for each mob, keeps your bless spells up, rests, and loots.

**Download:** most players want the ready-to-run build: grab the latest zip from [Releases](https://github.com/MudPilot/MudPilot/releases/latest), unzip anywhere and run `MudPilot.exe`. To update, drop the new zip in your Downloads folder and restart MudPilot. On Linux, take the `-linux.zip` and run `MudPilot`. **On a Mac**, take the `-mac-arm64.zip` (Apple Silicon) or `-mac-x64.zip`, and see [MAC.md](MAC.md) for the first launch. This repository is the full source (GPL-3.0): see **Setup (Windows)** below to run it from Python.

Questions and bug reports: the MudPilot Discord, #bug-reports. Or use **Report a problem** inside MudPilot.

## Credits

Big thanks to **syntax53** for **MajorMUD Explorer (MME)** ([github.com/syntax53/MMUD-Explorer](https://github.com/syntax53/MMUD-Explorer)). MudPilot's map, room, monster, item, shop and spell data come from MME's databases, and many of its game calculations (spell and melee damage, who can use an item, which spells a class learns, the exp tables, the monster attack simulator) are worked the way MME works them. Used with his blessing.

Thanks also to **Phrixas** for **pMUD**. Several of MudPilot's features were designed after studying how pMUD does them: the Go to walker, the gather rules for info commands, @spawn boss timers, area-spell safety, Enter on Tick, NoHang, the stall watchdog, room reports, the walked routes for puzzle areas, and the debug bundle. One file comes straight from pMUD: `mudpilot/bundled/megamud_messages.md` (pMUD's MegaMUD messages import, with its decoding of the flag bits). Used with his blessing.

## License

MudPilot is free software under the **GNU General Public License v3.0**; see [LICENSE](LICENSE). You may use, change and share it, and anything you share that's built on it must be released under the GPL too. MajorMUD is a registered trademark of its owners; MudPilot is a fan-made client and isn't affiliated with them.

The full setup guide with screenshots is **MudPilot Setup Guide.pdf** in this folder (an editable Word copy is next to it). Help → Setup guide opens it.

## Setup (Windows)

1. Install Python 3.10 or newer from python.org (tick **Add python.exe to PATH**).
2. Double-click **MudPilot.bat**. The first run sets itself up (about a minute); after that it just opens.

## First run

1. **File → Import MME database (.mdb)…** and pick your MME data file (e.g. `data-v1.11p.mdb`, or the one for your board). Takes a few seconds. Re-import any time your board's data changes.
2. **Character → Import MegaMUD character (.ini)…** and pick your character file from `MegaMUD\Chars`. You'll see every setting it found and what it maps to; untick anything you don't want. Unrecognised settings are kept with the profile.
3. **File → Import MegaMUD paths folder…** and pick your MegaMUD folder (e.g. `C:\MegaMUD\Chars\All` or `Default`). Every `.mp` path and loop is copied in and matched step by step to MME map/room numbers.
4. **Connect**, enter the BBS host, port, User-ID and password. Tick **Save password** to store it in Windows Credential Manager (never in a plain file). Login prompts are answered automatically.

Want to try it without risking a character? **Connection → Start practice server** runs a local MajorMUD look-alike built from your MME data.

## More than one BBS

MME data belongs to a **board**, and each character plays on one board (the **Board** picker next to **Character**). When you import an MME file you choose which board it's for; give it a new name for a different BBS. Each board keeps its own MME data, MegaMUD paths and boss timers, and switching characters switches boards automatically. Your first setup is the board "Main".

## For MegaMUD users

| MegaMUD | MudPilot |
|---|---|
| Keypad movement, Enter to look | Same (numpad 8/2/4/6/7/9/1/3, + up, − down, 5 look) |
| Esc / Stop | Esc or **Stop bot** |
| Auto-combat / Auto-rest / Auto-get toggles | Top bar checkboxes |
| Paths & loops (`.mp`) | **Paths** tab — Walk from here, Go to start then run, Run as loop |
| Go to room | **Paths → Go to room**: type a name or `map/room`, or double-click a room on the map |
| Attack spell / secondary | **Spells**: list in priority order; auto-switches by resistance |
| Pre-attack / multi-attack spell | **Spells**: Pre-attack spell, Multi-attack spell + mob count |
| Bless spells | **Bless** tab |
| Run / heal / rest HP & mana % | **Combat** tab |

Paths you build with Go to room can be saved as normal MegaMUD `.mp` files.

## How location tracking works

Every move is followed through MME's exit map, so the room number comes from where you actually walked, not from guessing by name (MajorMUD has 900+ rooms called "Stone Tunnel"). If you get teleported, flee, or die, it re-finds you from the room name and exits, preferring rooms near where you were, and narrows it down with your next moves. If a path ever drifts, it resyncs to the matching step or routes itself back onto the path.

## Combat rules

- **Attack only if mobs ≥ / ≤**: engage only when the room has between those numbers of attackable mobs; otherwise it keeps walking. If something attacks you anyway it fights back (can be turned off).
- **Automatic spells**: after login it types `spells` and reads every spell the character knows; no spell list to set up. It casts the strongest one that works on the mob (area spells scored on every mob in the room), skipping any that would do under 75% of their rated damage, e.g. fire on a 50% rfir mob. Spells the game refuses are dropped for the session.
- **Spell switching**: for each mob it calculates every attack spell's damage using MME's own formula (magic resist, anti-magic, full-resist chance, undead-only, and rcol/rfir/rsto/rlit/rwat). Any spell doing less than 75% of its rated damage on that mob is skipped, so a 50% rfir mob won't get fireballed. It also records the real damage you deal and uses that once it has a few hits. The **Spells** tab shows the live comparison for mobs in your room.
- Ignore 0-exp mobs (shopkeepers), never-attack list, only-attack list.

## Bless spells and ability checks

Each rule in the **Bless** tab is one of:

- **Check command + ability** (e.g. `abil 145`, ability `145`, read from `spells`): reads that line of the reply (`granted:` / `worn:` / `spells:`) and recasts when it's off target. No `spells:` line means the spell isn't up.

**Mana regen (flux / ntap / nity):** use the **Mana regen ▾** button for a ready-made rule. These spells roll a random ManaRegen value each cast and a recast replaces the old roll, so the bot rerolls until the spells line reaches your target. The editor shows each spell's possible range at your level (set Character level on the Spells tab) and warns if a target can't be reached (serenity tops out around +69 at level 38). Two guardrails: it stops after *Max casts in a row* (default 8) and retries later, and it won't cast below *Don't cast below MA %* (default 25).
- **Ability name** from a general command (e.g. `Spellcasting` from `abil`).
- **Recast every N seconds**, and/or a **wear-off text** that triggers an immediate recast.

Checks never interrupt a fight unless you tick "allowed during combat".

## Remote @commands (MegaMUD compatible)

Party members and friends can control you with the same @commands MegaMUD uses, by telepath (`/You @health`), say, gangpath, or broadcast (broadcast is off by default). Replies go back MegaMUD-style in braces, e.g. `{HP=650/650,MA=394/400, Meditating}`.

Supported: `@health @exp @level @status @lives @where @path @who @inventory (@inv) @what @wealth @enc @have @version @help @do @goto @loop @stop @rego @auto-all @auto-combat @auto-nuke @auto-heal @auto-rest @auto-bless @auto-cash @auto-get @settings @reset @invite @join @wait @ok @waiting @comeback @divert @hangup @relog`. MudPilot extras: `@timer [boss]` (boss timers) and `@bless [spell target]` (e.g. `@bless ntap 150`). Not yet: `@share`, `@auto-light/sneak/hide/search` (they reply that they're unavailable).

Security works like MegaMUD's: nobody can control you unless you add them on the **Remote** tab and tick what they may do. `@do` and `@hangup` ask for confirmation before you grant them. Party members can always use `@wait/@ok/@comeback`. Anything containing "suicide" or "reroll" is ignored no matter who sends it, and a flood guard caps replies.

## Windows (like MegaMUD)

**Window** menu: **Experience chart** (exp over the session, exp/hr, time to level), **Session statistics** (exp, kills, time fighting/resting/walking, kills by monster), **Conversations** (chat in its own window) and **Inventory calculator** (best armour per slot for AC, DR, mana regen, max mana, HP, spellcasting or a resist, using the board's MME items and MME's own class/race/level/armour rules, compared with what you're wearing, with where to get each piece). **Options** jumps to each settings page; **Help → Setup guide** opens the guide.

The calculator has **Armour** and **Weapons** pages. Weapons are ranked by damage per round with MME's combat formula (swings from level/class/agility/encumbrance/strength, crits, quick-and-deadly), optionally against a chosen mob's AC, DR and dodge.

The calculator needs item data added in 0.3: re-import each board's MME file once.

**More windows (0.6):** **CP / Exp calculator** (MME's exp tables for any class/race — total exp per level, exp for the next level and hours at your current rate — plus a CP planner: what a set of stats costs and the level you need), **Spell book** (every spell you know with level, mana, single/area, element, damage at your level and damage per mana) and **Game Data** (Options → Game Data, Alt+D): Players, Monsters, Items, Spells, Rooms (search, go there, "I'm here", relearn the current room), Paths (search by name or room) and Macros.

## PvP safety

Settings → **PvP** (and the **PvP / Users / Listen** toolbar buttons):

- **Alt+H hangs up instantly** — no prompt — and stays off.
- Hang up when a player attacks you (on by default).
- Hang up when HP drops below a % (on, 25% by default).
- Hang up when a player you marked **Enemy** shows up, or optionally when **any** player shows up. Your party, Friends, Talk-tab players and the "never for these players" list are ignored.
- Stay offline for N minutes after a hang-up (0 = until you press Connect).
- **Listen:** on "You hear movement to the northeast" MudPilot looks northeast, then ignores that direction for 3 s (settable) so a chasing pile of mobs doesn't cause five looks. Looking doesn't move you, doesn't start a fight, and doesn't confuse room tracking.

## Health tab extras

- **Hang up if HP below N%** (on, 25%).
- **Pre-rest / Post-rest / Pre-med / Post-med** gear swaps, as in MegaMUD. `^M` separates commands, e.g. `eq sparkling ring^Mremove platinum ring`. The "pre" commands go out just before rest/meditate; the "post" commands go out as soon as resting ends for any reason (topped up, a mob arrives, combat), before MudPilot moves or fights. Imported from a MegaMUD .ini when present.
- **Party check every N s** — sends `par` so **Window → Party** (Alt+P) shows everyone's health and mana bars, MegaMUD-style. The box can stay on top.

## Combat spells

On the **Combat** tab: automatic spell picking, attack spell(s), pre-attack spell, area spell (blank = the best area spell you know) and **use area spells when there are at least N monsters** — below that, single-target spells only.

## Password

BBS tab → **Password**. Typed into the login prompt for you; stored in Windows Credential Manager (per BBS and user-ID), not in MudPilot's files. The 🔒 button hides it on screen.

## 0.7: MegaMUD's Spells, Party, Talk, Auto-roam and Other tabs

- **Spells tab:** minor and major heal (each with its own HP %), HP regen (cast when you rest), mana regen (cast when you meditate), a spell for when HP or mana tops out, max attack casts per fight, and cures for blindness, poison, disease and being held (Freedom), plus room light. MudPilot cures when the game says you're poisoned, blind, diseased or held; there are ignore boxes and "cures before minor heal".
- **Bless timing:** a timer bless recasts at the spell's real duration from MME minus 15 s (adjustable), e.g. blur lasts 210 s, so it's recast every 195 s. MudPilot learns each spell's start message the first time you cast it and its wear-off message the first time it wears off, so it knows when a bless is really up. You can edit both. **Re-import your MME file once** (File → Import MME database) to get spell durations.
- **Party tab:** party heals (minor/major at a %, and an area heal when N members are below a %), heal-first priority players, request healing, Party Bless 1–4 (blank seconds = duration − margin, `{name}` = bless each member), and MegaMUD's options: heal party over self, rest healing applies to party, area over major, par after combat, attack in reverse order, attack what the leader attacks, attack last, defend party when PvP, auto-share cash, help leader bash, say/ignore @panic, ignore @party / @wait, max monsters/exp in a party, leader waits for hurt members (for at most N minutes), `par` every 5 s (default), @wait / @ok.
- **PvP spells:** a list cast in order, one per round, at the player you're fighting, each recast every N rounds. Example: mystic mist every 25 rounds, then sleep every round; melee when nothing's due. MudPilot fights back when attacked if "fight back" is on and PvP hang-up is off, defends the party if that's ticked, or you can start a fight from the PvP tab.
- **Talk tab:** log conversations, greet new players, disallow all remote control or only from gangpaths, keep N conversation lines, auto-AFK after N minutes or when minimized, typing cancels AFK, AFK reply and refused-command reply.
- **Auto-roam:** wander through the exits you tick (doors opened where allowed), with optional commands for special rooms. Start it from the tab or make it the default task.
- **General:** back up settings files (one copy a day), show or hide the toolbar.
- **Path builder** (Window menu, or Paths tab → Path builder): build MegaMUD paths and loops from the map without walking them. Add rooms by number, by name or by double-clicking the map; legs are routed through MME's exits; then save as a normal .mp file.

## 0.8.227.2

- **A weakness no longer stops your walk.** Near full encumbrance, "You feel weak and powerless!" leaves you too heavy to move until it wears off. MudPilot should wait that out, but its stat check missed the weakness (the 'st' line says "weak and powerless", not "held"), so it counted every "too heavy to move" against the exit, went round it, and stopped. Now it waits, trying again every few seconds. Still too heavy after 3 minutes, it stops and says to drop something.
- **No room for a raft: the dry way, however long.** Before a Go to sets off over water (or anything else each walker has to carry, like a climbing harness), MudPilot checks there's room for it: your pack, plus the copper, silver and gold it can drop. If a party member couldn't take one in the last half hour, that counts too. Without room, it takes any dry way there is, not just one up to about double the length. Only when there's no dry way at all does it still go for the raft.

## 0.8.227.1

- **Macs: the MUD window lines up.** MudPilot asked for Consolas, a Windows font. A Mac doesn't have it, so the text came out in the system font, whose letters are different widths, and boxes and columns (character creation, `who`) went crooked. On a Mac, Consolas and the other Windows monospace fonts are now drawn in Menlo, which every Mac has. A font you've picked yourself and do have is used as it is, and your settings aren't changed. Font… and the Conversations font menu list the Mac's own monospace fonts first. Windows and Linux work as before.

## 0.8.227

- **Attack order for each monster.** Game Data → Monsters: pick a monster and press **First** or **Last** (or right-click it). Set non-hostile bosses like the storm giant king or storm commander to Last, and the little ones in the room get cleared first. A monster set First is fought before the others. The leader's target still wins when "Attack what the leader attacks" is on.
- **Resting no longer waits on a mana tick that isn't coming.** "Take one more tick when it fills you right up" timed its wait on the HP tick (every ~5 s meditating), but mana only comes back every ~15–30 s. Miserable PVE sat at 100% HP and 86% mana for 7 s and got nothing. It now waits for the stat that's short, and only when that tick is due within 10 s. Otherwise it gets up and walks.
- **Edit loop: No attack / Don't rest on one pass through a room.** A room your loop walks through more than once now has a line for each time through ("1st time through — in from E, out W", "2nd time through — in from W, out E"), each with its own No attack and Don't rest boxes. The boxes above them still set every pass at once. Pick a pass and the map shows cyan arrows for the way it comes in and goes out, so there's no guessing whether a mark is before or after a move. The map label reads `NA 2/2` when only the 2nd pass is marked, and the list on the right has a row per pass. The .mp file is unchanged, so MegaMUD still reads it.
- **The map's hover label wraps instead of running off the edge.** One fact per line (room, regen room and what spawns there, traps) on a dark box that stays inside the map. A regen room also says when it respawns: your own timing if you've camped it, else MME's delay.

## 0.8.226.2

- **Macs no longer beachball on Character → New character…** (or any other menu item that opens a box). On macOS 27 a menu pick runs inside the system menu bar's own callback, and a box opened straight from it kept that callback waiting, so macOS showed the app as frozen. On a Mac, menu picks now run just after the menu closes. Windows and Linux work as before. Thanks to the Mac player whose stack sample pinned it down.

## 0.8.226.1

- **Macs no longer freeze on the loading screen** at "Opening the gates…". On macOS the loading screen's redraw never returned once MudPilot's timers were running, and the window layout re-applied itself hundreds of thousands of times in its first 10 seconds. Windows and Linux work as before.

## 0.8.226

- **A boss you stop for is a wall for routing.** A Go to takes any way round it, however long, unless the boss's room is where you're going. Miserable PVE's Go to the Great Pyramid went through the Crazed Inquisitor's Command Room (and a pool dive, a portal and an imp teleport) because the Khazarad → Dusty Village way was 160 rooms longer than the old "about as short" rule allowed. The every-key fallback (doors to pick) now goes round bosses too. A boss you'd simply fight keeps the old rule.
- **Look-alike rooms that all lead the same way don't need 'pro'.** Every Dark Pit's 'climb out' lands in 13/211, so after a dig drops you in, MudPilot doesn't ask which pit it is (26 'pro's in 10 minutes of digging). Look-alikes with different ways out (mazes, the Great Pyramid) are still checked.
- **The MUD screen's back-scroll stops fighting you.** Scrolling up while fight text poured in could snap you straight back down. Tk reports a scroll only when it's idle, and a line arriving before that queued a jump to the bottom.
- **Clicking the yellow back-scroll bar** jumps to the bottom and puts you in the command line.
- **Up arrow brings back your last command** (Down goes forward again), as in MegaMUD. Handy for retrying a spell in a boss fight: Up, Enter. On Windows, the arrow keys were being read as the number pad, so Up walked you north. The number pad still walks, with NumLock on or off.

## 0.8.225.1

- **Treasure digging kept stopping:** a dig that drops you into the Dark Pit counted as being knocked off the path. At 2–3 laps a minute that reached 7 in 5 minutes, and the loop stopped. The climb back out after a dig no longer counts.

## 0.8.225

From the 2026-11-22 hunt: about 12,000 Go tos on 0.8.224.2, loop and party walks, and a day of the six characters' logs.



Dan's picks from the hunt (HUNT_1123)
- **The Negative Power Plane by level:** under level 50 (the party's lowest) it's avoided unless it's the only way, and then it goes instead of refusing. From level 50 it isn't avoided at all, since it's much less dangerous there. So a level-50+ Go to to Tidepool goes through NPP to Port Blackwater and takes the ship to Terra Fuego, which needs level 50 and 2,000,000 copper. (From Silvermere the only way to Blackwater that keeps out of NPP needs quest flag 204.)
- **Two characters each running their own loop stay on their own loops.** No join and no more invites back and forth. Before, a "name that sorts first leads" join was decided, then refused by another check, and they kept inviting each other.
- **Drawing a loop on the map works wherever the keyboard focus is.** Clicking on the map first let its number-pad look-ahead take the keys: the view moved, but nothing was drawn.
- **Route searches are quicker and repeatable:** equal-length ways are broken by room number, so the same Go to gives the same route every time.
- **Leading a party, the items followers carry against room spells count** (a phoenix feather or magma amulet against magma heat). Followers' party sync only listed idols and passes, so the leader counted every lava room at full damage: "up to 3,060" for Evolution, who takes none. Followers on older versions still under-report until they update.
- **An errand finds the shop behind a door you said "try anyway" to.** The item search treated that door as a wall, so an L8 was told "the crowbar drops off Giovanni, too strong" with 8 shops selling one. If you said no, it names the door.
- **MudPilot's own Go tos are worked out in the background too**, as yours already were: back to the loop, comeback trips, errand and stash walks, event walks, boss-hunt returns, shop and bank trips, scroll and training trips. These froze the window for 2-13 s (about 45% of freezes). Rego, going round a failed exit and loop rotation still plan in place.
- **Leftover code from the old rooms-that-hurt wall is gone** (no change in behaviour).
- **Loop advice is realistic.** "A loop built around here could do …" is scaled by how this loop's own estimate compares with what it really pays (rests, waits, exp split, other players), skips a candidate that is the loop you're on, and is said once, not every 10 laps (Revolution got "~4,412k/hr" 33 times).
- **"Upgrade here" is said once per item per session** (as documented), and never for an item your own rule stashes, sells or drops (Revolution's runed stone cudgel: 18 alerts, then stashed).
- **The route question's answer is remembered for 3 hours** instead of being asked again on every re-plan.
- **Back in after a party low-HP hang-up:** monsters on your ignore list don't count as "still there".
- "What you really do a round" counts rounds you missed in, so a dropper doesn't look weaker than it is.
- **Stuck somewhere the map has no way out of** (aboard the Swiftwind, 14/744), a Go to says so instead of blaming the target.
- The time breakdown counts a party-wait rest that started topped up as waiting on the party, not resting.
- An errand leg whose Go to was refused for an item doesn't give up a second time with a wrong "no way from here" reason.
- Fewer log lines: "up on the tick" (the rest summary says it) and the knockdown "held … walking on" note (once every 10 minutes). Pre/post-rest commands show "; " instead of "^M".

Resting
- **Your own heal mid-rest no longer ends the rest early.** With heal at 85%, rest below 80 and rest until 89, the heal stood Buddy up at 81% and he walked on (178 of 188 rests). Once that took him into three manticores and a hang-up. It sits back down to 'rest until' now.
- **"Up on the tick" waits until mana is over the rest line too.** It stood up at 59% mana with the line at 60 and sat straight back down, with a full gear swap each way (186 times on PVE in a day).

Safety
- **A fresh start under the hang-up line no longer hangs up at once.** A board whose prompt shows no max HP read the first prompt (131) as full, then 'st' showed 131/738 and it hung up in an empty room. It waits for 'st' (15 s at most) first.

Fighting
- **No-attack rooms: the lap's last step counts too.** The 0.8.224 fix missed it (47 of 48 remaining casts at the Camp Site).
- **The stall watchdog knows touch spells** ("You reach out and touch…").

Walking
- **A Go to that its item check refuses says so.** It used to report "walking to…" (and @goto replied that) with nothing walking.
- **The "safe way round" never needs a door the party can't open** (it set off on a 1% key farm), and the question says whose max HP it means.
- **"No way into that area" Go tos are quicker** (15-50 s to about 6 s): look-alike rooms nothing leads to from here aren't searched.
- **A MegaMUD loop still being matched isn't stopped as "not matched to MME's map".**

Smaller fixes
- The saved password isn't looked up on every command sent (about 5 ms each; it showed in UI freezes).
- "Charged items you carry" is logged only when something on it is new (it was about 1,000 lines a session).
- The Stats and Exp chart panes aren't redrawn while hidden (22 freezes on one character).
- Settings → Connection: the reconnect hint no longer promises a back-off, and the unused "Longest wait between tries" row is gone.
- If MudPilot can't save your settings (a locked or full disk), it now says so in the log, at most once every 10 minutes, instead of failing silently.
- On Linux and Mac, the password and phone-alert messages say "the system keyring" instead of "Windows Credential Manager".
- Two old settings that do nothing any more (attack_last_wait, stash_looted) are marked unused in the code.
- The MUD screen scrolls once per burst of text instead of once per line. Scrolling back works as before, and the back-scroll bar no longer flickers.
- Faster start: the room commands read from the MME data are cached next to world.db, so the map loads in about a third of the time after the first start. The cache is rebuilt whenever world.db or MudPilot changes.

## 0.8.224.4

- **Item spells that need a two-handed weapon work after the first one again** (PVEREV's divine intervention failed 217 of 221 times). After any wear/remove line the hands lost their slot names until the next 'i', so the off-hand chalice wasn't taken off first. The slots are kept now.

## 0.8.224.3

- **A follower says "@ok" after rests again after a reconnect or a death.** Since 0.8.224 a follower that had been knocked down or held, then reconnected or died, never said "@ok" again until MudPilot restarted, so the leader waited about 2 minutes every rest.
- **The party low-HP relog really is twice at most.** A clear room on the look reset the count, so a character could relog again and again, lower each time. Now only 10 minutes ends a bout.
- **An engulfed follower says "@ok" when it's freed,** and later rests' "@ok" isn't swallowed (since 0.8.224).
- **A party you re-form yourself after a disband gets comeback again:** an invite or join you type ends the 5-minute pause.
- **A pyramid timed door that never opens is gone round at most every 10 s after 40 tries too** (it re-planned 1,037 times in 3 minutes).
- **Stop works while the "short way / safe way round" question is up.**
- **The safe way round gets the same boss-room and party-item checks** as the normal way, so it can't lead into a boss room or split the party at an item exit.

## 0.8.224.2

- **Rooms that hurt never stop a Go to any more** (Dan: "being the only option, it should just go"). The 0.8.223/0.8.224 "N rooms that hurt in a row" wall is gone, with its "go anyway?" question and its "no route" messages: the only way there is walked. Revolution's Go to to the Choira Pyromancer was stopped by the Lava Tube: 52 rooms of magma heat, counted at the most each room can do (60), came to ~3,100, and the real damage is far less.
- **A safe way round is offered when there's a real one.** If the short way has a run of rooms that could do more than half your max HP (and past your hang-up line), and a way round hurts no more than a quarter as much, is at most twice as long and no more than 120 rooms longer: "Yes = the short way through them / No = the safe way round". No answer, or nobody to ask, takes the safe way round. Room damage still weighs which way is planned, as before.
- A rest you type yourself gets your pre-rest / regen gear swap too, then sits back down.
- **A quest step you just did opens the way straight away, wherever you're standing.** Evolution asked the Grey Lord 'box' (NeutralQuest 4 → 5), then a Go to to Chancellor Annora said "No walkable route … next step: talk to The Grey Lord about 'box'". MudPilot did read `abil` again and the game said 5, but the answer was only taken in from a room with no monsters and no items, and Town Square has its two signs, so it was never saved. The Go to also tried again 3 s after asking, before the answer counted. Now the answer counts wherever you are, and the Go to waits for it (10 s at most).
- Goto → Add a room… adds any room by number (e.g. 2 873 for a gear stash), not just the one you're in. Right-click any room in the list → Add to my list as…
- **Mac: Update fetches the Mac build.** Anything that wasn't Linux was treated as Windows, so a Mac would have downloaded the Windows zip. It now takes MudPilot-x.y.z-mac-arm64.zip (Apple Silicon) or -mac-x64.zip (Intel).

## 0.8.224.1

- **The heal mana lines moved** to Settings → Health → Mana, under Rest below / Rest until MA %: "Heal in a fight above MA %" and "Heal out of a fight above MA %". Each shows what the % is in mana (0 = off, heal at any mana).

## 0.8.224

Found by re-walking 0.8.223 against 0.8.222 and by going through a week of the six characters' real logs.

New setting
- **Heal only above a mana %** (Spells tab): one line for in a fight, one for out of a fight (resting, walking). In a fight you might heal down to 15%; out of one, keep 60% for moving on and blessing. Below the line no heal goes out (yours or the party's) unless someone is under 30% HP. 0 = any mana, as before.

Rooms that hurt in a row (Dan's answers)
- **A question, not a wall.** A run of rooms that hurts past your limit asks "this way does up to N damage (your limit is M) — go anyway?". Yes walks it, and the same Go to isn't asked again for 3 hours. No, no answer, or nobody to ask (an errand, a member's @goto) refuses it, as before.
- **The limit is your hang-up line, not your whole max HP.** With 500 HP and a 30% hang-up, a run may do up to 350.
- **A cheap item that stops them is offered.** If a shop sells something that stops every room in the run (swamp boots in the bog, a fur cape on the icy path), you're asked whether to fetch one first. Yes buys it on the way and walks.
- **The right reason.** When rooms that hurt are what's in the way, it no longer says "only through Negative Power Plane", reads your quest flags again, or says "MME has no way into that area". A look-alike room cut off that way is named.
- **Faster refusals.** The same refusal again in one Go to comes back at once, and no search is made that can't succeed (Misty Bog from town: 9 s to 4 s).

Routing (0.8.223 regressions)
- **Raft errands are back.** 0.8.223's "rooms that hurt in a row" check refused every Silver River Go to that 0.8.222 got a log raft for. A boat a shop sells (log raft, river punt, skiff, canoe, waterskin) now counts when the walk would fetch it first. The Lava Tube, the bogs and magma still need a yes (below).
- **A dry way is found before "no route".** A thief was refused 14/1923 to 14/9045 with a 254-room dry way there. Go to now makes one last search round every room that hurts before giving up.
- **Starting inside a key door without its key** (the Fiery Lair): Go to fetches the key. It used to plan out and stop at "the door east is locked".
- **An errand leg's party check asks the quest flags too.** The pyramid walk no longer leaves a follower at a flag gate.
- **The bank-trip check is quicker.** When no toll over your cash leads towards the target, it skips its search.

Fighting
- **The stall watchdog knows the game's spell lines.** These include "Your flaming magma blast strikes…", "…blasts your foes for N damage", "You move your hands…", "You glow…", "You summon…" and "You raise your palm…". In the logs, 9 in 10 of its "No attack of ours… attacking again" re-sends came while our spell was landing every round, and each one cost a round.
- **The area spell isn't sent again before *Combat Engaged*.** That happened 1,513 times in a week, and each one toggled combat off.
- **Leaving a No-attack room, no spell at that room's monsters.** While the move is on its way, the step you're leaving counts. There were 1,925 chai casts on the way out of the Zombie pen's run-through rooms.
- **After a kill, MudPilot waits for the room to show again before resting** (2.5 s at most). It no longer swaps on the regen gear and rests with the zombie's parts still there.
- **'no effect' is blamed on the right bless.** When two go out at once, the one that isn't your spell gets the blame (a druid's flux, not his ntap). A bless's "no effect" just after a step no longer reads as "wrong room".

Party
- **A follower still flat on its back doesn't tell the leader "@ok — ready to go".** The leader walked off on it, and the party broke (83 times).
- **"X dropped — waiting here" isn't called off straight away.** The room display from before the disconnect no longer counts as them being back.
- **"You are engulfed!"** reads as being held, not as a wall that stops the walk.
- Joining someone sends 'disband party', not the gang command 'disband'.

Dan's answers: fighting and party
- **Attack last no longer throws away your opening cast** (PVEREV: 5,781 combat toggles a week). The re-attack went out before your first cast had landed, so *Combat Off* / *Engaged* cancelled it (1,867 of 2,093 in one trace). It now waits until the cast has had time to land (1.5 s).
- **A low-HP hang-up in a party comes back in after a minute** to see whether the party cleared the room. Monsters still there means it hangs up again at once. It tries twice at most, then stays offline. After a PvP hang-up it never comes back in by itself, whatever Relog / Stay offline say.
- **Heals much smaller than the damage coming in are skipped in heavy fights.** 'mihe' healed 5-14 a round while three nightshades did 100-420, and each cast is a round with no attack. A self-heal whose last casts averaged under a quarter of a round's damage (when rounds take 10%+ of your max HP) gives way to attacking.
- **Held or engulfed with Combat off, it fights back.**
- **Being hit with Combat off, it doesn't sit down.** Walking, it walks on; standing, it stays up.
- **A disband you meant: no automatic regrouping for 5 minutes,** no invites and no joins (it was 60 s, invites only). Someone who takes an invite from before the disband is disbanded again. Invites and joins you type still go.
- "The 'par' timer event fired" and "X not allowed @comeback" are logged once, then every 30 / 10 minutes (12,432 lines in one log).

Dan's answers: resting and walking
- **A short rest while waiting on the party doesn't swap gear.**
- **A self-mend mid-rest no longer swaps the regen ring off and back on** (11 swaps in one 60 s rest).
- **A room that keeps breaking rests up** (three times in 2 minutes) means resting a few rooms on, as in a lair.
- **A MegaMUD loop that isn't matched to MME's map stops at once when you're off it,** saying why, instead of pressing Enter for 60 s.
- **Wrong learned ways stay forgotten across sessions** (forgotten_exits.json next to learned_exits.json). 10/179 NE was re-learned and failed every start.
- **A pyramid timed door that won't open is gone round at most every 10 s** (it re-planned every tick, ~12 log lines a second).
- **"Too strong for you" for a key's dropper uses what you really do a round,** not 60 for anyone without an attack spell (the fire knight read the same for an L30 thief and an L60 warrior).

Smaller fixes
- The low-HP hang-up re-arms 3% over the line, so your own ring swap no longer hangs you up.
- A text exit with several wordings ('ask Lord code', 'ask Lord codeword'…): when one fails, all of them are gone round.
- "Reset session stats" mid-lap no longer saves a 0-exp lap into the loop stats.

## 0.8.223

Dan's answers to the 2026-11-21 bug hunt's "for Dan" list (everything but the start-room rule for rooms that hurt):

Routing
- **Go to counts rooms that hurt.** A bog, magma or a river without a raft now costs a route according to how much of your HP it would take. An L30 thief (390 HP) was walked 181 steps through 20+ Quagmire rooms (1,840 damage) when a 219-step dry way existed. Now it takes the dry way. A strong character still takes the short way through rooms that only scratch it.
- **A run of rooms that hurt for your whole max HP, with nowhere to rest between, isn't walked.** Go to finds a way round. If there isn't one, it stops and says so ("30 rooms that hurt in a row (7/996 to 15/1137) can do up to 1800 damage — your whole max HP (533) or more"). A paladin hung up in the middle of the Lava Tube this way.
- **The "no way back out" check counts only keys you can really get.** A key counts if you hold it, if the walk in fetches it, or if it can be had where you'd be. A thief who picked the jail cell's 101 door in couldn't pick the 151 door out (the jail key drops outside), and is now told before going in.
- **The inside of a key door is the same door.** MME types the inside of the Fiery Lair's, Molten River's and Mage Tower's key doors as plain locked doors ('[71 picklocks/strength]'). With the key, Go to walks in and back out through them, and uses the key on the way out.
- **The way back out needs a rope? It's bought first.** Dark-Elf City by the Large Hole, the Webbed Cave. It isn't refused, and you aren't sent in without one.
- **A key door your picklocks or strength open is used when it saves 30+ rooms.** Through Silvermere's sewer door 1/1098 W it's 10 rooms, not 106 round.
- **Planning is quicker.** On Go tos that find no route, 0.8.222 was 25-40% slower than 0.8.221. It's now within about a fifth of it, counting the new room-damage costs. The bank-trip check does one quick search first, the max-HP and room-damage answers are worked out once per search, and a way blocked only by rooms that hurt skips the look-alike-room and alignment searches.

Party
- **Errands ask the party too.** When a Go to first sends you on an errand (a key, a drop, your own raft), the walk there now asks the party `@have` for the rafts, waterskins, rope or idol it needs, and buys theirs first. It used to walk raftless followers down the Silver River on the leader's raft run. The golden idol is asked about before any errand.
- **A door only a follower can open: they're asked, and given time.** When a member's picklocks or strength will do and yours won't, MudPilot asks them (`@do pick south` / `@do bash south`, again every 20 s) and tries the door while they work. It waits a minute before going round or fetching the key, and up to 3 minutes when it's the only way. It used to give up within a second. A key that turns up at its door gets used.
- **Refusals say who.** "Buddy's whole max HP (90)" when it's a follower's. Class and alignment gates say who can't pass: "Druids only — Revolution (Mage) can't go through".

Fighting and resting
- **Ran from the same monster twice in a few minutes? It's too strong for 30 minutes.** MudPilot goes round that room and leaves that monster alone unless it attacks. It no longer runs, rests and walks straight back. A Go to you start yourself tries again.
- **After moving away from a fight, MudPilot no longer thinks it's still fighting** (it ran over and over with nothing hitting it).
- **Guards and item droppers get the "can I win this?" check.** One that would all but kill you isn't fought (an L10 sent after Sheriff Lionheart for the jail key), and the log says why.
- **Stop no longer blocks resting on your next trip.** A level 50+ caster out of mana with a monster in the room backs off a room and rests.

Errands, doors and keys
- **The warehouse door in Slum Street (1/1104 north) opens.** MudPilot sends 'use crowbar' and tries a few times (a strength test). Without a crowbar, Go to buys one first. Behind it are 18 rooms, including the Warehouse Loft boss lair (2/26).
- **A key only an NPC has: Go to says who.** For example, "the sleazy shopkeeper (8/486) has the moldy key — MudPilot won't kill an NPC for it".
- **Errands fetch things in the order the walk needs them.** The log raft now comes before the fang farm's Silver River crossing, and the errand still runs to the end. There's no waterskin run through the Go to's own target (112 rooms for a 26-room Go to).
- **"Can't fetch <key>" names the trap when that's the real block.**

Smaller fixes
- A pyramid door that never opens is no longer "gone round" forever (a few minutes of retries for the timed doors, then it stops and names the door).
- 'dig grave' digs on in the same grave (up to 40 tries), and notices a broken shovel.
- A loop started one room beside it in open country walks back onto it instead of shifting onto a look-alike row. Knocked off a loop, it rejoins where it was when that's only a little further, so a spur isn't skipped.
- Go to checks 'pro' before "Arrived" in a dark room that looks like others.
- Loop key steps written `use chiseled key(1264) SW` work.
- A Go to that reads 'st' first waits for the answer (up to 10 s).
- @status shows a toll you can't cover, not an old door reason.
- The low-picklocks "only through Black Wasteland" for Dark-Elf City wasn't a bug: every other way needs a door that character can't open. It now names the real block.

## 0.8.222

(includes the 0.8.221.1-0.8.221.3 hotfixes: the item-spell crash fix; a parked character no longer walks off to a leader it stopped following hours ago (Evolution walked 481 steps to the zombie pen); commands use the monster's / item's full name — 'smash large stitched zombie', 'use large iron key')

**MudPilot is open source now**, under the GNU General Public License v3.0 (`LICENSE`, in the zip too), with the blessing of Phrixas and syntax53. The source is at github.com/MudPilot/MudPilot. pMUD is credited next to MME in the README, the About box and the help book's Credits.

Dan's picks from the 2026-11-20 bug hunt's "for Dan" list:
- **Go to won't walk into a dead end.** Before it sets off, it checks that there's a way back out of where it's going that this character can use. A door nobody in the party can pick or bash counts as a wall when nobody's there to ask about trying it, and a '1000' door always does. If there's no way out it doesn't go, and says which doors are in the way (Stone Barracks 14/6217 and 14/6229, Manor Stables, Ruined Manor). It only refuses when doors (or a trap bigger than your max HP) are what shut you in: a spell-trap way out, random drops, sea rooms or a room MME shows no way out of (Ozrinom's Grand Chamber, the Tomb of the Pharaoh) walk as before, and so does a Go to inside a pocket you're already in. When the plain way has a '1000' door and a key or your picklocks open another, it takes that one (the Dark-Elf Castle by the moat) — re-plans on the way included.
- **A '1000' door as the only way stops before setting off.** It was tried over and over (a level-30 warrior at 15/731 NE on the way to the Throne Room). The pyramid's timed doors and Morukai's lair door, which do open, are left as they were.
- **A trap or room that can do your whole max HP (the weakest member's, leading) is never planned.** Go to goes another way, or says which trap or room is in the way (an L12 with 156 HP walked onto 8/1835's 200-damage trap from full and hung up at 1 HP).
- **No resting to full before rooms that hurt when full HP wouldn't see you through them either.** It used to rest about 2 minutes first anyway. When full HP would see you through, it still rests first (60 of 130 HP before a 100-damage trap), and a run of traps with safe rooms between them counts one trap at a time (the Ebon Blade corridor's 33 traps read as one 9,975-damage stretch, so it never rested).
- **'st' before a Go to that depends on a locked door.** When a door on the way, or on the way back out, comes down to picklocks / strength and those aren't read yet, it reads 'st' first. That takes a few seconds, instead of walking 135 rooms to find it can't open the door.
- **A toll or fare your cash won't cover: the bank first.** With the money in the bank, any toll or fare was a wall (even 5 copper). Now Go to plans the way with the toll or fare, goes to the nearest bank for what's missing, then on, the way bank runs for items work. An empty account still ends in "no route" with the reason. (Your Settings switch for toll bank runs still decides.)
- **A way in that needs a particular monster there says so.** It used to go to a look-alike room and say "Arrived". Now it says "needs <monster> there" and doesn't try the exit (14/1290 'go courtyard' into the Castle Courtyard).
- **A scattered member: the walk waits for their @where answer**, for 30 seconds at most, instead of walking on further away from them.
- **A member who sent @stop but never logged off** no longer holds everyone's @rego for 15 minutes before it's quietly dropped. Still in the party and following about 2 minutes after the @stop, they count as back, and the @rego goes ahead (logged). An @rego held the full 15 minutes is dropped with a log line.

From the 2026-11-21 simulated walks (12 agents on the practice server: maps 1-4, 9-18, the rest of map 14, 227 more loops, party routing with `e2e_realm_walk.py --party`, and a 0.8.221 / 0.8.222 comparison; `bug_hunt\HUNT_1121.md`):
- **Route planning is fast again.** The max-HP check made every plan with keys / items 4-7 times slower (one Go to took 40-100 s, long enough for "paused — reconnecting"). The spell-damage lookup now keys on just the items that matter to that spell.
- **Standing in rooms that hurt that much, Go to still walks you out** (an L8 in the White Forest got "No walkable route"). The max-HP check goes by what you really carry, not every item the key planner assumes (it read the magma as harmless thanks to a phoenix feather you didn't have), and by your real max HP from 'st', not the best prompt seen after a hurt login.
- **"No way in on MME's map" isn't said for a room behind a door you said no to, a trap bigger than your HP, or a quest arch** — those end in the normal "no route" with the real reason, instead of a walk to a look-alike room that "Arrived".
- **Loops:** a step that goes through a wall gives up after 3 tries (it asked 'pro' forever at 8/654); a loop run inside the Negative Power Plane, Black Wasteland or the Webbed Mine can find its way back onto its path; bumping a door the room didn't show as closed goes back to that step instead of skipping the room behind it (44 dead-end rooms in 11 loops); a loop's last move that didn't land is tried again, not counted as a lap each time; MegaMUD's `sea n` is a search (it was sent raw, and one miss stopped the loop); a text command two exits share ('go alley' at 2/2519) no longer loses the bot's place in the dark.
- **`@loop last` and @rego's fallback walk to the loop first** when you're not on it, as `@loop <name>` and the Paths tab do.
- **The lever tour no longer loops forever** behind a door nobody in the party can open (3,958 rooms in 15 minutes at the Temple Control Room); at most 8 times per leg.
- **Fetching an item never plans its way through exits that need that same item** (rope runs down Storm Mountain's rope exits; the red rock key behind its own key door; the chiseled key's own door at 16/1994).
- **'st' comes after the '1000'-door check** (no stats open those) and isn't sent when stats couldn't change the answer.
- **Quest flags on room commands get an 'abil N'** before giving up (the Tal'kiran passage, flag 211).
- **"The only way is through <area>" names the area the way really needs** (Webbed Hollow: the Webbed Mine, not Black Wasteland), and a Yes walks through that one only.
- **Leading a party, class / race room commands check every member** (a Bard led a Warrior up 'ask barmaid adventure').
- **A path's own `use <key> <dir>` is sent twice at most** when the door doesn't unlock ("You don't have …", a key that crumbled on an earlier lap); then the normal locked-door handling takes over. It was sent every 2.5 s forever.
- **Running away doesn't go straight back into the room you just ran out of**, nor, a few runs on, into the room the first run left (12 runs between two rooms, then a hang-up). Running from a fight at the Go to's destination isn't taken as the destination throwing you out.
- **A Go to a room nothing on the map leads into decides quickly** (it searched the whole realm twice: 40-150 s).
- **The warehouse door (1/1104 N) stop says how the game opens it** ('use crowbar' in that room — MudPilot doesn't do that yet; open it by hand, then Go to again). A rope or harness you don't carry isn't counted as the way back out of a pocket (the Stone Tunnel / Webbed Cave 1/1542, Storm Mountain 16/836).
- A step that was on its way when you pressed Stop no longer "places" you in a look-alike room on the next walk.
- **"Your path is blocked." isn't read as a locked door** any more: it bashed the last door's direction (from another room, even another loop) for ever. The step's retry limit only waits for a door in that step's own direction.
- **A walk waits for 'pro''s answer before its next move.** The answer cleared the move queue, so a move sent in between was lost — in the dark the bot thought it hadn't moved, walled a real exit and stopped (Storm Mountain, 16/1020).
- A stray control byte in a MegaMUD path step (`N` plus 0x05) is dropped instead of sent.
- **Max HP not read yet and a trap or room on the way could be all of it: 'st' first**, so the max-HP check works from the first Go to (an L8 walked into the White Forest's magma while it waited for some other 'st').
- **The bank run for a toll or fare makes the same checks first** (it withdrew 2,000,000 for the Blackwater fare, then the Go to was refused anyway), and an "only through <area>" left from planning the bank trip isn't given for another Go to.
- **The pyramid arches' "does it throw you" answer follows your quest flags** (an old answer, from before 'abil' was read, planned through the level-4 arches at DaoLord 8).
- A Go to whose last step lands somewhere else says so ("the step into 2/2530 took you to 2/2540") instead of "2/2530 sends you back out"; @status doesn't answer with an old plan's reason while walking.
- **Leading a party, the max-HP check counts only what every member carries** (a 50-HP follower was walked through 23 rooms of magma on the leader's phoenix feather), and a room command that needs an item ('climb hole' with a rope) needs one for each member, not just you (a follower was left in the 7/1524 pit).
- **Leading a party, a 'Level 0 to 5'-style gate has to let your highest member through too** (an L55 leader with an L3 follower walked to the Silver River's 'Level 0 to 3' gate), and a key only the party could have is asked about first, not after an 840-room errand for the other items.
- **A random drop into look-alike rooms (the Padded Cells) is checked with 'pro'** before "Arrived" — it said Arrived in whichever cell it landed in.
- **A door your picklocks cover that's the only way keeps being picked**, as an only-way door keeps being bashed (an L60 thief was left inside the Stone Barracks after 3 missed picks).
- **In the dark, a "no exit" isn't taken as a wall until 'pro' has said where you are** (a real exit was walled off for 2 hours and the way round, walked from the wrong room, walled more). The 'st' check before a Go to also looks at traps on the way back out (an L30 warrior was stranded in the Large Cave behind 600-damage traps).
- "No route" names a trap or room that can do your whole max HP first (8/1835's 200-damage trap was cut off behind three key doors), and a refused dead end names a room command that needs an item you don't carry (Pit Bottom 7/1524's 'climb hole' and its rope).
- Tests: `test_hunt1121_walks.py`; `e2e_realm_walk.py --party` now runs a pretend party on the practice server.

## 0.8.221

From a simulated bug hunt on the practice server (live loop walks, the first live walk of map 14, maps 5-8, party play, and Go to with combat, dark rooms, quest flags, a banked character and the Stock board):
- **Loops keep their place where MegaMUD's path has a step MME's map hasn't.** The way learned from the path was saved as an exit the game lists, so the room stopped matching itself and the loop lost its place (Sandy Beach SE at 13/530, Frozen Cavern, Ancient Stronghold, Abandoned Inn). Learned ways now count as exits the game may not show; ones already saved are read the same way.
- **'Resting to full first' doesn't stand there when resting isn't allowed.** Before a stretch of rooms that hurt or a dangerous lair, it held the step to rest, while the 2 minutes after a Stop, a message rule's 'keep going' or the pyramid timer said no resting, so it stood still until that ran out (Black Dragons loop, 6/415).
- **A held @rego goes ahead with 'Party comeback' off.** It waited for the members away for a restart to rejoin, but with that switch off nothing ever let it go.
- **@flags from a character that has never read its quest flags** says "not read yet" instead of "not set", which the leader took as a sure "doesn't have it" and refused the Go to or went the long way round.
- **Rooms past a spell trap count in "how far".** Go to already takes a spell trap when there's no other way; the distance lists (errand sources, spell scrolls, training) didn't, so the Darkened Tunnels Throne Room and ~250 more rooms read as unreachable.
- **A Rooms.md entry stays on its number when the monster it names lives there.** 'Thief Spirit (11)-1 2275' and 'Warrior Spirit (11)-1 2231' were moved one digit off by the 0.8.218 fix-up, to rooms with no way to the spirits' tombs.
- **A toll you can't pay is the reason, not "no way in".** Go to the 14/1792 Training Hall with too little for the 80,000 toll went to the 14/1791 Training Hall it stood in and said it had arrived. Deciding whether a room has a way in at all now goes by the map, not your cash, level, class or quest flags; the real reason (the toll) is shown.
- **Items you picked up count only until the next inventory.** They were counted as carried for good, so a key that crumbled or an item stashed or sold was never fetched again.
- **No 45-minute 'farm' for a part nothing drops.** A house key's parchment deed (sold only in a no-restock shop, which MudPilot doesn't buy from) was 'farmed' standing in the key room; it now stops with the reason.
- **A door's no-route reason** says "you said no to trying, or nobody was there to ask" (it claimed you'd said no when nobody was asked).

## 0.8.220

- **Keys whose short name matches something else you carry are used by their whole name.** At Thrag's door Revolution had the large iron key and the iron keyring, so 'use iron key east' got "Please be more specific" and the bot went on to bash. Now it sends 'use large iron key east'. Before, only another key ending in the same words counted as a clash.

## 0.8.220

- **A loop always starts with Combat on.** You can still run to the loop with combat off; when the loop starts, Combat comes back on even if 'When a loop starts or a Go to arrives, turn … back on' (Settings → Other) is unticked. When you lead a party, MudPilot also says '@auto-combat on' so followers you switched off with '.@auto-combat off' fight too.

## 0.8.219

- **'.@auto-combat off' / '@auto-combat on' typed yourself switches your own character too.** It was said to the party and their MudPilots acted on it, but your own never did (what you say comes back as 'You say', not a remote command). Same for the other @auto- switches, @auto-all and @attack-last.

## 0.8.218

- **Quest gates have to let the whole party through.** Before leading the party by a quest-flag gate, MudPilot asks everyone `@flags`; a member who has never had the flag answers `{ability 127 = not set …}`, and that form wasn't read, so after 12 s the party went anyway. Now both forms are read, the answers count for routing (30 min), and when someone's flag differs the Go to is worked out again by a way everyone gets through. Evolution (NeutralQuest 13) took Revolution, Miserable and Buddy (none) to Jorah to 'ask Jorah transport' on the way to the Pier.
- **Goto goes to the right room for Rooms.md entries with a wrong, squeezed or missing number.** 'Choira Pyromancer-15 1168' is the Temple of Fire inside the Crimson Fortress (behind the ancient obsidian key), so Goto detoured for the key; the hash is 15/1165, the Lava Pool where Choira stands. 'Stone Giant Chieftain-1601095' (no space) went to 2/10 Top of Mountain Stair near Annora, which shares the hash with 16/1095, the Chieftain's Tent (Revolution, 2026-11-20). An audit of the shared Rooms.md (Dan, 2026-11-21) found ~45 more: map typos ('Outside Master Assassin-8 1262' is 7/1262), one digit off ('Crystal Lake, Southern Dock-17 569' is 17/1569), names that nearly match the hash room, two spaces or a dash in the number, and unnumbered entries sent to the wrong area ('Blue Tower, Weapons (sharp)' went to a forest trail). When the hash and the room's name don't back the number: a hash room the named monster lives in, then a map or one-digit typo, then the hash room whose name fits best. Ties go to the map the entry's area mostly uses, then the room nearest the number, and an entry never moves onto a room another entry names by number.

## 0.8.217

- **No-attack rooms are for running through, not for being pinned.** Knocked down, held or stunned, it fights back at once (hit yet or not); being hit with the path's move 2 s gone and still here, or 4 s in the room, the same. Miserable PVE was knocked down in the zombie pen's no-attack room and went 920 → 88 HP in 33 s without a swing or a spell, then died a room later. (Run-through rooms work the same way.)
- **Don't-rest rooms rest as long as the room's refill allows.** From the lair clock's refill time (or the soonest it's been seen stocked), counted from when the room was cleared, less 12 s: a 90 s room rests ~75 s and moves on; an 8 s room, or one not learned yet, still moves straight on.

## 0.8.216

- **The combat calculator counts bash and smash.** Melee shows normal, bash and smash a round for the weapon, with the best marked, from MME's attack formula (stock rules): bash is double energy a swing, x1.1 then x3, no crits, -15 accuracy; smash is one swing a round, x1.2 then x5, no crits, -25 accuracy. A monster's DR comes off before the multiplier. Best spots uses the attack your attack command sends (bash / smash / sm).

## 0.8.215

- **Go to's own lever tours never go through their gate either**, and the Darkened Tunnels' 15/477 N is a timed gate (run from the first lever, no fighting). Buddy stopped at 15/335: "the N exit of 15/477 is opened from 15/604, and there's no way there from here". Walked on the practice server: both levers, then the Throne Room.

## 0.8.214

- **Timed gates are redone as often as it takes.** A lever gate that shut before we got there is gone back round up to 8 times (Go to: was 2; loops: was 3), with no human needed — the Darkened Tunnels gates often need a second or third go.

## 0.8.213

- **One-way '1000' gates are a last resort.** A '1000 picklocks/strength' door nothing we know opens now costs the router 2000 steps (was 60), and when the only other way is through spell traps, Go to takes the spell traps (disarming them) instead. The Darkened Tunnels Throne Room (15/416): Buddy sat at 15/401 NE and 15/546 NW, which never open from that side; now it walks to the levers at 15/604 and 15/730 and rushes back to 15/477 N, like the FMASDRKT path.
- **Lever tours never go through their own gate** to reach a lever (15/477 N's tour came out empty).
- **A '1000' door is tried 6 times (~12 s), not 40,** before going round it when there's a way round.
- **Loop / Goto picker: type a letter to jump.** Click in the list and press R to jump to the first folder starting with R, R again for the next one, or type 'rug' quickly to narrow it down.

## 0.8.212

- **The leader stays the leader when a party breaks.** A follower that isn't running a loop of its own no longer auto-invites (Game Data *invite if seen*, comeback, regroup) the member it followed in the last half hour: it joins them. And a leader walking its loop that has just invited a member back no longer leaves to join that member on their `@join`. (The PvP party broke at 23:39, Miserable invited Revolution, Revolution joined Miserable, and both stood there until morning.)

## 0.8.211

- **Run through rooms** (loop editor): tick *Run through (time the round)* on a room. The walker waits next door until a combat round has just gone off, then crosses the room (and any run-through rooms right after it) before the next round lands: no fighting, no resting in it. It needs the round clock (any fight in the last half hour); without it, it just walks straight through.

## 0.8.210

- **Edit loop on the map:** Paths → Edit loop now opens the loop on a map, MME style. Walk round it with the arrow keys / number pad or Prev / Next room, or click a room, then tick **No attack here**, **Don't rest here** or **Stash room here**. The loop's rooms are blue and their marks show as NA / DR / $; the list beside it is the same rooms in loop order. No attack means no fighting there even when hit, so mobs pile up behind you for an area spell in the next room.

## 0.8.209

- **Party items:** "asked the party twice … someone still has none" only counts rounds that came back short. A round where everyone said yes, or one you stopped before the answers came in, no longer counts, so a Go to after a Stop asks again instead of refusing.

## 0.8.208

- **Monster attitude: Enemy / Neutral / Friend** (Game Data → Monsters: right-click, or the Attitude buttons, as on MegaMUD; new Attitude column). Enemy attacks a monster MME calls non-hostile, like the amazon shamans for nature tap. Neutral and Friend leave it alone unless it attacks. Remotely: `@enemy amazon shaman`, `@neutral …`, `@friend …`, `@enemy off <name>` for default (needs the settings permission).
- **Help → My quests.** Opens the Quest guide (also under Window), which now has a **Next step** column, so every quest's next step shows at once. For example, GoodQuest 16: "talk to Chancellor Annora about 'success' — Large Office". The dark phoenix is the step after (17 → 18). Click a quest for every step, and click a room to walk there.
- **Route preview** (Goto → pick a room → **Preview route…**). Lists the places the Go to passes, with a run of rooms of one name shown once and tolls, keys, items, doors and teleports noted. Pick a place you'd rather not go through and **Avoid** it (or double-click). It finds another way, and you can keep striking places off: Seher, then the Negative Power Plane, then round by Arlysia and the lake. **Go this way** walks it. The struck-off rooms count for that Go to only, including its re-plans on the way.
- **Party heals every round again between fights.** Each heal on a member waits for a fresh `par`, which should go out 2 s after the heal. While walking out of combat, the 60 s "don't slow the moves" backstop held it back: Revolution healed Miserable once every 15 s, and 40% of heals waited over 10 s for the next `par`. For 20 s after a party heal, a member knocked down, or a member hit hard, `par` runs at the normal 5 s pace.
- **Freedom waits until the party is ready to move.** A knocked-down member was freed at once because the last `par` was from before the hit (Miserable read 97%), and the healer was under the mana rest line and about to sit anyway. Freedom now also waits for a `par` taken after the @held report (10 s at most), and while you are under "Rest below MA". Most knockdowns wear off on their own while the party heals.
- **Invites after a disband work when a member asks.** `@invite` and `@do invite …` from a member always go out. Before, Revolution's own blocked auto-invite filled the 8 s repeat filter, so Miserable's `@invite` was dropped without a word, and `@do invite` hit the 60 s disband pause.
- **A join refused with "You must be invited first!" no longer counts as joined.** The invite that arrives a second later joins. Before, Buddy's early `join` made the invite and the `@join` look like repeats.
- **Followers stash too.** Following through one of your loops' stash rooms stashes there, once a visit as before. Miserable's Stonecaps stash only applied while he led.
- **`@stash here`** sets a character's real stash room remotely, coins included. It goes to the loop it is walking (Paths tab), or to its default stash room (Loot tab) when it isn't looping. Needs the settings permission. Plain `@stash` is unchanged: a room for Auto-stash items only.
- **Spell traps get disarmed.** Exits MME marks "(Spell Trap: …)", like the Vine Bridge east of 16/1206 that drops you into the mists, now get `disarm trap <dir>` first, as plain traps do (with "Disarm traps" on, or the party's best disarmer). Before, only "(Trap" exits were disarmed.
- **The party quest-flag check no longer reads like a refusal.** It now says "a step on the way goes by quest flag (NeutralQuest) — asking Revolution theirs first (a few seconds), then walking".
- **No waiting on mana a member doesn't need.** Each MudPilot tells the leader its own "Rest below MA" line. A member with it at 0, like Buddy, a melee Paladin whose mana is a bonus, isn't waited on for mana. HP waits still apply, and its own MudPilot still rests mana if it wants to.
- **No rest-gear flapping while you wait.** Waiting for the party already over your "rest until" line, MudPilot rested in its regen gear, called it rested at once, swapped back, and did it again 6 s later (Miserable PVE swapped 4 items each way, over and over). It now rests in what's on when you're already rested.
- **Goto: a wrong room number in Rooms.md no longer sends you the wrong way.** MegaMUD's list has "Ship Captains Quarters-16 1617", but its checksum is 16/1517. 16/1617 is in the Undermountain Caverns, behind a raft, rope and grapple, and a golden idol for everyone. When the number in a name doesn't fit the checksum and the checksum fits a room with that exact name, the checksum wins.

## 0.8.207

- **The stash room hides once a visit.** Following a leader, standing in the stash room hid whatever you carried every few seconds — Miserable searched it, picked up the 10,800 gold to use his coin bag on it, and it was hidden again behind him. Now it stashes at most once each time you come into the room, and not at all while you've typed something in the last minute. Worst case a lap goes by before the next stash.

- **Smart resting (switch, off by default — Health tab → Smarter resting).** Picks the quickest way back to 'rest until': rest, meditate + your Heal command, HP regen spell (rgen) + meditate, or a few heals then rgen + meditate. It works it out from this character's own numbers: rest / meditate HP and mana per second, learned from finished rests, and the heal's real size from "healing N damage". On Revolution's logs: meditating gives ~3.8 mana/s and greater mend turns 9 mana into ~35 HP, so from 40% HP meditate + heals gets back in about half the time of resting; from 78% HP with low mana, one rgen then meditate is quickest. Each cast stands you up, so heals mid-rest go right after a regen tick. Under the safety line (50% HP by default) the heal goes straight out whatever the plan, and out of a fight a self-heal over that line only goes out when it's the quicker way back. Until it has learned enough it changes nothing.

- **Rest below MA % means what it says.** The mana throttle (Health tab → Smarter resting) also let a character walk on below the mana rest line, down to half of it, on cheap spells — Revolution, set to rest at 70%, walked on at 44%. It now only switches to cheaper spells as mana nears the line (renamed "Stretch mana"); at the line it stops to rest/meditate.

- **Single-target the moment someone walks in (PvP realm).** Anyone outside the party walking in — including a party member logging back in where they hung up ("walks into the room from nowhere"), who isn't in the party yet — stops area spells at once, before the room list catches up, and if the game is repeating your area spell MudPilot breaks off straight away. Miserable logged back in 8 minutes after hanging up, straight into Revolution's repeating tempest.

- **Keep mana regen up… picks your class's spell.** The Health tab button made a mage's flux rule for everyone; a druid gets nature tap (ntap) and a priest serenity (nity) now.

- **A spell rule the game won't take is left alone.** Three "Your command had no effect." in a row for a bless / regen rule (Revolution's druid sending flux) and MudPilot skips it for 10 minutes and says why, instead of sending it again and again.

## 0.8.206

- **Says when Combat is off.** With the Combat button off and monsters in the room, the status line says "Combat is off — not attacking N mob(s)" (and the log says so every 10 minutes), and @status starts with "Combat OFF - not attacking" instead of just "idle". Buddy followed his party for three hours with it off and nothing showed it.

- **Edit loop: No attack / Don't rest rooms.** Paths tab → right-click a loop (or More) → Edit loop… lists each room on the loop with tick boxes. No attack walks through without starting a fight; Don't rest never stops to rest there. They're MegaMUD's own step marks, so only those step lines change in the .mp file and MegaMUD still reads it. A room the loop passes twice is one row. Find my room jumps to where you're standing.

- **"Stay offline (minutes)" goes back in.** After a hang-up with Settings → Safety → Stay offline set, MudPilot reconnected after the wait but then sat at the MajorMUD menu ("not entering by itself because you hung up last time"), so the setting did nothing. It now goes back into the realm. With it at 0 (the default) a hang-up still waits for you, as before.

## 0.8.205

- **A follower says who it's following.** Back in its leader's party after a restart, it still showed "Stopped (before the restart) — Rego carries on…" until something else changed the status, which looked like a stuck character. It now shows "Following Evolution" (or whoever).
- **No river detour round a boss.** Stonecaps → Rodolfo's Salvage Yard is dry over the Dale Road, but going round Shadow Lord's spawn room took the River Lorian instead, so MudPilot went off for a wooden skiff (202 rooms, down the river itself) and later swapped a dry way back for the river. Going round a boss never trades a dry way for water you'd need a raft for now (a party is planned as carrying none); when water is the only way round, it keeps the dry road and the usual stop-before-a-boss rules apply. The dry way also holds through the later route checks, and counts as worth it up to the length of the trip by way of the raft shop.
- **Your own stashed raft before a shop.** A Go to that needs a boat picks up the raft stashed at the loop instead of buying another kind (Miserable's log raft sat at the Stonecaps while MudPilot went for a wooden skiff). Party members short of one still get one bought.
- **No paying a toll to regroup.** Going back for a party member (their `@comeback`, or finding them after the party breaks) whose room is past a toll now stops outside the toll and sends them `@summon` to come out. Revolution walked into Rodolfo's Training Hall four times at 80,000 copper a go while Miserable trained. If they haven't come out after 2 minutes, it waits there rather than paying.

## 0.8.204

- **The party stays together through an update.** A follower whose leader logged off a moment before its own restart (the PVE party: Evolution leads in the game and closed first) came back thinking it led, invited everyone, and the party re-formed under it without its loop, leaving Revolution behind. It now rejoins the leader it was following, a leader regrouping after a restart invites people back instead of joining them, and the rollout closes followers one at a time, the in-game leader last.
- **Fewer location checks after a knockdown.** The game's 'no effect' can arrive a moment after the knockdown wears off — that's covered too now (it was still asking `pro` now and then in Stonecaps).

## 0.8.203

- **No location check after a knockdown.** Knocked off your feet, the game answers the path's next step with 'Your command had no effect.' — MudPilot took that as being in the wrong room and asked `pro` every few minutes in Stonecaps, always finding the room it already thought. Knocked down or held, it now just waits.
- **Heal first, free after.** A party member knocked off their feet or held isn't freed while the party is still resting or healing (it was cast and then everyone sat healing for 3-4 rounds anyway). Once everyone's healed up and ready to move, anyone still down gets freedom / cure paralysis. Same for yourself. Poison, blindness and disease are still cured straight away.

## 0.8.202

Text the game sends that MudPilot misread (found by checking against another MajorMUD client):
- **Yells can't fake a telepath any more.** A yell ("From Bob (Yelling): …"), "You exclaim" and "You ask" now count
  as chat, and a quote that isn't closed yet means the next line is still their words. A yell padded so its second
  line reads "Revolution telepaths: @do drop all" is no longer taken as a real telepath, and a prompt quoted in a
  yell isn't read as your HP.
- **Nobody can kill you by talking.** "You have been killed!" yelled, exclaimed or said inside quotes is never your
  death, and the spells that wear off with "The flames enveloping you die down!" or "The insects biting and stinging
  you die off." aren't deaths either.
- **Down at 0 HP or less, it waits.** No more flee every 3 s with running off, no heals spammed and no walking at 0 HP
  (it already held below 0): the game won't take commands until you're healed back up.
- **Asleep, paralyzed, too stunned, drunk, turned to stone, in limbo, retching:** the step is refused for now, not a bad
  exit. It waits 3 s and tries again, and it never counts towards giving up on the exit.
- **A room command said aloud** ('You say "go hole"', with fast talk on) is handled like "Your command had no effect.":
  it checks where it really is instead of saying it again.
- **An attack said aloud** ('You say "bash wizard"': blind, or no such target) — it stops, looks again and waits a
  little longer each time before the next try.
- **Monsters that run, stalk, stomp, float, swim… in from a direction** are now noticed as they arrive, not at the next
  look.
- **"above" / "below" exits** ("secret passage below", "closed trap door above") read as up / down, so those rooms are
  recognised. A wrapped exits line ending in "passage", "trap" or "secret" keeps its last exit.
- **"There is a closed door in that direction!"** starts the door handling even when the room view didn't show it shut.
- **"Slightly dazed you get back onto your feet."** ends the knocked-down wait.
- **"Also here: Bob(Hidden), giant rat (Charmed)"** reads as Bob and giant rat, so a hidden party member counts as here.

## 0.8.201

- **Switches to a weapon that can hit.** A monster your weapon can't hurt (it needs a more magical one: Buddy's holy
  avenger, magic 3, against the Hidden Copse copsewights, magic 4) — if you carry one that can, MudPilot wields it and
  attacks again, then puts your own weapon back once the room's clear. It swaps before the first swing when MME says
  the monster needs more magic, never flips back and forth, and skips a weapon the game won't let you wield. Settings →
  Combat, on by default.
- **The stash room only stashes while looping.** Standing in it by hand (collecting the cash to use the coin bag on
  it) no longer hides everything again, and it waits 3 minutes after you've been there before stashing on a Rego.
- **Teleport tokens on a Go to.** Settings → Other → Routing → "Go to: use a teleport token I carry…" (off until you
  tick it). When you carry a town token (token of Silvermere, Rhudaur, Khazarad…) and it saves at least 40 rooms of
  walking (you can change that), Go to uses it: MME says where each one lands, the level it needs and the cash it
  costs. Only when you're on your own (it doesn't take the party), with no monsters in the room, out of combat, and
  not in the same round as a spell. If it doesn't work (out of uses, monsters walked in, a no-token room) the trip
  just walks. Only the new Go to walker uses tokens; loops never do.
- **Cheap items for rooms that hurt.** Settings → Other → Routing → "Rooms that hurt on the way…" (off until you
  tick it) and "Hazard item: at most" (300 gold). A path through swamp poison, freezing cold, magma and the like:
  if a shop sells something MME says stops it, it's under your cap, and the damage on the way is a real chunk of
  your HP, the errand buys it first (one you already carry counts — nothing bought). Dearer ones are only mentioned
  in the log. It doesn't put it on for you — wear it for the stretch.
- **Drop cheap loot, sell only what's worth the trip.** Settings → Loot → Bank and shop trips → "Drop cheap loot"
  (off until you tick it; default line 100 gold). What a shop pays is worked out from MME's price and your Charm
  (Paradigm pays half). Loot under the line isn't picked up, and what a chest you open hands you under the line is
  dropped straight away (the pack is read before and after the open). Valuable chest loot goes on the Sell trip
  (when "Sell these…" is ticked) — never more copies than the chests gave — and cheap items on your sell list are no
  longer walked to a shop. Never dropped: items with a rule in Game Data → Items, keys, lights, chests, quest items,
  your restock items, worn gear, or anything MME has no price for.
- **Upgrade alerts for weapons and shop lists.** The gear upgrade watch (on by default, alert only) now also says when
  a weapon would hit harder per round than the one you wield (MME's attack formula with your level, agility,
  strength and encumbrance), and checks every row of a shop's 'list'. Weapons are never picked up or wielded by
  themselves. Tick "Gear upgrade" under Alerts to get it on your phone too.
- **Charged items are counted.** Wands and other N-use items count down with each 'use' nothing turned away; per-day
  items (MME "Retain After Uses") get their uses back at the daily cleanup — set its time under Settings → Loot →
  Gear upgrades (blank = 24 h after it ran out). Paradigm's "Uses remaining: N" (look at the item) and "Nothing
  happens." / "no charges" straight after a use beat the count. An item that's out isn't used automatically any more
  (one try every 30 minutes in case it refilled); anything you type still goes out. Unlimited items (the crozier)
  are never counted. What you carry shows in the log after each inventory read ("Charged items you carry: teak wand
  7/10 left, skull wand 0/3 today").
- **Step-by-step guides.** Help → Step-by-step guides (also a button in the F1 help book): short walkthroughs for
  first-run setup (board, BBS, logon steps, Connect), running a loop, party play and remote @commands, auto-get /
  auto-stash items, and phone alerts. A small panel says "Step 2 of 5" with Back / Next / Close (Esc closes), opens the
  right Settings / Game Data tab, and flashes a yellow border round the real thing to click. Nothing is locked while it
  runs — the game and the bot carry on. Also fixed: Options → Map / Paths / Bosses / Stats and "Dock conversations"
  did nothing (they looked for the tabs in the wrong place).
- **BBS art (CP437), off by default.** Settings → Other → "BBS art (CP437)": the MUD window (and the full-screen page
  view) uses a font that draws the IBM PC box lines and block characters at letter width — an IBM VGA font
  (Mx437/Px437 IBM VGA 8x16, Perfect DOS VGA 437) when one is installed, else your own font if it already lines them
  up, else Consolas / Lucida Console. What the bot reads is unchanged: the board's bytes were already decoded as CP437.
- **All characters window.** Window → All characters (or `python -m mudpilot --overview` on its own) shows one row per
  MudPilot: name, realm, level/class, HP/mana, room, what it's doing (looping, resting, fighting, walking to…,
  stopped, hung up, offline), exp/hr, how old the news is (grey = stale, red = not running) and version. It reads each
  character's control\status.json (now every 10 s, with name/level/room added) from this PC's data folders plus any
  folders you add with Folders… (e.g. `M:\MudPilot\MudPilot`, `R:\MudPilot\MudPilot`). Read-only: nothing in it can
  send to, stop or restart a character. Optional LAN status packets (UDP broadcast) are off by default both ways.
- **Aliases and key bindings in Game Data.** A new Aliases tab (next to Macros): type "bs" and it sends "bash door";
  `$1 $2…` are the words after it, `$*` all of them (with no `$`, they go on the end: "k orc" → "kill orc"), and `^M`
  or `;` splits it into several commands. Only what you type or a macro key sends expands — a party member's `@do`
  never does. Key bindings stay on the Macros tab (F-keys, number pad, Ctrl+letter, and a macro can send an alias);
  it no longer hands out keys MudPilot already uses (F1 help, Ctrl+S, Ctrl+Shift+D, Page Up/Down, Ctrl+Home/End).
- **Chat keyword alerts (off unless ticked).** Settings → Phone alerts → Chat keywords: a gossip / auction / telepath /
  gangpath / broadcast / say / yell line from another player with one of your words is highlighted in the Log, and
  sent to the phone if ntfy is set up (one a minute at most; the same word from the same player once per 10 min).
- **Game Data → Items sorts by Get, Slot and Type.** Click the Get heading and everything you auto-grab (or stash,
  or never pick up) comes to the top; click again to flip it. Blank cells always sort to the bottom, and the sort
  stays put while you type in Find. The list also shows all of the realm's items now; it used to stop at 2,000.
- **Level-50+ druids and priests fight high-MR monsters.** When no spell rated over the minimum, only a mage fell back
  to its best below-par spell; a druid or priest wasn't allowed to swing either, so it stood there "waiting for mana"
  with full mana. They now cast the spell that hurts it most, like a mage.
- **A monster your weapon can't hurt no longer freezes the fight.** With the ghost first in the room it stood there for
  good, never swinging at the orc beside it; and "Your weapon has no effect" after its own swing was never acted on.
  It now swings at the first monster the weapon can hurt, breaks off (with your break command) when it's swinging at
  the immune one, and walks on when nothing here can be hurt. *Combat Off* now ends the swing, and a fight you typed
  yourself blames the monster you typed at, not the one MudPilot last attacked.
- **Area-spell "no effect" is stored against the right monster.** "Your spell has no effect on blood skeleton" after a
  quake aimed at a kobold thief marked quake useless on kobold thieves for good. It now goes against the monster the
  line names.
- **The multi spell isn't cast at what it can't hurt.** It went out with only a mana check: swarm at blood skeletons
  every round until the mana ran out, and a spell you haven't learned (or a typo) resent every 2 s. It's now skipped
  when it can't hurt any of them, the game refused it, or it's too low for your level, and its results are learned.
- **Area spells wait while something you don't attack is here.** A guard, a neutral shopkeeper or a monster on your
  never-attack list got hit by the area spell. Area spells (the multi spell, openers and the automatic picks) are now
  held while one is in the room, as they already were for a stranger on a PvP board; single-target spells still go out.
- **Heals and cures between PvP rounds.** While an enemy player was in the room nothing but the PvP attack ran — a
  priest never healed itself or the party. Heals and cures now go out between rounds.
- **Attack last ignores a party member's heal.** "Evolution casts cure poison on Buddy!" counted as starting a fight,
  and the re-attack cost a round. Only a cast at a monster in the room counts now.
- **A solo caster doesn't cast what it can't afford.** The "cast it anyway to share the party's kill" fallback also ran
  alone, sending a spell the game refused every round. It's party-only now.
- **The game's level beats the Character level setting in fights.** A stale level (say 30, imported from a MegaMUD
  profile, on a level-52 mage) switched off the too-low-spell filter and the no-melee rule and rated spells at 30.
- **The stall watchdog knows more of your own attacks** ("You slap", "You jumpkick", critical and surprise hits), so it
  doesn't re-attack mid-fight.
- **Room tracking after a summon or trap into a look-alike room.** A room shown with nothing asked for, looking just
  like the room we were in, read as "never moved". It now keeps both until the next room tells them apart. Moves
  typed just before dying are also dropped, so the respawn room isn't read as one of them.
- **No bless recast loop on stock MajorMUD.** Stock 'st' doesn't list effects, but every 'st' marked each bless as
  worn off and recast it, about every 15 s. Blesses only go by the 'st' list on a board that shows one (Paradigm).
- **A real rest goes to "rest until".** An old "resting while we wait" flag (a wait broken by a fight or a move)
  made the next real rest end at "rest below".
- **@ok after a broken rest.** A follower that sat down (and said @wait), then had the rest broken by a fight and
  ended over the rest line, never said @ok. It does now.
- **No endless rest on a max HP that dropped.** HP stuck short of the top for a minute while resting reads 'st',
  so a max that went down (regen gear swap, a bless wearing off) doesn't keep you sitting.
- **Ailments clear on death and reconnect; "You feel sick." isn't poison.** Your own cures stop after 3 tries
  with no "cured" line, instead of every 4 s for good.
- **Heals check mana.** A heal you can't afford isn't sent; with no mana for your own heal, it asks the party.
- **Party wait timeout is quiet.** After "Done waiting", the same members aren't logged every tick; once they're
  back over the line, a new wait can start.
- **Area heal waits for a fresh 'par'.** It was recast every 3 s on members it had just healed.
- **"You do not have enough mana" for a bless** counts it as down and not as a reroll; a bless costing more than
  your mana waits.
- **Kai with no KAI in the prompt reads as 0**, not the last value.
- **Party training asks a trailing member again.** A follower one room behind answered "not there" and was skipped
  for the whole trip; the leader now asks a few more times over about 10 s.
- **Hands off mid train-stats form** keeps the form going to its checked SAVE or QUIT, not frozen half-typed.
- **Someone's gossip about "now level 20"** no longer starts a spell scrolls errand.
- **Someone else's torch going out** no longer clears your lit light.
- **Spell scrolls / training trips stop** when you're made a follower mid-trip (and training when auto-train is
  switched off).
- **A failed update download** leaves no .part file, and a broken zip says "isn't a MudPilot zip".
- **Relog instead of hanging up really is 5 s.** The line's own "closed" note reset the reconnect timer, so the
  relog waited a whole reconnect delay (60 s) instead.
- **A hang-up survives a restart.** A restart or update during the stay-offline time logged straight back into the
  room it had run from. The hang-up (and "wait at the MajorMUD menu") now goes into resume.json, and the next start
  waits out the rest of the time, or stays off when the setting says to stay off until you connect.
- **A restart while the line is down carries on.** A restart during an outage or a reconnect forgot the loop and could
  come back offline. Now it comes back in and carries on with the loop, as it would after a dropped line.
- **One MudPilot per character folder, however it's opened.** Only the launcher checked this, so `python -m mudpilot`
  could open a second copy on a character that was already running, and the two kept logging each other off.
- **Back in after a drop: rest and regroup first.** The loop used to carry on 4 s after reconnecting, whatever the HP
  and whoever was back. Now it waits (resting meanwhile) until HP is over the rest line and the re-invited members
  are back in, for up to the comeback wait, then carries on.
- **Party @ commands come from the party leader.** @stash, @unstash, @makeroom, @panic, @party and @share are now
  taken only from the leader of our party, or from someone with the "party" box ticked. Any other permission no
  longer counts for them. Members can still send @wait, @ok, @waiting, @comeback, @health, the condition reports
  and party sync, and @ptrain follows its own rules.
- **Remote hardening.** Refusals ("command invalid or not allowed") go to each sender at most once every 10 s, so a
  stranger can't make us spam the server. A stranger's "{mpsync ok}" no longer saves a fake party peer into the
  profile. Digits like "²" no longer cause an error in @ptrain or @flags. A long chat line that arrives without the
  game's line-clear code still has its wrapped second half treated as chat, not as a telepath.
- **First run asks which board you play on**: Paradigm, Stock, or your own MME file. Before, a new install routed on
  Paradigm's map without asking. Installs that already have settings are left as they are.
- **Lair camping (Paths → Camp lairs).** A new mode, off unless you start it: mark a handful of lairs (Add this room,
  type a map/room, or Game Data → Rooms → Add to Camp lairs) and click **Start camping**. MudPilot waits in the room
  next to a lair and steps in as it comes back — never early — fights, loots and leaves (an empty lair after 3 s, a
  fight that won't end after 30 s once it's safe to walk), then picks the next: the closest lair that will be back by
  the time it walks in, else the one back soonest (or tick **Least-late pick**). Respawn times come from MME's room
  Delay — Stock: Delay×60+30 s from the last kill; Paradigm: (Delay−1)×60+30 s from your entry — until MudPilot has
  timed a lair itself. A lair behind a door the character can't open is dropped; one that won't let us in is tried
  again after 2 s, 4, 8 … 60. Bank, stash, sell and train trips go between lairs and come back to camping; a dropped
  line carries on with the clocks kept. Stop ends it; it never starts on a follower (the party follows the leader).
  From a party member: `@camp start`, `@camp stop`, `@camp list` (the "move" permission). The old loop lair pacing
  stays switched off.
- **Hang-up item pickup (Settings → PvP).** Some Stock boards drop items when you hang up in a fight. Tick "This board
  drops items…" and set how many it drops: back in the game the walk waits while MudPilot reads `i`, works out what's
  missing, checks it came back in the same room and can see it (not dark or blind, no monster), and gets each item
  back — never more than the floor shows or the board drops — then puts worn gear back on. Once per login. A hang-up
  that killed you (one life fewer) is left to death recovery. Off and 0 by default; Paradigm never drops items (only
  HP).
- **Doors nobody in the party can open are asked about.** A route through a locked door no one can pick or bash (and
  no key to fetch) went ahead silently. ('1000 picklocks' doors aren't counted: those open another way — a lever, a
  quest step — like Morukai's lair door.) Now: "<door> — nobody in the
  party can open it. Try anyway?", No by default (no answer or nobody at the keys = No). No plans round it, or says
  there's no route and names the door; Yes walks it as before. "How far is…" and errands no longer count rooms behind
  such doors. A member who can bash or pick it still does it.
- **"Drop smaller coins" no longer throws away a pile of gold.** It dropped every cheaper coin you carried — 300 gold
  crowns for 1 platinum piece. It now drops only as many as the pile needs, cheapest first, never a stash coin, and
  re-reads the encumbrance after.
- **Party gates check everyone.** Alignment and race gates only looked at the leader, so a Seedy or half-ogre follower
  was refused and left behind. They now use each member's alignment and race from Game Data → Players.
- **Tolls add up.** The cash check used the biggest toll on the path, not the total: 450 copper "passed" two 300 gates
  and the walk stopped at the second. A small toll before your cash is known is no longer a wall either.
- **Stash rooms are safe from loot and auto-search.** Only this loop's stash room was protected; another loop's and
  the party stash got searched and looted (and re-stashed, over and over).
- **Loot weighs everything it asks for in one look**, so the second heavy item goes to a stronger member instead of
  being refused; copper looted counts what you actually picked up; death forgets your coins and encumbrance.
- **Going round a blocked exit on a loop rejoins at the next visit** to that room, not the first (it re-walked half
  the lap).
- **Regen gear can't get stuck on.** A restart or death mid-rest left the regen set on for good (and Redress
  remembered it as your gear). The "put the fighting gear back" commands are saved and sent at the next login, nothing
  is remembered while resting in the regen set, a partial redress no longer shrinks the remembered set, and two worn
  rings with the same name are handled as two (regen swap and redress).
- **Shop trips that fail stop repeating.** A buy, sell or deposit that changed nothing (no cash, out of stock, refused)
  waits 30 minutes instead of going every lap; buying isn't tried without the cash for one; worn gear isn't counted as
  something to sell. An errand shop that's out of stock is left alone for 30 minutes instead of a bank run.
- **@makeroom drops only what's needed** and, in a shop, never the coins the item's price needs.
- **Paradigm's map fixes stay on Paradigm.** The pyramid doors, segments, sphinx answer, pinned path, timed gates and
  the 3/1 levitation exit were applied to Stock too (same room numbers). They now apply only on Paradigm (its board
  or its MME data).
- **"How far" agrees with the planner.** Rooms reached by a random drop (the Warped Asylum), item teleports and a sea
  room as the end of a trip were counted unreachable; and "no route" into Crystal Lake now says it's open water.
- **A fetch inside a fetch keeps the first errand.** The walk to the bracelet needed the bloodstone orb (or a key door
  on the way): the new errand replaced the first, so it got the orb, walked to the bracelet room and stood there. The
  new item now goes in front and the errand carries on to the real target.
- **A bank run for an item goes back to the Go to, not the bank.** After the withdraw it walked back to the bank
  itself and forgot where it was going.
- **Room commands aren't spells.** 'jump north', 'dive moat' and 'light torch' matched some MME spell's short name and
  were counted as casts — a failed rooftop jump then waited out the 10 s step timeout every time. Only your own spells
  count now, and never a room or path command.
- **Room-command exits that need an item are checked.** 'dig grave' needs a shovel: Go to walked to the graveyard and
  sent it 8 times. The shovel is now fetched (or you're told), and tolls, traps and quest flags on room commands count too.
- **Comeback: a member's @stop ends the fetch, and two drops at once are both fetched.** After Revolution's @stop the
  loop restarted by itself 30 s later; a second member who dropped mid-fetch was forgotten.
- **Room names padded with spaces in MME match.** The Mausoleum Labyrinth rooms (17/2245-2256) never matched, so the
  tracker picked a look-alike and the Go to to Ozrinom stopped.
- **A caster with Combat off swings at a guard.** No spell could go out, but the no-melee rule still held, so it stood
  at the deranged priest for 5 minutes.
- **Spell-trap pockets aren't one-way any more.** With "walk through spell-trap exits" off, the Darkened Tunnels' side
  pockets (trap only on the way out) let you in with no way back. With no other way, a trap exit is now used.
- **MegaMUD paths with 'FFFFFFFF' steps resolve** (Lower Bristlewood loop, Dark-elf Royal Guards), and a path's guess
  onto another map ('raise idol' at 3/817 → the swamp) is no longer saved as a learned exit.
- **A target inside an avoided area can be walked to.** Go to a Negative Power Plane room said "only through Black
  Wasteland" or went 651 rooms round; the target's own area is no longer avoided for that walk (the rest still is).
- **A follower doesn't run its own boss hunt.** With the leader's @hunt on, a follower set off for a boss by itself.
- **Stop (and your own Go to) cancel a shop/bank trip.** A trip left running finished on its own and its walk back
  hijacked your next Go to.
- **Small walk fixes:** the 1/1104 warehouse door is priced like the other 1000-picklock doors; one invite while on
  your loop no longer sends both 'invite' and 'join'; "put the  in at …" reads "get it at …"; a target whose room spell
  throws you back out stops after the second throw instead of 18-room laps.

## 0.8.200

- **Switching weapons lets it melee again.** Buddy's holy avenger had no effect on the copsewights (magic 4), so
  MudPilot stopped swinging at them. He switched to the ice crystal falchion, which can hurt them, and Buddy still
  wouldn't attack. "Your weapon has no effect" is now remembered for the weapon in hand only, and the game's "You are
  now holding …" clears it straight away.
- **Update check.** When MudPilot opens it asks GitHub whether there's a newer version (nothing about you is sent;
  Settings → General turns it off; Help → Check for updates asks now). If there is, a bar shows: **What's new** (the
  release notes), **Update** (downloads it next to the install; a restart installs it and logs back in), or **Skip
  this version**. A copy run from source is pointed at the download page instead.
- **Stat & mana-regen breakpoints** (Window menu). The game rounds every derived value down, so a stat only changes
  something at certain values. Pick a stat: each thing it feeds (dodge, crit, stealth, picklocks, carry weight, HP
  and mana a tick…), its value now, and the next stat values where it goes up. The Mana regen tab lists the spell
  rolls (ManaRgn +N) where your mana tick actually goes up, for your level, stats and gear: a flux / ntap / nity
  reroll target on one of those is worth it, anything in between buys nothing. Formulas for Stock and Paradigm.
- **Help topics (F1).** A searchable help book inside MudPilot: getting started, paths and Go to, combat, blesses,
  resting, loot and stashing, party play, every remote @command (built from the live list), boss hunting, PvP safety,
  phone alerts, calculators, updates, reporting a problem and keys.
- **Spell scrolls after a level-up** (Settings → Spells: "After a level-up, buy and read scrolls for spells I can
  now learn", off by default; **Look for scrolls now** runs it once). MudPilot works out which spells your class can
  learn at your level and you don't know yet, finds the shops that stock their scrolls, and buys and reads them —
  lowest level first, as far as the cash you carry goes, nearest shop first (one on your loop wins). It skips
  anything the shop marks "(You can't use)" or "(Too powerful)", reads scrolls you already carry instead of buying
  more, and goes back to the loop afterwards. Never mid-fight, never with Hands off on; Stop ends it.
- **Auto-train** (Settings → Loot → Training, every switch off by default). **Train levels automatically**: once a
  level is banked, at the end of a lap MudPilot walks to the nearest trainer that takes your class and level (from
  MME), fetches the fee from the bank if you're short, trains (again while more levels are banked) and goes back to
  the loop; you can keep some levels banked and set a level not to train above. **Spend CP by my CP plan**: after
  training, your plan's stats for the new level (type them in, e.g. `10: STR 60 AGL 50; 20: STR 70`, or use Game
  Data → Exp/CP → *Save as CP plan row*) go into `train stats`. Nothing automatic is sent while that form is up, and
  the form is read back before saving — if anything isn't exactly as typed it leaves with QUIT, so no CP is spent
  wrongly. **Train together with my MudPilot party**: the leader takes its MudPilot members to their trainers too,
  invites everyone back afterwards, and nobody's comeback treats the trip as the party breaking. Never mid-fight,
  never with Hands off on; Stop ends it.
- **Carried lights for dark rooms** (Settings → Other: "Ready a carried light (torch, lantern…) before dark rooms",
  off by default). Before the walk steps into a room too dark to see in, MudPilot lights the weakest torch or
  lantern you carry that's bright enough (then looks, so monsters there aren't missed), and puts it away where you
  can see without it. When one burns out it lights a spare; if it can't see with a light it thought was lit, it
  checks the pack first. At the end of a lap, short of a light bright enough for the loop's darkest room (or the
  one in use nearly spent with no spare), it buys about two hours' worth, as far as your cash goes. The older Light
  switch (a light command or spell) still works as before.

**Bugs fixed before anyone hit them.** Another MajorMUD client (MudPlay) keeps a long record of how the game really
behaves. Checked against MudPilot, these were wrong:

- **Mystics and Monks stayed in the party.** Once a Kai class has any kai, its `par` row shows `[K: 40%]` where a
  caster's shows `[M: …]`. The row wasn't read, so they dropped out of the party: no heals, no party blesses.
- **Stock boards: exits read right.** Stock hides a backspace inside direction words ("n", a stray capital,
  backspace, "orth"). The backspace was thrown away before it was applied, so exits read "nQorth" and room tracking
  failed. (Paradigm doesn't do this.)
- **"Your command had no effect." after an attack isn't "wrong room".** Paradigm says it for an attack on a monster
  the party has just killed, a spell that can't go, a 'break' or a 'bash' at a wall. Arriving and swinging at the
  party's kill was read as the path's own command failing, and MudPilot went looking for where it was.
- **More refusals read as a failed move:** too heavy to move (it reads the pack), held ("can't seem to move
  anywhere", "flat on your back"), "There is a closed door in that direction!", "The portal is shut!". A gate that
  won't let this character through (toll money short, alignment, quest progress, a spell or an item it needs)
  stops the walk with the game's own line after the second refusal, instead of retrying the step forever.
- **A resting class with no mana** shows `[HP=91 (Resting) ]:`; that status line wasn't read, so no HP while resting.
- **Martial arts:** "Your fists/feet have no effect against this monster!" stops it punching, like the weapon line.
- **"You are too sick to rest!"** holds rests off for a bit instead of resending `rest` every 4 s (it meditates if it
  can). **"Meditation will not help at this time."** means mana's full: the old max is dropped.
- **"--- Telepath Not Sent ---"** (Stock's 4-per-3-seconds limit): the @command is sent again once. The game's
  "typing too quickly" lines are logged.
- Also: a monster's hit that names "your feet" counts in a dark room; "rises from the ground" and "moves into the"
  count as arrivals; `lo` and `loo` count as looks.

- **Stash rooms typed with a backslash work, and a room it can't read is caught.** Miserable set Stonecaps' stash
  room as "14\6534"; only "14/6534" was read, so the loop had no stash room and kept its cash. "14\6534",
  "14 6534" and "14,6534" are all read now. The stash dialog won't save text it can't read or a room that isn't in
  the map data, and says so, and the Loot tab's stash box says the same under it.
- **Auto-stash, per item.** Game Data → Items has an **Auto-stash** button next to Auto-get: that item is picked up
  and hidden in the stash room, while everything else you auto-get (ears and the like) stays in your pack. Find
  "stash" lists them. Auto-get and Auto-stash are separate: an item on auto-get that isn't ticked Auto-stash (the
  rares) stays in your pack for good, and only the ticked ones (the sellables) are hidden, so you don't walk round
  heavy or make trips to sell. Loot tab → "Also stash everything the Get button picks up" is gone for that reason;
  "Stash these items" and the coin ticks still work.
- **`@stash` gives a party member your stash room.** Stand in the stash room and telepath `/Revolution @stash`: he
  remembers it and hides *his* Auto-stash items there every time the party passes, with no loop or stash room of
  his own. Only Auto-stash items, never his coins or anything else. The raft hand-off the leader sends is now
  `@stash raft`.
- **`@collect <item>` and `@stash <item>`: set them from across the realm.** `/Revolution @collect silver dagger`
  sets it to auto-get; `/Revolution @stash runed stone cudgel` sets it to auto-get and hide in the stash room. Part of
  a name is enough when only one item matches ("which one? …" when several do). `@collect off <item>` and
  `@stash off <item>` undo them; `@collect` on its own lists what it auto-gets, `@stash list` what it stashes.
  They change what the character picks up, so they need the Settings permission on its Remote tab.
- **Things a member picks up for you get stashed too.** Too heavy for Miserable, the runed stone cudgels went to
  Revolution and never reached the stash. Now, in the stash room, Miserable asks him to hide the Auto-stash items he
  picked up on Miserable's behalf (`/Revolution @do hide runed stone cudgel`).

## 0.8.199

- **Party heals while resting check the party straight away.** After healing a member MudPilot sends 'par' a
  couple of seconds later, so it can heal again as soon as needed. A follower sitting still could have that 'par'
  held back 12 seconds, so healers healed once every 12-15 s and rests ran longer than they needed to (Revolution).

## 0.8.198

- **The chat box keeps the conversation after a restart or update.** The last 12 hours of chat come back from
  data/chat, with a "MudPilot restarted" line under them, so you can see what was said before the update. The
  party's @ok / @held chatter is left out.

## 0.8.197

- **A comeback no longer forgets the loop.** When the party broke and the leader was already walking back for a
  member, that member's own @comeback replaced "back to the loop afterwards" with "go to this room". The leader
  found them, stood there, and never picked the loop up again (Miserable and Revolution, Stonecaps loop, overnight).
  The second @comeback now keeps the loop.

## 0.8.196

- **A spell's short name means the spell you know.** 'fury' is elemental fury for a druid and divine fury for a
  priest; 0.8.195 sent Evolution's attack spell 'fury' out as the Priest's divine fury. MudPilot now looks in your
  own spell list first.

## 0.8.195

- **The spell you set is the spell it casts**, unless there's a real reason not to: the game said "no effect",
  the monster resists that element by 50% or more, its spell immunity is above the spell's level, it's too low a
  spell for a level-50+ caster, or you can't afford it. Your spell for that monster (Game Data) comes first, then
  your attack spell list in your order. Damage ratings and mana-saving switches only come in when none of yours
  can go out. In a crowded room your area spell still comes first.
- **"Magical" no longer limits spells.** MME's Magical rating is the weapon needed to hit a monster; spells are
  limited only by its spell immunity. The adult red dragon needs a +4 weapon, but any level-20+ spell hits it
  (spell immunity 20). A gorgimera (Magical 5, no immunity) takes magma blast or sphere of implosion, so
  Miserable no longer storms a single one.
- **A level-50+ caster's floor is now level 30** (was 20).

## 0.8.194

- **A mage no longer swings when a monster in the room can't be hurt.** A large nightmare and a small gorehoof
  walked in on Miserable in Albion. Magma blast hurts the nightmare, but MudPilot dropped any spell that couldn't
  hurt every monster in the room, and the gorehoof is Magical 5. The storm was held because only 2 monsters were
  there, so the mage meleed. A single-target spell is now judged on the monster it's cast at, and an area spell
  counts if it can hurt any of them.
- **When nothing seems able to hurt a monster, the spell used to join the fight is the strongest you can afford,
  not the cheapest.** It was vine strike every time. A bigger spell is the one that may beat a magical monster,
  and once it lands MudPilot counts it as able to hurt that monster.
- **A level-50+ caster (Mage, Druid, Priest) never casts an attack spell below level 20:** no vine strike, magic
  missile, chaos and so on, whatever the attack list or a per-monster pick says.
- **A level-50+ caster never melees unless the monster is immune to all its magic.** Out of mana, it waits for
  the next spell instead of punching.
- **Drain healing (death touch) goes up to your rest max or 90%, whichever is lower,** then switches to a real
  spell. It used to stop at the rest line + 20 (80% at the usual 60).
  The game repeats a spell every round by itself, and MudPilot didn't interrupt its own drain, so Miserable PVE
  drained from 75% to 99%. Now it switches to the real spell as soon as the drain is done.
- **Your spell for a monster (Game Data) goes out unless the game says "no effect".** MME's Magical rule no
  longer overrules it: Evolution set elemental fury for copsewights and got an earthquake on a single one
  after logging back in.
- **Spells seen hurting a monster are remembered across restarts** (spell_memory.json in the board folder), so a
  relog doesn't forget that fury hurts copsewights.

## 0.8.193

- **@have finds keys too.** The game lists some carried items on their own line ("You have the following keys:
  golden idol."), and @have only searched "You are carrying". Miserable had the golden idol but answered Revolution
  "{no golden idol}", so Revolution wouldn't take the party to the Stone Chief (the idol teleport needs everyone to
  carry one). @have now searches both lines.
- Groundwork for a Linux version (no Linux download yet): files and folders open with the system's own program,
  sounds play through the Linux sound player, and the Windows fonts map to the Linux system fonts.
- **Magical monsters: what you've seen hit beats the game data.** Paradigm's copsewight is "Magical 4" in MME, which reads as single-target spells of level 40+ only, so Evolution's elemental fury (level 35, his spell for copsewights) was ruled out and MudPilot cast vine strike at them saying nothing he had could hurt them, while that vine strike (level 1) was hitting them for 13. Once a spell has done damage to a monster, any single-target spell of that level or higher counts as able to hurt it, so your spell for that monster and the automatic pick go back to working. A "no effect" from the game still rules a spell out.

## 0.8.192

- **The Go to to the Spectral Knight opens everything on the way.** The way down to the Ornate Tomb (6/994) is:
  - 'push sarcophagus' to get into the Tomb Vaults
  - four levers pulled in order in four alcoves to open the stairwell at 6/861; each alcove is behind a wall that a
    lever in an Ancestral Tomb opens, behind an iron door
  - a row of hidden rooms to search, then 'push button'

  Before 0.8.189 the walk round the levers gave up and typed 'd' into the wall at 6/861, so no lever was pulled.
  0.8.189 handled walls behind other walls. One gap was left: when an iron door's bashes kept missing, the Go to
  "went round" it, but the tomb lever is only behind that door, so the walk typed 'd' into 6/861 again. Now the walk
  round the levers goes back through a door that failed if it's the only way to a lever. When a lever really can't be
  reached, the walk stops and says which exit and room instead of walking into the wall.

## 0.8.191

- **A character on its own loop follows nobody.** Miserable PVE was still in Evolution's party from a relog and was
  looping Tidepool alone. On a restart it treated Evolution as its leader: it @stopped Evolution (the whole PVE party
  stood still) and walked off to Rotting Glade to rejoin them. Walking a loop of its own, a character now sends no
  @stop before a restart, asks nobody to @comeback when the party breaks, and comes back on its own loop.

## 0.8.190

- **Settings come back on the right character after a power cut.** Revolution's PC lost power and PVEREV came back
  on its old 'PVEREV' profile (last saved Oct 30) instead of 'Revolution', the profile it had run on for two weeks:
  no blesses, no @ players. Nothing was lost, it had opened the wrong one. Now the status file (written every 30 s)
  remembers which profile is running, and the next start opens that one if app.json disagrees; the log says which
  settings opened and when they were last saved. Game Data's player list is now flushed to the disk before it's
  swapped in, like the profiles always were.
- **A stuck window gets going again by itself.** Miserable PVE's window stopped at 07:59 with none of MudPilot's
  own code running (Windows / Tk holding it), and the character stood in a crab fight until it died; nothing moved
  until the window was clicked 2 h 45 min later. Now, stuck 15 s in the game, MudPilot cancels any menu or window
  move holding it; still stuck after 45 s (5 min if its own code is busy), it notes the loop and closes for the
  launcher, which reopens it: it logs back in and carries on, about a minute offline instead of hours.
- **New look.** A new loading screen (the moonlit keep, with "Another Miserable Gift" on the book) and a new
  MudPilot emblem for the window, the taskbar and MudPilot.exe.
- **Traps weighed against your HP.** A trap used to cost a route at most 21 rooms whatever it did, so a level 55 with
  715 HP was walked through the Hedge Maze's 400-700 damage traps. Now a trap counts by what it does against your max
  HP down to the hang-up line (in a party, the weakest member's, from party sync): one that could take someone to the
  hang-up line or kill them is only used when there's no other way, and smaller ones cost more the more they hurt.
  Farnholme's 400-damage trap (14/8543 east) now gets the 39-room way round.
- **Rest before a trap or a stretch that hurts.** Before a trap, or a run of rooms that damage you (Volcano magma,
  a bog, a river without a raft), the walk rests to full first if your HP wouldn't see you through above the hang-up
  line. Already full and it still wouldn't, it says so and goes. Already in the middle of the stretch, it keeps going
  instead of sitting down in it.
- **Doors you can't open are planned round.** A locked door's '[61 picklocks/strength]' is now compared with your
  picklocks and strength when planning (leading a party, with the best picker or basher among members who share their
  stats). If nobody can beat it, another way is used when there is one, instead of walking 100+ rooms and stopping at
  "the door is locked". Until your stats are known (from 'st'), doors cost what they always did.
- **Walls opened from another room cost what the walk round really is.** A lever or button in another room used to
  add a flat 12 rooms. Now it's the walk to each action room and back (the Grand Stair door is 7, the mummy's gate
  41). One whose action rooms are behind other such walls (the Treetops, the four-lever stairwell at 6/861) counts
  as 100.
- **Guarded portals.** A portal or hole MME only lets you use with the room clear (the Deranged Priest's 'go hole',
  the master assassin's 'push panel', the Altar of Blood's teleport): the walk now fights what's guarding it
  first, Combat on or off, then goes, instead of typing the command 8 times and giving up.
- **The golden idol for every follower.** Leading a party, the Earthen Catacombs' idol teleport, or any exit each
  walker needs their own item for, is only used when every follower is known to carry the item. A follower's MudPilot
  now tells the leader what it carries of those (party sync), and '@have' answers count too. Otherwise another way
  is used, even one that needs keys fetched; only if there's none at all is it the idol way as before.
- **A small log fix.** Hit straight after logging in, the stall check said "No attack of ours for 1794560551 s"
  (the time since 1970). It now says "No attack of ours yet".

## 0.8.189

- **Walls opened from another room, behind another such wall.** The Treetops' north wall at 16/551 opens with
  'tear bark' in 16/569, which is behind a wall 'push knot' in 16/567 opens, which is behind one 'pull vine' in
  16/556 opens. Go to gave up on the walk round them and typed 'n' into the wall: every Go to from the Lost City to
  the Volcano or Undermountain stopped there ("no exit n from 16/551"). Now each wall on the way gets its own walk
  round: vine, knot, bark, back, north.
- **Dark-Elf City alone, without Black Wasteland.** Solo, Silvermere to Dark-Elf City said "the only way is through
  Black Wasteland, which you're avoiding". The way in with every key went over the roofs with the amber talisman,
  which MME has nowhere to get, so the whole "fetch the opener instead" plan was dropped. Items nobody can get are now
  left out and the way without them is used: the Fungus Tunnel, with the bloodstone orb fetched on the way.
- **Fetches in the right order.** That way in needs the black star key, the bloodstone orb and the gate key, and the
  gate key's statue is past the orb's door (8/398 south). The fetches went key, statue, orb and stopped at 8/398 ("no
  exit s"): the fallback that lets a fetch plan through doors you can pick was counting on the orb still to be
  fetched. An item still to get is never assumed on the way to another; now it's key, orb, statue, Dark-Elf City.
- **The Heavy Iron Gates need the signet ring.** 'show signet ring' opens 6/2619 south only with the gold signet
  ring; MudPilot took the command as the opener but forgot the ring, walked a ringless character 944 rooms there and
  stood showing a ring it didn't have. A door a room command opens with an item now needs that item: it's fetched,
  or the Go to goes another way.
- **A lever door that's shut again gets its lever pulled again.** The Grand Stair's south-east door (7/150) opens
  with the lever in 7/152. A Go to that pulled it a few minutes earlier counted it as done, so the next one went
  straight to the door, shut again by then, typed 'pull lever' in 7/150 (there's no lever there), tried 'open' and
  stopped: "the door southeast is locked". A shut door that's opened from another room now sends the walk back round
  to do it again (twice at most).
- **A boss you've killed isn't stopped for again.** A wandering boss has a row of rooms (the Bloody Executioner on
  the Winding Trail, Shadow Master on the Library Steps): killed in the first, the walk still stopped before each of
  the others ("Alt+R to go in"), and an unattended walk stood there. A boss that's dead by its clock on the Bosses tab
  (killed, not due back) isn't stopped for or walked round; once it's due back it is again.
- **The right key when two look alike.** Doors are unlocked with the key's last two words ('use house key s'). With
  the iron and the copper house key on you that's either of them; when another key you carry ends the same way the
  whole name goes out.
- **Landing on a look-alike wharf.** The Kingsport boat lands on Kingsport Harbor, Wharf, one of 45 rooms of that
  name, so the walk sat "At sea" on the wharf until its estimate plus 90 s ran out. The landing room among the
  look-alikes now counts as landed.
- **"No route" says when it's the fare.** From Kingsport the only way off the island is the 2,000,000-copper secure
  passage; short of the money the message said the passage "needs level 1+". It now says the fare and what you have.
- **New toolbar buttons.** A fresh set of icons across the toolbar; hover any of them to see what it does, as before.
- **`@auto-combat` help** no longer mentions the retired `-cast` switch (Combat covers attack spells now).
- **Practice server with honest gates** (`python -m mudpilot.simserver --gates`): locked doors you unlock, pick or
  bash, keys that wear out, items an exit needs (the golden idol, rope and grapple), tolls out of your purse, traps,
  class / race / alignment / ability / level gates, the spells exits and rooms cast on you (the idol teleport, rivers
  without a raft), room commands run from MME's textblocks, hidden exits you search for or open in order, boats,
  shops, monsters that stand in their rooms and drop what MME says. `tests\e2e_realm_walk.py` walks whole Go tos
  all over the realm on it (the sweep behind the fixes above).

## 0.8.188

- **Item blesses wait for your pack.** Straight after logging in, a bless that uses an item's spell waits until the
  inventory has been read, so it knows what to take off first (PVEREV's first crozier cast after the 0.8.187 restart
  went out blind and hit the golden chalice again).
- **Record a loop by walking it.** Paths → More → "Record a loop by walking it…" (or a path) opens the map window
  and records every room you walk into, number pad or typed directions, until ■ Stop / Save. The map window's record
  bar has a "walk it in the game" tick for the same thing; unticked it still draws on the map without moving you.
  "Build a loop from the map" is now called "Find loops automatically (lair chains)" — that's what it does.

## 0.8.187

- **Item blesses swap gear properly.** A bless that uses an item's spell (the emerald-tipped crozier's divine
  intervention) now does the same swap as `#etc`: a two-hander takes the off-hand item off first, then it's equipped,
  used, and your weapon and off-hand item go back as they were. PVEREV's crozier never went on ("You may not ready a
  2-handed weapon with your golden chalice worn!"), so divine intervention never went up. Any unlimited-use item
  spell works the same way; a ring or amulet is swapped in and the old one put back.
- **Party lines are never learned as a bless's start or wear-off.** The crozier had learned "You are no longer
  following Evolution." as its wear-off; lines like that are ignored now, and ones already learned are forgotten.

## 0.8.186

- **Attack spells follow Combat.** The separate Cast button is gone: with Combat on, single-target attack
  spells are on; with Combat off, they're off. Nuke (area spells) keeps its own button. `@auto-cast` now toggles Combat.
- **Report a problem reaches the developer.** Reports now go to the developer's private Discord channel.

## 0.8.185

- **A second `@stop` clears Rego.** Already stopped, another `@stop` wipes what Rego (and `@rego`) would carry on
  with, so an old trip doesn't come back. PVEREV kept 'Rego carries on to 13/825' on the Pirate Galleon through
  two restarts. The first `@stop` still stops the walk and keeps Rego.
- **Bank and shop trips sit right under Cash** on the Loot tab, and Gear modes moved to the bottom.
- **Pick the bank by name.** The deposit bank is a dropdown of the realm's banks (Bank of Arlysia, Bank of Delanon
  (Shadowmere), the Blackwater branch…) or the nearest bank, instead of typing a room number. A named bank has no
  step limit.
- **Walks round bosses, even easy ones.** Going from the Bank of Arlysia to the Abandoned Inn, a level-55 Mage went
  down Haven Street into Shadow Master: only bosses you'd stop before (40%+ of your HP) were gone round, and the way
  back to a loop after a trip didn't check bosses at all. Now Go to, bank and shop trips and the way back all go round
  any boss you aren't hunting when the way round is at most a quarter longer (or 20 rooms). A Go to the boss itself
  still goes there. Bosses tab: "Walk round boss rooms when there's a way about as short" (on).

## 0.8.184

- **A mage never melees while a spell can hurt the monster.** Miserable PVE swung at the hanging tree: no spell
  rated over the minimum (the tree resists comet, chain lightning was blocked by strangers in the room), and the
  fallback was melee. A Mage now casts the strongest spell that can hurt it (comet; when it's immune to that, the
  next one that can), and only swings when no spell hurts it or there's no mana for one. Spells that can't hit it
  (magma blast, level 45, against level-50 magic) are never picked. Other classes keep the melee-fallback setting.

## 0.8.183

- **Go to goes round a boss room it would stop before, when there's a way about as short.** A Go to Tidepool
  rowed out to the Pirate Galleon, walked the deck past Captain Flintlock and jumped back onto the beach; the shore
  way is the same length. It now takes the shore. It keeps off the boss's whole area (the ship), not just the
  room, and only when the way round is at most a quarter longer, so a boss you're there for (the king crab for
  Seher'Sahham's shortcut) is still walked to. A Go to the boss itself still goes straight there.

## 0.8.182

- **Anyone in your party can ask `@health`**, even with no @ permissions (a MegaMUD habit: they'd otherwise keep
  sending it). Only `@health`: every other command still needs its permission. Someone outside the party with no
  permissions gets no answer.

## 0.8.181

- **Fixed: a Go to went hundreds of rooms out of the way instead of through the Earthen Catacombs with the golden
  idol.** The catacombs' idol exit (16/2273 east) is a spell that sends you to 16/2431 if you carry the idol, but
  MME draws it going to 16/2274, so MudPilot treated it as a teleport and never used it. An exit whose spell
  sends you somewhere only if you carry an item is now planned to where it really lands when you have that item.
  The Abandoned Temple to the Deranged Priest is 93 steps with the idol (it was 286).
- **Fixed: more window freezes while planning a Go to.** What you do to each monster is now worked out once per
  monster for the spells you have, not again for every lair on the way.

## 0.8.180

- **File → Open character…** lists every character on this PC, shows which one this window is and which are
  open already (those can't be opened twice), and opens the one you pick in its own window.
- **Fixed: reopening a character could open a second copy of one already running.** If nobody clicked in the
  "Which character?" box within 20 seconds, it opened `data\` (PvP Miserable) even when that one was open, and
  the two logged each other off. It now never opens a character that's already open, and the launcher refuses
  to run a second copy on the same folder.
- **Fixed: a long Go to could freeze the window.** Miserable PVE froze on a 784-step Go to: every lair on the
  way was fight-simulated again because a buff had just changed AC. The result for a monster is now reused when
  AC is within 10 and DR within 3.

## 0.8.179

- **Fixed: the PVE party stood still after a restart.** Evolution was walking the Rotting Glade loop when Buddy
  invited it; it joined Buddy's party and dropped its loop, and Buddy runs no loop. A character walking its own
  loop no longer joins on an invite (join if invited, or an invite from someone with @ commands). It invites
  them to follow it instead. An explicit `@join` is still obeyed, and on a one-off Go to or standing still it
  joins as before, and it always rejoins its own leader (after a restart). If both are walking loops, the
  name that sorts first leads so they don't hunt apart.
- **Fixed: the leader stood 'waiting for Buddy (regrouping)' with everyone grouped up at 100%.** Buddy dropped,
  came back 22 s later and the party re-formed, but Evolution's 'Buddy dropped' note was only cleared when
  Evolution was leading, so it waited out the full 5 minutes. A member who's back in the party (seen in a
  `par`) or standing in the room now ends the wait straight away.

## 0.8.178

- **Fixed: a Go to to the Crimson Fortress went off to fetch the dirty obsidian key.** The gate bashes or picks at
  about 91, and that key is a witchunter's quest ('ask witchunter' in a town shop on another map). A door you can
  bash or pick yourself now only gets a key run when the key is right there: on the way, or one step off it (like
  the Dark-Elf City gate statue).

## 0.8.177

- **`@inventory` answers with all of it**, with no `...(more)`. Long lists go out one game line at a time, 2 seconds
  apart, so the server keeps up. Each line fits in one game line, so no item is cut in two.
- Two old tests brought up to date. MudPilot was doing the right thing; the tests hadn't caught up:
  - Spell efficiency only steps down to a weaker spell when it really kills for less mana.
  - The Go to to the Crimson Fortress now fetches the dirty obsidian key instead of crossing Black Wasteland.

## 0.8.176

Fixes from a full bug sweep of the code:

- **Security:**
  - A long chat line the game wraps onto a second line is never read as game text. Someone padding a gossip or
    telepath could otherwise make the second line look like `Evolution telepaths: @do …`, a hit on you, your death
    or a fake HP prompt.
  - Chat no longer gives you ailments. Someone gossiping "you are poisoned" or "you can't move" made MudPilot cure,
    say `@held`, or stop walking.
  - Updates:
    - A zip that's still being copied in when a character restarts is tried again next start, not skipped for good.
    - An update that fails halfway (a file held open) puts the previous version back instead of starting on a mix.
  - The recover password can't slip into a trace file when the network splits it across two pieces.
- **Go to:**
  - **Stop**, `@stop` or moving by hand now also cancels a Go to that hasn't set off yet ("Calculating route…",
    "Checking your inventory…", reading `abil` or `who`).
  - A Go to waiting on `i` could freeze the window for up to 2 minutes if it needed to ask you something. It now
    asks straight away.
  - The new Go to walker no longer stops a trip with "no route" while it's waiting on `abil` or `who`.
  - "Finding out which room this is first" no longer gets lost when a loop was walking.
  - "Walk to the loop start, then loop" no longer ends standing at the start after a `who` check.
  - Rego keeps the trip if it couldn't set off yet.
- **Fighting:**
  - The AoE safety (someone outside the party in the room on a PvP board) now covers every area spell: openers,
    "keep casting", the "nothing else can hurt it" fallback and `#nuke`.
  - An area spell the game is repeating stops when a stranger walks in or the room drops under your "at least N".
  - The area spell's mana floor holds when the auto pick chooses an area spell too.
  - Party cures no longer use up their three tries while the healer's spell slot is busy.
  - The bot's attack isn't re-sent after a heal or for attack-last while you're fighting by hand, paused, or with
    Combat off.
- **Party:**
  - A stranger healing or blessing a party member is no longer read as PvP.
  - Two `@comeback`s at once: both members are fetched in turn, then the party carries on where it was going.
  - Attack-last now answers party members whose names end in "s".

## 0.8.175

- **Fixed: a spell at a monster that had just died** ("You don't see nightshade here!"). The death line
  ("The nightshade wails as it turns to dust") comes before "You gain … experience", and MudPilot only treated the
  room's monster list as out of date from the exp line, so a cast could go out in between. It now waits for the
  room to show again from the death line too.

## 0.8.174

- **Fixed: lag and a "No walkable route" popup after being flung out of the Dao Lord's room.** A party member's
  MudPilot briefly saw the party as broken. It sent `@comeback` for the room you were both standing in, then
  re-joined a second later. The search was called off, but the Go to was still being worked out in the
  background, so it went ahead anyway. Flung out to 12/335, it searched the whole map for a way back through the
  portal, read `abil`, searched again, then popped up the dialog.
  - A called-off Go to now never starts, even if it's still being planned or waiting on `i` / `abil`.
  - `@comeback` for the room you're already in (or from someone standing next to you) doesn't walk anywhere.
  - The "No route" popup only appears for a Go to you started yourself. A party member's `@comeback`, an errand,
    or a re-plan just logs it.

## 0.8.173

- **Nuke now means area spells; the new Cast button means single-target spells.** Before, Nuke switched every attack
  spell on or off, so a druid couldn't cast earthfist on single monsters without also earthquaking.
  - **Cast** (new, on by default): single-target attack spells: your Attack spell(s), or the automatic pick.
  - **Nuke**: area spells only, cast from the "Use area spells when there are at least N monsters" count on
    Settings → Combat. Unticking that box now means *no area spells at all*. Before, it meant "area spells with no
    minimum", which is how Evolution came to quake one nightshade.
  - Both buttons are in the Manual-mode and Auto-mode defaults (Settings → General). Over Talk: `@auto-cast on/off`
    as well as `@auto-nuke`.
  - Characters with Nuke on behave as before: Cast is on for everyone.
- **Fixed: "nightshade is magical — casting earthquake" on single nightshades and geists.** When the usual spell
  pick came up empty for any reason (most often being under the *Keep mana in reserve* line), MudPilot treated the
  monster as one your spells can't hurt. It then cast the area spell at any monster count, with any mana (`quak` at
  2 mana), even past the "no area spells while someone outside the party is here" safety. Now that fallback runs only
  when none of your single-target spells could hurt the monster at all, and the safety holds there too. Otherwise it
  swings until there's mana again.

## 0.8.172

- **Phone page (watch-only).** You can watch every MudPilot on this PC from your phone's browser over
  Headscale/Tailscale. MudPilot keeps running on the PC as before, and the phone only looks.
  - **Turning it on:** Settings → Phone alerts → **Phone page**. Tick *Run the phone page*. It finds this PC's
    Headscale address by itself and says where it's listening, for example `http://100.64.0.5:8770/`.
  - **Pairing a phone:** click **Pair a phone** and type the 6-digit code into the page on the phone. In Chrome,
    ⋮ → *Add to Home screen* gives it an icon.
  - **What it shows:** every character on this PC (exp/hr, HP/MA, where it is, what it's doing, who it follows,
    or "not running"), and a tap opens a character's live coloured screen, stats and party.
  - **Security:**
    - Off by default.
    - It listens only on the tailnet address, never on every address.
    - Every request needs the phone key, which lives in Credential Manager and is shared by each MudPilot on
      the PC, so one pairing covers them all.
    - A pairing code lasts 5 minutes and is burned by 5 wrong tries. An address that keeps failing is shut out
      for 10 minutes.
    - *Forget all phones* makes a new key.
    - Nothing on the page can walk, type or change settings. The recover password stays hidden, as on screen.
  - Tick it in each MudPilot you want to open from the phone. Each one takes the next port from 8770.

## 0.8.171

- **A loop you start yourself carries on after a restart.** MudPilot remembered the last party it was in, even after you went off on your own. Buddy left Evolution's party to loop Crimson Fort; after a restart he stood still, waiting for an invite from Evolution that never came. Now, if a character was walking a loop of its own (or a Go to on the way to one) when it closed, it isn't following anyone and carries straight on with that loop. A real follower, one its leader was walking, still goes back to its leader.

## 0.8.170

- **Go to looks first instead of giving up.** Straight after coming back in, MudPilot doesn't know which room you're in until it sees one, even when the map still shows where you were. A Go to then logged "Can't route: current room unknown. Press Enter to look first." and did nothing else. Buddy, going from the Rocky Trail to the Iron House entrance, needed three tries. Now Go to sends `pro` (or a look, on boards without it) and starts walking as soon as the room is known, like Rego already did. If it still can't tell after 15 seconds, it says so.

## 0.8.169

- **A follower's @ok goes out as soon as their confusion or blindness clears, even if the party is split.** Revolution, confused by a terror beast in the Black Wasteland, told Miserable `@wait (confused)`. The fear also split the party, and the confusion wore off while he was out of it, so his MudPilot never said `@ok`. Miserable then held a Go to to the Pharaoh for 2 minutes until the @wait ran out. The @ok now goes to whoever was told to wait, the moment the condition clears, in a party or not.
- **Poison no longer stops the run on the timed pyramid levels.** On level 2, a bee's poison landed with Miserable at 65% HP, under his 70% rest line. The walk stood still with "Poisoned — waiting for it to wear off before resting" while the clock ran. The timed levels allow no resting, so now there's no waiting for poison either. The same goes for anything else that switches resting off, such as a Messages rule like desert heat, or a room that drowns you. Elsewhere it still waits the poison out before resting, as before.
- **A Go to you start says when a member's @wait is holding it.** For example: "Your Go to waits on Revolution @wait: confused — it goes when they send @ok (at most 74 s more). NoWait, or '.@ok', to go now". Before, the Go to just sat there with nothing on screen.

## 0.8.168

- **Fetching an item works when you start inside an area you avoid.** In the Negative Power Plane, which is on Miserable's avoid list, a Go to the Pharaoh said there was "no known place to get" the golden lion key. The search for where to get an item stayed out of the avoided area even though he was standing in it, so nothing was in reach. Now it walks out the short way, as a Go to does, and goes to kill the floating key on level 3 for the key.
- **Followers leave the golden lion key to the leader.** When Miserable, leading on PvP, killed the floating key, Revolution, who was following and standing in 12/2005, @'d him to hand the key over. Followers now stay out of the floating-key job. If a follower picks the key up, the leader asks them for it.
- **The map keeps up when you're blind or in the dark.** Blind, the game answers each step with "You are blind." instead of the room. Those steps weren't counted, so after your `pro` put the map on 12/1993, `s s e e s s` left it six rooms behind. Now they're counted. In pitch-black rooms (level 2 of the pyramid), steps typed ahead each started from where you were when you typed them, and pressing Enter could use up a step's answer. That is how the map ended up a couple of rooms off in the northwest corner. Each answer now goes with its own command, and each step starts from where the last one landed.
- **The party's MudPilots share quest flags.** Each one tells the others its quest flags once a session, and then every time one changes. The other MudPilots log it, for example "Party sync: Revolution's quest flag: DaoLordQuest 12 → 13", and can send a phone alert (new alert type "A teammate's quest flag went up", off unless you turn it on). When the leader types something that might finish a quest step (say, ask, give, push…), the others check their flags every 30 seconds for the next 10 minutes. A MegaMUD leader still gets the old `{Quest flag: …}` telepath.
- **Quest flags are read every time you enter the realm, but only in a quiet moment.** It waits at least 20 seconds after you get in, and then for a moment with nothing to fight, no strangers in the room, HP at 80% or more, and no resting or running. So it won't type `abil` straight after you hang up on PvP or come in hurt. If no quiet moment comes in 5 minutes, it says what it's waiting for.

## 0.8.167

- **Handing boats to the party now checks what the game says back.** Evolution logged "Gave a wooden skiff to Revolution" when the game had actually said "You cannot afford wooden skiff" and "You don't have wooden skiff to give!". Now, if it can't afford the boat, it goes to the bank if one is near, and otherwise doesn't set off. If the buy didn't happen, it buys again, up to three tries. "You give log raft to Buddy." counts as handed over. "<name> cannot accept your offer" means the member is too heavy, so they make room (`@makeroom`) and it gives again. That now works even when the prompt is on the same line.
- **A walk that can't get what it needs doesn't go, and says why.** Before, it said "asked twice already — walking on" and took the party across the river without boats, and after the crimson mist it stood idle at "no shop sells it". Now, if it's a boss hunt, the hunt is given up and the party goes back to its loop. If it's a Go to with a loop to return to, it goes back to the loop. Otherwise it stops and logs the reason. The same applies when an errand fails: it couldn't buy, had no cash, couldn't reach the place, or the drop never came.
- **Items with only a few uses are never spent automatically.** The token of Silvermere (5 uses a day) had been learned as a way from the Overgrown Shrine to the Pier after you used it by hand, and Go to then used it by itself. Now a command that spends an item with a few uses is never learned as a way, never planned, and never added as a teleport. Any such way already learned is dropped when the map loads. One-shot items the party's carry check buys, like the potion of levitation up to the catacombs, still plan as before.
- **A Go to you start switches Hands off off.** This covers the Goto button and dialog, a path's or loop's start, and `@goto`. It works the same way Rego does, and the log says so.
- **Making room for a raft.** A member who's too heavy for their raft (a stash pickup, a hand-over, or buying one themselves) drops copper, then silver, then gold until it fits. It never drops platinum or runic. Picking up a stashed raft tries up to 5 searches, which helps low-int characters.
- **Auto search stops once it finds something,** then sends a look so you can see what turned up.

## 0.8.166

- **The Search switch searches every room once, for hidden gold and items.** Before, it only searched rooms where the map data shows a hidden exit, and its description said so. Now it does one `search` in each room you walk into (Settings → "Search each room" sets how many), then looks again so the Get button picks up whatever turned up. Hidden exits on your way were never tied to this switch: a Go to or a loop searches for them (`search north` until it's found, with the party helping) whether it's on or off.
- **New Loot option: "Don't pick up coins once I'm Heavy (at 66% encumbrance)".** It's off unless you tick it. When ticked, coins are left on the floor once you're at that percentage or the game says Heavy. Swapping cheaper coins for a better pile still goes ahead, because that doesn't add weight. The game turns Heavy somewhere between 59% and 70% (traces show Medium at 58% and Heavy at 70%), so 66 is a guess you can adjust.
- **Trailing a scripter no longer stands about.** Evolution stood at 17/1631 saying "lost sight" while Osiris was a room away. Now, once it's lost them, or they've left the area, the loop just carries on as normal. The next time you're in a room together, it picks the trail up again. In the room with them, it waits up to 15 seconds to see which way they go, then loops on if they stay put. If they run out while you're fighting, the fight comes first. It goes after them once the fight is over, as long as that's within 30 seconds.

## 0.8.165

- **The party picks up what you can't carry.** When something is too heavy for you, MudPilot asks the strongest party member standing with you (one running MudPilot) to pick it up for you: `/Evolution @do get platinum bracers`. If that one can't take it either, the next one is asked 20 seconds later. Each member is asked once per pile. The same goes for coins once you're full.
- **A `get` that didn't work isn't sent again on every look.** If the item is still lying there after the `get` (too heavy, its weight unknown, or your encumbrance out of date), MudPilot leaves it alone for 5 minutes and hands it to the party instead.
- **Trail someone who scripts on top of you (Settings → Health → On a loop, off unless you tick it).** Once someone is caught clearing the lairs just ahead of you, the leader leaves the loop and goes wherever they go. With your attack going in first, the kills are yours. It only follows them inside your loop's rooms. If they leave the area, it goes back to the loop, and it picks up the trail again if they come back within the hour. If you lose sight of them for 45 seconds, it goes back to the loop. The aim is to cut their exp until they go elsewhere. Meant for PVE; on PvP you'd just kill them.

## 0.8.164

- **Gear modes no longer take off your second ring, wristband or Worn item.** Finger, Wrist and Worn each hold two items, but a captured mode kept one item per slot. With a second item on, MudPilot decided the slot held the wrong thing: on Revolution it took off the sunstone wristband and the sash of the arch-mage, then tried to `wear diamond emblem`, which was already on, and left both places empty. Two-item slots are now treated as two places. A worn item comes off only when another mode put it on, or when an item this mode wants needs its place. It never comes off just to leave the slot empty. Capturing a mode now saves both items in those slots. Modes captured before this keep working as they are.

## 0.8.163

- **Doors opened from two rooms: each action in its own room, in order.** On the walk to Ozrinom (17/2243), the way down from 17/2068 needs `twist hand` in the Family Tomb (17/2094) and *then* `twist sword` in the north Private Tomb (17/2076). The Go to walker went to the first room only, typed both there, and walked on, so nothing opened and it circled the mausoleum. It now walks to each room in turn, does that room's action, and comes back to go through. The same goes for the way down from 17/2126 (`push eye` in 17/2161, then `twist sword` in 17/2156). If it gets knocked off partway, it carries on from the next action instead of starting over, so a specific-order lock doesn't get reset. (Saved MegaMUD paths already did this.)
- **No more "Running for the gate" in the wrong place.** When the Go to walker re-planned, it kept the old plan's lever-gate step numbers, so it could stop fighting and walk out of a fight somewhere unrelated (it did, at 17/2094). Re-plans now carry their own. Running without fighting from the first lever to the gate is kept for the mummy's timed gate (1/1056 N). Other doors are walked round fighting as usual, as the party did at Ozrinom.

## 0.8.162

- **Parting ways means parting ways.** After the party split up with Skittles on purpose, Skittles relogged and MudPilot treated them as Miserable PVE's leader coming back. It sent `@where Skittles` for 10 minutes, then walked off to 17/1773 to fetch them right after your Go to Chancellor Annora. Now it stops trying to rejoin an old leader once you start your own Go to, or once you've led your own party without them for over a minute. It says "Not rejoining Skittles — you've gone your own way" and cancels any walk it started to fetch them. A follower coming back from a restart still rejoins its leader as before.

- **"He bites into Skittles" isn't PvP.** In the Mausoleum, the vampire magus's follow-up line hung Revolution PVE up as "PvP: He attacked Skittles", because "He" was read as a player's name. Pronouns (He, She, They…) are never player names now. Also, on a **PVE realm** (players can't hurt each other) a line that only *looks* like PvP no longer hangs up; it logs and alerts your phone instead. A real "Server PvP Message" still hangs up anywhere, and marks the realm PvP from then on. Your PvP characters (realm marked PvP) behave exactly as before.
- **Room actions only in their own room.** In the Mausoleum's Family Tomb (17/2094), MudPilot typed `twist hand` and then `twist sword` straight after it. The sword is in the north tomb (17/2076), so it had no effect, and in a specific-order lock a wrong action can reset it. On a Go to, an action that MME says is done in another room is now skipped and logged.
- **Sick: one gear swap, then sit tight.** After the rotting beholder's stench ("You feel nauseous!"), every "You retch uncontrollably!" broke the rest. MudPilot swapped the fighting gear back on, then the regen gear again, minute after minute. While you're sick (nausea, or confusion eating commands), the regen gear now goes on once and stays on through broken rests and rest/meditate switches, until "You feel less sick" or a fight.

- **A follower's stashed raft is remembered even when the party walks on.** Buddy and Revolution hid their log rafts at 17/1631 ("You hid log raft."), but Evolution walked on before their 2-second inventory check, and moving off threw away the record. Next time they'd have bought new rafts and left the old ones on the floor. Once the `hide` has gone out, the raft is now recorded as stashed straight away; the pick-up still checks, and buys a new one if it has gone.
- **Rego waits until it knows where you are.** Just back in after a restart, Miserable PVE's Rego of his Go to 13/785 said "Can't route: current room unknown". The room was confirmed 2 s later, but nothing carried on. Rego now looks first and carries on once the room is known. A walk you start in the meantime wins.
- **Go to plans much faster when there's an alignment gate.** Miserable PVE's 87-room walk to Chancellor Annora took 70 s to plan, and the window lagged while it did. MudPilot didn't know his alignment, so the route through the alignment gate failed. It then tried a room with the same name and planned again as if it held every key, each a whole-map search, before checking `who`. Now:
  - It sends `who` as soon as an alignment gate is what stops the way.
  - A failed search stops after 2 whole-map passes instead of 8.
  - Your own alignment is saved in the player list, so after a restart it's already known and there's no `who` round at all.

  On this PC that Go to went from 10.7 s to under 3 s before the `who`.
- **Quest NPCs talking to you aren't monsters attacking you.** Turning in the Pastor's message, "The ghost gives you a stern look, "Be wary of these monsters…"" made MudPilot think a monster called *ghost* (an evil one in MME) had attacked you in the dark. It added one to the room, and Miserable PVE cast magic missile at Justice Darkbane twice ("You are overcome with a feeling of guilt"). That check, meant for being hit by something you can't see, now ignores speech and gestures. It also no longer counts "the ghost" as a new monster when the Ghost of Justice Darkbane is already in the room.
- **Dark rooms aren't "left behind".** In the Frozen Cavern's Dark Hole, Revolution said "Miserable isn't here — left behind" and sent `@wait`, with Miserable right there. A pitch-black room shows nobody. A follower no longer takes an empty dark room to mean the leader has gone.

## 0.8.161

- **The party's rafts get stashed even when the leader has none.** Evolution leads the PVE party without a raft; Buddy and Revolution carry them. Followers only stash when the leader sends `@stash`, and the leader only sent it when it hid a raft of its own, so theirs were never stashed. The leader now also sends `@stash` when it starts a new loop (just back in, it can't know what anyone carries) and when the party's `@have` round has just shown they carry rafts. A follower whose pack isn't read yet types `i` first, then stashes.

## 0.8.160

- **Rafts stashed after a restart too.** After 0.8.159 went out, Evolution logged back in and reached Rotting Glade Full 2 minutes later, still carrying his raft. His pack hadn't been read since the relog, so the stash saw nothing to hide. It now types `i` first and stashes once the pack has been read.

## 0.8.159

- **Checks its own pack before asking the party.** Buddy handed Evolution the glowing red amulet. Evolution's Go to the Massive Chest then asked Revolution and Buddy for one, heard nobody had one and stopped: its pack list was from before the hand-over. When a walk is missing something and the last inventory read is more than 10 s old, MudPilot now types `i` first. It only asks the party, or goes to get the item, if it's still missing.
- **Friendly NPCs aren't attacked for smiling at you.** Turning in the chalice, "The bishop smiles at you hopefully" counted as the bishop going for Buddy. Buddy fights back against anything that attacks it, whatever its alignment, so it went to `smash bishop`. Speech (anything in quotes) and friendly gestures (smiles, nods, gives you, bows…) no longer count as an attack. A real lunge or hit still does.
- **Boss hunts find their way back to the loop.** Evolution stood at 17/183 from 00:51 to 03:10. It came from a chain of three bugs:
  - 3 minutes into the crimson mist walk, he paused for a second to ask the party about rafts. That counted as "the walk there stopped", so the hunt gave up. Now waiting on the party's answer, or on a raft errand, doesn't count, and "stopped" means standing still for 20 s.
  - The guardian golem came due on the walk back to the loop's start, and that hunt saved the walk, not the loop, as its way home. It now goes back to the loop.
  - The dropped walk's raft check answered late, in the golem's room, and started the crimson walk again ("lost and no route back to the path"). A new Go to now drops the old one's question.
- **Rafts get stashed after an errand or a hunt too.** The stash only ran when a new loop started. A raft bought for a Go to (a shop, a boss hunt) came back to the same loop and was carried all day, slowing every step. Rafts are now stashed whenever you go back on a loop that doesn't cross water.
- **A monster's lightning isn't PvP.** In the manscorpion king fight, "Lightning strikes you for 2 damage!" hung Miserable PVE up as "PvP: attacked by Lightning". A line that starts with the first word of a monster or room spell (lightning, shards, poison, acid…) no longer counts as a player attacking. Three things still count: a player MudPilot has already seen by that name, someone standing in the room, and anyone who backstabs or sneaks up on you.

## 0.8.158

- **Rests no longer knock the loop off its path.** Miserable PVE kept stopping on Tidepool with "knocked off the path 7 times in 5 min". After each rest or meditate the gear swap goes back on (`eq shawl^Meq pho^M…`), and when one of those lines does nothing the game says "Your command had no effect." That reply was taken as the path's own room command failing, so every rest meant a resync and a drift, and seven of those stopped the walk. For a few seconds after MudPilot sends its own swap lines, that reply is now ignored.

## 0.8.157

- **No more errand loop for your own items.** In the desert with no waterskin, "Go to 6/1335 General Store needs waterskin (sold: … 6/1335) — getting it first" repeated every 5 s and Buddy never moved: the errand's walk to the shop counted the waterskin it was going for as missing and planned a new errand. The errand's own walk no longer counts what it's fetching.
- **Already in the desert: no waterskin trip just to walk out of it.** The desert you're standing in doesn't count towards what a walk needs: only desert the way goes back into later does (walking out can't be helped by fetching a waterskin — that's more desert too). From 12/142, Go to Khazarad just walks. And when one is needed while you're in the desert, it's the nearest shop (Nekojin's Village Store, 12/49), not one on the way.
- **Rafts stashed at the loop, not rebought.** Arriving on a loop that doesn't cross water, the leader (or a solo character) hides its raft (canoe, skiff, punt) in the loop's room and tells the party `@stash`; each character remembers where its own is. When a walk needs one again, the stash comes before any shop: it goes there, `search`es, picks it up and tells the party `@unstash`, giving them a few seconds before asking who has one. A raft that's gone missing is bought, as before. Off with Settings `stash_rafts`.
- **Dark temple key: the three keys first.** Going to the Champion of Blood, Evolution walked to the Room of Change, put in keys it didn't have and stopped ("put the  in at Room Of Change"). The device takes the cross, runed and skull keys (MME `takeitem`, which MudPilot didn't read as a need). Now it gets each from its boss first, nearest first: the dark wizard (7/1258), the dark bishop (7/1227) and the master assassin (7/1283). Then it puts the keys in. Parts dropped by one boss or sold in a shop are fetched directly; parts with many droppers (the dragon key's fangs) are still farmed.
- **A blank Area spell works with your per-monster spells again.** A spell you chose for a monster (Game Data → Monsters) gives way to the area spell in a crowded room. That only worked when the Area spell box was filled in. Left blank ("best area spell I know") the per-monster pick won every time: Revolution cast `fire` at full rooms of geists and nightshades. Blank now picks the best area spell you know there, as the box says.
- **No more 'dtch' from non-mages.** Right after a relog (before the game's `spells` list is read) the drain-heal assumed you knew deathtouch — Buddy, a Paladin, sent `dtch serpent` every round. It now goes by last session's spell list, else what your class can learn; and a spell the game just echoes back as `You say "dtch …"` counts as one you don't have, so it isn't tried again.
- **@rego waits for everyone stopped for a restart.** Revolution came back first and sent @rego; Buddy set off while Evolution was still logging in. Now an @rego holds ("waiting for Evolution to get back first") and the walk carries on by itself once they're following again.
- **Followers heal and bless in the timed pyramid.** Bless upkeep and 'par' checks were off for everyone there, so party heals had no HP to go on. Followers keep both; the leader still skips blesses and checks 'par' every 15 s instead of never.
- **@mpsync stays off the game screen.** MudPilot-to-MudPilot sync (rests, levels, spell tuning — "Revolution telepaths: @mpsync sk 3|90|…") is still read and kept in Conversations, just not shown in the game window.
- **The Dao Lord quest's next steps are right.** At DaoLordQuest 9 it said "talk to Orfeo" (who wants 11): the pharaoh and the Dao Lord move it on by dying, which MME keeps as death spells. Now: 9 → kill Pharaoh Rastep (12/2250), 10 → kill the Dao Lord (12/2251), 11 → Orfeo, 12 → done (no next step).
- **AFK doesn't answer bots.** Three AFK characters bounced `{AFK}` between each other: the AFK note no longer answers a `{…}` reply. And an `@flags` answer fits one telepath line (its tail went out alone as `{= 11}`).

## 0.8.156

- **A Go to that a quest flag blocks checks before it gives up.** Buddy wouldn't go to the pharaoh: he'd done the withered old man (DaoLordQuest 9 in the game) but MudPilot still had 8, and at 8 the Great Pyramid's level 4 arches throw you to a random room. Now, with no way there, it reads `abil` again once and plans again. The route memory also remembered routes by PhoenixQuest only, so a new DaoLordQuest value went unnoticed for 10 minutes; it now goes by every quest flag.
- **It says why, in words.** "blocked by … (Cast: pre-0, post-702)" now reads "it casts 'pyramid 4 arch fail' on you, which takes you somewhere else (your quest flags: DaoLordQuest (134) = 8 (next step: talk to withered old man about 'ale' at Small Pyramid, Storeroom (12/1182)))".
- **Leading: the party's quest flags are checked too.** Before leading the party down a way that a quest flag decides, it asks everyone `@flags <n>`. If someone's value wouldn't get through, it doesn't go: "Can't go to 12/2085 Great Pyramid: Revolution is on DaoLordQuest 8 (you're on 9) — that doesn't get through." Members who don't answer (MegaMUD) are left to it.
- **No 25 s freeze** when a Go to tries again by itself (after `who` or `abil`): that's worked out in the background now, like one you start.
- **Followers fight in the timed pyramid.** Everyone gets "time is running out", so everyone ran past monsters and nobody attacked. Only the leader runs past them now; followers fight what's on them as they go.
- **Num Lock isn't Alt.** With Num Lock on, the activity log recorded every key as "pressed Alt+…" (on Windows Tk reports Num Lock with the bit read as Alt). Only the log was wrong; shortcuts weren't affected.

## 0.8.155

- **The round clock times rounds itself and keeps doing it.** Buddy's clock said rounds were 8.2 s while Revolution's said 5. Replaying Buddy's own trace (1,946 rounds, nearly all 5 s apart) through the old clock left it at 8.23 s. Once it had a length it only refined itself against its own guess, and the saved one came back after every restart. Now the length is always measured from the last 40 gaps between rounds: the shortest gap that keeps coming back is one round, a longer gap counts as a whole number of rounds (rounds nothing happened in), and the length is total time over total rounds. Starting from Buddy's 8.25 s it's back to 5.05 s within a dozen rounds. Manual fight uses the timed round too, rather than a fixed 5 s.

## 0.8.154

- **The desert waterskin actually gets used.** Buddy's log said "using the waterskin" but the game got `use Windblade` ("You don't have Windblade."), so nobody drank and Dan had to by hand. The item-spell shortcut for the waterskin is `#w`, which is Windblade's. A bot `use <item>` now only becomes a shortcut when that shortcut really is the item's.
- **The party is asked about everything that would do.** Into the Scorching Desert it asks `@have waterskin` *and* `@have sunstone wristband`, and someone with either is fine. Revolution, who wears the wristband, got a waterskin bought for him.
- **No more stopping dead at the shop.** Walking to the Village Store to buy that waterskin asked the party again, which replaced the errand: "then on to 12/49 Village Store". It handed the waterskin over and stopped there. The errand's own walk no longer asks again, so it carries on to where you were going.
- **Auto-join on an invite from someone with @ commands.** "Buddy has invited you to follow him." is joined straight away when Buddy has any @ permissions on this character, without waiting for the `@join` telepath (a player without MudPilot never sends one). It doesn't join twice when the `@join` follows.
- **Peruse books says `.Books have been properly perused!`** (the leading `.` works with talk set slow), not `say …`.
- **The Loops list mirrors the toolbar's Loop picker.** Both now list the same loops, grouped by the same area folders, with Peruse books under Golden Spire in each. Folders open while you search.

## 0.8.153

- **Peruse books is in the Loops list.** Search "book" or "peruse" on the Loops tab and it's there: Run (or double-click) starts it, the same as `@loop peruse books`. 0.8.152 only had it under Window and `@loop`. Up to 100 goes at the red book now, and it won't start if quest flag 134 is already 7.

## 0.8.152
- **Spell efficiency counts the mana to kill, not the mana per round.** "Spell efficiency" steps down to a weaker spell only if it kills that monster (by its HP in MME) for at least 15% less mana. A quick spell like magma blast (5 mana, 6 casts a round) stops once the monster is dead, so on a 500 HP monster it's 30 mana in one round, against 50 mana over two rounds for sphere of implosion. Miserable PVE was flipping between magma blast, sphere of implosion and forked lightning on the same monsters for no real saving and less damage; now he keeps magma blast.
- **A boss whose death line makes it vanish is counted as killed.** Evolution's party killed the crimson mist twice ("The crimson mist suddenly solidifies and vanishes in a shower of blood!", then 100,000 exp), but the death line took it off the room list before the exp line came in, so it never counted as a kill. The Bosses tab still said "seen alive", and the hunt swept on through the other lairs and booked another check 7 h later. The kill now goes to the monster the death line named.
- **The Scorching Desert needs a waterskin (or the sunstone wristband).** The desert's rooms leave alone whoever has drunk from a waterskin, and the wristband covers you too, but MudPilot didn't know that: a Go to into the desert set off without asking the party or fetching anything. Now a walk through the desert counts like a river: each walker needs a waterskin or the wristband, the party is asked, and a waterskin is bought (25 copper) if someone has neither. In the desert each character uses their waterskin (`use waterskin`) when they come in (unless the last one, good for 600 seconds, is still working), and again only when "You suffer in the desert heat..." shows: a waterskin has 3 uses, so none are spent on a timer. Anyone wearing the wristband doesn't drink.
- **`@status` says what it's waiting on.** Besides the walk and the room, it now says why it's resting ("meditating (mana below 60% (20%))"), any condition it has (disease, poison, held…), a message rule it's waiting to wear off, and which party member it's waiting for and how far along they are.
- **`@hunt` on its own lists the bosses being hunted:** the one it's after now (and how many lairs it has checked), then each boss ticked for hunting with its clock, or when it looks again for one it has never caught. `@hunt off` stops hunting altogether, for when you take over leading: a hunt under way ends where it is, with no walk back to the loop, and nothing due starts. `@hunt on` turns it back on. `@hunt <name>` still starts a hunt.
- **`@flags`: ask a character for its quest flags.** Telepath `@flags` for the quest flags it holds, from its last `abil` read ("read 12m ago", or "from last session"). Asking also makes it read them again, so asking a second time gives fresh ones. `@flags <name or number>` gives that one flag and MME's next step for it, e.g. `/Evolution @flags 134`.
- **Peruse books (Golden Spire Secret Library, 12/2248).** `@loop peruse books`, or Window → Peruse books. It walks there (turning the stand to open the door), peruses the blue book once, then the red book over and over: a failed roll ("Despite countless minutes of painstaking translation…") goes straight again, otherwise every 15 s. When the pharaoh story comes, it says `Books have been properly perused!` in the room and stops, so you can see when an AFK character is done. It stops instead if the red book "makes no sense" 3 times running (quest flag 134 not at 6, blue book not done), after 100 goes, or on `@stop`. If quest flag 134 is already 7, it says so and doesn't go.

## 0.8.151
- **`@loop` still loops after picking up a straggler.** Buddy sent `@loop rotting glade full`; Evolution set off for the loop's start, stopped on the way to collect Buddy and Revolution, then carried on to 17/183 — and stood there, because the "then loop" part was dropped when the walk was picked up again. All three sat resting at full for 18 minutes. The walk after a pickup now keeps what it was for.
- **A trap isn't a player.** "Spikes shoot out and stab Revolution viciously!" (the trap below the docks) hung Evolution up as "PvP: attacked by Spikes". A trap line ("… shoot out", "… fly out", "… spring up") no longer counts as anyone attacking.
- **A hunt keeps going while it fetches what the way needs.** On the crimson mist hunt, Evolution reached the Pier for a log raft and stood still a moment to buy it. The hunt took that as "the walk there stopped", gave up, and walked him 96 rooms back, then the raft errand walked him to the Pier again. The hunt now waits while an item errand or bank trip is running, then carries on to the lairs.
- **A hunt goes back to your loop.** `@hunt` or Hunt now while you're not looping (stopped, or on a Go to) goes back to your last loop afterwards, the way a hunt started from the loop does, rather than to the room it started from. A restart's resume note can also say `"hunt": <monster number>` with a loop: the character logs back in, regroups, hunts, then loops.
- **A restart request is always cleared when it closes.** On Revolution's PC the request file, just written over the network, could still be locked when MudPilot closed for an update. The delete failed silently and the leftover file made updates wait 7 minutes for Evolution. It now retries for a couple of seconds and logs it if the delete still fails.

## 0.8.150
- **Finds the log raft from behind locked doors.** From the guardian golem's rooms, `@hunt crimson mist` stopped with "you need a log raft… no known place to get one". The search for where to get an item only counted places reachable with the keys you carry. Now, if nothing is in reach, it looks again through doors you can pick or bash, the same as a Go to, and finds the boatman at the Pier.
- **No cash for it? The bank first.** If buying an item keeps failing, MudPilot goes to the nearest bank (the Bank of Godfrey, next to the Pier), withdraws plenty, then plans the trip again so it buys the item on the way. Shops mark prices up, so the raft is 3 gold in MME but 15 at the boatman. Before, it stopped with "couldn't buy the log raft (enough cash?)".

## 0.8.149
- **After a hunt, the way back to the loop gets through locked doors too.** Evolution reached the guardian golem's room (behind doors he picks), found it wasn't up, and stopped with "lost and no route back to the path". The loop's own way back couldn't get through the locked doors. Now he takes a Go to back to the loop's start, picking the doors, and starts the loop when he arrives, the same as Rego.

## 0.8.148
- **Hunts get through locked doors.** `@hunt` and Hunt now plan the way the same as a Go to does: through doors you can pick or bash, and with keys fetched on the way. `@hunt guardian golem` said "no route" because the golem (1/1797) is behind the green metal and large iron key doors. Evolution picks them.

## 0.8.147
- **A leader back from a restart waits for members who aren't in yet.** If the invite on logging back in finds nobody ("You don't see buddy here"), the loop waits for that member the same way it waits for one who dropped (up to the Party tab's wait minutes). When they enter the Realm, the leader asks where they are, goes to get them and invites them. Before, Evolution got back from an update ahead of Buddy, invited him once, walked his loop, and left Buddy behind.
- **Hunt now.** On the Bosses tab, pick a boss and click **Hunt now**, or telepath `@hunt <boss>` (for example `/Evolution @hunt crimson mist`). It goes for the boss straight away, without waiting for its respawn clock. A boss that can be in several lairs (the crimson mist has 16 round the Ancient Ruin) gets the full sweep: nearest lair next, fighting it wherever it turns up. Afterwards it goes back to its loop, or to the room it started from. A long walk to the first lair counts towards the time before the hunt gives up. If the boss isn't in any lair, it looks again one respawn later (7 hours for the mist), and keeps doing that, from the loop, until it catches the boss. From then on the boss's own respawn clock takes over. This also applies to a boss you'd ticked Hunt on that wasn't there when it was due.
- **A boss's drops get picked up, chests left.** After a boss dies where you are (on a hunt, on a loop, or Alt+R'd in), MudPilot looks at the floor and picks up the items on that boss's drop list (MME's list plus what it has seen it drop). Chests are left behind because they're heavy, and so is anything else lying there. The "after a kill send" box still sends whatever you put in it, so clear it if it says `get all`.
- **Adding the crimson mist adds the right one.** MME has two crimson mists: the 300k boss with a 7-hour regen and an 11k one with none. Track and `@hunt` now take the one with the respawn time and don't ask for minutes for the other.
- **The Bosses tab fits any window.** On a short or narrow screen (Revolution's), the buttons and the Track box were pushed out of sight. The buttons now wrap onto more lines, they and the Track box stay at the bottom, the boss list takes whatever height is left, and the long settings lines are shorter (hover a checkbox for the full explanation).

## 0.8.146
- **No more 300-room detours round one lair.** A Go to still walks round a lair that would maul you, but only when the way round is at most twice as long and no more than 30 rooms extra. Buddy's Go to from Eastern Road to the Frozen Cavern is back to 28 rooms (it planned 338), and his Pier trip is 157 rooms (it planned 261).
- **A lair's danger is measured on your own HP.** It used to be the weakest member's, against the damage *you* take, so Buddy's worst visit to the Dirt Path acid beasts (17/4) flagged it against Evolution's HP. A healer in the party now counts against the damage you've actually taken there, too. With Revolution along, the Dirt Path isn't flagged; Buddy alone still would be.
- **A Go to no longer "arrives" on a chat line.** When it asked the board where it was (`pro`), any line with a room number counted as the answer, including the echo of its own telepath. Evolution's "/Buddy {walking to Dragon's Teeth Hills (2/873)}" made him think he'd arrived, and he stopped 134 rooms short without saying why. Says, telepaths, gossips and your own sent lines are now ignored.
- **Party members' stats are remembered.** Each MudPilot keeps the last level, HP, AC and damage each teammate sent, across restarts, and uses them until a newer update arrives. A teammate who restarts and says hi gets your stats again. Before, a restarted member forgot the party and judged every fight as if it were alone.

## 0.8.145
- **Meditating stops at your mana target.** It no longer also waits for HP to reach rest-until (meditating barely heals), unless HP is under your rest-below line.
- **Below your mana rest %, it rests where it is.** The "don't rest in a lair, walk up to 3 rooms on" rule no longer walks you into the next fight short of mana.
- **Rafts for a member who's too heavy.** If the hand-over comes back "Evolution cannot accept your offer", the leader asks them to `@makeroom log raft` and gives it again (up to 2 more tries, then stops and tells you). `@makeroom` buys 0 at the shop first, which swaps coins for bigger ones; only if that isn't enough does it drop copper, then silver, then gold. It never drops platinum or runic coins.
- **The Stop button says "Stopped" when he isn't going anywhere.** It reads Stop only while he's walking, and Rego when there's something to resume.
- **Reads max mana when it's marked with a `*`.** The stat sheet shows `Mana: * 336/346` when gear changes your max. MudPilot couldn't read that, so after Miserable PVE died and came back without his mana gear it still thought his max was 579 and rested forever before a Go to.
- **No more swarm when you have a multi spell set.** With chaos storm as the multi spell, it's the only area spell the automatic picks use: the normal pick, the "magical, can't hurt it" fallback and the "nothing hurts it, cast something to join in" cast. Low mana was what kept tipping Evolution onto swarm.
- **Switches back to the big spell when mana returns.** Out of mana it falls back to magic missile, and the game repeats that every round. Before, MudPilot let it keep repeating even after the mana was back, and that killed Miserable PVE on the crabs. Now it switches to the spell it wants once that does at least twice the damage.

- **@comeback without a room works.** MegaMUD sends it bare, so MudPilot now asks @where. If there's no answer, it walks back along its own trail, room by room, until it sees them. A bare `/Name @comeback` you type yourself has your room added, so a MudPilot leader knows straight away.
- **@comeback and @summon invite when they get there**, if the one who called isn't still in the party.
- **A follower whose leader logged off first still rejoins that leader after a restart.** In the 0.8.144 rollout, Evolution closed a few seconds before Buddy, so Buddy came back thinking he had no leader and was left behind.
- **Boss hunt sweeps roaming bosses.** A boss that can spawn in more than one lair (the crimson mist, any of 16 round the Ancient Ruin) is hunted by checking all of its lairs: where it was last killed first, then nearest next. MudPilot takes a quick look in each and fights it wherever it shows. It only gives up for that spawn after the whole round. Bosses with a single room work as before.
- **Nuke stays off; Combat and Heal come back on.** Arriving at a Go to used to switch Nuke back on along with Combat, Rest and Heal, so Evolution's Nuke came back after every Go to. Now Nuke is never switched on by itself. Combat, Heal and Rest still come on when a Go to arrives, and now also whenever a loop starts, even if you had them off on the way there.
- **Best spots doesn't bog MudPilot down.** The search (and Best case) runs at low priority and takes short pauses, so the game, the walk and the window keep getting their turn. Opening Best spots again within 30 minutes, with the same party, shows the last search straight away; "Search again" refreshes it.
- **Magical monsters: your multi spell first.** When single-target spells can't hit a monster and your multi spell can, it's used (chaos storm) rather than whatever rates highest (swarm).

## 0.8.144

- **Curses and boss spells stay out of normal fights.** Spells that sit on a monster for rounds (acid rain, burning aura) are curses, so MudPilot no longer picks them as attacks; Evolution had been casting acid rain on blood skeletons and missing the kills. Acid tempest is only picked when a boss is in the room. If you set one of these as your own spell for a monster, MudPilot still casts it.

## 0.8.143

- **Goto: your last 5 at the top.** The Goto window opens with a "Recent" folder: the last five places you went to (from Goto or the map) and loops you ran, newest first.
- **Rego with Hands off on now goes.** Buddy had Hands off switched on during the wheel trap, so Rego started the walk but nothing could go out and he stood there. Clicking Rego now switches Hands off off and says so in the log. A walk started any other way while Hands off is on says on the bottom bar that nothing will move until you switch it off.

## 0.8.142

- **The party searches too, and up to 20 tries.** Buddy (a half-ogre) searched for 10/275's hidden exit north 8 times, found nothing, and walked all the way back round through the Blackwood Forest, though the exit is there. Now, after 3 misses, the party's MudPilots in the room are asked to search with him (`@do search north` ×4 each, again every 20 s). MudPilot looks every few seconds, and as soon as anyone has found it, he walks through. He keeps searching himself up to **20** times (was 8).
- **Only then does it go round, and say why.** If the whole party has searched and nobody found it, the exit counts as a wall for 24 hours, saved to disk, so the next Go to doesn't climb up to it again. Searching alone, it's only avoided for 30 minutes as before. The bottom bar shows "Went round: searched north 20 times and found nothing…" in orange while it walks the long way.
- **@wait says why.** A follower's MudPilot now sends `@wait (confused)`, `@wait (meditating)`, `@wait (blind)` and so on, and says it again every minute while the reason lasts. The leader keeps the reason and shows it on the bottom bar, in `@status` and in the rest reason ("Revolution @wait: confused"). A bare `@wait` from MegaMUD shows "no reason given" with that member's HP and mana from `par`.
- **Letting go of a stuck @wait.** Typing `@ok` in any form on the leader (`.@ok`, `.@do .@ok`, `.@party .@ok`, `/name @ok`) lets every @wait go. Followers now do `@do .@ok` and `@party .@ok`; `@ok` is the one @command an @do may pass on, and any party member may ask for it. A @wait that isn't said again within 2 minutes (was 5) is dropped. A real one comes back within a minute, so nothing is lost. A topped-up HP bar no longer ends a "confused" or "blind" wait.
- **A locked door that's the only way: bash it.** Buddy went to the Darkwood tree house (1/2305). The door west of 1/2304 (`[6 picklocks/strength]`) was locked. His strength hadn't been read yet, so he counted himself too weak and sent `open west` about 20 times while waiting for Revolution and Evolution to bash it. They were never asked. Then he "went round" into a false "MME's map has no way into that area". Now unknown strength isn't "too weak", and he bashes it himself unless a stronger MudPilot was actually asked. When the door is the only way there, it isn't skipped; he keeps bashing (up to 40 more tries) instead of stopping.
- **Doors nobody can bash.** At the prismatic dragon's door (3/592 down, `[201 picklocks/strength]`), MudPilot no longer asks party members to bash a door their strength can't open. If your own strength isn't known yet it sends `st` first, and it doesn't bash a door that's beyond you and the whole party.

## 0.8.141

- **Someone clearing the loop just ahead: catch them up, never wait for them.** When two lairs in a few minutes are empty and the same other player was just in them, MudPilot used to stop and rest for up to 4 minutes to let them come round, then go on ahead of them. Evolution did that for Plusone on the Overgrown Trail: Plusone never came round, and that lap took 5.8 minutes at 163k/hr. Now it always keeps going and skips refill waits until it has caught them up (up to the same 240 s), then shares their rooms. On a small loop that's a lap or two, and with your area spell taking most of each room, they're left with a quarter of the exp. The option is the same checkbox (Paths → lair pacing, "Someone clearing the lairs just ahead of me"), so no setting changed; only what it does.

## 0.8.140

- **Walking, `par` waits for a fight.** A `par` sent just before a move held the next room back: Evolution's moves took 1.87 s with one and 1.74 s without, on 43% of steps. That was the whole difference from MegaMUD's step time (1.82 s against 1.75 s, about 12k exp/hr for the Overgrown Trail party). Nobody gets hurt between fights, so while walking with a party MudPilot now checks `par` once combat is engaged, then every 5 s (your setting) during a long fight. Out of combat it only sends one a minute, to catch poison and the like. Standing still, resting or waiting, it checks every 5 s as before. No setting changed.
- **A restart can't pick up an old Go to.** Starting any walk now drops a reconnect plan left over from an earlier relog. Evolution came back from a restart and sent the party to 8/493, then on a key errand through the Dark-elf Prison, instead of carrying on with the loop it had been started on.

## 0.8.139

- **Coming back in after a low-HP hang-up doesn't hang up again.** Reconnecting, the hang-up check judged the HP it still had from before the hang-up (full), armed itself, and the first real prompt (38/208) hung up straight away — Evolution, back in an empty room and taking no damage, hung up again in a second. Now nothing's decided until the first HP prompt after logging in: back in under the line, it stays (and re-arms once HP is back over it); falling another 10% still hangs up.
- **The spell tuner stops costing kills.** It tries a party caster on a weaker spell to save mana, then judges it — after 6 kills of that monster, however long that took. Revolution's trial on blood skeletons ran 28 minutes with kills at 3.5 s against 1.3 s. Now a trial that's clearly slower after 2 kills is called off there; a weaker spell is kept only if kills are within 15% (+0.3 s, was +1 s — at 1.3 s kills that let 2.5 s through); and one that lost isn't tried again for 6 hours (was 30 minutes).

## 0.8.138

- **Leading, the party walks as fast as MegaMUD's.** Every time our own followers walked in behind us ("Buddy walks into the room…"), MudPilot looked at the room again and waited for it before the next step — about a third of a second, every step. Evolution leading the Overgrown Trail on MudPilot took 2.2 s a step against MegaMUD's 1.75 s: 698 rooms an hour against 1,177, and 284k/hr against 426k for the party. Party members arriving no longer cause a look; monsters and other players still do.

- **No more attack-spell loop.** Re-sending an attack spell (attack last re-attacks when someone joins the fight) makes the game print *Combat Off* then *Combat Engaged*. MudPilot took that *Combat Off* for the end of the fight and sent the spell again — which toggled it again: Evolution sent `swar` 5 times for one bat. A *Combat Off* right after our own attack went out is now just the toggle; the fight carries on.
- **No casting into an empty room after a kill.** Right after something dies the monster list is from before the kill; MudPilot cast the area spell off it ("Your spell has no effect in this room!", 192 times in one of Evolution's runs). It now waits for the room to be shown again first.

- **Disband means disband for a minute.** Breaking a party up so someone else can lead used to be a race against auto-invite: the old leader invited everyone straight back. Now, after a disband you meant (typed by you, or a friend's `@do disband`), that character sends no automatic invites for 60 seconds, so the party can re-form under someone else. That covers invite-if-seen, re-invite after a reconnect, and comeback and rejoin invites. Invites you type, and an `@invite` someone asks for, still go. MudPilot's own disbands (to join someone) don't start the pause. MegaMUD's `@do disband party` works for this, and so does the new **`@disband`**.
- **Send a path or loop to another MudPilot.** Paths tab → right-click a path → **Send to a party member…**. It goes by telepath (the game is the only link between your PCs): the name, start room, every step, and the commands on the way (search, dig, levers). It's split into short pieces numbered "2/5" and so on, each short enough not to wrap. The other MudPilot builds the loop only when the last piece is in, checks it against its own map, saves it in a "Shared" folder, and answers `{got loop 'name' - 42 steps}`. It's only taken from someone in their party or allowed to move them. The pieces are party-sync traffic, so they stay out of the conversation box.
- **Conversation box: your answers, not the chatter.** 0.8.137 showed every @command and bot answer, including the MudPilots' own traffic: spell-tuning reports every fight (`@mpsync sk …`), the handshake (`@mpsync hi/me`, `{mpsync ok}`), `@rego`, `@invite`, `{AFK}`. That's hidden again by default. What you ask always shows, along with the answers: `/revolution @exp` by telepath, and now `.@level` said to the room too, with everyone's "(to you)" answers. View → "@ commands / bot answers" still shows everything.

## 0.8.137

- **@ answers in the conversation box.** `@level`, `@exp`, `@status` and the rest, and the bots' `{answers}`, now show in the conversation box, so they don't scroll away on the game screen. This is on for existing profiles too. View → "@ commands / bot answers" turns it off.
- **Party sync keeps the leader up to date.** Each MudPilot tells its leader its strength, picklocks and Traps skill. It used to say so only once a session, before 'st' had been read, so the numbers could be blank. Now it says it again when they change or turn up.
- **Door help: pickers pick.** When the leader asks the party for help with a door, a member with the picklocks for it (but not the strength) is asked to pick it, not bash it.

## 0.8.136

- **Lair pacing is off.** Waiting for the next lair to refill was costing far more than it gained: Revolution PVE spent about 4½ hours of Oct 31 standing at sentry lairs that would have been full by the next lap. It's switched off in the code, whatever each profile's setting says, until we come back to it.
- **A party member is never "another scripter".** Right after a restart Miserable said "Letting Revolution come round" and waited for his own partner: the party list was empty for a moment, so Revolution counted as a stranger clearing the lairs ahead. Friends are skipped now: anyone in the party now or in the last half hour, MudPilot partners, and your friends and remote-control list.

## 0.8.135

- **In the fight even when you can't hurt it.** Blood skeletons are magical and have spell immunity 20, so nothing Evolution has (swarm is level 12) can damage them. Now:
  - If a spell would hurt the monster but you lack the mana, MudPilot casts it anyway.
  - If nothing would hurt it and you're in a party, it casts a spell anyway so you're in the fight and get your share of the kill: the spell you set to 0 mana first, then an area spell, then the cheapest. Alone, it doesn't waste the round.
  - Your own mana cost (Game Data → Spells) no longer gets lost when the game's spell list names the real cost.
- **Draw a loop on the map with the number pad.** On the Map window, click a room (or start from yours), click ● Record Loop (or Record Path), and walk a pen round the map with the number pad: 8 n, 2 s, 4 w, 6 e, 7/9/1/3 the diagonals, 0 up, . down, Backspace undoes. Nothing is sent to the game, so there's no waiting for fights or rests. Come back to the start and click ■ Stop / Save to name it, and it's a loop like any other.
- **The number pad walks from any MudPilot window** (not just the main one), except while you're typing in a box.

## 0.8.134

- **No more lost rounds after a bless.** A bless cast mid-fight (skin, star…) stops the attack spell the game was repeating, but MudPilot thought it was still going. Evolution stood there being hit, "No attack of ours for 8–15 s while being hit", 188 times in one day. The attack now goes straight back in after the bless, as it already does after a heal.
- **Lair pacing uses your real lap time.** The sentries fix judged a lap at about 5 s a room. Evolution's real laps took 0.8–1.5 min with the fights, so he still stopped at every sentry lair, and his rate fell from 332k/hr to 163k/hr. Pacing now goes by how long your recent laps actually took.
- **@goto by name, no room numbers.** `@goto bank of godfrey`, `@goto tree house`: the Goto list's names (your Rooms.md places, path ends, MME's shops and NPCs) are checked first, then room names and monsters as before. One place goes there, and the same name in several rooms goes to the nearest. Several different places get a reply listing them so you can say which. The Goto window still shows the numbers.
- **Alignment gates know your alignment.** Buddy (Good) got "No walkable route — blocked by the Temple Foyer (Alignment: Saint to Seedy)". MudPilot learns alignments from `who`, but it skipped your own line, so it never knew yours and every alignment gate looked shut. It now reads your own line (a blank one is Neutral). When a route is blocked only by an alignment gate and your alignment isn't known, it sends `who` and tries the route again.
- **The dragon key, made automatically.** The Iceforge needs a dragon key, and it isn't a quest item: you put a white, black, green, blue and red fang in the slot at the Unholy Temple (3/606) with the room clear. MudPilot now reads recipes like this from MME. When a walk needs the key it:
  1. Asks the party for the key, then for each fang. Anyone who has one hands it over.
  2. Farms the rest by looping the dragon serpent lairs and the prismatic dragon's room (3/560, 586, 588, 591, 593, 594, 595), fighting everything and picking the fangs up.
  3. Clears the Unholy Temple, puts the fangs in the slot in order, and takes the key.
  4. Carries on to where you were going.
  If the key turns up along the way, the farming stops. After 45 minutes without a fang, it stops and says so.
- **The bottom bar says why it isn't going.** When MudPilot won't do what you asked ("Not walking … you need a dragon key"), the full reason now shows in orange on the bottom bar until you ask for something else. Before, it was cut off after 26 characters.
- **A key nobody knows where to get: ask the party first.** Buddy's Go to the Iceforge stopped at "can't fetch dragon key automatically", because MME lists nowhere to get one, without asking anyone. Now MudPilot asks the party with @have. Whoever has one is asked to hand it over and the walk carries on. If nobody has one, it stops and says so.
- **"Waiting for Evolution" doesn't linger.** The status bar kept showing the leader's old wait for a member to rest up long after the walk had stopped. Stopping clears it, and it only shows while walking.
- **@status says what it's waiting for.** Buddy sat waiting for Evolution to rest up, and @status didn't say so. It now names the wait: a member resting up (with their HP and mana), someone joining, a lair refilling, another scripter, a door, or a trap being disarmed.
- **Whose party window is it?** Several MudPilots' party windows can be open on one screen, and Miserable's sat over Buddy's looking like Buddy's party. The window's title and footer now name the character ("Party (Buddy)", "Buddy's party · 3 in party").
- **The party's trap-disarmer does the traps.** Each MudPilot now reads its Traps skill from 'st' and shares it over party sync. At a trapped exit, if a party member standing in the room is better at traps than the leader, the leader sends them "@do disarm trap <dir>". They disarm it and report back ("{trap north disarmed}" or "not disarmed"), and the leader waits for that before walking on. A failure gets another try, then the party goes through, the same rule as disarming it yourself. MME doesn't list how hard each trap is, so "better" means the higher Traps skill.
- **@have checks the pack first when it may have changed.** Buddy gave Revolution a log raft, asked "@have log raft", and got "no": Revolution answered from the inventory he'd read before the raft arrived. So Buddy bought and handed out another, twice for each of them. Now, if anything has come or gone since the last inventory look (handed over, picked up, bought, given, dropped), MudPilot reads it again before answering.
- **@have answers the same everywhere.** Evolution said "{yes: 2}" where Revolution said "{yes: 2 log raft}", because his inventory listing had wrapped between "2" and "log raft". Wrapped lines are joined now, so both say "yes: 2 log raft".
- **Room search on the map window, labelled.** The pop-up map's search box was marked only with a 🔍 icon. It's now labelled "Find room". Type "17 1626", "17/1626", a room name, a place or a monster and press Enter: the map shows the room without walking. Double-click it (or the Go to button) to walk there.
- **Never walks into a closed gate or door.** Buddy's Go to the Tree House went through the Slum Street Rusted Gate (1/1169 east), which nobody can pick or bash, and sent "e" into "The gate is closed!" about 80 times. Doors that nothing opens now cost 60 steps in planning, so routes go round them when there's any other way (the Great Pyramid's timed doors still work). And MudPilot never walks into a door shown closed until the game says it opened: it tries "open" (or pick or bash), and after about 2 minutes it goes round or stops and says why.
- **Game Data → Spells: click a spell to see what it does.** Level, mana, what it targets, damage or strength at your level, how long it lasts, what resists it, its effects, and where it's learned.
- **Your own mana cost per spell.** Select a spell and click "Set mana cost…" (or double-click it). Power-levelling: set a little character's spell to 0 and it casts anyway, so it engages and earns its share even though the spell never goes off. "MME's cost" puts it back, and a * in the Mana column marks your own costs.

## 0.8.133

- **Friendly fire: no more false hang-ups.** 0.8.131 and 0.8.132 hung Miserable, Revolution and Buddy up on each other. Every case was a false alarm: a party member's area spell ("moves to attack everyone in the room") or a heal ("Revolution casts greater mend on you, healing 26 damage!" — the word "damage" is in a heal). From a party member, only "moves to attack you" or a hit on you "for N damage" that isn't a heal counts now. A stranger healing or curing you no longer counts as an attack either. Checked against every line of tonight's traces (about 218,000): no false hang-ups.

## 0.8.132

- **Fix: a party member's area spell isn't friendly fire.** 0.8.131 hung up on "Revolution moves to attack everyone in the room.", which is his area spell and never hits the party. Miserable and Revolution hung each other up. Only an attack aimed at you counts now.
- **Someone else scripting your loop.** Sharing rooms with them is fine, since your area spell takes most of each room. What costs you is trailing them into lairs they cleared a moment ago. MudPilot now notes where other players are seen. When a lair that should be full is empty and one of them was just in it, twice within 5 minutes while you lead a loop:
  - **Just ahead** (they were there under a minute ago): no lair-pacing stops until you catch up and share their rooms.
  - **Further ahead:** rest until they come round to you (up to 4 min, Settings → Health → Lairs), then carry on ahead of them.
  Nothing changes when they're behind you or in the room with you, and party members never count.
- **Reset session stats, where you can see it.** The Session statistics window's reset button was at the very bottom, under a list that fills the window, so it was easy to miss. It's now first on a bar at the top ("Reset session stats", with Exp chart and Rest log). It resets everything the window shows, and so does @reset.

## 0.8.131

- **Auto-get in Game Data → Items, like MegaMUD.** Select items (Ctrl/Shift for several) and click Auto-get, Auto-get up to… (pick up until you have N), Never get, or Normal. Double-click toggles auto-get. A Get column shows each item's setting, and typing "auto" in Find lists the items you auto-get. It's the same list as Settings → Loot → Item rules. Right-clicking an item on the game screen also offers "Always pick up …".
- **Full means full.** At 100% encumbrance (Evolution: 3024/3024) MudPilot kept trying every pile of gold ("picked up 0 gold crown"). It now leaves coins alone until there's room again.
- **Pick the lock first.** If your picklocks cover what a door needs (e.g. "[41 picklocks/strength]" and you have 60), MudPilot picks it first: before using a key and before bashing. Miserable PVE bashed doors it could pick, even with Pick locks ticked.
- Right-clicking a player on the game screen can now mark them **Friend**.
- **Friendly fire hangs up, and nothing else changes.** If someone in your party attacks you, MudPilot hangs up, like any other PvP hit (NoHang still overrides it). They stay a friend and keep their @ permissions: in a party it's nearly always an accident.
- **Friend in Game Data means friend.** A player marked Friend in Game Data → Players is never a PvP target, whatever they were before.

## 0.8.130

- **Never attacks its own party leader.** When Evolution reconnected, the party reshuffled and for a moment Revolution wasn't on Buddy's party list. "Revolution casts greater healing on Evolution!" was then read as Revolution attacking Evolution, and Buddy went after Revolution ("PvP: attacking Revolution"). Now a cast only counts as an attack when it does damage, and MudPilot never picks a PvP fight with a friend: anyone in the party now or in the last half hour, your leader, a MudPilot partner, or anyone on your PvP friends or remote-control list. A target that turns out to be a friend is dropped.

## 0.8.129

- **Attack last answers everyone.** Re-attacks were spaced 1.5 s apart, so when Evolution joined a second after Buddy, Revolution never answered him and wasn't the last to attack for about half the kills. Now every member who joins gets an answer straight away — but at most 5 re-attacks in any one round, so two characters that both have attack last on can't keep answering each other. And the *Combat Off* / *Combat Engaged* a re-attack shows is no longer taken as the fight ending (it was clearing who had already been answered).
- **No lair pacing where you lap faster than the regen.** In the dark-elf sentries (about a 30 s regen, 10 rooms at about a round each) every lair is full again by the next lap, but MudPilot kept stopping because the next lair "refills in 7 s". It now paces only when a lap is shorter than the lair's regen.
- **Lair pacing back as it was.** 0.8.128 only paced when you were below your rest settings; that walks you into a lair before it has refilled, and its spawn is lost for the lap. Waiting is time you spend anyway, so it meditates through it again (unless you're full).

## 0.8.128

- **Attack last means attack, then attack again.** Revolution: "it's waiting for others to attack first — I want it to attack immediately, then attack again if someone attacks after me." Attack last no longer holds the attack back: it attacks at once, and when a party member joins the fight after it ("Evolution moves to attack …"), it sends its attack again — once per member per fight — so it's the last to attack and the monster stays on it. (The "wait up to" setting is gone.)
- **No meditating for a lair when you're nearly full.** Waiting for the next lair to refill sat Revolution down to meditate at 93% mana. Lair pacing now only stops you when you're below your rest settings anyway (Rest below HP % / MA %); otherwise it walks on.

## 0.8.127

- **No more invite and @where spam.** Waiting to rejoin its leader (after a restart or the leader coming back), a follower asked '@invite' every 15 s even when the leader was a map away — Buddy, dead in the temple, asked Revolution over and over and got "not inviting yet: you're not in my room" each time, plus an @where every minute. Now it asks for an invite only when the leader is in its room (straight away, then at most every 30 s), and asks @where at most every 3 minutes — and not at all while it can't walk to them (dead, or Hands off).

## 0.8.126

- **A power cut can't lose your login any more.** `app.json` (which profile to open) was rewritten on every settings save, straight onto the disk; a power cut on Revolution's PC left it as 25 zero bytes, MudPilot opened a blank Default profile — no login, no password, no realm or MajorMUD answers. Now it's only written when the profile changes, and like the profile itself it goes to a temp file, is flushed to the disk and swapped in — the old file or the new one, never nothing. And if it's ever unreadable, MudPilot opens the profile you saved most recently (with a login) instead of Default.

## 0.8.125

- **The Conversations box opens at a proper size.** It opened squeezed to a couple of lines over a huge map, every time: the split was set 0.3 s after start (while the window was still sizing itself) and saved on every close, restarts and minimised windows included — profiles had kept 14%. Now Conversations get 40% and the map 60% by default, the split is applied again while the window settles, it's only remembered when you drag it yourself, and it never opens below 30%. Saves under 30% move to 40% once.

## 0.8.124

- **A leader doesn't go looking for a member who's restarting.** A member that @stops the leader and logs off (a restart) comes back to the same room, so the leader stays put for them (up to 15 minutes, or until they follow again). The PVE leader used to set off to find Evolution; Buddy then logged back in where the party had been, walked alone through the dark elves to find it, and hung up on low HP.

## 0.8.123

- **A restart that can't connect keeps trying.** Opening by itself (a restart, auto-connect), a failed first connect showed a "Couldn't connect" box and stopped there — Buddy sat logged out after a restart. Now it's logged and retried every 60 s like a dropped line. Connecting by hand still shows the box.

## 0.8.122

- **A follower's restart doesn't strand the party in a lair room.** Restarting, a follower asked its leader to @stop first and then waited to be out of the (PvP) lair room — which the stopped party never left, so it stood there the full 6 minutes. Now it waits for the safe moment first, then asks the leader to @stop and closes 2 s later. And the PvP lair-room wait only applies while walking: standing still, it would never leave the room.
- **A called-off comeback trip doesn't replace the loop.** Stopped by a member's @stop, the leader set off to find them; when they came back the trip was called off — and Rego then carried on with that little trip instead of the loop (the party Miserable stood idle at 17/1630). Rego now carries on with what it had before the search.

## 0.8.121

- **The leader doesn't stand while the healer tops someone up.** Settings → Party "wait if members below HP %" was 80% and, once waiting, held until they were back to 90% — the healer's minor-heal line, which is there to heal on the move. Now it's **70% by default**, and the walk carries on as soon as they're back over that line ("…until they're back to HP %": 0 = the line). @wait always holds. Saves still on the old 80/90 move to 70/0; your own numbers stay.

## 0.8.120

- **No more invite circle.** In the Ancient Ruin, Revolution and Buddy each waited for the other to invite them: @invite both ways every 15 s, invites sent to Buddy from rooms away, and 18 disband/joins in one second. Now: @invite is answered only when they're in your room; someone asking you for an invite isn't your leader, so you stop waiting for theirs; "invite if seen" invites once as they show up, not every minute while they stand there; and "disband your own party first" gets one disband, not a burst.
- **Stop ends the chase.** After Buddy's @summon and a Stop, Revolution set off for Buddy again in the same second (the rejoin), and again a minute later. Your Stop now ends all of it: comeback, rejoin, and going after anyone. For a minute after, someone walking off isn't chased either.
- **Corpse gear goes back on, even the first time.** Revolution recovered his corpse and wore none of it for a couple of hours: MudPilot puts back what it remembers you wearing, and it hadn't seen him dressed since the update, so it remembered nothing. With nothing remembered, it now wears the armour that came out of the corpse (not weapons).
- **A party member who's strong enough bashes the door.** The chrome key door in the Ancient Ruin is bashable, but not on the leader's strength. MudPilots in the party now share their strength and picklocks; if someone in the party can bash or pick a door, the leader plans through it and asks them to bash it (only them), trying the door himself instead of bashing it for nothing. If they aren't in the room, it says so and waits for them.
- **Attack last, every fight.** The party opened on the first monster in a room, then Revolution opened every next one himself (their attack on the first one still counted). Each fight now waits for the party again, and "Buddy moves to attack …" counts as them starting.
- **Serenity (nity) stopped recasting every 15 s.** Its start line had been learned as "Dark Corridor" (a room name), so the effects list never showed it up. Bless start lines now come from the Messages file (like the end lines), and a room name is never learned as one. Mana-regen blesses are kept up all the time, not just when mana's low.
- **Sleep at the end of the round.** Sleep only lasts until the round goes, so cast early it does nothing. Spells listed under Settings → Attack spells → *Cast late in the round* (default `slep`) are held for the last 2 s of the round.
- **Conversation text size:** − and + buttons right above Find Next.
- **Bash harder, and together.** A bashable door gets up to 20 bashes before MudPilot gives up (it was 3 — the Dark Passageway's door down, 8/433, '41 strength', 'won't open' after three unlucky rolls). Old saves still on 3 move to 20; your own number stays. Leading, the party's MudPilots standing in the room are asked to bash it too (4 each, every 20 s) — Settings switch `party_bash_help`.
- **Planning a route doesn't stutter the window.** Go to plans in the background, but the planner hogged Python's lock — the window still caught up in jerks. It now steps aside every few milliseconds (worst window gap while planning: 42 ms → 20 ms).
- **Short freezes are recorded.** The window-freeze log now also catches 1–8 s stalls (once per 30 s, no message), so a 2-second hitch on Revolution's PC shows exactly what held it up.
- **The leader waits for everyone it invited.** "Buddy started to follow you." is the game saying they joined — that's what MudPilot goes by now (no 'par' needed). Until everyone invited has started to follow, the walk waits ("Waiting for Buddy to join", up to 40 s, @join resent as before) — a member who lagged out isn't left behind. And no @join is sent to someone already following.
- **Reconnect every 60 s, for as long as MudPilot is open.** After a dropped line (an internet outage, a board restart) MudPilot used to retry after 20 s, then 40, 80, 160, and every 5 minutes after that — when Dan's internet came back after 20 minutes, the PVE characters sat out another few minutes waiting for the next try. Now it's every 60 s, no back-off, until you close it; it logs straight in and carries on with the loop as before. Old saves still on the 20 s default move to 60 (`reconnect_delay`).
- **Joining a party stops your own walk.** Buddy joined Revolution's party with a Go to still running and ran off on it. "You are now following …" now stops any Go to or loop of your own, and while you're following someone, Rego (yours or their @rego) won't start a trip or old loop of your own — the leader walks.

## 0.8.119

- **@join just joins.** No "{joining Revolution}" telepath back — it joins and checks the party (`par`).
- **A follower stops when it finds its leader.** Buddy walked into Revolution on the way to where Revolution had said he was, got the invite — and walked on past him. Walking to someone and they're right here: stop.
- **The leader checks the party when someone joins** — a `par`, and the walk waits a moment for it, before running off.
- **Followers don't start a party of their own after a restart.** Buddy came back and invited Revolution (its leader) — which made Buddy a party leader, so every 'join Revolution' got "You must disband your own party first!" and the two kept inviting each other. A follower's restart now gathers nobody, MudPilot never invites the leader it follows, and "disband your own party first" after a join → disband, then join.

## 0.8.118

- **@party go hole takes the whole party through.** Revolution said '@party go hole' and went; Buddy and Evolution stood still (a follower's @party only sent 'par'), the party broke, they sent '@comeback 2/1306' and Revolution walked back down for them. Now a follower does the command its leader @party's (never an @command — same rule as @do), and for 20 s after, the party breaking is expected: nobody sends or acts on @comeback. On the other side they ask to be invited back and rejoin.
- **Item blesses swap the weapon.** Buddy's corrosion bless sends 'use longsword' — with the longbow out: "You do not have shimmering longsword equipped." It now equips the longsword, uses it, and puts the longbow back (as '#sl' does).
- **A dry way when the party has no raft.** Rafts are heavy and the followers usually don't carry one: with a party, a Go to goes round the water — up to about twice as far — instead of across it, even if you have a raft yourself.
- **PvP: a restart doesn't log you out in a lair room.** It waits (up to 6 min) till the walk is out of a regen room.

- **A follower doesn't walk off on its own after a restart.** Miserable came back while Revolution lay dead in the temple, couldn't get to him (the temple's alignment gate), and went off looping the Glades solo. What a follower was walking now waits until it's back in its leader's party; never back in → it stays put and Rego carries on when you say.
- **After a death MudPilot never walks by itself.** No rejoin, comeback, errand, Rego or resuming a loop — back to the gear naked and solo it just dies again. It stays put ("Died — waiting for you"), even through a restart, until someone starts a walk: you (Go to, Loop, Rego in the window) or a friend's @goto / @summon / @comeback / @loop / @rego.
- **Corpse recovered → the floor too.** On PvP some of your things land outside the corpse every time; nearly everything on the floor of the corpse room is yours. After "You have recovered the corpse of …" MudPilot looks, picks up everything on the floor except copper farthings and silver nobles, then reads the pack and puts your gear back on.
- **@do never passes an @command on.** `@do /Buddy @goto …`, `@do say @rego`, `@do .@stop` and the like are refused (as MegaMUD does): otherwise anyone a friend trusts — an enemy you happen to share a friend with — could steer everyone who trusts that friend. Ordinary @do (go portal, eq, use, tel …) works as before.
- **Room numbers with a space:** `@goto 17 1626` and `@comeback 17 1626` (also `17,1626`, `map 17 room 1626`, and `17/1626` as before).
- **@death** — the last 3 deaths, from the 'Recent Deaths' rows at the bottom of `pro`: when, what killed it, and where ("10/20/2026 6:20 AM grimhound at Swamp of Tharollok, Small Path (13/2925) | …").

## 0.8.117

- **Go to the dark-elf prison with a low-level party.** Revolution with Buddy (15) and Evolution (20): "the only way is through the Negative Power Plane — members of the party aren't big enough". Not true — there's a way on their level through the Black Steel Gate (the gate key, or a bash), but the 'too small' check ran before the way with keys was tried. Now the way with keys comes first; 'too small' only when there really is no way on the party's level.

## 0.8.116

- **Spell efficiency doesn't wander down to the weakest spell.** On purple worms Revolution (set to let MudPilot decide) went soul rip → soulstrike → divine fury → god's wrath → holy force → godstrike, each 'barely slower' than the one before. Now a weaker spell is kept only if kills stay within 15% of the strongest spell's, and never more than two spells below it.
- **Attack last waits in every room.** Walking from one worm room into the next, the last room's fight still counted — Revolution opened the new fight himself. Each room now has its own wait for the party.

- **A follower back with its leader has nothing left over to Rego.** After a restart Buddy and Evolution walked to Revolution, rejoined — and still showed "Stopped — Rego carries on to 1/2342": an @rego would have sent them back to where Revolution had been. Cleared once they're back in the party.

## 0.8.115

- **Spells that can actually hurt a magical monster.** The prismatic dragon is "Magical 2" in MME: only single-target spells of level 20+ (10 × its magic) hurt it, area spells always do. Evolution cast vine strike and stonestrike at the serpents and never touched the dragon, with blaze (level 20) in his book. Now every spell choice skips spells that can't hurt the target — the scripted spell, your spell for that monster, the opener, the automatic pick — and when none of yours can, MudPilot casts the best one you know that can (area spells included) and says so in the log.
- **Biggest threat first.** In the dragon's arena every serpent died before the dragon. With more than one monster, MudPilot now attacks the one worth the most exp first (Settings → Party → Priority → "Biggest threat first", on by default; "Attack which monster" counts from it).

## 0.8.114

- **Route planning is about 100× faster, and remembered.** Go to Witch's Cave from the Blue Tower took minutes on Revolution's PC (the window stuck at the boatman and right after logging in): finding where to get a log raft planned a separate route to every shop and lair room that has one (391 searches), and the danger check asked the party for everyone's HP for every exit looked at (8 million times). Now two searches cover every candidate, the danger check works its key out once every 2 s, and a route is remembered for 10 minutes — the same Go to again takes 0.03 s instead of 1.6 s. Forgotten when the map or you change (a learned way, a wall, a door that wouldn't open, quest flags).
- **Still fights, heals and runs while it plans.** Only walking and new Go tos wait for "Calculating route — one moment please…" (Dan: locking up like that in PvP is dangerous).
- **'go hole' in the wrong room — fixed.** Five Dragon's Teeth Hills rooms look exactly like 2/487, where the hole is; a walk that drifted onto one (2/193) typed 'go hole' over and over ("Your command had no effect."). Now: before a room's own command (go hole, go path…) in a room that looks like others, MudPilot checks the room number with `pro` first; and "Your command had no effect." right after a path's step means "not where the path thinks" — it checks where it is and plans from there. Walked through the hole on the practice server from five rooms, including the drifted case.
- **A stopped Go to survives a restart, and @rego carries on with it.** Revolution was stopped on the way to the Bank of Godfrey by a follower's @stop, restarted, and sat 'Idle' — nothing to Rego, @rego found 'nothing to resume'. The stopped Go to is kept, Rego / @rego carries on to it, and the status says why it's parked: "Stopped (Buddy's @stop) — Rego carries on to 1/297" (and @status says it too).
- **A restart during a rejoin carries it on** (a follower still on its way back to its leader).
- **The leader never walks off without a lost member.** Evolution dropped out of the party; Revolution went where Evolution said he was, didn't find him, and 20 s later carried on to the Bank of Godfrey without him. Now: invited and still not back → ask `@where` again (3 times), then stop and wait ("Stopped: lost Evolution… Rego carries on without them").
- **@where and @comeback send the right room number.** Evolution said 8/847 from 8/16 — a look-alike Hilltop Fortress courtyard. In a room that looks like others, a member checks the board's room number (`pro`) before answering `@where` or asking its leader to `@comeback`.

## 0.8.113

- **A follower back from a restart walks to its leader before asking to rejoin.** 'invite' only works in the same room — Buddy and Evolution logged back in at 8/899 with Revolution at 8/16 and asked for an @invite 22 times ("You don't see buddy here."). Now: leader not in the room → `@where`, walk there, then `@invite` and `@rego`.

## 0.8.112

- **Random drops: the Warped Asylum and the Caves of Chaos.** Exits that drop you in a random room of a range — the asylum (anywhere in 9/1183–1206, the cells' corridors into a random north cell), the uninvited Ancient Darkwood portal at quest stage 4 (anywhere in the Caves of Chaos) — can now be routed through when there's no other way. The walk takes the drop, finds out where it landed and plans on; in the asylum that's Dan's "n, s, n, s… until we see the old man" (5 drops on the practice server). Landing somewhere else in the range isn't counted as being knocked off the path. Every other route is planned exactly as before.
- **Phoenix feather quest simulation** (`tests/sim_phoenix.py`): every leg planned for a party whose lowest member is level 15 — no vortex (they need level 20+), the old man and the shadow guard now reachable.

## 0.8.111

- **Party window: a green ✓ after everyone running MudPilot** (you, and anyone whose party sync has been heard).
- **Buttons and levers done once each, in the right room.** MME lists some steps twice (the scorpion temple's 'push onyx', the Graveyard's 'push button' from both sides) — doing one twice resets the sequence, so each step is done once, from the exit's own room when there's a choice: Go to the Mausoleum Entrance and the Temple Colonnade now get there. A door opened by a lever in another room (the Black Fortress gatehouse: the lever's in the hidden room to the south) gets the walk there and back, instead of pulling at nothing in the gatehouse.
- **A follower whose leader comes back asks to rejoin.** When the leader you follow drops and comes back into the realm, MudPilot telepaths `/Leader @invite` at once (every 15 s, up to 5 minutes), joins on their invite and then sends `@rego` — Buddy stood in Revolution's room for 8 minutes waiting to be invited.
- **Bash-only doors are walked through.** MME lists some doors with a key that doesn't exist ("Key: 1 [or 31 picklocks/strength]" — the Town Gates archway, 8/462 N): there's no key to fetch, so routes now go through and the door gets bashed or picked. `@goto bank of godfrey` from the Dark Corridor said "No walkable route".
- **`@status` says what's jamming it up.** Idle after a Go to that couldn't go → `idle - No walkable route from … blocked by …`, and `@goto` answers with the reason when the route fails after it's read your inventory.
- **Goto doesn't freeze the window any more.** The route is worked out in the background with "Calculating route — one moment please…" showing, instead of the window going white ("Not Responding") for up to 15 s. `@goto` from a party member plans the same way and answers when it's done.
- **Route questions go to whoever sent the @command.** A remote `@goto` whose way goes through an area you avoid asks the sender: "take Negative Power Plane? … reply y or n". They telepath back `y` or `n`; no answer in 90 s = no.
- **Goto finds monsters.** Type a monster's name ("sleazy shopkeeper") in Goto, in the Paths tab's Go to room, or in `@goto`, and it lists where it stands, spawns or lairs — pick one and go. Goto also lists MME's shops and NPCs built in, so it has rooms without MegaMUD's Rooms.md.
- **Hidden exits: keeps searching for low Intelligence.** After 3 searches find nothing, MudPilot looks to make sure it's in the right room and the exit is still hidden, then searches on (up to 8) — half-ogres and kang can need 4 or 5.
- **Settings opens again after adding an item bless.** Adding a bless from an item rebuilt the Settings window and left it broken: every click on Settings did nothing ("bad window path name"). It's built again when needed.
- **Goto Guardian Golem goes to the guardian golem.** 1/1797 is behind the green metal and large iron key doors; MudPilot decided it had "no way in" and went to 1/662 — another "Small Room" 1100 rooms away, through the sewers. A same-named stand-in room is now only used when nothing at all leads in, keys or not.
- **Combat isn't broken off a monster you're killing.** The "nothing to kill here — break combat" rule (for the pyramid's stone sphinx, 0 exp and 9999 HP) also fired on the floating key MudPilot was there to kill. It's only for what can't be killed now.
- **Stop/Rego on a key detour carries on to where you were going.** Goto the Pharoah needs the golden lion key, so MudPilot detours to 12/2005 for it; Stop and Rego on the way resumed only the detour — it got the key and stood there. Rego now goes on to the real destination (and fetches the key again if it's still needed).
- **The Log tab stays where you scrolled.** Scrolled up to read something, new lines no longer pull it to the bottom; a button shows how many came in and jumps down when you click it.
- **Stop stops resting too.** With nothing walking, Stop now means "stop resting": no auto rest (and no resting while waiting on the party) for 2 minutes, so you can take over — Buddy went on "Resting to full" through four Stops.
- **Timed lever gates: pull the levers, then run.** A gate opened by levers in other rooms (the mummy's crypt: levers in 1/1038 and 1/1044 open 1/1056 N) now gets each lever pulled in its own room, then a run to the gate — no stopping to fight or rest from the first lever until through. If it shut before we got there ("no exit in that direction"), back round the levers, up to 3 more times.

## 0.8.110

- **Your gear goes back on after you recover your corpse.** MudPilot remembers what you had on (saved, so it survives a restart) and after "You have recovered the corpse of …" puts back on everything of it that's in your pack — PVE recovered its corpse and walked on unarmoured, getting poisoned through the golden headdress that negates it. Logging in wearing 3+ pieces fewer than it remembers does the same; smaller differences (rest-gear swaps) are left alone.

## 0.8.109

- **A spell that has no effect isn't cast again.** "Your spell has no effect on surf elemental." → that spell is never cast at that monster again — the automatic pick, your choice for that monster, the opener and pre-attack spells all skip it. PVE died dtch'ing a surf elemental every round from 537 HP down.
- **No draining what can't be drained.** Drain heal (dtch) skips NonLiving monsters (elementals) as well as undead, and gives up on a monster when your HP keeps dropping across two drains.
- **Stopped for a restart, rego still works.** A leader that a follower `@stop`ped before its own restart, and then restarted itself, keeps the loop for `@rego` (party Miserable sat idle after Revolution's @rego).

## 0.8.108

- **Fight one by hand and MudPilot keeps out of it.** Type an attack or a spell at a monster (`dtch sc`, `a orc`) and that fight is yours: no attacks, re-engages or spell switches from MudPilot — it used to see *Combat Off* after each dtch and cast fork, so you took turns. `sc` is matched to the monster in the room (the game's "You reach out and touch large giant scorpion!" settles which). It hands back when the monster dies or leaves, or you do (MudPilot then fights what's next), or when combat's been off 2 rounds (~10 s) with nothing from you — a bless or `st` doesn't count, and one missed round is fine — or 4 rounds (~20 s) since your last attack; then MudPilot takes that monster over. Running away, hanging up, heals and cures still happen. A red **⚔ MANUAL: large giant scorpion (8 s)** shows on the toolbar with the time left; click it to hand back now. Settings → Combat: "Hands off a monster you attack…" (on).
- **Move the toolbar buttons.** Drag a toolbar button left or right to put it where you want; the order is saved with your character. Right-click the toolbar → Reset to default order.
- **Record Path / Record Loop (Map window).** Click one and walk it for real: every room change is a step (a move that fails isn't), door open/bash/unlock/pick commands go with the step through that door, and the route is drawn in red on the map as you go with ● REC and the step count. **Undo step** takes the last one off (walk back and carry on); **Stop / Save** asks for a name. A loop only saves once you're back where you started ("Not back at start" — keep recording, or throw it away). Saved like Path builder paths: Go to and the Loops list use it straight away, and it works in MegaMUD.
- **Paths and loops you make go in their area's folder.** Saving one (recorded, Path builder) puts it in the folder your other paths around its start room use — the treasure-digging loop by the Jungle Trail lagoon goes with Terra Fuego's loops, not into "MudPilot". Nothing around to go by → it asks which folder. Paths tab: right-click → **Move to area folder…** for one you've already got; the folder shows after each path's start room.
- **Map search: room numbers and Go to.** Just a room number (`345`) finds that room on your map first, then on the others; `12/345` and names as before. **Go to** next to the box walks to the room you found.
- **Click a room on the Map window** for a side panel: its name, number, area and exits, and every monster MME says can turn up there — its own lair list, the area's wandering groups, a boss's set room — with exp and HP; in your own room, what's standing there now. Click a monster for its MME sheet: HP, AC/DR, magic resistance, each attack (damage, how often, accuracy, what a hit casts), spells it casts, average damage a round, flags (undead, poison immunity, animal…), respawn time for set spawns, realm limit, drops with chances, your kills and what you've seen drop, and roughly how you'd do against it — with a button for the combat calculator. (MME has no level for monsters, or cash.)
- **Party "about me" goes once.** Each MudPilot tells a teammate its stats once a session (a level-up has its own short message) — no more telepath every time a bless moved AC.
- **"More ▾" on the Paths tab always shows** — in a narrow window the Go to / Loops / Paths buttons get squeezed instead (Revolution's showed only the arrow).
- **Pyramid level 3: no walking into doors.** On a "doors creak and thump" level, a door you can pick or bash is picked/bashed at once; only the [1000 picklocks] timer doors are waited for. PVE walked into 12/2046 E and 12/2031 W five times each (~10 s each) before picking them first try.
- **Pyramid floating key: also when a Go to ends there.** Standing in the key room without the golden lion key (a Go to that ended there, or you walked in) now melees the floating key and grabs the key — it used to stand next to it.
- **Scattered party members get picked up.** Leading a walk, a member who's still in the party but hasn't been with you for 30 s (and 3+ rooms) gets an @where, and MudPilot walks to them — no re-invite needed — then carries on with the trip. For the Caves of Chaos on the phoenix feather quest: everyone's found before heading on to Morukai. Settings: `party_missing_secs` (30; 0 = off).
- **No more both-sitting-at-100%.** A follower that sent @wait now says @ok as soon as it's back at its own rest targets — even if it keeps topping up alongside the leader. Before, the leader rested because of the follower's @wait and the follower kept resting because the leader was (party sync), both at ~100% until a 45 s timeout broke it.
- **@exp and @level: short and straight.** "Level 15, can train to 17, 2.71M to 18 in 3.9 hours" — or "Level 47, 110.31M to 48 in 75 hours"; @exp adds "· made 1.52M at 1.48M/hr". @exp reads `exp` itself first if it has to — no more "type exp for needed".
- **A bless that drops is noticed at once.** Each bless's end line now comes from the Messages file instead of a guess: mageshield had learned "The effects of the poison wear off!" (so poison ending recast it, and mageshield really dropping went unnoticed) and blur had mageshield's "shimmers and fades". Fixed on the next start; lines you typed yourself are kept.
- **AC and DR blesses never lapse.** A bless that gives AC or DR is recast 5% of its duration before it runs out (magic armour: 37 s early, mageshield 23 s) instead of the usual 15 s — a lapsed AC bless is a lot more damage taken.

## 0.8.107

- **An unanswered route prompt takes the safe way.** "The short way goes through Negative Power Plane — go through it?" now counts down: no answer in 10 s (you're away from the keys) = No — the safe way round, never through the area (and if that's the only way, it doesn't go).
- **MudPilots in a party tell each other what they've got.** Level, class, max HP/mana, AC/DR and their best spell's damage go over party sync (`@mpsync me …`, when they team up and when it changes). The leader judges a lair by the party: the weakest member's HP is the line (a 52-HP Buddy died following into the orc barracks), and the party's combined damage counts — risky for one can be easy for three.
- **Webbed Mine is asked about for everyone,** like the Negative Power Plane and Black Wasteland (Dan: rooms of wraith spiders — too much for a couple of level 45s, whatever the numbers say).
- **Routes know the danger.** Every route — Go to, errands, fetches — keeps out of lairs whose full spawn would cost you 60%+ of your HP (the Webbed Mine Chamber's wraith spiders for two level-45s), and if the only way goes through one it says so first ("careful — the only way goes through 8 dangerous lairs, e.g. … up to 9 wraith spiders, ~1460 damage"). Settings: `route_danger_pct` (60; 0 = off).
- **The cheapest way counts what it takes to get there.** A way that needs an item is weighed by what fetching it costs — a shop item is the walk to the shop, a rare drop is the extra kills (a 10% black star key ≈ 10 cultists). The flaming mammoths: buy a mine pass at the Miner's Guild and go down through Khazarad's mines, not the Black House door or the Old Mine jump.
- **Everyone gets their own mine pass.** Item-gated exits (the Iron Mine entrance) count like rafts: the leader asks the party `@have mine pass` and buys one for whoever hasn't.
- **Best spots: safe to get to, and what you'll need.** Areas you can only reach past dangerous lairs aren't offered (the Old Mine loop behind the spiders); areas behind a shop item are, with "needs mine pass (bought on the way)". When one nasty lair makes an area's loop 'deadly', it builds the loop without it (the mammoths without the horned demon). Unproven 'risky?' areas rank with the moderate ones; 20 shown.
- **How? (Paths tab).** Pick a loop or path and click How?: the areas it goes through in order (Black House → Fungus Forest → Cracked Plain → Old Mine → Webbed Mine → Diamond Mine…), on the way there and on the loop, each with a room number — a known room if the stretch has one, else one with monsters. Double-click one to see it on the map; dangerous or avoided places show in red. Pick one and click **Not safe: this room** or **Not safe: this whole area**: it goes on your avoid list (Settings → Other → Routing) and the way there is worked out again on the spot.

## 0.8.106

- **No bashing a door that can't be bashed.** "[or 100 picklocks]" with no strength in it isn't bashed (party Miserable took damage bashing the Black House door 3×), and it isn't picked without the picklocks for it. When only the key will do: ask the party (`@have black star key` → `@do give…`), pick it up if it's lying there, else hunt what drops it — at its lairs if it has no spawn room (dark cultists: the regen rooms round the door).
- **Parties stay off chance jumps.** The Building Rooftops' `jump north` / `jump east` split Revolution off. Each chance jump counts as ~100 extra rooms for a party, so it takes the way a key opens (the Black House door, fetching the key) instead of the rooftops.
- **Best case… (Best spots).** Pick an area and click Best case…: the gear from anything in the game that would make the most exp/hr there, slot by slot — what you wear, what to wear instead, and where it comes from (shop, drop, chest, quest). It scores each item by kill speed (spells or weapon), damage taken and the resting that costs, against that area's monsters, and shows the rough exp/hr gain and the stat changes (Spellcasting, AC, DR, mana regen). Only items your class, race, level and alignment can use.

## 0.8.105

- **Weakness doesn't stop the walk** unless the game says you're too heavy to move (it's over-encumbered, not held) — that, like "You are held!", makes it pause (not stop): it carries on by itself when the weakness wears off, and tries a step again every minute in case the wear-off line was missed.
- **Pyramid floating key: grab the golden lion key first.** With the key on the floor it's picked up before fighting anything else in the room (it cast at an undead priest and the key was gone). When the key room comes up empty it asks `pro` before stepping out and back — every room there looks alike and it spent minutes one room off — and its 6-try give-up now counts across the steps out.
- **Map search shows the whole name.** The box stays the same size; the list of hits drops down as wide as the longest one ("Rugged Shoreline, Tidepool — 13/430").
- **Avoided areas stay avoided when a key's missing.** Planning "as if you had the keys" (doors to pick or bash, keys to fetch) kept to your avoid list only half the time — 14 Go tos (Crimson Fortress, Rhudaur, the Dark-elf Queen…) went through Black Wasteland. Now they go round, or it asks when that's the only way (and doesn't go unattended). Item fetches keep out too.
- **Bash or pick the doors you can.** A key door that says "[or 91 picklocks/strength]" is checked against your picklocks and strength: if you can do it, no key run. Keys from an `ask` or a summoned monster (the gate key) are still fetched.
- **Takes shortcuts an item opens.** When fetching an item makes the trip much shorter, detour included, it fetches it: Seher'Sahham gets the king crab claw from the Sandbar (~226 rooms instead of 324). Not from a monster that could all but kill you.
- **Mages drain the last weak monster back up (dtch).** One monster left, HP under the rest line + 20 (60 → 80%), the monster hits for ≤6% of your HP a round, it isn't undead, and there's mana above your rest line: deathtouch it instead of the big spell, so you come out of the fight not needing a rest. Anything that hits harder still gets the hardest-hitting spell. Settings: `drain_heal` (on), `drain_spell` (dtch).
- **Treasure digging stops when you're out of spades.** "Nothing happens." after `dig` → it reads your inventory; no spade left → the dig loop stops and tells you (three "Nothing happens" in a row stop it anyway).
- **Best spots: size up each monster.** Select an area and its monsters are listed underneath — exp, HP, how many rounds you kill it in (and with what), how hard it hits you a round, how many rounds it would take to kill you, HP lost per kill, and a verdict (easy / fine / hurts / deadly). Double-click one for the full combat calculator, opened on that monster.
- **See who has @ control.** Game Data → Players has an **@** column: "all", "3/9", or blank. **@ all on/off** gives the selected player every @ command in one click (it asks first — that includes @do) or takes them all away; the player dialog has an **All / None** button too.

## 0.8.104

- **Each MudPilot window has its own dull colour** — the title bar (Windows 11) and a strip across the top: brown, plum, olive, tan, slate… picked from the data folder so the party, PVE and Buddy windows differ. Settings → General → Window colour to choose one.
- **Touch a statue, look at once.** `touch statue`, `touch hammer` and other commands that call a monster up (from MME) are followed straight away by a look, and "…animates, and attacks!" / "…comes to life!" make it look too — it used to stand there until you pressed Enter.
- **Fights what it can't see.** In a dark room, a monster that hits you or a party member ("The angry dark-elf sentry swings at Revolution…"), or that a party member moves to attack, is taken as being in the room and fought — it used to stand there.
- **A follower stops its leader before an update.** Following someone else's party (Buddy with Revolution and Evolution on MegaMUD) when a restart comes: it telepaths the leader `@stop`, restarts, then asks `@invite`, joins, and sends `@rego` — they don't walk off and leave it behind. Gives up after 5 minutes (and says the leader may still be stopped).
- **Search the map.** A search box on the Map tab and the pop-out map: a room name, `8/459`, a Rooms.md place, or a monster (shows where it spawns). Enter, pick a hit, the map centres there (yellow outline); double-click to walk.

## 0.8.103

- **Dark-Elf City: the gate key from the statue.** With the orb in hand, the way on goes through the Black Steel Gate — it fetches the gate key (`touch statue`, kill the obsidian statue) even for someone who could pick it, instead of saying "only way is through Black Wasteland" and stopping.
- **Dark room, unknown spot: asks `pro`.** It used to press Enter every 6 s in the dark. A `@summon` that comes before it knows where it is waits for the answer and then goes (no more "try again in a moment").
- **A picked or unlocked door is opened straight away.** "You successfully unlocked the door." → `open east` at once, then the step — not `e`, "The door is closed!", then `open`. Same after a key. A bashed door is already open.

## 0.8.102

- **Item spells are commands, like MegaMUD's `#etc`.** Every item that casts a spell with unlimited uses gets `#` + its initials: emerald-tipped crozier → `#etc`, large silvery cross → `#lsc`. Put one anywhere a spell goes (heal, attack, bless, typed: `#etc`, `#lsc orc`). MudPilot does the swap: takes off the off-hand item if the item is two-handed, equips it, uses it, then puts your weapon and off-hand item back — no message responses. Already holding it: just uses it. Wands and other limited-use items don't get one. After an `i`, the log lists the item spells you carry.
- **Dark-Elf City through the Fungus Tunnel (7/1405).** Go to takes Dan's way in, not the Dragon's Teeth Hills one (no rusty iron key run either).
- **Detours aren't gangpathed.** "Detouring to … for …" stays in the log and is the answer to `@status` while it's on the errand — not broadcast to the whole gang.

## 0.8.101

- **Dark-Elf City the normal way.** Instead of going through the Negative Power Plane (or asking about it), Go to fetches what opens the normal way: the bloodstone orb (`ask commander orb` in the Commander's Office, 8/459) and the gate key (`touch statue` at the Black Steel Gate calls up the obsidian statue, which drops it), nearest first. A party never plans on the amber talisman (roof jumping splits the party).
- **Routes on the party's lowest level.** MudPilots tell each other their level (party sync). If the only way is through a level-gated area (NPP is 40) and someone's too low, it says "members of the party aren't big enough" — no asking, no running off.
- **Nearest place to get an item.** Every room of a shop counts (the raft shop is Arlysia's docks *and* the Silvermere pier — it always went to Arlysia), weighed by the whole detour. Monsters' talk ("ask X topic") that hands out an item counts as a source.
- **Says where it's detouring.** "Detouring to the Pier (1/1813) for a log raft — then on to …" in the log and to the party.
- **King Crab Go to lands on the crab.** A Rooms.md label that's a monster goes to where it spawns (16/287), not the nearest same-name room.

## 0.8.100

- **Prompt areas built in for everyone.** "Negative Power Plane" and "Black Wasteland" now prompt before routing through them for every character (dangerous for lower levels), on top of whatever each person adds. Avoid-prompt "no" sticks on automatic re-plans; a fresh Go to you're there for still asks.
- **The headless launcher can't freeze on the picker.** If nobody picks a character within 20 s (a mini PC with no screen), the launcher opens its own folder and carries on — this is what froze the party character for an hour.
- **@have / @wealth / @enc read `i` then answer; @lives reads `st`.** No more "type i first" — it gets the answer itself (like @level already did).

## 0.8.99

- **Import from MegaMUD.** The Connect box has an "Import from MegaMUD…" button: point it at a character's Chars\<name>.ini and MudPilot reads the UserID and saved password and logs in. The password goes straight into Windows Credential Manager (encrypted) — never shown, logged or copied out. Moving from MegaMUD, or to a new PC, is one click.
- **"Go through the avoided area?" stops nagging.** A No is remembered for the trip (no re-asking on every re-plan). When the only mapped way is through the area you avoid (Negative Power Plane), the Go to stops cleanly with a message instead of re-prompting or quietly fetching keys.
- **No looking at exits that aren't there.** "You hear movement to the up" in a room with no up exit no longer sends "l u" — that's a sound from beyond a vortex/portal.
- **An unlocked gate just opens.** "The gate was not locked." was read as locked (the trailing period matched), so it picked three times and bashed (costing HP). Now it opens and goes.
- **@join is resent if they don't join** — every 8 s, up to 5 times (a partner with no remotes yet won't be left un-joined).
- **Arrived where you were summoned but they're not here?** It verifies the room (pro) and @wheres them, then goes to find them.
- **@level:** "ready to train to 5, 29,750, 40 min until 6" — the highest level your banked exp covers and how long to the one after; part-way levels show "20,000 to 4, in 27 min".

## 0.8.98

- **The leader waits for its party after a restart.** On an update or reboot the leader used to run the loop solo before the followers were back in the realm (Miserable looped off without Buddy; you had to @summon by hand). Now it holds the loop and re-invites the party it had — inviting whoever's in the room, waiting for the rest — until they're back, up to the comeback timeout (5 min default), then carries on. Restart order no longer matters.

## 0.8.97

- **@attack-last on / off works.** It was ignored — MegaMUD's way to let the party's tougher members start the fight and draw the monsters while this one joins in after.
- **@level looks it up.** Not known yet? It sends 'exp' and answers when it comes back, instead of "level unknown".
- **A wrong saved password is forgotten.** When the board rejects the login, MudPilot drops the saved password, so Connect asks again (☎ Connect skipped the box once a password was saved — even a wrong one).
- **Every launcher marks its character as open.** Launchers started before 0.8.96 didn't, so the character picker offered characters that were already running.

## 0.8.96

- **Pick the character when MudPilot opens.** With more than one character on the PC, opening MudPilot asks which: the ones already running are shown but can't be picked (opening the last one used logged in over the one that was playing), a click opens and logs in that one. "New character…" gives it its own folder (data-<Name>: settings, logs, restarts), with the board data and the BBS address copied in. One character: straight in, as before. Restarts and updates never ask.
- **Connect just connects.** With a saved password the ☎ Connect button logs straight in — the Connect box only comes up when nothing's saved.
- **Go to a room MME has no way into.** "King Crab" is 16/297, a Sandbar MME lists with no exits at all; Go to now heads for the Sandbar next to it (16/296) instead of "no walkable route".
- **No running into walls.** "There is no exit in that direction!" twice from a room it's sure of is a wall: it goes round it straight away, and the next Go to doesn't try it again (PVE hit 1/2104's south wall 16 times — a hidden exit that opens from a room you can't get to).
- **Round the water only when it's close.** A raft-free way is taken when it's at most half as long again (it was twice as long).
- **@level says how long.** "Level 54, 3,140,418,816 exp, 41,000,000 to 55, in 9h 12m at 4,450k/hr" — and when you can already train, how long to the level after.

## 0.8.95

- **No more "@mpsync st" telepaths.** Who's resting, their HP and mana are all in 'par' ("[H: 94%]R" resting, "M" meditating) — MudPilot reads it there. Only the one "@mpsync hi" per session is left.
- **Eco looks after the little guy.** A monster that's hitting a party member is a fight, not something to walk past (a level-1 paladin behind a level-55 mage got beaten to the ground by an orc lieutenant). And once you've stopped — resting, meditating, held by an @wait — eco doesn't skip anything: what's hostile in the room gets fought.
- **Good picklocks: no key runs.** With Picklocks 100+ on your 'st', a key door is one to pick (picking first, before bashing), so a Go to doesn't send you off for the green metal and large iron keys. An errand that does need a key picks up one, not the whole pile of 10.
- **Gates on typed commands are checked too.** On the way to the bank PVE walked into the Blue Tower and typed 'ask Jorah portal / teleport' 8 times — MME gates that teleport on ability 127 (a quest Miserable hasn't done). Class, race, alignment and ability gates used to count only on 'restricted' exits; now on every exit.

## 0.8.94

- **Comeback calls itself off when the party's whole again.** At the pyramid top Revolution stopped following, didn't answer @where in time, and MudPilot set off 313 steps back to the tomb where it last saw him — and kept going after he re-joined a second later. Now a member back in the party (a fresh 'par' or "started to follow you") ends the search and stops that walk; standing in the room with you, they're just invited back.
- **Go to goes round the water when it's not much longer.** Pier → Dragon's Teeth Hills (111 rooms, across a river) set off 220 rooms the other way to the only log-raft shop. The dry way is 133: it takes that ("Going round the water…") and only fetches a raft when there's no sensible way round.
- **Nothing left to kill → break combat.** Pyramid top: the stone sphinx (0 exp, 9999 HP) held combat after the area spell, so the game repeated esto at it every round — three casts, 210 mana, into the Pharaoh's tomb at 27%. Now MudPilot sends `bre` when only monsters it won't fight are left (never in a PvP fight). Anything MME has at 0 exp and 9999+ HP is never a target, even after it swings at you.
- **Pyramid level 3 doors.** "Doors on this level creak and thump!" made every door there a timer door, so the bashable east door in 12/2046 got `e` over and over. Now it gives a door ~5 s to open by itself, then bashes it; the [1000 picklocks] ones still just wait.
- **Key doors: key once, open, walk.** A path's `use lion key w` at a shut door used the key twice at once (the second "You don't have lion key"), walked into the still-closed door, and kept re-sending the crumbled key. Now: the key, wait for "unlocked", `open west`, then through.

## 0.8.93

- **A trap that splits the party gets them back.** Pyramid: 'push block', two rooms on a trap ("…and vanish!", down a shaft into the Scorched Cavern) — MudPilot blamed the block, asked Revolution to '@do push block', waited 30 s and walked back up alone. Now a trap message means they're somewhere else: it holds the walk, asks them @where, walks there, invites them and carries on. And anyone who doesn't come through a portal in 30 s is fetched the same way instead of left.

## 0.8.92

- **Path builder: a loop of only commands stays in the room.** Add `dig` with no moves and save: a loop that digs, waits a round for the answer, digs again — it never walks, so 430% encumbrance with ten chests doesn't matter. Dig drops you in a Dark Pit (13/315–323)? It fights what's down there, climbs out (MME's exit back to 13/211) and carries on digging.
- **"You picked up 0 gold crown" with a pile of "40 gold crowns"** — the 0.8.87 skip compared the singular answer with the plural pile, so it asked again every look. It goes by coin type now.

## 0.8.91

- **Auto regen gear no longer rests in the fighting set.** The inventory read after the post-rest swap never cleared the "gear changed" flag, so in busy spots (Tidepool: fight → rest → fight, no idle moment) the next rest skipped the swap and sat in the faded shawl (−100 HP regen): 9 rests of ~310 s instead of ~75 s over six hours, about 3.4M/hr instead of 4M+. The "You are carrying…" answer clears it now, and if it's still stale when a rest is due MudPilot reads `i` and waits a moment before sitting.
- **Settings and tool windows say whose they are.** With two or three MudPilots open, the title bar reads "Miserable — Settings - MudPilot", and opening one from the taskbar brings its own main window up right behind it.
- **Path builder: your own commands.** "Command here" + Add command puts dig, search, a spell… into a path or loop. It's sent in that room before the next move; on a loop, commands at the end go before the first step so every lap does them (a one-room dig loop: dig, step out, step back).

## 0.8.90

- **Auto regen gear: a rest always goes for HP regen** (mana only breaks ties). You get up when HP is back, so that's what you wait on — weighting by what was short kept the faded shawl (−100 HP regen) on with mana at 9% and made a 233 s rest. Meditating still goes for mana.

## 0.8.89

- **Auto regen gear re-reads the inventory after any gear change** ("You are now wearing…" — a post-rest line, or you typing eq). 0.8.88 planned the next rest from the inventory read before the post-rest swap, so it left the faded shawl on to rest. Until the fresh read comes back it doesn't swap.

## 0.8.88

- **Auto regen gear reads your inventory first.** 0.8.87 skipped the swap when the inventory hadn't been read since MudPilot started (PVE rested in its fighting gear, faded shawl's −100 HP regen and all: 5-minute rests). It now sends `i` once early when the inventory isn't known, and logs it if a rest comes before that.

## 0.8.87

- **Auto regen gear** (Settings → Health, under the rest/meditate commands). Sitting down to rest, MudPilot puts on the best HP-regen gear in your pack, slot by slot, from MME's item stats; meditating, the best mana-regen gear. Your fighting set (whatever you had on) goes back on when you get up. On Dan's mage it picks his own hand-made swaps: sparkling pendant, white gold ring and runed cape to rest (the faded shawl's −100 HP regen comes off), the rainbow stone to meditate. The weapon and quest trinkets are never touched. The old Pre/Post boxes still work for anything else.
- **'pro' right after 'st'** (post-rest commands end in st): "Lives/CP: 9/5" was read as the room and it walked east into a wall. The Location: line wins now, and st lines and the deaths list are never read as a room.
- **'You picked up 0 gold crown'** (too heavy): reads the inventory once and leaves that pile for 5 minutes instead of asking for it on every look.
- **Keypad moves: one per press.** Holding a number-pad key (or Windows auto-repeat while the game sat a round on 'dig treasure') sent 30 'w's.
- **Eco counts the pack.** One locust nibbling at you is still walked past, but when what eco is walking past hits you for 5% of your max HP or more in a round, MudPilot stops and clears the room (area spell and all). It goes by the damage you actually take, so at level 50 a room of orc rogues that mostly miss doesn't stop you. Settings → Eco: "…or a pack hits ≥ % HP a round" (0 = off).

## 0.8.86

- **Rafts, boats and the golden idol for the whole party.** The map's room spells say where you drown without a raft (rivers, seas, the ocean) and where the golden idol teleport checks for the idol. Go to and paths now count those as needed items: MudPilot buys its own raft first, then, leading a party, asks everyone `@have log raft`. Whoever says no, or doesn't answer in 15 s, gets one bought and handed over (`give log raft to Revolution`) before the walk starts. Items no shop sells (the idol) stop the walk with a note saying who needs one.
- **Into the Necromancer's catacombs (Paradigm):** MME has no way in. Dan: drink a potion of levitation in Mossy Cave, Waterfall (3/1) and it lifts you to 9/1009. Go to now routes that way, and everyone in the party needs their own potion (the gnome alchemist sells them; MudPilot can't buy from him yet, so it stops and says who needs one). Inside, the catacomb doors need a titanium fork and the barrier a magical quartz rod, carried by the leader.
- **Quest flags reach the leader.** MudPilot reads `abil` again a few seconds after a quest-style command (say, ask, give, push, press…) and every half hour. A new or changed quest flag is logged and, when you're following, telepathed to the party leader.

## 0.8.85

- **A dropped member who doesn't answer @where** (MegaMUD in the dark doesn't): MudPilot walks back to the room it last saw them in, then up to 4 rooms further back along its trail, and invites them when they're there.
- **Eco walks past monsters a party member is fighting again** (0.8.84 stopped for them; Dan: the party kills the little ones that follow on the run). What left Revolution behind was being knocked flat — that still holds the walk.

## 0.8.84

- **Keeping the party together:** a party member 'knocked flat' (Paradigm's wording) counts as can't-move, so the leader waits; and a member who says '@wait (can't move)' + '@comeback' is walked to, not waited for (the two used to deadlock).
- **Finding a dropped member from a MegaMUD @where:** the room name + exits are matched to the latest room on our own trail first (they were following us), then the nearest look-alike.

## 0.8.83

- **Doors: unlocked isn't open.** After a key or a successful pick the door still has to be opened - MudPilot now sends 'open <dir>' next, on every door ("You successfully unlocked the door." used to count as open, so the move hit "The door is closed!" and it gave up with the key already used). A bashed door is open as before.
- **Keys go by their last two words** ('use lion key w'): 'use key west' was ambiguous with a keyring.
- **Asking a party member for a key** says 'give <key> to <you>' (MegaMUD answered ok and gave nothing without 'to').

## 0.8.82

- **'pro' typed by you counts:** its answer moves the map to the right room (it only counted when MudPilot asked, so the map stayed one room off).
- **Floating key:** a party member who picks up the golden lion key (MegaMUD auto-loot) is asked for it ('@do give golden lion key <you>'); the out-and-back to bring the floating key back no longer trips the 'move isn't getting anywhere' stop.
- **Doors that open and shut by themselves** ('Doors on this level creak and thump!') are waited on and retried like a timed door.
- **Recordings:** the recover password from 'pro' is hidden in the trace files too.

## 0.8.81

- **Floating key (pyramid level 3):** when the Go to fetching the golden lion key ends in 12/2005 and the floating key dies without dropping it, MudPilot now steps out and back in to bring it back (it stood there waiting before - only a path walking on through 12/2005 did that), and steps back in by itself.

## 0.8.80

- **Timed pyramid levels run flat out:** while the 'time is running out' timer is on, no party checks, no bless / abil / st upkeep and no periodic re-looks — the 4-minute run was losing time to 41 'par's, 14 'abil 145's, 5 'st's and 61 re-looks (1.6 s a step; the five block pushes and ~150 steps need ~1.2).

## 0.8.79

- **A restart carries on a Go to too**, not just loops and paths — including a Go to that's off fetching a key first (Great Pyramid → golden lion key). Before, MudPilot came back idle with nothing said.

## 0.8.78

- **Top sphinx (12/2085):** Paradigm's answer is 'ask sphinx E' (capital E), not stock MajorMUD's 'time' that 0.8.77 used.

## 0.8.77

From a review of pMUD (a year of live testing):

- **Great Pyramid:** on levels 3-5, the '[1000 picklocks/strength]' doors that never open (12/2004 south and the like — where every Go to to the top got stuck retrying) are now shut for routing. Only the four that open on a timer (12/2004 N, 12/2017 E, 12/2022 S, 12/2032 S) and the doors on Dan's walked level 3 are used.
- **Pyramid level 4 maze:** it passes 12/2052 twice; MudPilot now remembers how far through it you are, so a replan on the second visit carries on with the last 8 moves instead of starting the maze over.
- **Top sphinx:** see 0.8.78.
- **Stall watchdog:** in a fight, still being hit but no attack of ours for 8 s (a repeating spell can stop without *Combat Off*) — attack again. Setting `stall_secs`.
- **Mid-fight blesses and minor heals** may go any time except the last 1.6 s before the next round (pMUD's late-cast guard), instead of only the first 1.5-2 s. Setting `late_cast_guard`.
- **Round clock:** the game's rounds are one server-wide beat. Once learned, the round length is refined over a long stretch and its phase carried across walking, resting and restarts (data\round_clock.json), so the first round of every fight is timed too.

## 0.8.76

- **Max casts in a row really stops the rerolling.** After using up its casts, a bless chasing a roll (mana flux +110) used to start a fresh set a minute later — 8 flux casts in 95 s, ~160 mana. Now it keeps the roll it has until it wears off, then starts fresh.

## 0.8.75

- **PVE realm: other players don't block the area spell.** AoE safety (no area spells while someone outside the party is in the room) only applies on a PvP realm, where an area spell can count as an attack. On PVE, a player passing through Tidepool no longer turns esto off.

## 0.8.74

- **The area spell wins in a crowded room.** A per-monster pick in Game Data → Monsters (e.g. drooling geist → dfir) used to beat the area spell too, so Full Glades never cast esto even with 3-4 geists in the room. Now a single-target pick only applies below your area-spell count; melee-only picks still mean melee.
- **The area spell isn't re-sent every round.** MajorMUD repeats it by itself; re-sending only toggled combat off and on. It's cast again after *Combat Off* if the room is still crowded.
- **Solo: no `par` checks** once the game says you're not in a party, until you invite, join or follow someone (or someone joins you).
- **NoHang on a PVE realm** shows as a steady label, not flashing.
- **PvP realm detection:** a BBS menu that lists both realms ("Game 1 PVE", "Game 2 PVP") no longer marks the character PvP.
- **Boards without bless timers in `st`** (stock MajorMUD): after two readings without them MudPilot stops the extra `st` reads and goes by spell durations.

## 0.8.73

- **A second character from the same install.** `MudPilot.bat --data PVE` (or the launcher with `--data PVE`) runs MudPilot on its own data folder, `data-PVE\`: its own settings, profile, logs, traces and control folder. Both characters run the same program, so every update reaches both, and the two never touch each other's files. Your MudPilot shortcuts aren't changed by the second one.
- **Bless lengths go by the level the game shows** (`st` / `exp`), not the level saved in settings, so they're relearned when you level even if the setting is out of date.

## 0.8.72

- **Blesses go up mid-fight without losing a round.** Any bless that's due (Bless during combat, on by default) is cast in the first 1.5 s after a combat round goes off, then the attack is armed again straight away, so it fires on the very next round. Until now a non-Priority bless never went up while monsters were in the room. Before the first round of a fight, the attack still goes first.
- **Heals too:** mid-fight minor heals (yours and the party's) go out in the first 2 s after a round, then the attack is re-armed. Major heals don't wait. Settings: `bless_round_window`, `heal_round_window`.
- **Bless timers from `st`:** Paradigm's `st` shows each bless's time left ("You feel protected! (216s)"). MudPilot now reads `st` a few seconds after casting a bless and every 3 minutes, learns how long each bless really lasts at your level (relearned after a level-up), and uses that for the recast instead of MME's estimate. MME had mageshield ending well before it really did.
- **A damaged map file heals itself on Windows too:** the file stayed open after the read failed, so Windows couldn't move it aside to fall back to the last good copy.

## 0.8.71

- **Restart and update without anyone at the PC (control folder).** MudPilot now opens through a small launcher (the shortcuts and MudPilot.bat switch to it by themselves). Dropping a `restart.request` file into `data\control` makes MudPilot stop at a safe moment (never mid-fight), note the loop and the party, and close. The launcher then installs any newer `MudPilot-x.y.z.zip` from Downloads (never touching `data\`), waits while `data\control\hold` exists, and opens MudPilot again. MudPilot logs back in, re-invites the party and carries on with the loop, just as after a dropped line. Only files named like that do anything, and nothing in them is ever run. A version that crashes within a minute of being installed is rolled back and skipped. Closing MudPilot yourself still closes it for good. `data\control\status.json` shows what it's doing every 30 s.
- **Bless wear-offs:** a line that's already another bless's wear-off ("The effects of magic armour wear off!") isn't learned for a second one, and a line naming a bless's spell (its MME name) goes to that bless.

## 0.8.70

- **A wear-off line that names a bless goes to that bless.** "The mana flux dissipates rapidly." was learned as mageshield wearing off, because mageshield was the bless that had been up long enough. A line that names one of your blesses (by its name or its spell's name) is now only ever learned for that one.

## 0.8.69

- **Bless messages aren't learned from the wrong lines.** A hit like "A fire elemental appears and scorches … for 300 damage, then vanishes!" was taken as a bless wearing off (because of "vanishes"), and was saved as the wear-off message for mshi, blur and Mana flux. And blur's "You are blurred!" arriving just after a flux cast was saved as Mana flux's start message. Damage lines are never wear-offs now, and a line that's already another bless's start message isn't learned for a second one.

## 0.8.68

- **@ok while resting is heard again.** When you're resting or meditating, the game can leave several `[HP=..]: (Resting)` prompts in front of a party member's telepath. Only the first one was being stripped, so "Revolution telepaths: @ok" wasn't recognised and the party held 45–67 s for the "they look ready" fallback instead of moving on when the @ok arrived (often 4–20 s). In the 0.8.67 log this happened on almost every @wait: about 15% of the Full Glades loop. The same fix applies to any game line that arrives behind resting prompts.

## 0.8.67

- **"Weakness" doesn't stop the party any more.** The Messages file MudPilot ships with (pMUD's) says "You feel weak and powerless" means can't-move-and-wait-for-it-to-wear-off — so in the glades MudPilot stood still ~45 s every time a geist weakened you, several times a lap. Shipped rules no longer make the walk wait; a shipped "can't move" only holds you when it really is a hold (entangled, webbed, paralysed, held, bola…) or when the game then refuses a move ("You are held!"). Your own Messages rules still work exactly as you set them.

## 0.8.66

- **Pyramid level 3, the way that actually works.** MME's map has shortcuts across level 3 through doors that never open (east from 12/2045, south from 12/2048, east from 12/2044…), so MudPilot never knew the way. Dan's route is now built in (board_fixes.py, used only on a map where every move fits): from 12/2002 s e s s e e e e e n w n n w w to 12/2005; kill the **floating key** there — melee only, spells don't touch it — and grab its **golden lion key** the moment it drops; if it's missed (or the key isn't up), step east and back so it respawns; then e s, `use lion key w`, w w s e u up to the sphinx and level 4. Routes that start part-way across, or go to a room on it (12/2005), follow it too. The 1000-strength doors on the way are waited on (they open by themselves); the ordinary ones are bashed.

## 0.8.65

- **What you click is logged.** Every button you click, menu item you pick, shortcut key you press (Alt+R, Esc, F-keys…), Goto / Loop entry you choose (and what you'd typed to find it), and setting you change (old → new) goes into the log as "You: …". So a Report a problem bundle shows what you did next to what MudPilot did — e.g. "You: picked 'Great Pyramid-12 2071' in Goto". Passwords are never written.

## 0.8.64

- **The underwater passage, found: 'pro' got learned as a way.** The tracker relocating after a `pro` was saved as "type pro at 12/124 to get to 12/129", and every route through the passage then stood in 12/124 typing `pro` until you drowned. `pro` (and look / par / spells / other non-moves) are never learned as ways now, and old ones are thrown out at start-up. In a drowning room, `pro` is only used if MudPilot is truly lost.
- **Room commands that open doors.** MME's "turn stand" opens the Golden Spire library's north door (1000 picklocks/strength — no bash or pick will ever do it). Door commands like that are now part of the route: it turns the stand and walks through, and if the door's still shut it turns it again — never bashes, picks, or mistakes it for a timed pyramid door.
- **Closed doors: bash first.** Across the board, a closed door is bashed straight away (a key you carry still goes first), then picked, and plain `open` is the last thing tried. Doors that can't be bashed or picked are routed round instead of hammered. (Settings: bash_doors_first.)
- **Stop before a boss only when it's a real threat.** The rakshasha sage stopped two near-50 casters (and they sat resting). Now MudPilot only stops before a boss expected to do at least 40% of your max HP (boss_stop_pct); anything less it walks straight in on, and says so in the log. The Dao Lord still stops you. And every boss you get stopped before now shows on the Bosses tab, so you can untick its **Stop** box to never stop for it.

## 0.8.63

- **Rest off means no resting.** With the Rest button off, MudPilot still sat down "to top up" while waiting — stopped before a boss, waiting on the party, or because Revolution was resting (party sync). Now nothing rests while Rest is off.

## 0.8.62

- **Never stand still where you drown.** In the Muddy Underwater Passage MudPilot stopped and kept asking `pro` where it was until you both drowned. Rooms that kill you if you stay (the underwater passage to start with; any room where "You are drowning!" shows is learned and remembered) now get: no `pro` checks, no resting, no @wait / held / regroup holds, no stopping for fights, and no "this exit isn't shown" stops — just keep walking. If you're drowning while stopped, MudPilot carries on with the trip (Rego) or goes back out the way you came.

## 0.8.61

- **Goto list rebuilt clean from MegaMUD's rooms.** It's now just your Rooms.md (MegaMUD's Goto list), one entry per room number — the number in each name decides the room — and no longer mixes in every path's start and end names (where most of the doubles came from).
- **Make it yours:** **Add this room** (in the Goto window) saves the room you're standing in under a name and folder you choose; **right-click** an entry to **Rename** or **Remove** it. Your changes are kept per board and survive re-importing Rooms.md.

## 0.8.60

- **No doubled party commands.** Regroup, Game Data's "invite if seen", comeback and the reconnect re-invite could each invite the same member in the same second. Now one `invite`, one `@join`, one `@party …`, `@do` or `@where` goes out; the same one again within 8 s is dropped (what you type always goes). Regroup's 15 s re-invite still works.
- **Moving by hand cancels the trip properly.** Walking back a couple of rooms yourself (to fetch Revolution at the chained apparition) stopped the Go to — but a party fetch that was going on was still set to "carry on to" the trip afterwards and dragged you back. Moving by hand now also cancels that, and anything else queued to restart the trip.
- **Goto list: one entry per place.** Names with the room number written different ways ("Vortex+3 681", "Vortex)3 669", "Vortex-8 978-8 958") are read properly, and a place listed both with and without its number in Rooms.md shows once, at the numbered room — the vortexes, the Chaotic Vortex, the NPP vortex and the rest.
- **The log doesn't print the same line twice in a row** ("Eco: walking past …" ×2).

## 0.8.59

- **"Below Pharoah" listed once, for real.** The second entry came from your Rooms.md (MegaMUD's room list), whose name for it also ends in "-12 2085" but whose room hash fits the look-alike 12/1808. Rooms.md names that carry a room number now go to that room, so Goto shows just 12/2085.

## 0.8.58

- **Darts aren't PvP.** "Darts …" on pyramid level 2 is a room spell, not a player — it hung you up. Lines that start with the name of one of MME's room/trap spells (darts, poison darts…) are never taken for a player attacking you. A real player hitting you still hangs up.
- **One Goto entry per room.** "Great Pyramid (Below Pharoah)" showed three times (12/2085, 12/1808, 12/1915): your paths' labels say 12 2085, but their MegaMUD room hashes matched look-alike pyramid rooms. The room number in a label now wins, so it's listed once, at 12/2085.
- **Pyramid timed doors: "s", not "south".** Waiting on a door that opens by itself, the retry typed the long word, which this board answers with "Your command had no effect". It types the short direction now.
- **Who started a Go to** is logged now when it isn't you ("Go to 12/2071 — started by …"), to pin down the trips to 12/2071 that started by themselves after arriving at a firepit; and stopping clears anything a trip had queued so it can't restart later.

## 0.8.57

- **New Go to walker (pMUD's way).** Every step it works out where you really are, then plans the next move from there — no step counter to fall out of line. Land somewhere unexpected (a fight dragged you, a twin room, a skipped step) and it simply plans again from that room. In look-alike areas (the pyramid) it asks the board (`pro`) when it can't be sure — after a teleport, or starting in a twin room — and what `pro` says always wins. Push-block style actions are walked to, done, and walked back from; if the wall's shut again it goes back and redoes it. Fights, Eco, party regroup, vortexes, doors and the pyramid timer all work as before. Loops and imported MegaMUD paths still use the old walker for now. Switch: Settings → Other → "New Go to walker" (on; the old one goes away once this one's proven).

## 0.8.56

- **The sphinx shortcut can't come back.** 0.8.55 forgot it — and then re-learned it from your MegaMUD pyramid path at start-up (its room hashes matched the look-alike dead end). Now no way is ever learned between two rooms that both look like other rooms, from a path or from walking, and one that failed stays forgotten for the session.
- **Pyramid timer.** "You have a strange feeling that time is running out!" → until you reach level 3: no resting for HP or mana, `@wait` and the leader's wait-for-hurt-members are ignored, and monsters are run past (unless your HP is under the Eco HP %). The party is still kept together: a member who's held (says `@held`, or is knocked down / held in the room) still holds the walk until their `@ok` (30 s at most), and a broken party still regroups. Everything goes back to normal at level 3, or when you leave the pyramid.

## 0.8.55

- **The pyramid dead end, found.** Every Go to up the pyramid walked north at 12/1828 into the 12/1830 dead end and asked the sphinx there. The cause: last night MudPilot "learned" that asking the sphinx in 12/1830 takes you to 12/1920 — a guess between two rooms that look exactly alike (Great Pyramid, exit south only). Routes then used that made-up shortcut. Now:
  - a way is only learned when the room you land in is one nothing else looks like;
  - learned ways between look-alike rooms are thrown out when MudPilot starts (your learned list is cleaned);
  - a learned way that fails ("You don't see sphinx fire here", "no exit") is forgotten on the spot and the Go to is planned again without it.
- **`pro` beats the path's guess.** Once the board says which room you're in, the path can't "place" you somewhere else a second later (it kept putting you at 12/1921 after `pro` said 12/1830).

## 0.8.54

- **NoWait** (toolbar): ignores `@wait` from the party and the leader stops waiting for hurt members — for timed lairs like pyramid level 1, where stopping dumps you back in the desert. It's dangerous, so it flashes a red banner while it's on (click the banner to turn it off), and it's always off when MudPilot starts.
- **Hands off** (toolbar): switches everything automatic off — no fighting, walking, spells, resting, looting, party replies or timed commands; only what you type goes out. Low-HP / PvP hang-ups and reconnect still work. Flashes an amber banner; off at start-up.
- **Eco takes the whole room.** When something in the room is worth stopping for (the saracen leader), the rest of the room is fought too — so the area spell goes out instead of one magma blast on the leader while four raiders swing at you. Anything that's swinging at you counts as worth it.
- **Wrong room in the pyramid → ask the board.** "You don't see sphinx fire here" after a path action, or "There is no exit in that direction!" while walking, now sends your room-number command (`pro`) and carries on from the room it really is in, instead of asking the sphinx (that isn't there) over and over.
- **The area spell keeps a mana floor.** It won't cast esto if that takes you under half your Rest below MA % (unless the fight's dangerous) — it was going from ~130 down to 25 mid-fight.

## 0.8.53

- **The party breaks → regroup before another step.** Going through a portal or vortex that disbands the party, MudPilot now waits on the far side until everyone's there, invites each one back, and doesn't move until they've all joined ("Revolution started to follow you"); it re-invites every 15 s while they're standing there. It used to see Revolution arrive and walk off without him in the party.
- **"Revolution appears in a flash of light!"** (or steps out of / walks in) while it's waiting for him: it looks straight away, so the invite goes out at once.

## 0.8.52

- **Vortex steps actually go through.** A step written as `@party go vortex` (learned from an earlier trip, or in a MegaMUD path) used to only *say* it, so Revolution went and Miserable stood there. Now MudPilot says `@party go vortex` and then goes through itself, then checks the party made it. Learned ways are stored as the real command ("go vortex"), and old `@...` ones in your learned list are cleaned up on load.
- **"Yes" to an avoided area sticks.** Say yes to the Negative Power Plane route and the walk keeps using it for 3 hours — it no longer turns round halfway and goes the long way through the Darkwood vortex.
- **Go to doesn't turn hang-ups off.** NoHang is never one of the switches a mode turns on (and an old setting that did is removed). Eco is on by default now.
- **You move by hand → it stops until Rego.** Type a move while it's walking a path or Go to and it stops ("Paused: you moved by hand"); click Rego and it carries on from wherever you are. Switch: Other tab → Timing.
- **Running ahead by hand doesn't lose the map.** Typing 5–8 moves before the game answers: each room is matched from the one before it, not from where you started.
- **Fewer stops overnight.** Catching up a few rooms on a path isn't counted as drifting off it, a second drift holds and finds where you are instead of stopping, and leftover `look`s no longer time a step out. Auto-tune says when it's paused rather than silently standing there.

## 0.8.51

- **Train stats / the character editor look right.** Full-screen pages are drawn by moving the cursor around; MudPilot used to print them as scrambled lines. Now it keeps a real 80×25 screen and shows it over the MUD window while the page is up (the field you're on highlighted), until you're back at a game prompt. While it's up, keys go straight to the game one at a time like a terminal — Space toggles a choice, arrows / Tab / Enter move, Backspace fixes a typo.
- **Vortexes that break the party.** Leading: when a portal command (typed or on a path) breaks the party — "Revolution is no longer following you" — MudPilot asks each one left behind to step through (`/Revolution @do go vortex`), waits for them, and invites them back. Following: when your leader steps through a portal and the party breaks, MudPilot goes through after them (and joins again when invited).
- **Lost in the Great Pyramid, fixed for real.** When a Go to path was knocked off for a moment (a fight dragged you a room over), MudPilot used to "re-anchor" it by matching the room's MegaMUD hash — and in the pyramid every room looks the same, so it decided you were 150 steps further on, at the sphinx, and kept asking a sphinx that wasn't there. A path planned on MME's map now only ever matches its own rooms; off it, it walks back.
- **"Your party has been disbanded" = someone got left.** A room spell flinging you into the desert, a warded archway, a trap: when the party breaks while you walk, MudPilot now holds the walk — Go to's too, not just loops — asks the one who's missing where they are (`@where`), goes and gets them or invites them back, then carries on to where it was going. It checks the party at the start of every trip, and someone who's just rejoined ("started to follow you") isn't invited a second time.
- **Knocked flat on your back** ("You are knocked off your feet… You are flat on your back!") stops the walk until you're up, and tells the party `@held` — then `@ok` when you get back on your feet.
- **Room commands that are magic get the party first.** "dive sinkhole", "go vortex" — MME marks them as teleports, and followers don't follow those — get `@party dive sinkhole` before you go, then a check that everyone made it (go path / go hole / go crack, which followers do follow, are just checked).
- **Doors don't stall the walk.** After `open` / `bash` / `pick` MudPilot now waits for the game's answer before moving (it used to walk into the door before hearing it was locked), and once a door's bashed or opened — by you or your partner — it walks straight through instead of trying to open it again.
- **Eco's threshold grows with you.** The automatic "worth stopping for" is now level × 50 (2,350 at 47) or half a minute of your exp/hr, whichever is more — a lone sandworm doesn't stop two level-47s any more. Set your own on the Combat tab (Eco: "Still fight if worth ≥").
- **Combat off mid-fight walks on.** Switch Combat off while fighting on a path and MudPilot walks on out instead of standing there finishing it.
- **NoHang flashes a red banner** in the toolbar while it's on (click it to turn NoHang off), like the PvP reminder.
- **New loading screen art** (Dan's): the gold bar painted into the picture is the real progress bar now, with what's loading written under it.

## 0.8.50

- **The server tick.** MudPilot learns when MajorMUD's ~5-second clock goes off (from combat rounds and from your HP/mana going up by themselves) and uses it for:
  - **Enter on tick** (Other tab, on): entering the realm just after a tick gives you a whole round before anything acts.
  - **Commands timed to the tick** (Other tab): one per line, e.g. `0.3 resting look` sends `look` 0.3 s after every tick while resting. Modes: any, combat, resting, idle, pvp.
- **Stop on danger** (Other tab, on): after a low-HP hang-up MudPilot doesn't relog by itself, even with "Relog instead of hanging" — that would walk straight back into what nearly killed you.
- **Rules for the bot's own info commands** (Other tab, pMUD's Gather settings): for `par`, `i`, `stat`, `exp`, `abil` — at most every N seconds, not in combat, not while walking. A held one waits and goes out once it's allowed, so whatever asked still gets its answer. Shows how many went out / were held. All off by default (nothing changes until you set one).
- **Macros on any key** (Game Data → Macros): Ctrl+a letter or digit (Ctrl+Shift too), Home / End / Insert / Page Up / Page Down / Pause / Delete, as well as the F-keys and number pad. "Press a key…" captures it. Ctrl+C / V / X / A / Z stay copy, paste and friends.
- **Damaged map data fixes itself.** If a board's map file gets damaged (a crash or power cut mid-write), MudPilot puts it aside, uses the last good copy, and re-imports in the background — instead of failing to start. Two MudPilots re-importing at the same moment can't step on each other any more.
- Rest / meditate gear swaps now happen for the short rests too (waiting on the party, pacing for a lair).
- **Flagged players** (Game Data → Players → a player): "Alert when this player shows up" now reaches your phone too; new **Auto-track**: when they come on and you're idle, MudPilot tracks them down. (Hang up on them = mark them Enemy, as before.)

## 0.8.49

- **Timers for any monster** (Bosses tab → "Track a boss or any monster"). Not just MME's bosses: put any monster on the list, give it a respawn time if MME doesn't have one, and it's tracked like a boss (kills, next spawn, Hunt).
- **Set kill time… / Set next spawn… / Respawn time…** — enter a kill you missed (someone else got it, or it died before you logged on): "2h 15m ago", "back in 40m".
- **Shared timers (@spawn).** `@spawn <monster>` answers in pMUD's format ("Ice Queen: dead - Next spawn: 2h 5m"), so MudPilot and pMUD bots can ask each other. "Ask the party (@spawn)" sends it to your party; their answers fill in your timers. (It's a Status/query command: allowed only for players you've given that on the Remote tab.)
- **Quest guide** (Window → Quest guide): every quest flag MME knows, step by step for your class — done ✓, your next step ►, needs level N, later — where each step happens (click the room to walk there), and what it needs (items, with where they drop or who sells them; other quest flags; cash). "Hide finished quests". Read your flags with the button (it sends `abil`).

## 0.8.48

- **More from MME (map data v9 — boards you imported re-import by themselves):**
  - Shops: type (banks are type 7), class limits (guild shops only for their class), level limits, markup and stock. Shop trips skip a guild shop that isn't yours.
  - Items: Not Droppable (Item rules won't keep trying to drop one), Destroy On Death, uses.
  - Key doors that only say "or 151 picklocks" on one side now have it on both (10 on Paradigm's map 15) — the other side was routed round for no reason.
- **Banks are safe rooms** (PvP tab: "and every bank", on): no fights started in a bank — pMUD's defaults.
- **Combat summary** (Window → Combat summary): per monster your hit %, hits, misses, crits, backstabs, average and min–max hit, damage per round and spell damage; what each one did to you (hits, misses, % avoided, average and max); each spell's casts, hits, hit % and damage; and the last 10 rounds (done / taken / HP). Reset button.
- **What monsters drop** (Game Data → Monsters, pick one): MME's drop list with %, next to what actually turned up after *your* kills (counted, with when it last dropped — kept per board).
- **Item history** (Window → Item history): everything picked up, dropped, sold, given or stashed this session — time, room, a Copy button — plus the coins you've dropped or stashed and your total with them.

## 0.8.47

- **Same-name monsters told apart by room.** 130-odd names in Paradigm belong to monsters that really differ (a zombie worth 70 exp and one worth 500). Once MudPilot knows the room, it takes the one that lairs there, or on that map — so danger checks, Eco, spell choice, exp/hr and bosses use the right one.
- **Party cures.** Your cures (Health tab) go on party members too: poison from the P after their health in `par`, blind / held / diseased when they say `@blind`, `@held`, `@diseased` (pMUD and MudPilot both say these). Anyone's "casts cure poison on Revolution", a clean `par`, or two minutes without a repeat clears it. And when *you* go blind / held / diseased in a party and can't cure it yourself, MudPilot says it for your healer. (Health tab: two new boxes, both on.)
- **Party window shows conditions** — Poisoned, Blind, Held, Diseased, Resting, Meditating — in red when something's wrong.
- **Target priority** (Party tab → Priority): attack the first, second, third or last monster in the room list, so two bots can split a room.
- **NoHang** toolbar switch: one click overrides every automatic hang-up — PvP, low HP, Enemy, message rules — for a boss or a corpse run. It says what it would have hung up for, and Alt+H / the Hang up button still work. It's never left on from last time.
- **Confusion isn't a wall.** "You fumble in confusion" / retch / look around stupidly ate the command — the walker tries again instead of counting the exit as failed and routing round it.
- **Only lines about you set conditions.** "Vexx casts poison bolt upon you" comes before the roll; a resisted spell no longer marks you poisoned.
- **Your stat effects are the truth.** A blind / held / stunned / confused that the `st` effects list doesn't show any more is cleared (we missed the wear-off line) — no more stalling for minutes on a stale "held".
- **Players found hiding.** "You see Sneaky hiding in the shadows" — a search found a player in your room: added to the room's players, logged, and the Enemy hang-up applies.

## 0.8.46

- Great Pyramid, for real this time: MME says the 'push block' that opens a wall is done in a *different* room (push the block in 12/1808 and the north wall of 12/1811 opens). Paths now walk over to that room, push, come back and go through — 44 exits like that across the realm. Pushing in the wrong room ('Your command had no effect') is gone.

## 0.8.45

The rest of the first pMUD sweep:

**Combat & spells**
- Spells are timed to the game's round: once the round has ticked over since your last spell, the next can
  go — buffs and heals no longer wait a fixed 4 s.
- The `st` effects list is the truth for blesses: one that isn't listed is down (a dispel, a missed
  wear-off message) and gets recast. Durations like `(1:52)` and `(2m 5s)` are read too.
- A monster winding up a spell ("makes a quick grasping gesture", "speaks a vile word"…) keeps the round
  free of blesses for a moment.
- Spells tab → "Cheapest spell for monsters under N exp": trash gets the cheap spell, the big one is for
  what's worth it.
- No sitting down to rest while poisoned (the stings break it) — unless you have a cure set, which goes
  first.
- MA ↔ KAI prompts are separate pools (the max starts over when it switches).

**Party & safety**
- 20 s of silence in the middle of a fight = the line's dead → reconnect (was 90 s).
- A big hit on Revolution asks `par` straight away, so heals land sooner.
- Revolution knocked down / stunned / held → the walk waits 12 s for him.
- You type a move yourself → the bot keeps its hands off for 6 s.
- Hanging up on PvP telepaths the party "*Attacked* at 12/335 — … — hanging up!" first.
- Hang up on monsters: right-click one on the screen → "Hang up whenever … shows up" (PvP tab list).
- Safe rooms: right-click → "Safe room: never start a fight here" (it still fights back).

**Walking & data**
- Restarting remembers the room you were in, so look-alike rooms aren't a guess.
- "No exit" in a dark room → asks the board where you are instead of guessing again.
- **↶ Back** button (and Alt+B): one step back the way you came.
- A closed or locked door on screen helps tell look-alike rooms apart.
- The Golden Phoenix maze's fake links aren't walked.
- What you carry stays current between `i`s: picked up, dropped, sold, worn, removed.
- Your quest flags are read once a session (`abil`) and kept for next time, so routing knows which quest
  gates you've opened before it plans.
- Combat tab: "backstab weapon" — wielded for a `bs`, then your usual weapon again.

**From the second look at pMUD (Great Pyramid and friends)**

- Go to no longer gives up when the only way in is an exit that failed earlier (e.g. the Great Pyramid's 'push block' wall): it tries it again, and a push that didn't work is retried with MME's next wording ('push square block', 'move block').
- Great Pyramid level 4 walks the 22-move path that actually works (`w w n n n n e e s w s s e s e e n n n w
  s u`) — the maze changes as you go, so MME's shortcut doesn't.
- The level 2 doors that "need 1000 picklocks" are timed doors: MudPilot waits and tries again each
  second (up to 2 minutes) instead of picking, bashing and giving up.
- Sea rooms (they throw you somewhere random) are never walked into — the boats are the way across.
- "You lose N experience" comes off the session's exp; "You don't see X here!" means look again.

## 0.8.44

- **Goto by room number.** Type it in the Goto box and press Enter: `12/2002`, `12 2002`,
  `map 12 room 2002`, or just `2002` (the room on the map you're on comes first, the same number on other
  maps listed under it).
- **Goto a party member.** Type the start of their name (`rev`) in the Goto box: MudPilot telepaths them
  `@where` and walks to the room they answer with (works with MegaMUD's answer too).

## 0.8.43

- **Rooms left, counting down.** The step counter in the status bar now shows how many rooms are left
  (Go to: until you get there; a loop: left this lap), and the status says "Going to … — 212 rooms to go".
- **Loading screen.** MudPilot opens on a moonlit keep with a gold progress bar and what it's loading
  (settings, the map, your paths…), builds the window behind it, and then opens full-screen
  (Settings → Other to open it windowed).

## 0.8.42

- **The Great Pyramid routes.** MME has the sphinx answers — they're talk topics on the stone sphinxes
  that open the way up (`ask sphinx fire`, `ask sphinx sun`, `ask sphinx stars`, `ask sphinx e`). MudPilot
  now reads every monster you can talk to the same way (`ask <monster> <topic>`): what opens an exit
  becomes that exit's action, what takes you somewhere becomes a way to go. ~3,300 more rooms reachable.
- **Fixed:** MME's `remoteaction <room> … <exit>` — the last number is *which exit* (0 = N … 8 = up),
  not a map. Room commands now open the right exit.
- **Level 4's arches:** an exit that casts something on you that teleports you away (the pyramid's
  "fail" arch, the Ebon Blade's gloomy teleport) isn't walked; a quest-gated "pass" arch is, if your
  quest flag lets you through.
- **Left behind:** "Revolution is no longer following you" now always holds the walk and goes to get him
  — even if he's still in the room that second (he usually isn't for long). MegaMUD's @where answer
  (`{Eastern Road (Exits: N,NW)}`, no room number) is placed on the map by name and exits, nearest first.
- **No more '@party go path' by default:** MegaMUD followers follow a typed exit by themselves, so saying
  it as well sent Revolution straight back out. Now it's only said for a command a follower didn't follow
  last time (learned), and MudPilot goes to fetch them that time.
- **Hang up on enemies, not everyone.** "Users" (hang up when any player shows up) is off — it had come on
  through the Auto/Manual mode defaults; your saved setting is switched off once. MudPilot hangs up only on
  players marked **Enemy**: right-click their name on the game screen → "Enemy (hang up when they show
  up)", or Game Data → Players.
- **Conversations:** a `/name @where` you type yourself, and the answer to it, show even with bot traffic
  hidden.

## 0.8.41

- **Actions in the Conversations box:** socials — "You spit.", "Revolution grins at you!", "Bob waves at
  Revolution" — show there too (orange), from the game's 64 actions and how each is worded for you,
  someone else and a target. Filters → Actions turns them off.

## 0.8.40

Debugging tools, so a bug can be found from a recording instead of a pasted log (from pMUD):

- **Session recordings.** Every session is quietly recorded to `data\traces` — what the board sent, what
  you and MudPilot sent, the log, and MudPilot's decisions. Passwords never get in: anything typed at a
  password prompt, your saved password, and any password the game prints are written as (hidden); the
  settings copy has your user name, passwords and tokens taken out. Kept to 8 files / 150 MB.
  Settings → Other to turn it off.
- **Help → Save debug bundle (zip for Claude)…** — the last two recordings, today's log, errors, a freeze
  report if any, the diagnostics and your settings (cleaned), in one zip to attach in the chat.
- **Replay.** A recording can be run back through MudPilot offline (`python -m mudpilot.replay <file>`),
  on a virtual clock, and what it sends this time is compared with what it sent then. The same bytes can
  also be fed a line at a time or all at once, to catch bugs that only show up on lag.
- **Fixtures.** A slice of a recording plus what should (or shouldn't) be sent becomes a test that's
  replayed on every test run — a bug fixed from a log stays fixed.
- **Decisions in Copy diagnostics:** the last 25 things MudPilot decided and why — which spell and why,
  each step sent (from, to, how sure of the room), ways round, Eco skips, walls.
- **Window-freeze report:** if the window stops answering for 8 s, where every part of MudPilot was stuck is
  written to `data\ui_freeze.log`, and MudPilot says so when it comes back.
- The log says how long MudPilot took to start.

**And the rest of the pMUD list:**
- **Boats.** MME's paid passages (`secure passage to terra fuego` at 14/759, and the other Tal'kiran
  routes) are routed through: the fare is checked, the voyage counts as its time at sea, and while you're
  aboard the walk waits instead of thinking it's lost — then carries on from the landing.
- **Traps:** Settings → Other → "Disarm traps…" (thieves): `disarm trap <dir>` before a trapped exit,
  wait for "successfully disarmed" (two tries), else walk on through.
- **Bank run for tolls:** short for a toll gate on the path? Off to the nearest bank, withdraw the
  difference, back on the path (once per path per 10 min).
- **Protective gear:** walking into a room MME says casts something nasty on you, while carrying an item
  that negates it → it's put on first.
- **Item rules** (Loot tab → Item rules…): per item `max N`, `keep N`, `drop`, `never`, `get` — and
  nothing is picked up that would put you over your encumbrance.
- **Corpse recovery:** finding your own corpse → `recover corpse <you>`.
- **Quest steps from MME:** every textblock that raises a quest flag is indexed (who to talk to, what to say,
  what it needs). Window → Quests lists your quest flags against them with the next step, and "No route"
  names the step that opens a quest gate. "Read them from the game" also checks your flags (`abil`).
- **Paste box:** pasting several lines into the command line asks where they go (say / gossip / gangpath /
  broadcast / as commands) and sends them one at a time, split at the game's 127-character limit.
- **Right-click the game screen:** Copy, Copy this line, Go to a room the line names (`10/23`,
  `Location: 10,23`), Never attack a monster the line names.
- Remote replies are split at 127 characters (the game cuts longer lines).
- Map data v8 (room spells, items that negate them) — re-imports itself on first start.

## 0.8.39

From a line-by-line comparison with pMUD (all ~476k lines of it), tiers 1 and 2:

**Fixes**
- A prompt someone types into chat (`Vel gossips: [HP=5/MA=0]:`) is no longer read as your HP.
- No reconnect while you're in train stats / the character editor, browsing the BBS menus yourself, or with
  auto-enter off — only a login that's really stuck.
- Spell learning counts every round of a fight, not just the first (the game repeats the spell by itself),
  so MudPilot learns which spells work about 5–10× faster.
- Flux: a late or lost `abil` reply means "don't know yet", never "flux is down" — no more rerolling a good
  flux. A fizzle doesn't count toward "max casts in a row".
- Heals, cures and party blesses wait for the next round instead of colliding with this round's spell.
- Detours have retry limits: a move that fails twice is routed round; an unplaceable room after a move means
  look / `pro`, not the old move again. The way back onto a path honours the avoid list and your keys.
- Hidden exits: `search`, wait for "You found an exit…", search again (3 tries), then go round.
- Ability names like `Conquest1(208)` and `Damage(-MR)(17)` are read.
- After a death, your old inventory is forgotten until the next `i`.
- "Bob moves to attack you!" counts as PvP — the earliest warning there is (your own party's area attacks
  don't).
- Leading: the party check never lapses on a long walk, and MudPilot won't walk on an old one.

**New**
- **Keys:** a locked door with its key in your pack gets `use key <dir>` first, then pick, then bash.
- **Ways round:** a door that won't open, a search that keeps missing or a move that goes nowhere is
  remembered for 30 minutes and routes go round it instead of stopping.
- **Portals with the party:** leading through `go portal` / `dive sinkhole`, MudPilot says
  `@party <command>` first, then waits (up to 30 s) for everyone to turn up on the far side.
- **Aid:** `aid <name>` when a party member drops to the ground bleeding.
- **Party wait** for mana too (below 20% → until 60%), and once waiting, until they're well back up
  (HP to 90%) — no more stop-start. Settings → Party.
- **Another healer's heal** is noticed: no double heal off an old `par`.
- **Stunned:** everything holds until it wears off, then starts fresh.
- **Spell immunity** from MME (immune below level N, nonliving) — no mana thrown at monsters a spell can't
  touch. "Your weapon has no effect" is remembered: no swinging forever.
- **Look-alike rooms:** the twin with an exit back to where you just were, or whose lair holds the monsters
  standing there, wins.
- **Sleep:** if MudPilot was paused for 45 s+ (the PC slept), it drops the line and comes back in fresh
  instead of acting on an old screen.
- **Light ahead:** once you've had to light a dark room, MudPilot lights up *before* walking into rooms MME
  says are that dark.
- **Best spots** uses MME's lair refill delay per lair until it has timed them itself.
- Map data v7 (lair delays) — re-imports itself on first start.

## 0.8.38

- **Best spots tells the truth about bosses.** A boss on a regen timer (Tasloi Village's massive fanged
  spider, 3 h) no longer counts as a kill every lap — it's worth its exp ÷ regen hours, at half that since
  you won't get every spawn. A monster MME limits to one in the realm (the Farmstead Scarecrow,
  GameLimit 1) counts once a lap however many lairs could hold it. Farmstead and Tasloi drop from
  26M and 14M/hr to what you'd really make. The loop builder uses the same numbers.
- **"Starts at" column** in Best spots: the room number and name each loop starts from, to look up in MME.
- **Best spots is about 50× faster** (seconds, not minutes): it was re-reading your whole spell list for
  every lair. Fights pick spells faster too.
- The search window updates safely from the background search, and if the search fails it says so instead
  of staying blank.
- Map data is v6 (monster GameLimit); a board you imported yourself re-imports itself on first start.

## 0.8.37

- **No more double-casting.** The game repeats your attack spell every round, so MudPilot never sends it
  again while it's working: an area spell (esto) keeps going until the fight ends, and a single-target
  spell keeps going while its monster is still here — even if the room list comes back in a different
  order or someone walks in. Before the fight starts, one cast and then a wait for *Combat Engaged*,
  whatever the picker thinks next. (Sending it twice was toggling *Combat Off* / *Combat Engaged* and
  losing the round.)
- Party sync only asks once: a party member on MegaMUD answers `@mpsync hi` with "{command invalid or not
  allowed}" — MudPilot now remembers that for a week instead of asking every session. If they start using
  MudPilot, theirs says hi to yours and syncing starts straight away.

## 0.8.36

- Fix: 0.8.35 wouldn't start once MudPilot had learned an exit from your walking (it wrote to the log
  before the log existed).

## 0.8.35

- **Everything MME's textblocks say is on the map.** A room's commands are now read the way the game runs
  them, all the way down the chain (`text N`, `random N`) — so a command that *casts* a teleport counts too.
  `dive sinkhole` at Scorching Desert, Sinkhole (12/1075) casts *sinkhole* (teleport to 12/2224, level 20+):
  that's the way into the Crumbling Temple, and Go to uses it. 275 command-teleports on Paradigm; from
  Silvermere the router can now reach about 51,000 of 57,600 rooms (it was about 23,000). What's left is
  behind class / race / alignment / quest gates or keys. Needs: level, class, race, items, quest abilities
  and cash are checked; a skill roll or random outcome counts as "a few tries".
- **"No route" explains more:** "opened by typing 'lift portcullis' in 3/909 first", "'go courtyard' needs
  level 60+, ability 126 ≥ 50", and monsters that take you somewhere when you talk to them.
- **Exits read right:** "Level: 64 to 0" means 64 and up (was: never); Ticket/Item exits need the ticket;
  Cast exits (a spell cast on you as you pass) are walked, a little dearer.
- **No more typing into walls.** If a step says `e` but the room on screen has no east exit (48 rooms called
  Rocky Trail…), MudPilot asks the board where it is (`pro`), then takes the map's way to where that step goes.
- **Set talk slow.** "Your command had no effect." after saying `@party go portal` → said again as
  `.@party go portal`, and from then on with the `.`. If the `.` gets said out loud, it's dropped again.
  `pro`'s "Talking speed: Slow" sets it too.
- **Eco travel** (the **Eco** button, Settings → Combat): on the way somewhere (Go to, or a path that isn't a
  loop) walk past bandits, thugs and little spiders. Still fights anything worth the exp (level × 20 by
  default — sandworms at 47, yes; bandits, no), anything that hits harder than 8% of your max HP, and
  everything on you once HP drops below 60%.
- The recover password `pro` prints is shown as (hidden) on screen as well as in logs
  (Settings → Other to show it).
- Map data is v5 — the bundled maps are already updated, and a board you imported yourself re-imports
  itself in the background on first start (about 30 seconds).

## 0.8.34

- **Ways MME's map doesn't have** (the Small Pyramid / Crumbling Temple: MME has no exit in at all): MegaMUD paths that walk them now match anyway — the move MME is missing is bridged to the room the path says comes next — and that move goes on the map, so Go to can use it. Walk one by hand (type the command, end up somewhere MME has no way to) and MudPilot learns it too. Saved per board (`learned_exits.json`). "No route" with nothing blocking now says MME has no way into the area and how to teach it.
- **Named holds** (from pMUD): everything that stops the walk — @wait, a dropped member, a message rule (held), mortally wounded, drift — is held by name, and only that thing lets go. Copy diagnostics lists each one.
- **Arrival placed by the path**: after a step, if the room shown (name + exits) fits the room the path said comes next, that's where we are — look-alike rooms can't send the tracker to a twin. (Not when the tracker saw we stayed put.)
- **Drift policy**: knocked off the path more than 6 times in 5 min (or the same detour 3 times) → stop moving 10 s, look properly, carry on; again within 10 min → stop and say so. Replans at most every 0.8 s.
- **Never re-sent**: a party command (`.@party go portal`) or a toll/fare move that got no answer stops instead of going out again (twice through a portal / paying twice).
- **Doors opened first**: "closed door east" in the exits → `open east` before walking into it; a locked one goes to the pick / bash tries.
- **Kills credited by their own death line**: each exp line goes to the monster named in the death line above it (and that one leaves the room list), so an area spell's three kills land on three monsters, not all on the target.

## 0.8.33

- **MME room commands**: rooms whose hidden exit opens with a command (Small Pyramid, Living Area: `say gazmuldduhaz`) now route — MudPilot says the word and walks through. Map data v4 (re-imports itself; bundled boards updated).
- **Quest-ability exits** ("Ability: 134 w/value 9 to 9999"): when a route is blocked by one, MudPilot asks the game (`abil 134` …) and plans again with your real values. The No route message says what yours is.
- **Mana throttle never drops to a toy spell**: saving mana still picks the cheapest damage per mana, but only among spells doing at least half of the hardest one's damage (no more magic missile at level 47). Spell efficiency gets the same floor, and goes at most 2 steps down (Spells tab).
- **No spell switch mid-fight**: once a spell is going on a monster, a mana-throttle flip doesn't change it (that sent a second cast, restarted the fight with *Combat Off* and lost a round); the new choice starts with the next monster.
- **Resync to the nearest step**: after a hiccup in a loop through look-alike rooms (Rotting Glade, Trail…) it picks the matching step closest to where it was, not one 20 steps back.
- "Rest: up on the tick" no longer fills the log 25 times a second.

## 0.8.32

- **Two MudPilots tune spells together:** when a party member runs MudPilot too (0.8.32+, party sync on), they stop tuning separately. One decides: the party leader if it runs MudPilot, else the first by name. It changes **one caster at a time**: whoever is doing the most damage tries one step weaker for 6 kills while everyone else keeps their spell. It judges the whole party: kill time, and mana per kill added up across both of you (the other MudPilot reports its mana quietly by telepath). Kills nearly as fast for at least 10% less party mana → keep it. Slower → back up, and that step is off the table for 30 min for that caster. When you're both nuking and things die in about a round, that counts as overkill too. In testing it settled on dfir + dfir where magm + magm was overkill, and stayed there. If the other MudPilot leaves or goes quiet, each goes back to tuning alone; a party change starts again from the hardest spells.

- **Spell efficiency reads Paradigm's spell lines properly:** "A withering blast of dragonfire sears drooling geist for 343 damage!" doesn't say whose it is. It now belongs to whoever just gestured ("You make a complex circling gesture!" / "Revolution makes a sweeping gesture!"). Before, dragonfire kills weren't counted at all, so a monster that had been tried on dfir never got judged.
- **Monster variants learn together:** large / nasty / tall … versions ("nasty drooling geist", "large drooling geist") share one tuning, so each step needs about 12 kills of the kind instead of 12 of every variant.
- **No double cast at the start of a fight:** a second `dfir geist` before *Combat Engaged* came back restarted the fight (*Combat Off*) and lost a round. Same for melee.
- **Your spell per monster** (Game Data → Monsters, double-click): pick the spell to hit it with, or melee only, optionally for all its variants. Your choice beats the automatic pick and the learning. A "My spell" column shows what you've set; tick "Only monsters I've set a spell for" to list just those.
- Copy diagnostics shows where spell efficiency stands for each monster.

### Ideas from pMUD (Phrixas's client)

- **Boss hunting / boss farm** (Bosses tab): tick **Hunt** on a boss and MudPilot goes to kill it when its respawn time comes, sends `get all` once it's dead, then goes back to what it was doing (the loop, the path, or the spot it was standing). Several due at once → it does them all, nearest first, before going back. Once per spawn, never more than N steps away, and Stop always wins. New columns: Kills and Next spawn, plus "Next ticked boss: … due in …".
- **Gear modes** (Loot tab): capture what you're wearing as Base / Combat / Rest / Meditate / PvP; MudPilot swaps it by itself (mana-regen gear while meditating, and so on).
- **Bank and shop trips** (Loot tab): at the end of a lap, deposit when carrying N copper, sell listed items at the nearest shop that trades in them, restock supplies ("healing potion 3-10"), then back to the loop.
- **Party comeback** (Party tab): a member drops → the loop waits (5 min by default); when they log back in MudPilot asks them @where, walks there, invites them again and goes back to the loop. Following and the party breaks → you ask the leader `@comeback <your room>`.
- **MegaMUD Messages** (Game Data → Messages): MegaMUD's messages file works in MudPilot. Blind / confused / poisoned / held / diseased come from it (held = no walking until it wears off); "ends combat", "last action failed", "check the room", "wait for it to wear off", "rest to full", "don't rest" and hang-up rules all act. Ships with the 841-entry file pMUD imported (its replies and hang-ups stay off until you press Make them mine or import your own). Death lines MudPilot didn't know land in **Needs review**.
- **Area-spell safety** (Combat tab): no area spells while a player outside the party is in the room, while it isn't sure who's here, or for 5 s after the party breaks. "You have already cast a spell this round!" now waits for the next round.
- **Smarter routes**: class / race / alignment / ability exit gates (when you lead, a class gate has to let the whole party through), toll exits you can afford, traps cost extra so the way round is taken when it's close, spell traps only when much shorter (off by default). Settings → Other → routing.
- **Conversations** redone like pMUD's Chatter: View / Filters / Actions / Font / Colors menus, a Search box with Find Next, timestamps, and a line to type into with **Split ;**.
- **Extras**: sounds per event (Phone alerts tab), scheduled actions (log on/off, relog, go to, loop, command — Window menu), track a player with `trac` (Window menu), XP leaderboard of everyone's exp/hr from `top 200`, quests pages (`? questlist`, `? questflags`), and a Magic 8-Ball for gossip (off by default).

### Fixes from pMUD's year of real-game testing

- Party rows with no mana bar (Kai classes), negative HP or `[Invited]` no longer wipe the whole party list; "Your party has been disbanded." and "X is no longer following you." update it.
- "Deacon*" in *Also here* is the party member Deacon (the `*` made him look like a stranger — area spells were always blocked and "hang up on players" could hang up on him).
- A failed `look <dir>` no longer swallows the next real move.
- Exit lists that wrap onto a second line are read whole; a dark room with no title keeps the place the move led to.
- Refused moves also include "A strange power holds you back", "You fumble in confusion!", "You look around stupidly…" — no more false steps.
- The party-follow line "-- Following your Party leader north --" moves a follower's map with the leader.
- Sneak: a move that arrives without "Sneaking..." means sneak was lost; "You don't think you're sneaking." too.
- Chat can't fake the game any more ("Bob gossips: you have been killed" isn't your death); 0-exp lines aren't kills; every exp line triggers a fresh look.
- Negative-HP prompts (mortally wounded) are read; jail ("dragged off to jail") drops the planned move.
- More monster arrivals/departures noticed ("thunders in from the east", "suddenly forms beside you", "out of the room to the west").
- Party damage no longer counts as your spell's damage when learning spell damage; "Bob casts merciful grace upon you!" isn't PvP; invites "to follow him" are invites; "You took …" counts as a pick-up; the who list drops the trailing V/S flag from gangs.
- Quiet line check: a minute with nothing coming in → a bare Enter; no answer in 20 s → reconnect. Stuck at the menu 45 s → reconnect.
- A death clears every queued goto, detour, errand, summon, boss hunt, trip, re-invite and comeback.

## 0.8.31

- **Invite → @join uses the full name:** after `invite re`, MudPilot waits for "You have invited Revolution to follow you." and telepaths `/Revolution @join`, so a short name can't land on the wrong player (Reveal).
- **Spell efficiency** (Combat → Spells, on by default): every monster starts on your hardest-hitting spell. When you're doing ≥75% of the damage (the party hardly gets a swing in because things die to your nuke), it tries the next weaker spell on that monster for 6 kills. Nearly as fast (≤15% slower) for ≥10% less mana → it keeps it, and may try weaker still. Slower → back up, and that spell is left alone for 30 min. Dangerous fights, bosses and a party change always go back to the hardest spell. The Log says each switch and why.
- **One move at a time:** after a step goes out, MudPilot waits for the game to answer (new room, or "you can't go that way") before sending anything else — at most 10 s, then it looks and carries on. Fixes `go hole` being sent 10× on a laggy realm. If the same move from the same room gets nowhere 4 times it looks around; 8 times, it stops and says so.
- **Low-HP hang-up fires once:** coming back in still under the line doesn't hang up again straight away; it re-arms once HP is back over it (falling another 10% meanwhile still hangs up).
- **PvP covers the whole party:** a player hitting anyone in your party ("Bob backstabs Revolution for 400 damage!") hangs you up too — before the next combat round. If they killed him, MudPilot sends `get all` (PvP tab, "Party member killed: grab first") and then hangs up, still before the next round.
- **@pvp on / @pvp off** (from a party member, Settings permission): on = fight back and defend the party, no PvP hang-up (the low-HP hang-up still works); off = hang up on PvP against anyone in the party. `@pvp` alone says which.
- **Re-invites your party** after a drop or hang-up (Connection tab, on by default): whoever was following you gets `invite`, then the @join telepath.
- **Locked doors you can bash** (green metal key…) no longer block Go to/loops when you don't carry the key — it walks and bashes. Off: Settings → Other → routing.
- **No more `sn` spam** with monsters in the room (the game won't let you sneak then).
- **Help → Copy diagnostics** (Ctrl+Shift+D): one paste with why it isn't moving, the route, log and screen (passwords hidden).

## 0.8.30

- **Go to reads your keys first:** if MudPilot hasn't seen your inventory yet, it types `i` before planning, so doors your keys open (Thrag's green metal key…) count. Before, it could give up on the spot.
- **No route = a pop-up saying why** (which exit, which key), not just a log line.
- **MME's odd action counts** ("Needs 1278 Actions" on the Gigantic Cavern passage) no longer lock an exit whose action is listed (pull switch).
- A closed Path builder can't swallow Go to clicks any more; any error planning a route pops up instead of failing silently.

## 0.8.29

- **Fix — map data upgrade on Windows:** the check that swaps in the new map data could misread the version on paths with spaces (e.g. "Claude projects") and skip the upgrade, so goto/loop still couldn't get out of Rotting Glade. It reads the file header now, and an old map re-imports itself in the background if its MME file is still around. The Log tab says which map data is in use ("Map data: … data v3, 299 exit actions").
- **Analyze a loop** (Paths → right-click a loop, or More → Analyze selected loop…): room by room, what spawns, how much it could hurt you, HP needed, risk, bosses/traps/locked exits, exp/hr.
- **Best spots for me** (Paths → More): ranks the hunting areas you can reach for your character and party, builds a loop in each, calibrated on your own loops. Build loop & go.
- **@where** always says map and room number; **@ac** reports AC/DR from `stat all` (vs evil/good, blesses on).
- **`pro` → yellow "You are in map 1 room 1810 — name" line in Conversations.**
- **Passwords the game prints (`pro` shows Recover Password) are never kept** in the timeline, death replays or reports.

## 0.8.28

- **Fix — Go to from Rotting Glade (and ~190 other places):** MME keeps the action that opens some hidden exits (e.g. *pull lever* at Small Chamber 10/4) in a spare column; MudPilot now imports those, routes through them and types the action first. The bundled Paradigm/Stock map data is rebuilt (your old copy is kept as world.db.old).
- **No route?** It now says so on screen and names the exit in the way, instead of sitting idle.
- **Goto list:** each room once (no more "Bank of Godfrey-1 297-1 297").

- **Auto-tune is a fair test now:** each trial starts in the loop's first room at full HP and mana (getting there and topping up isn't timed), runs whole laps (when time's up it finishes the lap), and whatever it ends short of full is charged as resting time. Rotation pauses during a test.
- **Help → Remote @ commands:** every @ command with an example.

## 0.8.26

- **Loop builder** (Paths → More → Build a loop from the map…): loops through the best lairs near a room, straight from the MME map, with a rough exp/hr each. Save, or save and run.
- **Danger check** (Combat tab, on): learns what each lair really costs you in HP; before a lair it rests to enough HP first (optionally stops if even full isn't enough). MME's numbers alone only give a heads-up.
- **Dangerous fight opener** (Combat tab): curse first (e.g. `mist`) when a fight looks dangerous — expected damage ≥ X% of your HP, 3+ monsters, or a boss — then the hardest-hitting spells.
- **Loop advisor:** every 10 laps, and at the top of Loop stats: better loops at your level, this loop's trend, empty lairs, deaths, what a built loop could do.
- **Gear upgrade alerts** (Loot tab): armour better than yours, seen or picked up; optional pick up / wear.
- **Party sync** (Party tab, on): MudPilots in a party share rest/HP/mana and rest together.
- **Timeline** (Window → Timeline): what it was doing minute by minute, events, click for the screen at that moment.
- **Death replays** (Window → Deaths): HP over the last minute, who hit you, and what might have saved it.
- **Sync between PCs** (General tab): characters, settings, paths and everything learned, merged through a shared folder.
- **Command line:** `;` = Enter (`e;mist;.@do sand;simp dragon`), `;;` = a real `;`. Also works in the conversation box. `@do` with `^M` runs each part.
- **Fix:** your own telepaths show their text in Conversations even when you shorten the name (`/phrix …`).

## 0.8.25

- **Auto-tune resting** (Health tab → Auto-tune resting…): tries your rest settings, "rest less often", "rest longer" and both, 30 min of looping each, and keeps the one that made the most exp/hr. Safe HP floor; a death or closing MudPilot mid-test restores your own settings.
- **Lair pacing** (Health tab → On a loop): learns how long each lair takes to refill; if the next one isn't ready and you're not full, rests here meanwhile.
- **Loop rotation** (Paths → More → Loop rotation…): rotate between loops when a lap's lairs come up mostly empty, or every N laps. Exp/hr keeps counting.
- **Lag meter:** 10-minute average / worst board response in Stats; a log note when the board's been slow.
- **Phone control** (Phone alerts tab, off by default): type status, stop or hang up in the ntfy app.
- **After a death** (Health tab): stop and stay put, or hang up. Never walks the loop again by itself; your phone gets where and what killed you.
- **History** (Window → History): exp/hr by day and by loop, with a chart.
- **@summon** (needs "Move me" on the Talk tab for that player): `@summon 10 297` sends a MudPilot there; plain `/Name @summon` adds your room automatically.

## 0.8.23 — overnight runs

- **Auto-reconnect** after a dropped line: reconnects in the background (no frozen window), backs off up to 5 min between tries, logs in, enters the realm and carries on with the loop. A line that goes silent (sent a command, no reply for 90 s) is dropped and reconnected too. Never after a hang-up or Disconnect. Settings → BBS.
- **Rest diagnosis:** every rest is logged — why it sat down (HP / mana / waiting on someone), how long, what it got back, why it got up. Stats → *Why it rested* and *Rest log…*; also in reports.
- **Smarter resting** (Health tab): learns the regen tick; gets up on the tick when it's only a sliver short; solo, takes one more tick when that fills you up.
- **Mana throttle** (Health tab, on): near the mana rest line it uses the most mana-efficient spells (0.8.207: it still stops at the line).
- **Attack on room entry** (Combat tab, on): walking into hostile monsters, the attack goes out first.
- **Leader watch** (Party tab, on): following someone who drops/logs off, or getting left behind — waits, rests up and tells your phone.
- **Phone alerts tab:** all ntfy alerts in one place, plus the **stuck watchdog** (off by default), the **morning summary** (off by default) and **boss due back** warnings.
- **Daily log file** in `data\logs` (kept two weeks).

## 0.8

- **Bundled boards:** Paradigm (default) and Stock MME data come with MudPilot (`MME data\` has the original files). Put MegaMUD paths in `data\boards\Paradigm\paths` (or `Stock\paths`); subfolders are fine.
- **Layout:** MUD window two-thirds of the width; conversations top-right and map bottom-right, half each. Drag to resize (remembered), **Minimize** the map panel, pop the map into its own window, Window → Reset layout.
- **Fonts:** Options → Font… for the MUD window and the conversation box.
- **Map:** regen rooms red, trap rooms with a yellow **!**; hover for spawns and trap damage.
- **Conversations:** MegaMUD colours and wording, enter/exit/disconnect lines, every channel toggleable.
- **Status bar:** path file, step, lag, what it's doing (resting/meditating to full, waiting for a party member, fighting), loop and lap, exp/hr and mana per tick. The Party box marks the leader (★) and who the leader is waiting on.
- **Responses (Settings → Responses):** team commands such as `br nuke`, `br bs Bob`, sneak, hide, hold, track and attack, triggered by your party/Friends only by default; track alerts tell the team (broadcast, gangpath, say or party telepath) when you track players.
- **Combat calculator (Window menu):** your melee and spells against a monster, how hard it hits you (MME's monster attack simulator) and rounds to kill or be killed.
- **Cat-proof keyboard:** keys pressed on the MUD screen or map go to the command line. Nothing stops the bot or the output.

## Config profiles

Options → **Config Profile 1–4** (Alt+1…Alt+4), like MegaMUD. Each holds a full set of options — combat, spells, bless, health, loot, PvP. Example: Profile 1 "Solo" with PvP hang-ups on; Profile 2 "Group" with them off so five of you don't all hang up when three enemies walk in. Switching keeps who you are, where you connect, your macros, events and learned spells. Rename with Options → Rename this config profile.

## Macros

Game Data → **Macros**. F1–F12 (with Shift/Ctrl) and the number pad. `^M` is Enter: `n^Ml n^M` walks north and looks north; text after the last `^M` stays in the input box for you to finish. **Char** macros belong to one character, **Def** macros to all of them; the number pad starts with MegaMUD's layout (8 = n, 2 = s, 0 = u, . = d, + = rest…). Macros in a MegaMUD .ini are imported with the character.

## Players

MudPilot keeps a player list per board (Game Data → Players): relationship (Friend / Enemy / Neutral / Unknown), class, race, when last seen, and what they were last seen wearing. It learns gear by looking at a player **at most once per day** (settable) — players in shadow form show nothing, and MudPilot still won't look again until the day is up. Tick **Don't look** for anyone you never want looked at, or **Alert** to be told when they show up. The remote-control boxes there are the same as the Talk tab's.

## Chat

The **Chat** tab collects gossip, telepaths, says, gangpaths, broadcasts, auctions and yells, with filters and a send box. Chat is also saved to `data\chat\<date>.log` on your PC.

## Bosses

The **Bosses** tab tracks every MME boss (monsters with a respawn timer and a spawn room, 247 in stock data). Kills are recorded automatically when a boss you were fighting is gone after the experience comes in; sightings are recorded whenever one is in your room. It shows time until respawn, alerts you (sound + log) when one should be back, and **Go to spawn** walks you to the nearest spawn room. Timers are shared by all your characters and survive restarts.

## Files

Everything lives next to the app in `data\`: `boards\<board>\` (that board's `world.db` MME data, `paths\` and `bosses.json`), `profiles\` (one file per character), `chat\` (chat logs). Passwords are only in Windows Credential Manager.
