import asyncio
from typing import Any
from collections.abc import Generator
import logging
from contextlib import suppress
### TODO: review exception handlers for asyncio


async def shutdown(loop: asyncio.AbstractEventLoop, signal: Any = None):
    """Cleanup tasks tied to the service's shutdown."""
    if signal:
        logging.info(
            f"Received exit signal {signal.name}..."
        )
    else:
        logging.warning("Shutting NOT via signal")
    logging.info("Closing all connections")
    try:
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        if len(tasks) > 0:
            status = [task.cancel() for task in tasks]
            logging.warning(
                f"Cancelling {len(tasks)} outstanding tasks: {status}"
            )
            await asyncio.gather(*tasks, return_exceptions=True)
        logging.warning('Asyncio Shutdown: Done graceful shutdown of subtasks')
    except asyncio.exceptions.CancelledError:
        pass
    except Exception as e:
        logging.exception(e, stack_info=True)
        raise Exception(
            f"Asyncio Shutdown Error: {e}"
        ) from e
    finally:
        with suppress(asyncio.exceptions.CancelledError):
            loop.stop()


def nav_exception_handler(loop: asyncio.AbstractEventLoop, context: Generator):
    """Exception Handler for Asyncio Loops."""
    # first, handle with default handler
    if context:
        loop.default_exception_handler(context)
        exception = context.get("exception")
        try:
            msg = context.get("exception", context["message"])
            logging.error(f"Caught Exception: {msg}")
        except (TypeError, AttributeError, IndexError):
            logging.error(
                f"Caught Exception: {exception!s}, Context: {context!s}"
            )
        # Canceling pending tasks and stopping the loop
        try:
            loop.run_until_complete(shutdown(loop))
        except Exception as e:
            print("Shutdown Error: ", e)
