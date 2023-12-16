import asyncio
from urllib.parse import urlencode
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.auth import HTTPBasicAuth
# processing the response:
from bs4 import BeautifulSoup as bs
from lxml import html, etree
# flowtask related.
from querysource.libs.encoders import DefaultEncoder
from navigator.exceptions import ConfigError
from .abstract import AbstractAction


class RESTAction(AbstractAction):
    """RESTAction.

    Base class for actions that interact with REST APIs.
    """
    timeout: int = 60
    method: str = 'get'
    headers = {
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        'cache-control': 'max-age=0',
    }
    auth_type: str = 'key'
    token_type: str = 'Bearer'
    data_format: str = 'raw'

    def __init__(self, *args, **kwargs):
        self.timeout = int(kwargs.pop('timeout', 60))
        self.url: str = ''
        ## Auth Object:
        self.auth: dict = {}
        self.accept = kwargs.pop('accept', 'application/json')
        self.content_type = kwargs.pop('content_type', 'application/json')
        self._last_execution: dict = {}
        ## Headers
        try:
            headers = kwargs['headers']
        except KeyError:
            headers = {}
        self.headers = {
            "Accept": self.accept,
            "Content-Type": self.content_type,
            **self.headers,
            **headers
        }
        # Language:
        self.language: list = kwargs.pop('language', ['en-GB', 'en-US'])
        langs = []
        for lang in self.language:
            lang_str = f"{lang};q=0.9"
            langs.append(lang_str)
        langs.append('ml;q=0.7')
        self.headers["Accept-Language"] = ','.join(langs)
        super(RESTAction, self).__init__(*args, **kwargs)
        self._encoder = DefaultEncoder()

    def build_url(self, url, queryparams: str = None, args: dict = None):
        if isinstance(args, dict):
            u = url.format(**args)
        else:
            u = url
        if queryparams:
            if '?' in u:
                full_url = u + '&' + queryparams
            else:
                full_url = u + '?' + queryparams
        else:
            full_url = u
        self._logger.debug(
            f'Action URL: {full_url!s}'
        )
        return full_url

    async def request(
        self,
        url,
        method: str = 'get',
        data: dict = None,
        cookies: dict = None,
        headers: dict = None
    ):
        """
        request
            connect to an http source
        """
        result = []
        error = {}
        auth = None
        executor = ThreadPoolExecutor(max_workers=4)
        if headers is not None and isinstance(headers, dict):
            self.headers = {**self.headers, **headers}
        if self.auth_type == 'apikey':
            self.headers['Authorization'] = f"{self.token_type} {self.auth['apikey']}"
        elif self.auth:
            if 'apikey' in self.auth:
                self.headers['Authorization'] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == 'api_key':
                self.headers = {**self.headers, **self.auth}
            elif self.auth_type == 'key':
                url = self.build_url(
                    url,
                    args=self._arguments,
                    queryparams=urlencode(self.auth)
                )
            elif self.auth_type == 'basic':
                auth = HTTPBasicAuth(*self.auth)
            else:
                auth = HTTPBasicAuth(*self.auth)
        elif self._user:
            auth = HTTPBasicAuth(
                self._user,
                self._pwd
            )
        elif self.auth_type == 'basic':
            auth = HTTPBasicAuth(
                self._user,
                self._pwd
            )
        ## Start connection:
        self._logger.notice(f'HTTP: Connecting to {url} using {method}')
        if method == 'get':
            my_request = partial(
                requests.get,
                headers=self.headers,
                verify=False,
                auth=auth,
                params=data,
                timeout=self.timeout,
                cookies=cookies
            )
        elif method == 'post':
            if self.data_format == 'json':
                data = self._encoder.dumps(data)
                my_request = partial(
                    requests.post,
                    headers=self.headers,
                    json={"query": data},
                    verify=False,
                    auth=auth,
                    timeout=self.timeout,
                    cookies=cookies
                )
            else:
                data = self._encoder.dumps(data)
                my_request = partial(
                    requests.post,
                    headers=self.headers,
                    data=data,
                    verify=False,
                    auth=auth,
                    timeout=self.timeout,
                    cookies=cookies
                )
        elif method == 'put':
            my_request = partial(
                requests.put,
                headers=self.headers,
                data=data,
                verify=False,
                auth=auth,
                timeout=self.timeout
            )
        elif method == 'delete':
            my_request = partial(
                requests.delete,
                headers=self.headers,
                data=data,
                verify=False,
                auth=auth,
                timeout=self.timeout
            )
        elif method == 'patch':
            my_request = partial(
                requests.patch,
                headers=self.headers,
                data=data,
                verify=False,
                auth=auth,
                timeout=self.timeout
            )
        else:
            my_request = partial(
                requests.post,
                headers=self.headers,
                data=data,
                verify=False,
                auth=auth,
                timeout=self.timeout,
                cookies=cookies
            )
        # making request
        loop = asyncio.get_event_loop()
        future = [
            loop.run_in_executor(executor, my_request, url)
        ]
        try:
            result, error = await self.process_request(future)
            if error:
                if isinstance(error, BaseException):
                    raise error
                elif isinstance(error, bs):
                    return (result, error)
                else:
                    raise ConfigError(str(error))
            ## saving last execution parameters:
            self._last_execution = {
                "url": self.url,
                "method": method,
                "data": data,
                "auth": bool(auth),
                "headers": self.headers
            }
            return (result, error)
        except Exception as err:
            self._logger.exception(err)
            raise ConfigError(
                f"Error: {err}"
            ) from err

    async def process_request(self, future):
        try:
            loop = asyncio.get_running_loop()
            asyncio.set_event_loop(loop)
            error = None
            for response in await asyncio.gather(*future):
                # getting the result, based on the Accept logic
                if self.accept in (
                    'application/xhtml+xml',
                    'text/html',
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
                ):
                    try:
                        # html parser for lxml
                        self._parser = html.fromstring(response.text)
                        # Returning a BeautifulSoup parser
                        self._bs = bs(response.text, 'html.parser')
                        result = self._bs
                    except (AttributeError, ValueError) as e:
                        error = e
                elif self.accept == 'application/xml':
                    try:
                        self._parser = etree.fromstring(response.text)
                    except (AttributeError, ValueError) as e:
                        error = e
                elif self.accept in ('text/plain', 'text/csv'):
                    result = response.text
                elif self.accept == 'application/json':
                    try:
                        result = self._encoder.loads(response.text)
                        # result = response.json()
                    except (AttributeError, ValueError) as e:
                        self._logger.error(e)
                        # is not an json, try first with beautiful soup:
                        try:
                            self._bs = bs(response.text, 'html.parser')
                            result = self._bs
                        except (AttributeError, ValueError) as ex:
                            error = ex
                else:
                    try:
                        self._bs = bs(response.text, 'html.parser')
                    except (AttributeError, ValueError) as ex:
                        error = ex
                    result = response.text
            return (result, error)
        except (requests.exceptions.ProxyError) as err:
            raise ConfigError(
                f"Proxy Connection Error: {err!r}"
            ) from err
        except (requests.ReadTimeout) as ex:
            return ([], ex)
        except requests.exceptions.Timeout as err:
            return ([], err)
        except requests.exceptions.HTTPError as err:
            return ([], err)
        except (
            requests.exceptions.RequestException,
        ) as e:
            raise ConfigError(
                f"HTTP Connection Error: {e!r}"
            ) from e
        except Exception as e:
            self.logger.exception(e)
            raise ConfigError(
                f"HTTP Connection Error: {e!r}"
            ) from e
