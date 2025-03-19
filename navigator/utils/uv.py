import asyncio
import contextlib


def install_uvloop():
    """ install uvloop and set as default loop for asyncio. """
    with contextlib.suppress(ImportError):
        import uvloop  # noqa pylint: disable=C0415
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        uvloop.install()
