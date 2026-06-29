"""
i18n/__init__.py
Centralised gettext loader for cat_gui.

Usage (in cat_gui.py):
    from i18n import _, ngettext, pgettext
    tk.Label(parent, text=_("Connect"))
"""

import gettext
import os

_DOMAIN    = "cat_gui"
_LOCALEDIR = os.path.join(os.path.dirname(__file__), "..", "locale")

_current_translation: "gettext.NullTranslations | None" = None


def setup(lang: "str | None" = None) -> None:
    """
    Initialise translations.

    Priority:
      1. ``lang`` argument (from --lang CLI flag or cat_gui.toml [display] lang=)
      2. LANGUAGE / LC_ALL / LANG environment variables (gettext default)
      3. Falls back to English (NullTranslations) on any error.

    Call once before building any Tk widget.
    """
    global _current_translation

    # Normalise: "es_AR" -> try "es_AR" then "es"
    languages = None
    if lang:
        languages = [lang, lang.split("_")[0]]

    try:
        _current_translation = gettext.translation(
            _DOMAIN,
            localedir=_LOCALEDIR,
            languages=languages,
        )
    except FileNotFoundError:
        _current_translation = gettext.NullTranslations()

    _current_translation.install()          # installs builtins._()


def _(message: str) -> str:
    """Translate a string. Falls back to the original on any error."""
    if _current_translation is None:
        return message
    return _current_translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate with plural forms."""
    if _current_translation is None:
        return singular if n == 1 else plural
    return _current_translation.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    """Translate with disambiguating context (requires Python 3.8+)."""
    if _current_translation is None:
        return message
    return _current_translation.pgettext(context, message) or message
