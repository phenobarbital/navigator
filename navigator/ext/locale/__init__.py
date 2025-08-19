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
locale_finder = re.compile(r'([a-zA-Z]{2,3}(?:[_-][a-zA-Z]{2})?)(?:;q=(\d\.\d))?')

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
                    self.translation = gettext.translation(
                        domain=self.domain,
                        localedir=str(self.locale_path),
                        languages=[self.localization[0]] if self.localization else ['en'],
                        fallback=True
                    )
                    self.logger.debug(
                        f"LocaleSupport: Loaded translation for {self.localization[0] if self.localization else 'en'}")
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

    def parse_accept_language(self, accept_language: str):
        """Parse the Accept-Language header into a list of locales.

        The header is sorted by the quality factor (q parameter).
        """
        if not accept_language:
            return [self.localization[0] if self.localization else 'en']

        try:
            # Find all matches
            locales = locale_finder.findall(accept_language)
            # Sort by q value (quality), highest first
            sorted_locales = sorted(
                locales, key=lambda x: float(x[1]) if x[1] else 1.0, reverse=True
            )
            # Convert hyphens to underscores
            locales = [
                loc.replace('-', '_') for loc, _ in sorted_locales if loc is not None
            ]
            if not locales:
                # If nothing matches the pattern, simply normalise the header string
                locales = [accept_language.replace('-', '_')]
            return locales
        except Exception:
            # Fallback if parsing fails
            return [self.localization[0] if self.localization else 'en']

    def get_translator_for_request(self, lang: str = None) -> Callable[[str], str]:
        """Return a gettext function for a particular request.

        Determine the best language from the Accept-Language header and load
        the appropriate translation. If no translation is found, use the
        fallback translator.
        """
        try:
            selected_locales = None

            if lang:
                langs = self.parse_accept_language(lang)
                # If parse returns a list, use the first entry; otherwise use it directly
                if not langs:
                    selected_locales = [self.localization[0] if self.localization else 'en']
                elif isinstance(langs, list):
                    selected_locales = [langs[0]]
                else:
                    selected_locales = [langs]
            else:
                selected_locales = [self.localization[0] if self.localization else 'en']

            # Manual fixes for Chinese locales used by gettext/Babel
            if selected_locales[0] == 'zh_CN':
                selected_locales[0] = 'zh_Hans_CN'
            elif selected_locales[0] == 'zh_TW':
                selected_locales[0] = 'zh_Hant_TW'

            try:
                if self.locale_path and self.locale_path.exists():
                    trans = support.Translations.load(
                        str(self.locale_path),
                        domain=self.domain,
                        locales=selected_locales,
                        fallback=True
                    )
                    return trans.gettext
                else:
                    return self.translation.gettext if self.translation else lambda x: x
            except Exception as ex:
                self.logger.warning(
                    f"LocaleSupport: Could not load domain file for {self.domain}: {ex}"
                )
                return self.translation.gettext if self.translation else lambda x: x

        except Exception as err:
            self.logger.error(f"LocaleSupport: Error in get_translator_for_request: {err}")
            return lambda x: x  # Ultimate fallback

    def translator(
        self,
        domain: Union[str, None] = None,
        locale: Union[Locale, None] = None,
        lang: str = None
    ) -> Callable[[str], str]:
        """Return a gettext function for the given language.

        This is a backwards-compatible wrapper around get_translator_for_request().
        """
        return self.get_translator_for_request(lang)
