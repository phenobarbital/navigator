"""Locale (Babel) Extension.
Add Support for Babel (i18n engine) for Navigator.
"""
import locale
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


locale_finder = re.compile(r'([a-zA-Z]{2,3}(?:[_-][a-zA-Z]{2})?)(?:;q=(\d\.\d))?')


class LocaleSupport(BaseExtension):
    """LocaleSupport.

    Description: Add Support for Babel (i18n engine) and localization for Navigator.

    Args:
        app_name (str): Name of the current connection, will use it to save it into aiohttp Application.
        language (str): language, default use system language.

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: Babel or something wrong happened.

    Returns:
        self: an instance of LocaleSupport Object.
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
        self.translation: gettext = None
        if isinstance(self.locale_path, str):
            self.locale_path = Path(locale_path).resolve()
        super(LocaleSupport, self).__init__(app_name=app_name, **kwargs)
        self.domain = domain
        if not domain:
            self.domain = self.name
        if language is None:
            self.language = config.get(
                "language", section=self.locale_section, fallback="en"
            )
        if localization is None:
            self.localization = [
                config.get(
                    "localization", section=self.locale_section, fallback="en_US"
                )
            ]
        elif isinstance(self.localization, str):
            self.localization = [self.localization]
        for local in self.localization:
            if '-' in local and '_' not in local:
                self.localization.append(local.replace('-', '_'))
        if country is None:
            self.country = config.get(
                "country", section=self.locale_section, fallback="US"
            )
        if self.locale_path is None:
            self.locale_path = BASE_DIR.joinpath("locale")

    def setup(self, app: WebApp):
        """setup.
        Configure Localization and Babel Model for Application.

        TODO: add support for Jinja2 on Setup.
        """
        try:
            try:
                locale.setlocale(
                    locale.LC_ALL, f"{self.localization[0]}.UTF-8"
                )  # set the current localization
            except locale.Error as e:
                raise ConfigError(
                    f"Locale: Unsupported locale {self.localization[0]}, {e}"
                ) from e
            logging.debug(
                f":: Locale: Set the current locale to: {self.localization[0]}"
            )
            try:
                self._locale = Locale(self.language, self.country)
            except UnknownLocaleError:
                self._locale.parse(self.localization[0])
            ## get translations:
            try:
                self.translation = gettext.translation(
                    domain=self.domain,
                    localedir=self.locale_path,
                    languages=self.localization,
                )
                self.translation.install()  # Magically make the _ function globally available
            except FileNotFoundError as ex:
                logging.warning(
                    f"There is no Domain file for {self.domain} or locale directory is missing: {ex}"
                )
        except Exception as err:
            raise ConfigError(f"NAV: Error loading Babel Module: {err}") from err
        ## calling parent Setup:
        super(LocaleSupport, self).setup(app)

    async def on_startup(self, app: WebApp) -> None:
        ### adding Jinja2 Support:
        try:
            if "template" in app.extensions.keys():
                ## adding support for gettext on Jinja2
                tmpl = app["template"]
                tmpl.environment.install_gettext_translations(
                    self.translation, newstyle=True
                )
        except AttributeError:
            pass
        except Exception as ex:
            raise RuntimeError(
                f"Locale: Error installing Jinja2 Support for Gettext: {ex}"
            ) from ex

    def trans(self):
        return self.translation.gettext

    def current_locale(self):
        return locale.getlocale(locale.LC_ALL)

    def format_number(self, number: Union[float, int]) -> str:
        return locale.atof(number)

    def currency(self, number: Union[float, int], grouping: bool = True) -> str:
        return locale.currency(number, grouping=grouping)

    def current_i18n(self):
        return self.translation.gettext

    def parse_accept_language(self, accept_language: str):
        # Regular expression to parse the accept language header
        # Use the compiled pattern to find all matches
        locales = locale_finder.findall(accept_language)
        # Sorting locales by quality factor, defaulting to 1.0 for unspecified
        sorted_locales = sorted(
            locales, key=lambda x: float(x[1]) if x[1] else 1.0,
            reverse=True
        )
        locales = [locale.replace('-', '_') for locale, _ in sorted_locales if locale is not None]
        if not locales:
            locales = accept_language.replace('-', '_')
        return locales

    def translator(
        self,
        domain: Union[str, None] = None,
        locale: Union[Locale, None] = None,
        lang: str = None
    ) -> support.Translations:  # pylint: disable=W0621
        lc = None
        if domain is None:
            domain = self.domain
        if lang:
            lng = self.parse_accept_language(lang)
            if not lng:
                lng = self.localization[0]
            elif isinstance(lng, list):
                lng = lng[0]
            # TODO: manual patch for Chinese and Taiwanese
            if lng == 'zh_CN':
                lng = 'zh_Hans_CN'
            if lng == 'zh_TW':
                lng = 'zh_Hant_TW'
            try:
                lc = Locale(lng)
            except Exception as ex:
                self.logger.error(
                    f"Error Getting locale {ex}"
                )
        if not lc:
            if locale:
                lc = locale
            else:
                lc = self._locale
        try:
            # Add this line for debugging
            self.logger.notice(
                f"Locales attempted to load: {lc}"
            )
            trans = support.Translations.load(
                self.locale_path, domain=domain, locales=lc
            )
            self.logger.notice(
                f"Translation Requested: {trans!r}"
            )
            return trans.gettext
        except FileNotFoundError as ex:
            logging.warning(
                f"There is no Domain file for {domain} or locale directory is missing: {ex}"
            )
