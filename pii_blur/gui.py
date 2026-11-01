"""Settings window, built on ttkbootstrap (a themed layer over stdlib tkinter/
ttk — MIT-licensed, ~550KB, pure Python).

Opened from the tray menu via `request_open()`. A SINGLE window is built once
(in its own dedicated thread, started once from tray.py) and reused for the
rest of the app's life, shown/hidden rather than recreated — ttkbootstrap
explicitly does not support creating more than one root window per process
("ttkbootstrap supports a single application root window"); the earlier
version built a fresh `tb.Window()` on every click, which crashed with that
exact error on the second open (silently, since it ran on a daemon thread —
from the user's side, clicking "Settings" just did nothing).

Plain tkinter's checkbox glyph (the little square indicator) renders in a
dated, Windows-95-era style that no amount of border/background tweaking on
the SURROUNDING widget can change -- it's the glyph itself, drawn natively.
The toggle switches here are hand-drawn on a small Canvas (see
`_toggle_switch`) rather than ttkbootstrap's own "round-toggle" Checkbutton
variant -- that one's knob renders in the SURFACE colour by design (a
deliberate "cut-out" look in its own source), which read as a stray dark
dot to real users; drawing it ourselves gives a conventional white knob with
no further fighting the library's style engine.
"""
from __future__ import annotations

import logging
import queue
import threading

from pii_blur import autostart, i18n, settings_store
from pii_blur.config import Settings

logger = logging.getLogger(__name__)

_QUEUE: "queue.Queue | None" = None
_THREAD: threading.Thread | None = None


def _toggle_switch(parent, variable, bg: str, on_color: str, off_color: str, command=None):
    """A hand-drawn toggle switch (pill track + round knob) -- NOT
    ttkbootstrap's "round-toggle" Checkbutton. That one renders its knob in
    the SURFACE colour (see ttkbootstrap/style/builders/toggle.py: the
    switch asset's black channel is deliberately recoloured to match the
    background it sits on, a "cut-out" look), which read as a stray dark
    dot/glitch to real users -- confirmed by zooming into a screenshot: it's
    the widget's actual, consistent design, not a rendering bug, just not
    the white-knob convention most toggle switches (iOS, Android, every
    other OS) use. Drawing it ourselves on a small Canvas gives full control
    over the knob colour with no further fighting the library's style
    engine. Width/height match ttkbootstrap's round-toggle closely enough
    that rows don't visibly resize.
    """
    import tkinter as tk

    width, height = 38, 20
    knob_color = "#ffffff"
    canvas = tk.Canvas(parent, width=width, height=height, bg=bg,
                       highlightthickness=0, cursor="hand2")

    def draw(*_args):
        canvas.delete("all")
        on = bool(variable.get())
        track = on_color if on else off_color
        r = height / 2
        canvas.create_oval(0, 0, height, height, fill=track, outline=track)
        canvas.create_oval(width - height, 0, width, height, fill=track, outline=track)
        canvas.create_rectangle(r, 0, width - r, height, fill=track, outline=track)
        pad = 2
        knob_x = (width - height + pad) if on else pad
        canvas.create_oval(knob_x, pad, knob_x + height - 2 * pad, height - pad,
                           fill=knob_color, outline=knob_color)

    # A plain Canvas has no ttk-style `command=` option to re-`.configure()`
    # later -- some callers (the names/faces "both off" guard) need to bind
    # their command AFTER this widget exists, since that command itself
    # references this same widget's tooltip. `cb.set_command(fn)` lets them
    # do that; `_command` defaults to the constructor argument so the common
    # case (command known up front) needs nothing extra.
    state = {"command": command}

    def on_click(_event=None):
        variable.set(not variable.get())
        if state["command"] is not None:
            state["command"]()

    # Redraws on ANY change to the variable, not just clicks here -- so a
    # programmatic .set() (refresh_from_settings on reopen, or the both-off
    # guard correcting a value) repaints correctly too, with no separate
    # call needed and no risk of a stale half-drawn state (a full canvas
    # redraw is atomic, unlike a themed widget's own click animation).
    variable.trace_add("write", draw)
    canvas.bind("<Button-1>", on_click)
    canvas.set_command = lambda fn: state.__setitem__("command", fn)
    draw()
    return canvas


