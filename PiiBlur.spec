# PyInstaller spec — builds a self-contained PiiBlur.exe (Python + all libs +
# the OCR models inside). Nothing to install on the target machine.
#
#   build:  pyinstaller PiiBlur.spec --noconfirm
#   result: dist/PiiBlur.exe
#
# console=False -> no console window (silent tray). Set True to see CLI output
# while debugging (`PiiBlur.exe file in.png out.png`).

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Bundle RapidOCR + its ONNX runtime AND the model files, so OCR works offline
# with nothing to download on first run. winocr + winrt are the FAST primary path
# (native Windows OCR, reads Cyrillic); if winrt can't be bundled on a given setup
# the app simply falls back to RapidOCR at runtime, so this stays best-effort.
for pkg in ("rapidocr_onnxruntime", "onnxruntime", "winocr", "winrt"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass
try:
    hiddenimports += collect_submodules("winrt")
except Exception:
    pass

# Face blurring (pii_blur.faces) needs OpenCV's Haar cascade XML files — these are
# plain data files inside the cv2 package that PyInstaller doesn't pick up unless
# told to, so bundle cv2's own data folder explicitly.
try:
    import os as _os_cv
    import cv2
    datas.append((cv2.data.haarcascades, _os_cv.path.join("cv2", "data")))
except Exception:
    pass

hiddenimports += [
    "win32clipboard", "win32gui", "win32con", "win32event", "win32api", "winerror",
    "pystray._win32",
    "PIL.Image", "PIL.ImageGrab", "PIL.ImageFilter",
    "tkinter", "tkinter.ttk",
]
hiddenimports += collect_submodules("pii_blur")

# Ship the MSVC runtime DLLs so a clean machine without the VC++ Redistributable
# doesn't throw "DLL load failed" (a very common end-user crash with onnxruntime).
import glob as _glob, os as _os, sys as _sys
for _dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"):
    for _base in (_os.path.join(_sys.base_prefix), r"C:\Windows\System32"):
        _hits = _glob.glob(_os.path.join(_base, "**", _dll), recursive=True)
        if _hits:
            binaries.append((_hits[0], "."))
            break

# Heavy libraries nothing here uses — excluded so a transitive import can't bloat
# the build. (RapidOCR's real deps — numpy, opencv, onnxruntime — are kept.)
_HEAVY = ["matplotlib", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6",
          "IPython", "notebook", "pytest", "tornado", "sympy", "scipy.spatial.cKDTree"]

# Bundle the tray/app icon so the tray shows the real icon at runtime.
if _os.path.exists("app_icon.png"):
    datas.append(("app_icon.png", "."))

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["regex"] + _HEAVY,  # trim heavy unused libs (winocr/winrt now bundled)
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ONEDIR build: a folder (dist/PiiBlur/) that Inno Setup compresses hard (lzma2).
# This makes the *installer* small (~100-130MB) even though the installed folder
# is ~280MB — far better than a onefile exe, and it starts faster.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PiiBlur",
    debug=False,
    strip=False,
    upx=False,              # UPX makes antivirus flag the exe harder — off on purpose
    console=False,          # silent tray; set True to debug the CLI
    disable_windowed_traceback=False,
    icon="app_icon.ico" if __import__("os").path.exists("app_icon.ico") else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="PiiBlur",
)
