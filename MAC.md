# MudPilot on a Mac

MudPilot runs on macOS 11 (Big Sur) or newer. There are two downloads on the [Releases](https://github.com/MudPilot/MudPilot/releases/latest) page, so pick the one for your Mac:

- **MudPilot-x.y.z-mac-arm64.zip** is for Apple Silicon Macs: M1, M2, M3, M4 and newer.
- **MudPilot-x.y.z-mac-x64.zip** is for older Intel Macs.

To check which one you have, open the Apple menu → **About This Mac**. If it says "Chip: Apple M…", get arm64. If it says "Processor: Intel", get x64.

## Install

1. Download the zip and double-click it in Downloads. You get a **MudPilot** folder.
2. Move that folder to your home folder (the one with your name, so it ends up at `~/MudPilot`). Don't keep it in Downloads, or in a Desktop or Documents folder that iCloud syncs.

## First launch

MudPilot isn't signed with a paid Apple developer certificate, so macOS blocks it at first. Do this once:

1. Open **Terminal** (Applications → Utilities) and paste in this line:

   ```
   xattr -dr com.apple.quarantine ~/MudPilot
   ```

   This removes the "downloaded from the internet" mark from MudPilot's files. It doesn't change any of your Mac's security settings.
2. In Finder, double-click **MudPilot** inside the MudPilot folder.

If you'd rather not use Terminal, right-click **MudPilot** and choose **Open**, then click **Open** again. On macOS 15 (Sequoia) or newer, or if macOS blocks the app inside the folder too, open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to the MudPilot message. You may have to do this more than once. The Terminal line above avoids all of that.

A Terminal window opens along with MudPilot. **Leave it open** (you can minimise it), because closing it closes MudPilot.

## Where your things live

- **Settings, characters, paths, logs:** the `data` folder inside your MudPilot folder (`~/MudPilot/data`). Back that folder up to keep everything. A second character set (`--data PVE`) lives in `data-PVE` beside it.
- **Saved passwords:** in your Mac's **Keychain**, not in a file. The first time, macOS asks whether MudPilot may use the keychain. Click **Always Allow**.
- **MegaMUD files:** to import a character or paths from MegaMUD, copy your `MegaMUD\Chars` folder over from the Windows PC first, then pick the files from where you put them.

## Updating

MudPilot tells you when a new version is out. Click **Update** and it downloads the right Mac zip for you, then installs it the next time MudPilot restarts. Your `data` folder isn't touched.

To update by hand instead (or if the Update button doesn't work for you):

1. Download the new Mac zip for your Mac (arm64 or x64).
2. In Terminal, run the line for your Mac:

   ```
   unzip -o ~/Downloads/MudPilot-*-mac-arm64.zip -d ~ && xattr -dr com.apple.quarantine ~/MudPilot
   ```

   (Intel Macs: put `mac-x64` in place of `mac-arm64`. Keep only the newest Mac zip in Downloads.)
3. Close MudPilot and open it again. Your `data` folder isn't touched, and the new version sits beside the old one in `MudPilot/app`.

## Problems?

Use **Help → Report a problem** inside MudPilot, or ask in #bug-reports on the MudPilot Discord. Say that you're on a Mac.