def _pause_icon(parent, active_var, bg: str, fg: str, command=None):
    """A small circular pause/play button, hand-drawn (same Canvas approach
    as `_toggle_switch`/`_help_icon`) -- a compact icon in the window's own
    corner, NOT a full card row. A whole extra row for "PiiBlur active" was
    tried and explicitly rejected (it read as clutter, not a convenience);
    this is the quieter alternative -- click to pause/resume right from the
    window without opening the tray menu. Shows the ACTION the click will
    take (a pause glyph "||" while running -- click to pause; a play
    triangle while paused -- click to resume), the same convention media
    players use, not the current state as a label."""
    import tkinter as tk

    size = 22
    c = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0,
                  cursor="hand2")

    def draw(*_args):
        c.delete("all")
        c.create_oval(1, 1, size - 1, size - 1, outline=fg, width=1)
        cx, cy = size / 2, size / 2
        if active_var.get():
            # Running -> show a pause glyph (click to pause).
            c.create_rectangle(cx - 4, cy - 5, cx - 1.5, cy + 5, fill=fg, outline=fg)
            c.create_rectangle(cx + 1.5, cy - 5, cx + 4, cy + 5, fill=fg, outline=fg)
        else:
            # Paused -> show a play glyph (click to resume).
            c.create_polygon(cx - 3.5, cy - 5, cx - 3.5, cy + 5, cx + 5, cy,
                             fill=fg, outline=fg)

    def on_click(_event=None):
        active_var.set(not active_var.get())
        if command is not None:
            command()

    active_var.trace_add("write", draw)
    c.bind("<Button-1>", on_click)
    draw()
    return c


