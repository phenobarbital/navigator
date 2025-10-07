"""Locale (Babel) Extension.
Add support for Babel (i18n engine) for Navigator.
"""

import locale as pylocale
import re
import gettext
from typing import Union, Optional
from pathlib import Path
from collections.abc import Callable

from babel import Locale, support, UnknownLocaleError
from navconfig import config, BASE_DIR
from navconfig.logging import logging
from ...types import WebApp
from ...extensions import BaseExtension
from ...exceptions import ConfigError

# Regular expression to parse the Accept-Language HTTP header
_lang_re = re.compile(r'(?P<tag>[A-Za-z]{1,8}(?:[-_][A-Za-z0-9]{1,8})*)(?:\s*;\s*q=(?P<q>0(?:\.\d+)?|1(?:\.0+)?))?')

class LocaleSupport(BaseExtension):
    """LocaleSupport.
    Description: Add support for Babel (i18n engine) and localization for Navigator.
    """

    name: str = "locale"
    app: WebApp = None

    def __init__(
        self,
        app_name: str = None,
        localization: Union[str, list, None] = None,
        language: Optional[Union[str, None]] = None,
        country: Optional[Union[str, None]] = None,
        locale_section: str = "i18n",  # INI section for default locales
        locale_path: Union[str, Path] = None,
        domain: str = None,
        **kwargs,
    ) -> None:
        self.language = language
        self.localization = localization
        self.locale_section = locale_section
        self.country = country
        self._locale: Callable = None
        self.locale_path = locale_path
        self.translation: Optional[gettext.NullTranslations] = None
        self._trans_cache: dict = {}

        # Ensure the locale_path is a Path object
        if isinstance(self.locale_path, str):
            self.locale_path = Path(locale_path).resolve()

        super(LocaleSupport, self).__init__(app_name=app_name, **kwargs)

        # Set the domain for translations
        self.domain = domain or self.name

        if language is None:
            # Default language from configuration
            try:
                self.language = config.get(
                    "language", section=self.locale_section, fallback="en"
                )
            except Exception:
                self.language = "en"

        if localization is None:
            # Default localization from configuration
            try:
                default_loc = config.get(
                    "localization",
                    section=self.locale_section,
                    fallback="en_US"
                )
                self.localization = [default_loc]
            except Exception:
                self.localization = ["en_US"]
        elif isinstance(self.localization, str):
            # Convert a single value into a list
            self.localization = [self.localization]

        # Normalise any localisation codes with hyphens to underscores
        if self.localization:
            for loc in list(self.localization):
                if '-' in loc and '_' not in loc:
                    self.localization.append(loc.replace('-', '_'))

        if country is None:
            # Default country from configuration
            try:
                self.country = config.get(
                    "country", section=self.locale_section, fallback="US"
                )
            except Exception:
                self.country = "US"

        if self.locale_path is None:
            # Default locale directory
            self.locale_path = BASE_DIR.joinpath("locale")

    def setup(self, app: WebApp):
        """Configure localization and Babel for the application.

        This method does not change the global locale. It loads a fallback
        translation for the first localisation in the list.
        """
        try:
            self.logger.debug("LocaleSupport: Starting setup...")

            # Set the locale to the system default (does not change between requests)
            try:
                pylocale.setlocale(pylocale.LC_ALL, '')
                self.logger.debug("LocaleSupport: System locale set successfully")
            except pylocale.Error as e:
                self.logger.warning(
                    f"LocaleSupport: Could not set system locale: {e}"
                )
                # Continue anyway - this is not critical

            # Create a Babel Locale object for the configured language and country
            try:
                self._locale = Locale(self.language, self.country)
                self.logger.debug(f"LocaleSupport: Created locale {self.language}_{self.country}")
            except UnknownLocaleError as e:
                _loc = self.localization[0] if self.localization else 'en_US'
                self.logger.warning(
                    f"LocaleSupport: Unknown locale {self.language}_{self.country}, falling back to {_loc}"
                )
                try:
                    self._locale = Locale.parse(self.localization[0])
                except Exception as parse_err:
                    self.logger.warning(f"LocaleSupport: Could not parse fallback locale: {parse_err}")
                    self._locale = Locale('en', 'US')  # Ultimate fallback

            # Load a fallback translation for the first localisation
            try:
                if self.locale_path and self.locale_path.exists():
                    self._trans_cache[self.domain] = {}
                    print('LOCALES', self.localization)
                    for locale in self.localization:
                        self._trans_cache[self.domain][locale] = gettext.translation(
                            domain=self.domain,
                            localedir=str(self.locale_path),
                            languages=[locale],
                            fallback=True
                        )
                        self.logger.debug(
                            f"LocaleSupport: Loaded {locale} for domain {self.domain}")
                    if any(loc == self._locale for loc in self.localization):
                        key = self._locale
                    else:
                        key = next((k for k, v in self._trans_cache[self.domain].items() if k.startswith(f"{self._locale}_")), 'en_US')
                    self.translation = self._trans_cache[self.domain][key]
                    self.logger.debug(
                        f"LocaleSupport: Loaded translation for {self._locale if self.localization else 'en_US'}")
                else:
                    self.logger.warning(
                        f"LocaleSupport: Locale path {self.locale_path} does not exist, using NullTranslations"
                    )
                    self.translation = gettext.NullTranslations()
            except Exception as trans_err:
                self.logger.warning(f"LocaleSupport: Could not load translations: {trans_err}")
                # If translation files are not found, use a NullTranslations instance
                self.translation = gettext.NullTranslations()

            self.logger.debug(
                "LocaleSupport: Setup completed successfully"
            )

        except Exception as err:
            self.logger.error(
                f"LocaleSupport: Critical error during setup: {err}"
            )
            # Don't raise the error - just log it and continue with minimal functionality
            self.translation = gettext.NullTranslations()
            self._locale = Locale('en', 'US')
        ## calling parent Setup:
        super(LocaleSupport, self).setup(app)

    async def on_startup(self, app: WebApp) -> None:
        """Install fallback gettext translations into Jinja2 if present.

        We deliberately avoid installing a global _() function; instead,
        templates can use the fallback translator until a per-request
        translator is supplied.
        """
        try:
            self.logger.debug("LocaleSupport: Starting on_startup...")

            if hasattr(app, 'extensions') and "template" in app.extensions.keys():
                tmpl = app["template"]
                if hasattr(tmpl, 'environment') and hasattr(
                    tmpl.environment, 'install_gettext_translations'
                ):
                    # Install fallback translations into the environment
                    tmpl.environment.install_gettext_translations(
                        self.translation, newstyle=True
                    )
                    self.logger.debug(
                        "LocaleSupport: Installed gettext translations into Jinja2"
                    )
                else:
                    self.logger.debug(
                        "LocaleSupport: Template environment does not support gettext"
                    )
            else:
                self.logger.debug(
                    "LocaleSupport: No template extension found"
                )

        except AttributeError as attr_err:
            self.logger.warning(
                f"LocaleSupport: Template attribute error: {attr_err}"
            )
        except Exception as ex:
            self.logger.error(
                f"LocaleSupport: Error installing Jinja2 support for gettext: {ex}"
            )
            # Don't raise - just log and continue

        # Call the parent startup handler if needed - wrap in try/catch
        try:
            await super(LocaleSupport, self).on_startup(app)
        except Exception as parent_err:
            self.logger.warning(
                f"LocaleSupport: Error at on_startup: {parent_err}"
            )
            # Don't re-raise

    def trans(self) -> Callable[[str], str]:
        """Return the gettext function for the fallback translation."""
        return self.translation.gettext if self.translation else (lambda x: x)

    def current_locale(self):
        """Return the current system locale."""
        try:
            return pylocale.getlocale(pylocale.LC_ALL)
        except Exception:
            return ('en_US', 'UTF-8')  # Safe fallback

    def format_number(self, number: Union[float, int]) -> str:
        """Format a number using the current locale settings."""
        try:
            return pylocale.format_string("%g", number, grouping=True)
        except Exception:
            return str(number)  # Fallback to simple string conversion

    def currency(self, number: Union[float, int], grouping: bool = True) -> str:
        """Format a currency value using the current locale settings."""
        try:
            return pylocale.currency(number, grouping=grouping)
        except Exception:
            return f"${number:.2f}"  # Simple fallback

    def current_i18n(self) -> Callable[[str], str]:
        """Alias for trans() for backward compatibility."""
        return self.trans()

    def parse_accept_language(self, header: str):
        if not header:
            return [self.localization[0] if self.localization else 'en_US']
        items = []
        for m in _lang_re.finditer(header):
            tag = m.group('tag').replace('-', '_')
            q = float(m.group('q')) if m.group('q') else 1.0
            items.append((tag, q))
        if not items:
            return [self.localization[0] if self.localization else 'en_US']
        items.sort(key=lambda x: x[1], reverse=True)
        seen = set(); ordered = []
        for t, _ in items:
            if t not in seen:
                seen.add(t); ordered.append(t)
        return ordered

    def get_translator_for_request(self, lang: str = None):
        try:
            if lang:
                requested = self.parse_accept_language(lang)
            else:
                requested = list(self.localization) if self.localization else ['en_US']

            # Normalize Chinese
            requested = [('zh_Hans_CN' if l == 'zh_CN' else 'zh_Hant_TW' if l == 'zh_TW' else l)
                        for l in requested]
            if any(loc == requested[0] for loc in self.localization):
                key = requested[0]
            else:
                key = next((k for k, v in self._trans_cache[self.domain].items() if k.startswith(f"{requested[0]}_")), 'en_US')
            self.translation = self._trans_cache[self.domain][key]
            return self.translation.gettext if self.translation else (lambda x: x)
        except Exception as err:
            self.logger.error(f"LocaleSupport: Error in get_translator_for_request: {err}")
            return (lambda x: x)

    def translator(self, domain: Union[str, None] = None, locale=None, lang: str = None):
        if domain and domain != self.domain:
            def _for_domain(s: str):
                trans = support.Translations.load(
                    str(self.locale_path), domain=domain,
                    locales=self.parse_accept_language(lang) if lang else self.localization or ['en_US'],
                    fallback=True
                )
                return trans.gettext(s)
            return _for_domain
        return self.get_translator_for_request(lang)
