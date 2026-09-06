"""Действие, объявленное данными: правило + запись, без единого байта кода."""

from __future__ import annotations

from ..errors import OneFrameworkError

#: Исполнителей здесь нет и не должно быть: действие исполняет устройство
#: (`libs/js/src/core/runtime/logic.js`), правила -- в `tests/js/logic-
#: host.test.mjs`.
__all__ = ["is_declarative", "is_python", "is_js", "is_wasm"]

def is_declarative(doc):
    return isinstance(doc, dict) and "entry" not in doc and (
        "rule" in doc or "write" in doc or is_python(doc) or is_js(doc)
        or is_wasm(doc))

def is_python(doc):
    return isinstance(doc, dict) and isinstance(doc.get("python"), dict) \
        and "source" in doc["python"]

def is_wasm(doc):
    return isinstance(doc, dict) and isinstance(doc.get("wasm"), dict) \
        and "module" in doc["wasm"]

def is_js(doc):
    return isinstance(doc, dict) and isinstance(doc.get("js"), dict) \
        and "source" in doc["js"]
