"""Идентификатор записи, не зависящий от того, кто вставил первым."""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
import uuid as _uuid

__all__ = ["new_id", "is_id", "uuid7", "seeded_ids"]

_COUNTER_BITS = 12
_COUNTER_MAX = (1 << _COUNTER_BITS) - 1

_last_ms = 0
_counter = 0

def _uuid7_local() -> _uuid.UUID:
    """UUIDv7 своими руками -- для рантаймов старше 3.14."""
    global _last_ms, _counter

    ms = time.time_ns() // 1_000_000
    if ms > _last_ms:
        _last_ms, _counter = ms, 0
    else:
        _counter += 1
        if _counter > _COUNTER_MAX:
            _last_ms, _counter = _last_ms + 1, 0
        ms = _last_ms

    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (
        (ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | _counter << 64
        | 0b10 << 62
        | rand_b
    )
    return _uuid.UUID(int=value)

#: ``uuid.uuid7`` появился в стандартной библиотеке 3.14 (Pyodide у нас
#: 3.14.2).
uuid7 = getattr(_uuid, "uuid7", _uuid7_local)

_источник = None

_ПОСЕВ_MS = 1_577_836_800_000

def new_id() -> str:
    """Новый ключ записи -- строкой, потому что строкой он и хранится."""
    if _источник is not None:
        return _источник()
    return str(uuid7())

@contextlib.contextmanager
def seeded_ids(поток: str):
    global _источник
    номер = 0

    def следующий() -> str:
        nonlocal номер
        ms = _ПОСЕВ_MS + (номер >> _COUNTER_BITS)
        счёт = номер & _COUNTER_MAX
        зерно = hashlib.sha256(f"{поток}\0{номер}".encode("utf-8")).digest()
        rand_b = int.from_bytes(зерно[:8], "big") & ((1 << 62) - 1)
        номер += 1
        return str(_uuid.UUID(int=(
            (ms & ((1 << 48) - 1)) << 80
            | 0x7 << 76
            | счёт << 64
            | 0b10 << 62
            | rand_b
        )))

    прежний, _источник = _источник, следующий
    try:
        yield
    finally:
        _источник = прежний

def is_id(value) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        _uuid.UUID(value)
    except ValueError:
        return False
    return True