def _help_icon(parent, bg: str, fg: str):
    """A small circular "?" icon -- a round outline with a centered question
    mark, drawn on a tiny Canvas (ttk has no built-in round-icon widget).
    Replaces the earlier plain "(?)" text label, which read as a parenthetical
    footnote rather than a distinct clickable/hoverable icon."""
    import tkinter as tk

    size = 16
    c = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0,
                  cursor="question_arrow")
    pad = 1
    c.create_oval(pad, pad, size - pad, size - pad, outline=fg, width=1)
    c.create_text(size // 2, size // 2 + 1, text="?", fill=fg, font=("Segoe UI", 8))
    return c


class _Tooltip:
    """A small popup that appears on hover and follows the cursor away on
    leave — the standard "?" hover-help pattern. tkinter has no built-in
    tooltip widget, so this is a minimal hand-rolled one: a borderless
    Toplevel with a single label, shown/hidden on Enter/Leave."""

    def __init__(self, widget, text_fn):
        self._widget = widget
        self._text_fn = text_fn  # callable so it re-reads the current language
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        import tkinter as tk

        if self._tip is not None:
            return
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        # The main window is "-topmost" (see start()); without the SAME flag
        # here, the tooltip rendered BEHIND it in z-order instead of over it
        # -- confirmed directly: a real screenshot showed the tooltip's text
        # peeking out from behind the settings window, overlapping whatever
        # else was on screen, instead of appearing on top of it.
        self._tip.wm_attributes("-topmost", True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self._text_fn(), justify="left", wraplength=280,
                background="#ffffe0", relief="solid", borderwidth=1,
                padx=6, pady=4).pack()

    def _hide(self, _event=None):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def refresh(self):
        """Call after the language changes so an OPEN tooltip's text updates
        instead of showing stale text until the next hover."""
        if self._tip is not None:
            self._hide()
            self._show()


def _build(root, settings: Settings, control, q: "queue.Queue", on_pause_change) -> None:
    """Build every widget ONCE. `settings` is the app's one live Settings
    instance (the same object tray.py holds for its whole lifetime), so this
    never needs to be rebuilt per open -- only the displayed VALUES get
    refreshed, each time the window is (re)shown, from a `poll()` loop
    watching `q` for open requests."""
    import ttkbootstrap as tb

    root.title(i18n.t("gui_title", settings.language))
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", root.withdraw)  # close (X) just hides it
    # The window must be REALIZED (have a real native HWND with its own frame)
    # before DwmSetWindowAttribute can target it correctly -- calling this
    # too early (right after creation, before anything has been drawn) let
    # the call silently target the wrong handle and do nothing, which is
    # exactly what happened the first time around.
    root.update_idletasks()
    _use_dark_titlebar(root)
    # Mica/Acrylic (_apply_glass) was tried TWICE and reverted both times:
    # attempt 1 (dark grey ttkbootstrap background) washed the window white;
    # attempt 2 (pure black background first, per py-window-styles' own
    # documented requirement) didn't wash it white, but didn't produce real
    # blur/transparency either -- just a different flat solid grey fill, no
    # see-through, no blur texture. Confirmed visually both times (screenshot
    # inspection), not assumed. Matches what GitHub research found: open,
    # unresolved issues on this exact failure mode for ttk/CTk-themed windows
    # specifically, with the library maintainer's own advice being "use Qt
    # instead." Not pursuing a third attempt -- this is a genuine, currently
    # unresolved ecosystem-wide limitation for tkinter, not a one-off miss.

    pad = {"padx": 12, "pady": 6}
    frm = tb.Frame(root)
    frm.grid(sticky="nsew")
    colors = tb.Style().colors
    row_fg = colors.fg
    on_color, off_color = colors.primary, colors.dark
    # The "card" surface -- a slightly lighter panel colour than the window's
    # own background -- is what groups each toggle into its own visually
    # distinct row, the way the reference mockup does. Looked up from an
    # actual styled widget rather than hardcoded, so it stays correct if the
    # theme ever changes.
    _card_probe = tb.Frame(frm, bootstyle="@card")
    row_bg = tb.Style().lookup(_card_probe.cget("style"), "background")
    _card_probe.destroy()

    # ON = "active/running" (matches every toggle's own ON=enabled
    # convention), so OFF = paused -- the inverse of control.paused.
    active_v = tb.BooleanVar(value=not control.paused)
    names_v = tb.BooleanVar(value=settings.detect_names)
    faces_v = tb.BooleanVar(value=settings.blur_faces)
    start_v = tb.BooleanVar(value=_safe(autostart.is_enabled))
    # "Automatic (silent) mode" used to be a toggle here too, but turning it
    # OFF had no visible review screen behind it (none is wired up in the
    # tray app) -- it silently stopped PiiBlur from doing anything at all,
    # with zero feedback. Removed rather than left as a trap; the tray always
    # runs in auto mode (settings.auto stays True, untouched by this window).
    # Blur strength is likewise not a user-facing knob (see git history) --
    # it stays at whatever Settings/config.json already holds.
    # The "smart name model (AI)" toggle is gone too -- it's the thing that
    # catches names the gazetteer alone would miss, so turning it off quietly
    # weakened protection for no real benefit to the user; it now just always
    # stays on (settings.name_model is never touched by this window).
    # Shown/edited as the language's own NATIVE name ("O'zbekcha"/"English"/
    # "Русский"), not its code -- codes are for config.json, not for reading.
    code_by_name = {v: k for k, v in i18n.LANGUAGES.items()}
    lang_name_v = tb.StringVar(value=i18n.LANGUAGES.get(settings.language, i18n.LANGUAGES["uz"]))

    def t(key: str) -> str:
        # Reads the LIVE combobox selection, not settings.language -- so
        # picking a different language retranslates the window immediately,
        # before Save is even clicked (a live preview, not a blind guess).
        return i18n.t(key, code_by_name.get(lang_name_v.get(), settings.language))

    title_lbl = tb.Label(frm, text="PiiBlur", font=("Segoe UI", 13, "bold"))
    title_lbl.grid(row=0, column=0, columnspan=3, **pad)

    def _toggle_active():
        control.paused = not active_v.get()
        if on_pause_change is not None:
            try:
                on_pause_change()
            except Exception:
                pass

    pause_icon = _pause_icon(frm, active_v, colors.bg, row_fg, command=_toggle_active)
    # Placed by absolute position (not grid) in the window's own top-right
    # corner, independent of the title row's own centered layout -- a
    # compact icon here, not the full "PiiBlur active" card row tried and
    # explicitly rejected earlier as clutter.
    pause_icon.place(relx=1.0, x=-14, y=10, anchor="ne")
    # Tooltip describes the ACTION a click takes (same convention as the
    # icon itself) -- reuses the tray menu's own "Pause"/"Resume" strings.
    pause_tip = _Tooltip(pause_icon, lambda: t("menu_pause" if active_v.get() else "menu_resume"))

    def _row(r: int, var, label_key: str, help_key: str, command=None):
        """One row, in its own "card" (a visually distinct panel, matching the
        reference mockup) containing [toggle switch] [setting name] [(?)
        icon] packed snugly together on the left -- the (?) sits immediately
        after the text it explains, not off in its own column at the far
        right of the window. `command` (if given) fires only on an actual
        USER click (unlike a variable trace, which would also fire during
        refresh_from_settings' programmatic .set() calls on every re-open)."""
        card = tb.Frame(frm, bootstyle="@card")
        card.grid(row=r, column=0, columnspan=3, sticky="ew", padx=12, pady=5)
        cb = _toggle_switch(card, var, row_bg, on_color, off_color, command=command)
        cb.pack(side="left", padx=(10, 0), pady=10)
        lbl = tb.Label(card, text=t(label_key), bootstyle="@card")
        lbl.pack(side="left", padx=(8, 4), pady=10)
        hint = _help_icon(card, row_bg, row_fg)
        hint.pack(side="left", pady=10)
        tip = _Tooltip(hint, lambda: t(help_key))
        return cb, lbl, tip

    # Turning OFF both name- and face-blurring at once leaves almost nothing
    # protected on the exact screenshots (chat lists, contact cards) that are
    # most PII-dense -- the structured-pattern detectors (card/phone/passport
    # numbers) keep running regardless, but names and faces are what most
    # everyday screenshots actually need hidden. Rather than let the user
    # silently end up unprotected, the SECOND one clicked off snaps back on
    # if the other is already off, and its tooltip explains why -- instead of
    # a popup interrupting the click.
    def _guard_both_off(changed_var, other_var, changed_tip):
        if not changed_var.get() and not other_var.get():
            changed_var.set(True)
            changed_tip._show()
            root.after(2500, changed_tip._hide)

    # Every change saves itself immediately -- no Save/Cancel buttons. Each
    # toggle already takes effect in the running app the instant it's
    # clicked (there's nothing to "cancel" back out of), so a Save step was
    # just an extra click with no real purpose; the footer label says so.
    def _save_now():
        settings.detect_names = names_v.get()
        settings.blur_faces = faces_v.get()
        settings.language = code_by_name.get(lang_name_v.get(), settings.language)
        settings_store.save(settings)

    names_cb, names_lbl, names_tip = _row(1, names_v, "gui_blur_names", "help_blur_names")
    faces_cb, faces_lbl, faces_tip = _row(2, faces_v, "gui_blur_faces", "help_blur_faces")
    names_cb.set_command(lambda: (_guard_both_off(names_v, faces_v, names_tip), _save_now()))
    faces_cb.set_command(lambda: (_guard_both_off(faces_v, names_v, faces_tip), _save_now()))
    start_cb, start_lbl, start_tip = _row(3, start_v, "gui_autostart", "help_autostart")

    def _toggle_autostart():
        _safe(autostart.enable) if start_v.get() else _safe(autostart.disable)

    start_cb.set_command(_toggle_autostart)

    lang_card = tb.Frame(frm, bootstyle="@card")
    lang_card.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=5)
    lang_lbl = tb.Label(lang_card, text=t("gui_language"), bootstyle="@card")
    lang_lbl.pack(side="left", padx=(10, 0), pady=10)
    lang_values = list(i18n.LANGUAGES.values())
    lang_combo = tb.Combobox(lang_card, textvariable=lang_name_v, values=lang_values,
                             state="readonly", width=14)
    lang_combo.pack(side="left", padx=(8, 4), pady=10)
    lang_hint = _help_icon(lang_card, row_bg, row_fg)
    lang_hint.pack(side="left", pady=10)
    lang_tip = _Tooltip(lang_hint, lambda: t("help_language"))

    footer_lbl = tb.Label(frm, text=t("gui_autosaved"), bootstyle="secondary")
    footer_lbl.grid(row=5, column=0, columnspan=3, pady=(4, 12))

    def retranslate(_event=None):
        root.title(t("gui_title"))
        names_lbl.configure(text=t("gui_blur_names"))
        faces_lbl.configure(text=t("gui_blur_faces"))
        start_lbl.configure(text=t("gui_autostart"))
        lang_lbl.configure(text=t("gui_language"))
        footer_lbl.configure(text=t("gui_autosaved"))
        for tip in (pause_tip, names_tip, faces_tip, start_tip, lang_tip):
            tip.refresh()

    def _on_language_selected(_event=None):
        retranslate()
        _save_now()

    lang_combo.bind("<<ComboboxSelected>>", _on_language_selected)

    def refresh_from_settings():
        """Re-read the live Settings object into the widgets -- called every
        time the window is (re)opened, since it's never rebuilt from scratch
        and settings may have changed (e.g. autostart toggled elsewhere)."""
        active_v.set(not control.paused)
        names_v.set(settings.detect_names)
        faces_v.set(settings.blur_faces)
        start_v.set(_safe(autostart.is_enabled))
        current_name = i18n.LANGUAGES.get(settings.language, i18n.LANGUAGES["uz"])
        lang_combo.current(lang_values.index(current_name))
        retranslate()

    def poll():
        try:
            while True:
                q.get_nowait()
                refresh_from_settings()
                root.deiconify()
                root.lift()
                root.focus_force()
        except queue.Empty:
            pass
        root.after(50, poll)

    root.after(50, poll)


