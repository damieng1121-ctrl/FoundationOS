# Stoa Check (for Windows)

"Will my stuff work on Stoa?" - run this on a Windows 10 or 11 PC before switching.

1. Double-click **Stoa Check.cmd** (it's also on every Stoa USB stick, in *Stoa Check (run on Windows)*).
   For TPM, Secure Boot and BitLocker details, right-click it and choose **Run as administrator**.
2. A report opens in your browser and is saved to the Desktop as **Stoa readiness report.html**:
   - **Hardware:** memory, graphics, free space, Secure Boot, BitLocker and Fast Startup, with what to change.
   - **Apps:** each installed app and its Stoa version, a built-in equivalent or the closest alternative.
   - **Steam games:** ratings from ProtonDB player reports and AreWeAntiCheatYet.
   - **Printers and gaming gear:** Razer, Logitech, Corsair, SteelSeries and controllers.
3. **Stoa-plan.json** is saved next to it. After installing Stoa, *Move from Windows* finds it and installs
   the same apps for you.

Nothing on the PC is changed. The only network requests are the public game-rating look-ups.
