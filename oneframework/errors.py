"""Developer-facing errors.

Every error raised while a user's ``app.py`` is being defined or bound should be
actionable: name the offending symbol, name the context it appeared in, and when
possible suggest the intended spelling.
"""

from __future__ import annotations

import difflib

__all__ = ["OneFrameworkError", "DslError", "SchemaError", "ValidationError",
           "suggest", "did_you_mean"]


class OneFrameworkError(Exception):
    """Base class for every error raised by oneframework."""


class DslError(OneFrameworkError):
    """Raised while interpreting a declarative ``Model``/``View`` body."""


class ValidationError(OneFrameworkError):
    """Набор не прошёл проверку бизнес-логики.

    Ошибок держится **список**, а не первая: набор -- это и одна карточка, и
    импорт тысячи строк, и человеку, поправившему одну строку из тысячи, не
    место в очереди из тысячи заходов. Каждая называет номер записи в наборе и
    поле, если оно известно, -- ровно то, что отдаёт ``oneframework_validate``.
    """

    def __init__(self, errors, message=None):
        self.errors = [dict(e) for e in errors]
        super().__init__(message or "; ".join(
            str(e.get("message") or e) for e in self.errors
        ))


class SchemaError(OneFrameworkError):
    """Raised when the declared models cannot be reconciled with the database."""


def suggest(name: str, candidates) -> str | None:
    """Return the closest candidate to *name*, or ``None``."""
    candidates = [c for c in candidates if c != name]
    if not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    # difflib is strict about short names; fall back to a prefix heuristic.
    lowered = name.lower()
    for c in candidates:
        if c.lower().startswith(lowered[:3]) or lowered.startswith(c.lower()[:3]):
            return c
    return None


def did_you_mean(name: str, candidates) -> str:
    """Return a ``" Did you mean 'x'?"`` fragment, or an empty string."""
    match = suggest(name, candidates)
    return f" Did you mean {match!r}?" if match else ""
