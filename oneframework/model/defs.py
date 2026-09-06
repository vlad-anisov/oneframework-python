"""Определения приложения как записи в базе."""

from __future__ import annotations

import json

# Каноническая запись и отпечаток -- местные, без WASM: правило вернулось в оба
# языка, а сторожит его RFC 8785 и сверка питона с JavaScript.
from .schema import model_schema, type_schema
from . import docschema

__all__ = ["DEF_TABLE", "DEF_COLUMNS", "KINDS", "SKIPPED", "model_defs", "view_defs"]

DEF_TABLE = "_oneframework_def"

#: Раскладка таблицы определений: имя колонки, тип, остальное объявление.
DEF_COLUMNS = (
    ("kind", "TEXT", "NOT NULL"),
    ("name", "TEXT", "NOT NULL"),
    ("fingerprint", "TEXT", "NOT NULL"),
    ("doc", "TEXT", "NOT NULL"),
    ("revision", "INTEGER", "NOT NULL DEFAULT 1"),
    ("hlc", "TEXT", "NOT NULL DEFAULT ''"),
)

KINDS = ("types", "model", "view", "action")

def model_defs(models):
    """Определения моделей как данные: ``[(вид, имя, документ), ...]``."""
    models = list(models)
    docs = [type_schema(models)] + [model_schema(m) for m in models]
    # Вся выкладка -- один переход границы, а не по одному на определение.
    return [("types", "_", docs[0])] + [
        ("model", m.__name__, d) for m, d in zip(models, docs[1:])
    ]

SKIPPED: dict[str, str] = {}

def view_defs(views):
    """Документы видов как данные -- пара к :func:`model_defs`."""
    from ..ui.view import document

    SKIPPED.clear()
    ready = []
    for view in views:
        try:
            doc = document(view)
        except Exception as exc:
            SKIPPED[view.__name__] = f"{type(exc).__name__}: {exc}"
            continue
        # Рубеж на форме, и стоит он **здесь**, а не при записи.
        беды = docschema.problems(doc)
        if беды:
            raise ValueError(
                f"Документ вида {view.__name__!r} не сходится с "
                "protocol/document.json:\n  " + "\n  ".join(беды),
            )
        ready.append(("view", view.__name__, doc))

    return ready

#: Питоновский писатель определений удалён: базу пишет сборщик на JS
#: (`libs/js/src/build-db.mjs`) тем же кодом, каким её пишет устройство, а
#: правила переехали в `tests/js/defs.test.mjs`.
