"""navigator.brokers — shim re-exporting from navigator_eventbus.brokers.

The broker implementations were extracted to the ``navigator-eventbus``
package. This shim keeps ``from navigator.brokers import ...`` and
``from navigator.brokers.rabbitmq import ...`` working so existing
consumers don't break immediately.

Install ``navigator-api[brokers]`` (or ``navigator-eventbus[brokers]``)
to pull the concrete broker dependencies.
"""
import importlib
import warnings

_EVENTBUS_PKG = "navigator_eventbus.brokers"


def __getattr__(name: str):
    try:
        mod = importlib.import_module(_EVENTBUS_PKG)
    except ModuleNotFoundError:
        raise ImportError(
            "navigator.brokers has been extracted to the 'navigator-eventbus' "
            "package. Install it with: pip install navigator-eventbus[brokers]"
        ) from None
    warnings.warn(
        f"navigator.brokers.{name} is deprecated — use "
        f"navigator_eventbus.brokers.{name} instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(mod, name)
