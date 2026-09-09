# Taskbar / Start crash — 2026-09-09

Windows 11 25H2 (build 26200.6584). ProductName still reports "Windows 10 Pro".

## What happened

Pressing the Windows key made Start fail and the taskbar vanish. Restarting Explorer alone did not bring the bar back. Hovering the empty strip later showed the wait cursor (spinning wheel).

The Win32 taskbar windows were still there (`Shell_TrayWnd` at the bottom of each monitor, ~48px reserved in the working area). They were empty: no Start button, icons, or clock. On Windows 11 those controls are XAML, hosted through `StartMenuExperienceHost.exe` and Explorer. When that host dies or Explorer hangs, you get a blank bar that still hits-tests.

## Layout at the time

- 3× MSI MAG 255XF at 1920×1080 (primary + left + right)
- 1× TCL “Beyond TV” (`TCL9653`) at 3840×2160, 300% scale (logical 1280×720)
- TV was placed far off-grid: about `(-5760, -2097)`, then Y was moved to `0`, then the display was detached from the desktop
- NVIDIA RTX 5080 still enumerated the TV as a 4K output even in standby. AMD iGPU had no mode.
- The TV does not power off; it stays in HDMI standby and keeps EDID alive, so Windows still treats it as a monitor

## Crash signature

```
Faulting application: StartMenuExperienceHost.exe  10.0.26100.5074
Faulting module:     Windows.UI.Xaml.dll           10.0.26100.5074
Exception:           0xc0000409  (STATUS_STACK_BUFFER_OVERRUN / fail-fast)
Fault offset:        0x690cee
```

AppX package version was **10.0.26100.4768** while the running binary was **10.0.26100.5074** (version skew).

Explorer also hung (`Application Hang` on `explorer.exe`) when Start was opened. After several cycles, **every new Explorer hung within seconds** (`Responding=False`, `IsHungAppWindow=True`). Threads were mostly `UserRequest` plus `LpcReply` — waiting on another process / XAML activation.

At one point a **Search** `Windows.UI.Core.CoreWindow` was visible full-screen `(0,0)-(1920,1080)` and the taskbar XAML island (`DesktopWindowXamlSource`) was **1×1 pixel**. That matches “invisible bar + Win key does nothing.”

## What we tried

| Action | Result |
|---|---|
| Restart Explorer only | Blank bar came back; no icons. Does not recover dead XAML. |
| Kill/restart `StartMenuExperienceHost`, `ShellExperienceHost`, `SearchHost` | Host often died immediately with `0xc0000409` / exit `-1073740791` |
| Launch Start exe raw vs AppX activation | Both crashed. COM activation hung. |
| `Reset-AppxPackage` + re-register Start | Reset succeeded once; Start still crashed. Later resets hung. |
| `Reset-AppxPackage` on `MicrosoftWindows.Client.CBS` | Hung (Explorer had the package locked) |
| Disable transparency (`EnableTransparency=0`) | Still crashed. **This registry value is still off.** |
| Move TV from `Y=-2097` to `Y=0` | Better geometry; not enough by itself |
| **Detach TCL (DISPLAY1) from the desktop** | Needed. Start could stay alive afterward. |
| **Ctrl+Win+Shift+B (GPU reset) + kill full shell + start Explorer + start StartMenu host** | **This is what restored a painted taskbar once.** |
| Press Windows key after restore | Start opened, crashed, bar went blank again |
| Delete Start `LocalState` / `TempState` / `AC` / `LocalCache` | **Made it worse.** Start then crashed on launch, not only on open. Folders were recreated empty; that did not fully recover state. |
| Resize XAML island / show Win32 tray children | Did not paint. May have contributed to Explorer hanging. |
| Recycle `sihost` + DWM + Explorer | New Explorer still hung in this session |
| Emergency PowerShell taskbar | Process ran; form never appeared (MTA/STA / script issues). Files left in `%TEMP%`. |
| Set `NoWinKeys` | Access denied |
| Sign-out / reboot | Not done yet (this note is for after reboot) |

## What actually worked

The only in-session restore that painted a real taskbar (Start, search, pins, clock):

1. TCL detached from the Windows desktop (not just “standby”)
2. GPU reset: **Ctrl + Win + Shift + B**
3. Kill `SearchHost`, `ShellExperienceHost`, `StartMenuExperienceHost`, `ShellHost`, `explorer`
4. Start `explorer.exe`
5. Start `StartMenuExperienceHost.exe`
6. **Do not press the Windows key**

That held until Start was opened again.

Explorer-only restarts never restored the painted bar once XAML was dead.

After the Start cache wipe, that same sequence could keep the host process up sometimes, but the bar stayed empty and Explorer started hanging on every launch. At that point only a **new logon** (sign-out or reboot) can rebuild the shell.

## Hypothesis

1. **Primary trigger:** mixed-DPI multi-monitor + a 4K TCL that never really disconnects. The TV sat at a broken origin (`Y=-2097`, 300% scale). Pressing Win makes Start/XAML measure every display. That hit a fail-fast in `Windows.UI.Xaml.dll` (`0xc0000409`).
2. **Why the bar vanished:** Win11 taskbar chrome is XAML. When `StartMenuExperienceHost` dies (or Explorer deadlocks waiting on it), the tray window remains but draws nothing. Hover → wait cursor because Explorer’s UI thread is hung.
3. **Why Explorer restart “did nothing”:** it recreates the empty Win32 tray, then blocks again on the same broken Start/XAML init. After enough crashes, the session stays wedged (LPC wait / crash backoff).
4. **Why the TV matters even “off”:** TCL standby still presents EDID. NVIDIA kept a 3840×2160 path. Windows still saw `TCL9653` as `Active=True`.
5. **Secondary issue:** Start package **4768** vs binary **5074** may have made the XAML host more fragile.

## After reboot — check these

- Transparency is **off** (`HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\EnableTransparency=0`). Turn it back on in Settings → Personalization → Colors if you want it.
- TCL may come back as a fourth display. If Start/taskbar dies again after Win:
  - Unplug HDMI when the TV is unused, or
  - Disable HDMI-CEC / T-Link and Instant On / Fast Start on the TCL, then power it down for real
- Start menu local cache was wiped. A new sign-in should recreate it. If Start is empty or crashy, that is why.
- Leftover scripts (safe to delete):
  - `%TEMP%\emergency-taskbar.ps1`
  - `%TEMP%\taskbar-check*.png`

## If it happens again

1. Do **not** mash Win. That is what blanks the bar.
2. Detach or unplug the TCL first.
3. Use the restore sequence above (GPU reset + full shell kill + Explorer + Start host).
4. If hover shows a spinner and new Explorers hang immediately, **sign out**. Do not wipe Start `LocalState` again.
5. Task Manager without a taskbar: **Ctrl+Shift+Esc** → File → Run new task.
