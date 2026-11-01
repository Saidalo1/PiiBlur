"""Tiny built-in UI translations: a flat {key: {lang: text}} table and a
lookup helper. No gettext/.po pipeline -- that's real overhead (a build step,
a compiled .mo per language) for what is currently ~16 short strings; a plain
dict is easier to keep in sync by hand at this size and needs no extra
dependency or build step.

Three languages, matching the app's actual userbase: Uzbek Latin (the
default -- most users), English (the code/menu convention so far), Russian
(common second language in the region). `DEFAULT_LANGUAGE` is what a fresh
install starts with before the user (or the installer, see installer_net.iss)
ever picks one explicitly.
"""
from __future__ import annotations

LANGUAGES = {"uz": "O'zbekcha", "en": "English", "ru": "Русский"}
DEFAULT_LANGUAGE = "uz"

_STRINGS: dict[str, dict[str, str]] = {
    "menu_resume": {"uz": "Davom ettirish", "en": "Resume", "ru": "Продолжить"},
    "menu_pause": {"uz": "Pauza", "en": "Pause", "ru": "Пауза"},
    "menu_settings": {"uz": "Sozlamalar…", "en": "Settings…", "ru": "Настройки…"},
    "menu_quit": {"uz": "Chiqish", "en": "Quit", "ru": "Выход"},
    "menu_update_available": {
        "uz": "Yangilanish mavjud ({tag})", "en": "Update available ({tag})",
        "ru": "Доступно обновление ({tag})",
    },
    "menu_skip_update": {
        "uz": "Bu versiyani o'tkazib yuborish", "en": "Skip this version",
        "ru": "Пропустить эту версию",
    },
    "toast_update_available": {
        "uz": "PiiBlur {tag} chiqdi. O'rnatish uchun tray menyusidan tanlang.",
        "en": "PiiBlur {tag} is out. Pick it from the tray menu to install.",
        "ru": "Вышла PiiBlur {tag}. Выберите в меню трея, чтобы установить.",
    },

    "gui_title": {"uz": "PiiBlur — Sozlamalar", "en": "PiiBlur — Settings",
                 "ru": "PiiBlur — Настройки"},
    "gui_blur_names": {"uz": "Ismlarni ham xiralashtirish (taxminiy)",
                       "en": "Blur names too (fuzzy)", "ru": "Размывать и имена (нечётко)"},
    "gui_blur_faces": {"uz": "Yuzlarni xiralashtirish",
                       "en": "Blur faces", "ru": "Размывать лица"},
    "gui_autostart": {"uz": "Windows bilan ishga tushirish",
                      "en": "Start with Windows", "ru": "Запускать с Windows"},
    "gui_language": {"uz": "Til", "en": "Language", "ru": "Язык"},
    "gui_autosaved": {
        "uz": "Sozlamalar avtomatik saqlanadi",
        "en": "Settings are saved automatically",
        "ru": "Настройки сохраняются автоматически",
    },

    # Plain-language hover explanations for each toggle -- real users found
    # the checkbox labels alone weren't enough to know what a setting
    # actually does or what flipping it changes.
    "help_blur_names": {
        "uz": "Yoqilgan bo'lsa, dastur rasmdagi odamlarning ismi va familiyasini ham topib xiralashtiradi.",
        "en": "When on, the app also finds and blurs people's names in the screenshot.",
        "ru": "Если включено, программа также находит и размывает имена людей на скриншоте.",
    },
    "help_blur_faces": {
        "uz": "Rasmdagi odamlarning yuzlarini ham avtomatik topib xiralashtiradi.",
        "en": "Also detects and blurs people's faces in the screenshot.",
        "ru": "Также находит и размывает лица людей на скриншоте.",
    },
    "help_autostart": {
        "uz": ("Yoqilgan bo'lsa, kompyuter yoqilganda PiiBlur avtomatik ishga tushadi "
              "va orqa fonda ishlab turadi."),
        "en": "When on, PiiBlur starts automatically with Windows and runs quietly in the background.",
        "ru": "Если включено, PiiBlur запускается автоматически вместе с Windows и работает в фоне.",
    },
    "help_language": {
        "uz": "Dastur menyusi va xabarlari shu tilda ko'rsatiladi.",
        "en": "The app's menu and messages are shown in this language.",
        "ru": "Меню и сообщения программы показываются на этом языке.",
    },

    "toast_flash_intro": {
        "uz": ("Agar ekranning pastki o'ng burchagida kichik sariq chaqnashni "
              "ko'rsangiz — bu PiiBlur: skrinshot qayta ishlandi degani."),
        "en": ("If you see a small amber flash at the bottom-right of your "
              "screen — that's PiiBlur: it means your screenshot was processed."),
        "ru": ("Если вы видите маленькую янтарную вспышку внизу справа "
              "экрана — это PiiBlur: значит, скриншот обработан."),
    },
}


def t(key: str, lang: str) -> str:
    """Look up a UI string. Falls back to English, then the raw key, if a
    translation or the whole language is missing -- so a typo or a language
    this table doesn't cover yet never breaks the UI, just shows a less
    localized string instead of crashing."""
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry.get("en") or key
