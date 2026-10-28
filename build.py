"""One-shot release build: PyInstaller (onedir) -> Inno Setup installer.

    python build.py

Produces installer_output/PiiBlur_Setup.exe and prints its size + SHA-256.
Version is read from pii_blur.__version__.
"""
import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pii_blur import __version__ as VERSION  # noqa: E402

ISCC_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def find_iscc():
    for p in ISCC_CANDIDATES:
        if os.path.exists(p):
            return p
    found = shutil.which("ISCC")
    if found:
        return found
    sys.exit("ISCC.exe (Inno Setup 6) not found — install it or edit ISCC_CANDIDATES.")


def run(cmd):
    print("\n>>>", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"Step failed (exit {r.returncode}).")


def main():
    print(f"=== Building PiiBlur v{VERSION} ===", flush=True)
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

    run([sys.executable, "-m", "PyInstaller", "PiiBlur.spec", "--noconfirm", "--log-level", "WARN"])
    folder = os.path.join(ROOT, "dist", "PiiBlur")
    if not os.path.exists(os.path.join(folder, "PiiBlur.exe")):
        sys.exit("PyInstaller finished but dist/PiiBlur/PiiBlur.exe is missing.")

    run([find_iscc(), f"/DAppVer={VERSION}", "installer.iss"])
    installer = os.path.join(ROOT, "installer_output", "PiiBlur_Setup.exe")
    if not os.path.exists(installer):
        sys.exit("ISCC finished but the installer is missing.")

    data = open(installer, "rb").read()
    folder_mb = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fs in os.walk(folder) for f in fs
    ) / 1_048_576
    print("\n=== DONE ===")
    print("Installer:   ", installer)
    print("Installer MB:", f"{len(data) / 1_048_576:.1f}")
    print("Installed MB:", f"{folder_mb:.1f}")
    print("SHA-256:     ", hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
