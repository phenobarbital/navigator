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
        self.translation: gettext.NullTranslations = None

        # Ensure the locale_path is a Path object
        if isinstance(self.locale_path, str):
            self.locale_path = Path(locale_path).resolve()

        super(LocaleSupport, self).__init__(app_name=app_name, **kwargs)

        self.domain = domain
        if not domain:
            self.domain = self.name

        if language is None:
            # Default language from configuration
            self.language = config.get(
                "language", section=self.locale_section, fallback="en"
            )

        if localization is None:
            # Default localization from configuration
            self.localization = [
                config.get(
                    "localization", section=self.locale_section, fallback="en_US"
                )
            ]
        elif isinstance(self.localization, str):
            # Convert a single value into a list
            self.localization = [self.localization]

        # Normalise any localisation codes with hyphens to underscores
        for loc in list(self.localization):
            if '-' in loc and '_' not in loc:
                self.localization.append(loc.replace('-', '_'))

        if country is None:
            # Default country from configuration
            self.country = config.get(
                "country", section=self.locale_section, fallback="US"
            )

        if self.locale_path is None:
            # Default locale directory
            self.locale_path = BASE_DIR.joinpath("locale")

    def setup(self, app: WebApp):
        """Configure localization and Babel for the application.

        This method does not change the global locale. It loads a fallback
        translation for the first localisation in the list.
        """
        try:
            # Set the locale to the system default (does not change between requests)
            try:
                pylocale.setlocale(pylocale.LC_ALL, '')
            except pylocale.Error as e:
                raise ConfigError(
                    f"Locale: Unsupported default locale '', {e}"
                ) from e

            logging.debug(":: Locale: Using system default locale")

            # Create a Babel Locale object for the configured language and country
            try:
                self._locale = Locale(self.language, self.country)
            except UnknownLocaleError:
                # If the specified locale is unknown, fall back to the first localisation
                self._locale = Locale.parse(self.localization[0])

            # Load a fallback translation for the first localisation
            try:
                self.translation = gettext.translation(
                    domain=self.domain,
                    localedir=self.locale_path,
                    languages=[self.localization[0]],
                    fallback=True
                )
            except Exception:
                # If translation files are not found, use a NullTranslations instance
                self.translation = gettext.NullTranslations()

        except Exception as err:
            raise ConfigError(f"NAV: Error loading Babel module: {err}") from err

        # Call parent setup
        super(LocaleSupport, self).setup(app)

    async def on_startup(self, app: WebApp) -> None:
        """Install fallback gettext translations into Jinja2 if present.

        We deliberately avoid installing a global _() function; instead,
        templates can use the fallback translator until a per-request
        translator is supplied.
        """
        try:
            if "template" in app.extensions.keys():
                tmpl = app["template"]
                # Install fallback translations into the environment
                tmpl.environment.install_gettext_translations(
                    self.translation, newstyle=True
                )
        except AttributeError:
            pass
        except Exception as ex:
            raise RuntimeError(
                f"Locale: Error installing Jinja2 support for gettext: {ex}"
            ) from ex

        # Call the parent startup handler if needed
        await super(LocaleSupport, self).on_startup(app)

    def trans(self) -> Callable[[str], str]:
        """Return the gettext function for the fallback translation."""
        return self.translation.gettext

    def current_locale(self):
        """Return the current system locale."""
        return pylocale.getlocale(pylocale.LC_ALL)

    def format_number(self, number: Union[float, int]) -> str:
        """Format a number using the current locale settings."""
        return pylocale.format_string("%d", number, grouping=True)

    def currency(self, number: Union[float, int], grouping: bool = True) -> str:
        """Format a currency value using the current locale settings."""
        return pylocale.currency(number, grouping=grouping)

    def current_i18n(self) -> Callable[[str], str]:
        """Alias for trans() for backward compatibility."""
        return self.translation.gettext

    def parse_accept_language(self, accept_language: str):
        """Parse the Accept-Language header into a list of locales.

        The header is sorted by the quality factor (q parameter).
        """
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
            locales = accept_language.replace('-', '_')
        return locales

    def get_translator_for_request(self, lang: str = None) -> Callable[[str], str]:
        """Return a gettext function for a particular request.

        Determine the best language from the Accept-Language header and load
        the appropriate translation. If no translation is found, use the
        fallback translator.
        """
        selected_locales = None

        if lang:
            langs = self.parse_accept_language(lang)
            # If parse returns a list, use the first entry; otherwise use it directly
            if not langs:
                selected_locales = [self.localization[0]]
            elif isinstance(langs, list):
                selected_locales = [langs[0]]
            else:
                selected_locales = [langs]
        else:
            selected_locales = [self.localization[0]]

        # Manual fixes for Chinese locales used by gettext/Babel
        if selected_locales[0] == 'zh_CN':
            selected_locales[0] = 'zh_Hans_CN'
        elif selected_locales[0] == 'zh_TW':
            selected_locales[0] = 'zh_Hant_TW'

        try:
            trans = support.Translations.load(
                self.locale_path,
                domain=self.domain,
                locales=selected_locales,
                fallback=True
            )
            return trans.gettext
        except Exception as ex:
            logging.warning(
                f"There is no domain file for {self.domain} or locale directory is missing: {ex}"
            )
            return self.translation.gettext

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
