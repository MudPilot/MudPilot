#!/bin/sh
# MudPilot at the top of the Linux install: opens the newest compiled version in app/<version>/ (the launcher
# there does the rest), passing on any arguments ('--data PVE'). A version named in data/control/skip-versions.txt
# is passed over (one that crashed on install). The Linux twin of starter.c.
root=$(cd "$(dirname "$0")" && pwd)
skip="$root/data/control/skip-versions.txt"
best=""
for d in "$root"/app/*/; do
    v=$(basename "$d")
    case "$v" in *[!0-9.]*|"") continue ;; esac
    [ -x "$d/MudPilot" ] || continue
    if [ -f "$skip" ] && grep -qx "$v" "$skip" 2>/dev/null; then continue; fi
    if [ -z "$best" ] || [ "$(printf '%s\n%s\n' "$best" "$v" | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | tail -n1)" = "$v" ]; then
        best=$v
    fi
done
if [ -z "$best" ]; then
    msg="MudPilot isn't installed properly: there's no app folder next to this file. Unzip the whole MudPilot download again."
    if [ "$(uname)" = Darwin ]; then
        osascript -e "display alert \"MudPilot\" message \"$msg\" as critical" >/dev/null 2>&1 || echo "$msg" >&2
    else
        command -v zenity >/dev/null 2>&1 && zenity --error --title=MudPilot --text="$msg" 2>/dev/null || echo "$msg" >&2
    fi
    exit 1
fi
cd "$root" && exec "$root/app/$best/MudPilot" -m mudpilot.launcher "$@"
