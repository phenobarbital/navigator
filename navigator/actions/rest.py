import os
import asyncio
from urllib.parse import urlencode
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import random
from pathlib import Path
from io import BytesIO
import aiofiles
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import HTTPError
import httpx
import aiohttp
from aiohttp import BasicAuth
# processing the response:
from bs4 import BeautifulSoup as bs
from lxml import html, etree
from proxylists.proxies import FreeProxy
from asyncdb.utils.functions import cPrint
from ..libs.json import JSONContent
from ..exceptions import ConfigError
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
        self._user: str = kwargs.get('user', None)
        self._pwd: str = kwargs.get('password', None)
        self.accept = kwargs.pop('accept', 'application/json')
        self.content_type = kwargs.pop('content_type', 'application/json')
        self._last_execution: dict = {}
        self.download: bool = kwargs.pop('download', False)
        self.use_streams: bool = kwargs.pop('use_streams', False)
        self.use_proxy: bool = kwargs.pop('use_proxy', False)
        self.file_buffer: bool = kwargs.pop('file_buffer', False)
        self._proxies: list = []
        ## Headers
        try:
            headers = kwargs['headers']
        except KeyError:
            headers = {}
        self.headers = {
            "Accept": self.accept,
            "Content-Type": self.content_type,
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            **self.headers,
            **headers
        }
        # Language:
        self.language: list = kwargs.pop(
            'language', ['en-GB', 'en-US']
        )
        langs = []
        for lang in self.language:
            lang_str = f"{lang};q=0.9"
            langs.append(lang_str)
        langs.append('ml;q=0.7')
        self.headers["Accept-Language"] = ','.join(langs)
        super(RESTAction, self).__init__(*args, **kwargs)
        self._encoder = JSONContent()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._semaphore = asyncio.Semaphore(10)  # Adjust the number as neededd

    async def get_proxies(self):
        """
        Asynchronously retrieves a list of free proxies.
        """
        return await FreeProxy().get_list()

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

    async def open(self) -> None:
        if self.use_proxy is True:
            self._proxies = await self.get_proxies()

    async def close(self):
        pass

    async def request(
        self,
        url,
        method: str = 'get',
        data: dict = None,
        cookies: dict = None,
        headers: dict = None
    ):
        """
        request.
            connect to an http source unsing Requests.
        """
        result = []
        error = {}
        auth = None
        proxies = None
        if self._proxies:
            proxy = random.choice(self._proxies)
            proxies = {
                "http": proxy,
                "https": proxy,
                "ftp": proxy
            }
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
        self._logger.notice(
            f'HTTP: Connecting to {url} using {method}'
        )
        args = {
            "timeout": self.timeout,
            "headers": self.headers,
            "cookies": cookies
        }
        if auth is not None:
            args['auth'] = auth
            args['verify'] = False
        if self._proxies:
            args['proxies'] = proxies
        if method == 'get':
            my_request = partial(
                requests.get,
                params=data,
                **args
            )
        elif method == 'post':
            if self.data_format == 'json':
                data = self._encoder.dumps(data)
                my_request = partial(
                    requests.post,
                    json={"query": data},
                    **args
                )
            else:
                data = self._encoder.dumps(data)
                my_request = partial(
                    requests.post,
                    data=data,
                    **args
                )
        elif method == 'put':
            my_request = partial(
                requests.put,
                data=data,
                **args
            )
        elif method == 'delete':
            my_request = partial(
                requests.delete,
                data=data,
                **args
            )
        elif method == 'patch':
            my_request = partial(
                requests.patch,
                data=data,
                **args
            )
        else:
            my_request = partial(
                requests.post,
                data=data,
                **args
            )
        # making request
        async with self._semaphore:
            try:
                loop = asyncio.get_running_loop()
                future = loop.run_in_executor(self._executor, my_request, url)
                result, error = await self.process_request(future, url)
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
            except HTTPError as err:
                self._logger.error(
                    f"HTTP error occurred: {err}"
                )
                # Log the error or perform other error handling
                raise ConfigError(
                    f"{err}"
                )
            except requests.exceptions.ReadTimeout as err:
                self._logger.warning(
                    f"Timeout Error: {err!r}"
                )
                # TODO: retrying
                raise ConfigError(
                    f"Timeout: {err}"
                ) from err
            except Exception as err:
                self._logger.exception(err)
                raise ConfigError(
                    f"Error: {err}"
                ) from err

    async def process_request(self, future, url: str):
        error = None
        result = None
        loop = asyncio.get_running_loop()
        asyncio.set_event_loop(loop)
        done, _ = await asyncio.wait([future], return_when=asyncio.FIRST_COMPLETED)
        for f in done:
            response = f.result()
            # Check for HTTP errors
            try:
                response.raise_for_status()
            except HTTPError as http_err:
                # Handle HTTP errors here
                error = http_err
                # Log the error or perform other error handling
                if response.headers.get('content_type') == 'application/json':
                    rsp = response.json()
                else:
                    rsp = response.text
                self._logger.error(
                    f"HTTP error: {http_err} with response: {rsp!s}"
                )
                # You can choose to continue, break, or return based on your logic
                raise HTTPError(
                    f"HTTP error: {http_err} with response: {rsp!s}"
                )
            try:
                if self.download is True:
                    # Filename:
                    filename = os.path.basename(url)
                    # Get the filename from the response headers, if available
                    content_disposition = response.headers.get('content-disposition')
                    if content_disposition:
                        _, params = content_disposition.split(';')
                        try:
                            key, value = params.strip().split('=')
                            if key == 'filename':
                                filename = value.strip('\'"')
                        except ValueError:
                            pass
                    if isinstance(filename, str):
                        filename = Path(filename)
                    # Saving File in Directory:
                        total_length = response.headers.get('Content-Length')
                        self._logger.info(
                            f'HTTPClient: Saving File {filename}, size: {total_length}'
                        )
                        pathname = filename.parent.absolute()
                        if not pathname.exists():
                            # Create a new directory
                            pathname.mkdir(parents=True, exist_ok=True)
                        transfer = response.headers.get("transfer-encoding", None)
                        if transfer is None:
                            chunk_size = int(total_length)
                        else:
                            chunk_size = 8192
                        with open(filename, 'wb') as fp:
                            try:
                                for chunk in response.iter_content(
                                    chunk_size=chunk_size
                                ):
                                    fp.write(chunk)
                                fp.flush()
                            except Exception:
                                pass
                        self._logger.debug(
                            f'Filename Saved Successfully: {filename}'
                        )
                        result = filename
                # getting the result, based on the Accept logic
                elif self.file_buffer is True:
                    data = await response.read()
                    buffer = BytesIO(data)
                    buffer.seek(0)
                    result = buffer
                elif self.accept in (
                    'text/html',
                    'application/xhtml+xml',
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
                elif self.accept in ('application/xhtml+xml', 'application/xml'):
                    try:
                        self._parser = etree.fromstring(response.text)
                    except (AttributeError, ValueError) as e:
                        error = e
                elif self.accept in ('text/plain', 'text/csv'):
                    result = response.text
                elif self.accept == 'application/json':
                    try:
                        result = self._encoder.loads(response.text)
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

    async def async_request(
        self,
        url: str,
        method: str = 'get',
        data: dict = None,
        cookies: dict = None,
        headers: dict = None,
        use_json: bool = False
    ):
        """
        Asynchronously sends an HTTP request using aiohttp.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :param use_json: Whether to send the data as JSON.
        :param cookies: A dictionary of cookies to send with the request.
        :param headers: A dictionary of headers to send with the request.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxies = None
        if self._proxies:
            proxies = random.choice(self._proxies)
        if self.credentials:
            if 'apikey' in self.auth:
                self.headers['Authorization'] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == 'api_key':
                self.headers = {**self.headers, **self.credentials}
            elif self.auth_type == 'key':
                url = self.build_url(
                    url,
                    args=self._arguments,
                    queryparams=urlencode(self.credentials)
                )
            elif self.auth_type in ['basic', 'auth', 'user']:
                auth = BasicAuth(
                    self.credentials['username'],
                    self.credentials['password']
                )
        elif self._user and self.auth_type == 'basic':
            auth = BasicAuth(self._user, self._pwd)
        cPrint(
            f'HTTP: Connecting to {url} using {method}', level='DEBUG'
        )
        if auth is not None:
            args = {
                "auth": auth
            }
        else:
            args = {}
        if self.download is True:
            self.headers['Accept'] = 'application/octet-stream'
            self.headers['Content-Type'] = 'application/octet-stream'
            if hasattr(self, 'use_streams'):
                self.headers['Transfer-Encoding'] = 'chunked'
                args["stream"] = True
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = self.headers
        if headers is not None and isinstance(headers, dict):
            headers = {**self.headers, **headers}
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            auth=auth,
            cookies=cookies
        ) as session:
            try:
                if use_json is True:
                    async with session.request(
                        method.upper(),
                        url,
                        json=data,
                        proxy=proxies,
                        **args
                    ) as response:
                        result, error = await self.process_response(response, url)
                else:
                    async with session.request(
                        method.upper(),
                        url,
                        data=data,
                        proxy=proxies,
                        **args
                    ) as response:
                        # Process the response
                        result, error = await self.process_response(response, url)
            except aiohttp.ClientError as e:
                error = str(e)
        return (result, error)

    async def process_response(self, response, url: str) -> tuple:
        """
        Processes the response from an HTTP request.

        :param response: The response object from aiohttp.
        :param url: The URL that was requested.
        :return: A tuple containing the processed result and any error information.
        """
        error = None
        result = None
        # Process the response
        if response.status >= 400:
            # Evaluate response body and headers.
            content_type = response.headers.get('Content-Type', '').lower()
            if 'application/json' in content_type:
                message = await response.json()
            elif 'text/' in content_type:
                message = await response.text()
            elif 'X-Error' in response.headers:
                message = response.headers['X-Error']
            else:
                message = response.reason
            # Log the error or perform other error handling
            self._logger.error(
                f"Error: {message}, status: {response.status}"
            )
            if hasattr(self, 'no_errors'):
                for key, msg in self.no_errors.items():
                    if int(key) == response.status:
                        if await self.evaluate_error(message, msg):
                            return (response, response.status)
            # Raise an exception
            error = {
                "status": response.status,
                "message": message,
                "response": response
            }
            return (None, error)
        else:
            if self.download is True:
                filename = os.path.basename(url)
                # Get the filename from the response headers, if available
                content_disposition = response.headers.get('content-disposition')
                if content_disposition:
                    _, params = content_disposition.split(';')
                    try:
                        key, value = params.strip().split('=')
                        if key == 'filename':
                            filename = value.strip('\'"')
                    except ValueError:
                        pass
                if isinstance(filename, str):
                    filename = Path(filename)
                # Saving File in Directory:
                total_length = response.headers.get('Content-Length')
                self._logger.info(
                    f'HTTPClient: Saving File {filename}, size: {total_length}'
                )
                pathname = filename.parent.absolute()
                if not pathname.exists():
                    # Create a new directory
                    pathname.mkdir(parents=True, exist_ok=True)
                transfer = response.headers.get("transfer-encoding", None)
                if transfer is None:
                    chunk_size = int(total_length)
                else:
                    chunk_size = 8192
                # Asynchronous file writing
                if filename.exists() and filename.is_file():
                    self._logger.warning(
                        f'HTTPClient: File Already exists: {filename}'
                    )
                    # Filename already exists
                    result = filename
                    return result, error
                if self.use_streams is True:
                    async with aiofiles.open(filename, 'wb') as file:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await file.write(chunk)
                else:
                    with open(filename, 'wb') as fp:
                        try:
                            fp.write(await response.read())
                        except Exception:
                            pass
                self._logger.debug(
                    f'Filename Saved Successfully: {filename}'
                )
                result = filename
            elif self.file_buffer is True:
                data = await response.read()
                buffer = BytesIO(data)
                buffer.seek(0)
                result = buffer
            elif self.accept in ('text/html'):
                result = await response.read()  # Get content of the response as bytes
                try:
                    # html parser for lxml
                    self._parser = html.fromstring(result)
                    # BeautifulSoup parser
                    self._bs = bs(await response.text(), 'html.parser')
                    result = self._bs
                except Exception as e:
                    error = e
            elif self.accept in ('application/xhtml+xml', 'application/xml'):
                result = await response.read()  # Get content of the response as bytes
                try:
                    self._parser = etree.fromstring(result)
                except Exception as e:
                    error = e
            elif self.accept == 'application/json':
                try:
                    result = await response.json()
                except Exception as e:
                    self._logger.error(
                        f"Error: {e!r}"
                    )
                    # is not an json, try first with beautiful soup:
                    try:
                        self._bs = bs(await response.text(), 'html.parser')
                        result = self._bs
                    except Exception:
                        error = e
            else:
                result = await response.text()
        return result, error

    async def session(
        self,
        url: str,
        method: str = 'get',
        data: dict = None,
        cookies: dict = None,
        headers: dict = None,
        use_json: bool = False
    ):
        """
        Asynchronously sends an HTTP request using HTTPx.

        :param url: The URL to send the request to.
        :param method: The HTTP method to use (e.g., 'GET', 'POST').
        :param data: The data to send in the request body.
        :param use_json: Whether to send the data as JSON.
        :param cookies: A dictionary of cookies to send with the request.
        :param headers: A dictionary of headers to send with the request.
        :return: A tuple containing the result and any error information.
        """
        result = []
        error = {}
        auth = None
        proxies = None
        if self._proxies:
            proxy = random.choice(self._proxies)
            proxies = {
                "http": proxy,
                "https": proxy,
                "ftp": proxy
            }
        if self.credentials:
            if 'apikey' in self.auth:
                self.headers['Authorization'] = f"{self.token_type} {self.auth['apikey']}"
            elif self.auth_type == 'api_key':
                self.headers = {**self.headers, **self.credentials}
            elif self.auth_type == 'key':
                url = self.build_url(
                    url,
                    args=self._arguments,
                    queryparams=urlencode(self.credentials)
                )
            elif self.auth_type in ['basic', 'auth', 'user']:
                auth = (
                    self.credentials['username'],
                    self.credentials['password']
                )
        elif self._user and self.auth_type == 'basic':
            auth = (self._user, self._pwd)
        cPrint(
            f'HTTP: Connecting to {url} using {method}', level='DEBUG'
        )
        if self.download is True:
            self.headers['Accept'] = 'application/octet-stream'
            self.headers['Content-Type'] = 'application/octet-stream'
            if self.use_streams is True:
                self.headers['Transfer-Encoding'] = 'chunked'
        headers = self.headers
        if headers is not None and isinstance(headers, dict):
            headers = {**self.headers, **headers}
        timeout = httpx.Timeout(self.timeout)
        args = {
            "timeout": timeout,
            "headers": headers,
            "cookies": cookies
        }
        if auth is not None:
            args['auth'] = auth
        if proxies:
            args['proxies'] = proxies
        async with httpx.AsyncClient(**args) as client:
            try:
                request_func = getattr(client, method.lower())
                if use_json:
                    response = await request_func(url, json=data)
                else:
                    response = await request_func(url, data=data)
                # Process the response
                result, error = await self.process_response(response, url)
            except httpx.HTTPError as e:
                error = str(e)
        return (result, error)
