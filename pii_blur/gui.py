"""Minimal settings window (tkinter, stdlib — no extra dependency).

Opened from the tray menu. Edits the live Settings object AND saves to disk, so
changes take effect immediately and survive a restart. Deliberately tiny: the
tray is the real interface; this is just the knobs.
"""
from __future__ import annotations

from pii_blur import autostart, settings_store
from pii_blur.config import Settings


def open_settings(settings: Settings) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("PiiBlur — Settings")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    pad = {"padx": 12, "pady": 6}
    frm = ttk.Frame(root)
    frm.grid(sticky="nsew")

    auto_v = tk.BooleanVar(value=settings.auto)
    names_v = tk.BooleanVar(value=settings.detect_names)
    model_v = tk.BooleanVar(value=settings.name_model)
    faces_v = tk.BooleanVar(value=settings.blur_faces)
    start_v = tk.BooleanVar(value=_safe(autostart.is_enabled))
    strength_v = tk.IntVar(value=settings.blur_strength)

    ttk.Label(frm, text="PiiBlur", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, **pad)
    ttk.Checkbutton(frm, text="Automatic (silent) mode", variable=auto_v).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
    ttk.Checkbutton(frm, text="Blur names too (fuzzy)", variable=names_v).grid(row=2, column=0, columnspan=2, sticky="w", **pad)
    ttk.Checkbutton(frm, text="Smart name model (AI, catches unlisted names)", variable=model_v).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
    ttk.Checkbutton(frm, text="Blur faces", variable=faces_v).grid(row=4, column=0, columnspan=2, sticky="w", **pad)
    ttk.Checkbutton(frm, text="Start with Windows", variable=start_v).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
    ttk.Label(frm, text="Blur strength").grid(row=6, column=0, sticky="w", **pad)
    ttk.Scale(frm, from_=6, to=24, variable=strength_v, orient="horizontal", length=160).grid(row=6, column=1, **pad)

    def save_close():
        settings.auto = auto_v.get()
        settings.detect_names = names_v.get()
        settings.name_model = model_v.get()
        settings.blur_faces = faces_v.get()
        settings.blur_strength = int(strength_v.get())
        settings_store.save(settings)
        if start_v.get():
            _safe(autostart.enable)
        else:
            _safe(autostart.disable)
        root.destroy()

    ttk.Button(frm, text="Save", command=save_close).grid(row=7, column=1, sticky="e", **pad)
    ttk.Button(frm, text="Cancel", command=root.destroy).grid(row=7, column=0, sticky="w", **pad)

    root.update_idletasks()
    root.mainloop()


def _safe(fn):
    try:
        return fn()
    except Exception:
        return False