def start(settings: Settings, control, on_pause_change=None) -> None:
    """Build the settings window once, in its own dedicated thread, and leave
    it hidden until requested. Idempotent — a no-op on later calls. Must be
    called once from tray.py at startup, before the first `request_open()`.

    `control` is the watcher's shared Control object -- the Settings window
    has its own pause/resume icon (top-right corner, not a full row -- a
    whole extra toggle row was tried and explicitly rejected as clutter), so
    it needs to read/write `control.paused` directly. `on_pause_change`, if
    given, is called right after a change here so the CALLER (tray.py) can
    refresh whatever ELSE reflects pause state (its own tray icon tint) --
    this module doesn't know about that, deliberately, to avoid reaching
    back into tray.py's internals."""
    global _QUEUE, _THREAD
    if _THREAD is not None:
        return
    try:
        q: "queue.Queue" = queue.Queue()

        def _run():
            import ttkbootstrap as tb

            from pii_blur import status_overlay

            # ONE Tk root, ONE thread, for the whole app's UI -- the status
            # overlay (see its own module docstring) attaches to THIS root
            # rather than running its own independent one; two separate Tk
            # interpreters across two threads corrupted ttkbootstrap's style
            # engine intermittently (confirmed directly, not theoretical).
            root = tb.Window(themename="one-dark")
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            _build(root, settings, control, q, on_pause_change)
            status_overlay.attach(root)
            root.mainloop()

        t = threading.Thread(target=_run, name="settings-window", daemon=True)
        t.start()
        _QUEUE, _THREAD = q, t
    except Exception:
        logger.exception("settings window failed to start")
        _QUEUE, _THREAD = None, None


def request_open() -> None:
    """Show the settings window (building it on first call is NOT done here —
    call start() once at tray startup instead). No-op if start() wasn't
    called or failed to come up."""
    if _QUEUE is not None:
        try:
            _QUEUE.put_nowait(None)
        except Exception:
            pass


def _use_dark_titlebar(root) -> None:
    """Ask Windows to draw THIS window's native title bar (the OS-drawn strip
    with the icon/title/minimize/close buttons) in dark mode too. tkinter/ttk
    theming only reaches the window's CONTENT -- the title bar is drawn by
    Windows itself (DWM), so a dark ttk theme alone leaves a jarring white
    strip above it. `DwmSetWindowAttribute` with the "immersive dark mode"
    attribute is Microsoft's own documented way to opt a window into this
    (support varies by Windows 10/11 build, hence trying both known attribute
    IDs and swallowing failure entirely -- a white title bar is a cosmetic
    miss, never worth crashing the settings window over)."""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 (20H1+), 19 (older)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def _safe(fn):
    try:
        return fn()
    except Exception:
        return False
