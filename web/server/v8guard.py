"""One thread at a time in V8.

AKShare runs JavaScript through py_mini_racer (an embedded V8) in over a hundred functions: to
work out 同花顺's request token, to decode Sina's quotes, the trading calendar and more. The web
server calls AKShare from many threads at once (a sync in the background, each card's request
in the thread pool), and V8 entered from two threads together brings the whole process down
with a native crash (seen as libmini_racer.dylib in a stack and the page's 500). This wraps the
MiniRacer methods that enter V8 (creating one, running code in it, closing it, and its
finalizer) in one process-wide lock. Only the JavaScript is serialized, which takes
milliseconds; the network requests around it still run in parallel.
"""
from __future__ import annotations

import functools
import threading

LOCK = threading.RLock()
_METHODS = ("__init__", "eval", "call", "execute", "close", "__del__")


def install() -> bool:
    """Wrap MiniRacer's V8-entering methods in LOCK (once); False when py_mini_racer is absent."""
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        return False
    wrap(MiniRacer)
    return True


def wrap(cls: type) -> type:
    """Wrap ``cls``'s V8-entering methods in LOCK, once."""
    if getattr(cls, "_v8guard", False):
        return cls
    for name in _METHODS:
        original = cls.__dict__.get(name)
        if original is None:
            continue

        def locked(*args, _original=original, **kwargs):
            with LOCK:
                return _original(*args, **kwargs)
        functools.update_wrapper(locked, original)
        setattr(cls, name, locked)
    cls._v8guard = True
    return cls
