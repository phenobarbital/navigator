"""Push provider abstractions for geofencing notifications.

Defines the :class:`PushProvider` ABC that all push notification backends
must implement.  v1 ships :class:`~.fcm.FCMProvider` (FCM HTTP v1).
v2 will add ``apns.py`` (native Apple Push Notifications) behind this same
interface.

See Also:
    ``sdd/specs/mqtt-rabbitmq-broker.spec.md`` Module 8.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PushProvider(ABC):
    """Abstract base class for mobile push notification providers.

    All concrete providers must implement :meth:`send`.  The interface is
    intentionally minimal so both FCM (v1) and APNs (v2) fit without
    adaptation.
    """

    @abstractmethod
    async def send(self, device_token: str, payload: dict) -> None:
        """Send a push notification to a single device.

        Args:
            device_token: Platform-specific device registration token
                (FCM registration ID, APNs device token, etc.).
            payload: JSON-serializable notification payload dict.  The
                concrete provider is responsible for adapting this to its
                platform-specific structure.

        Raises:
            Exception: Any provider-specific error (e.g., ``FCMError``).
                Callers should handle exceptions per-provider.
        """
