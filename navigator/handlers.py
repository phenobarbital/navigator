import asyncio
import logging


async def shutdown(loop, signal=None):
    """Cleanup tasks tied to the service's shutdown."""
    if signal:
        print(f"Received exit signal {signal.name}...")
    try:
        tasks = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        result = [task.cancel() for task in tasks]
        # asyncio.gather(*asyncio.Task.all_tasks()).cancel()
        print(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass  # Nothing to do or see here
    except Exception as err:
        print("Generic Error", err)


def nav_exception_handler(loop, context):
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
