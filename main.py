"""Single entry point for the bundled .exe.

No arguments  -> run the tray app (the normal double-click use).
With arguments -> run the CLI (`PiiBlur.exe file in.png out.png`, `… watch`).

crashguard is installed FIRST (it only imports stdlib), so even a DLL-load failure
while importing PIL/onnxruntime becomes a logged line + a clean message box —
never the raw 'Unhandled exception in script' dialog.
"""
import sys
import traceback


def run():
    from pii_blur import crashguard
    crashguard.install()
    try:
        if len(sys.argv) > 1:
            from pii_blur.app import main
            sys.exit(main())
        from pii_blur.tray import main as tray_main
        tray_main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        crashguard._write("STARTUP", tb)
        _friendly_box(tb)
        sys.exit(1)


def _friendly_box(tb: str) -> None:
    """A clean 'couldn't start' dialog instead of a scary traceback window."""
    try:
        import ctypes

        last = (tb.strip().splitlines() or ["Unknown error"])[-1][:400]
        msg = ("PiiBlur couldn't start.\n\n" + last +
               "\n\nDetails were saved to:\n%APPDATA%\\PiiBlur\\logs\\crash.log")
        ctypes.windll.user32.MessageBoxW(0, msg, "PiiBlur", 0x10)  # MB_ICONERROR
    except Exception:
        pass


if __name__ == "__main__":
    run()
