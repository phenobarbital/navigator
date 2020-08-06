import asyncio

async def shutdown(loop, signal=None):
    """Cleanup tasks tied to the service's shutdown."""
    if signal:
        print(f"Received exit signal {signal.name}...")
    print("Closing all connections")
    try:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        [task.cancel() for task in tasks]
        print(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        print('Tasks has been canceled')
    #asyncio.gather(*asyncio.Task.all_tasks()).cancel()

def nav_exception_handler(loop, context):
    """Exception Handler for Asyncio Loops."""
    # first, handle with default handler
    if context:
        loop.default_exception_handler(context)
        exception = context.get('exception')
        print(exception)
        print(context)
        try:
            msg = context.get("exception", context["message"])
            print("Caught Exception: {}".format(str(msg)))
        except (TypeError, AttributeError, IndexError):
            print("Caught Exception: {}, Context: {}".format(str(exception), str(context)))
        # Canceling pending tasks and stopping the loop
        try:
            print("Asyncio Shutting down...")
            loop.run_until_complete(shutdown(loop))
        except Exception as e:
            print(e)
        finally:
            print("Successfully shutdown service.")
            #loop.stop()
