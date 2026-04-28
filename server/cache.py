"""LRU cache for expensive beancount computations keyed on entries list identity."""

import threading
from collections import OrderedDict

from beancount.core import realization, prices

_lock = threading.Lock()
_realize_cache: OrderedDict = OrderedDict()
_price_cache: OrderedDict = OrderedDict()
_MAX_SIZE = 3


def _lru_get_or_compute(cache, key, compute_fn):
    with _lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]

    value = compute_fn()

    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _MAX_SIZE:
            cache.popitem(last=False)

    return value


def get_realized(entries):
    """Return cached realization tree for the given entries list."""
    return _lru_get_or_compute(
        _realize_cache,
        id(entries),
        lambda: realization.realize(entries),
    )


def get_price_map(entries):
    """Return cached price map for the given entries list."""
    return _lru_get_or_compute(
        _price_cache,
        id(entries),
        lambda: prices.build_price_map(entries),
    )
