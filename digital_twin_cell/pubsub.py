"""In-process publish/subscribe broker.

No external MQTT broker: topics are plain strings, delivery is
synchronous and in-process, so a demo runs anywhere with plain Python.
Supports exact topics (``cell/part``) and a trailing ``/*`` wildcard
(``cell/*`` matches every topic under ``cell/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class Message:
    """One published message."""

    topic: str
    payload: Dict[str, Any]
    timestamp_s: float = 0.0
    seq: int = 0


class Broker:
    """A tiny synchronous pub/sub broker."""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[Message], None]]] = {}
        self._seq = 0
        self.published = 0  # total messages published (handy for tests/demos)

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> None:
        """Subscribe ``callback`` to ``topic`` (exact or ``prefix/*``)."""
        self._subs.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[Message], None]) -> bool:
        """Remove a subscription; returns True if one was removed."""
        callbacks = self._subs.get(topic, [])
        if callback in callbacks:
            callbacks.remove(callback)
            if not callbacks:
                del self._subs[topic]
            return True
        return False

    def publish(self, topic: str, payload: Dict[str, Any], timestamp_s: float = 0.0) -> Message:
        """Publish a message to every matching subscriber, in order."""
        self._seq += 1
        self.published += 1
        msg = Message(topic=topic, payload=payload, timestamp_s=timestamp_s, seq=self._seq)
        for pattern, callbacks in list(self._subs.items()):
            if self._matches(pattern, topic):
                for cb in list(callbacks):
                    cb(msg)
        return msg

    @staticmethod
    def _matches(pattern: str, topic: str) -> bool:
        if pattern == topic:
            return True
        if pattern.endswith("/*"):
            return topic.startswith(pattern[:-1])  # "cell/*" -> prefix "cell/"
        return False

    @property
    def subscription_count(self) -> int:
        return sum(len(cbs) for cbs in self._subs.values())
