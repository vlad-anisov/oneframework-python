"""Таблица типов -- исходником для Kotlin.

Ресурс рядом с классами читает только JVM, а библиотека объявления собирается
ещё и под WebAssembly, где никакого classpath нет. Строка есть на обеих
платформах -- значит таблица едет строкой.

Порождается отсюда, сторожится ``tests/test_protocol.py``:

    python3 -m oneframework.cli.kotlin_table
"""

from __future__ import annotations

import json
from pathlib import Path

from ..protocol import TABLE_PATH

OUT = (Path(__file__).resolve().parents[2] / "libs" / "kotlin" / "src" / "main"
       / "kotlin" / "oneframework" / "FieldTypes.kt")

ШАПКА = '''package oneframework

/**
 * Таблица типов полей -- та же, что у питона и у JavaScript.
 *
 * Лежит **исходником**, а не ресурсом рядом с классами: ресурс читает только
 * JVM, а эта библиотека собирается ещё и под WebAssembly, где никакого
 * classpath нет. Строка есть на обеих платформах.
 *
 * Порождается из `protocol/field-types.json`
 * (`python3 -m oneframework.cli.kotlin_table`), совпадение сторожит
 * `tests/test_protocol.py`. Руками не править: правка уедет при первой
 * пересборке.
 */
internal const val FIELD_TYPES_JSON: String =
'''


def source() -> str:
    """Файл целиком -- то, что должно лежать в ``FieldTypes.kt``."""
    текст = TABLE_PATH.read_text(encoding="utf-8")
    # Экранирование JSON почти совпадает с котлиновским, но доллар в Kotlin
    # начинает подстановку. В таблице он есть -- ключ `$comment`.
    литерал = json.dumps(текст).replace("$", "\\$")
    return f"{ШАПКА}    {литерал}\n"


def write() -> Path:
    OUT.write_text(source(), encoding="utf-8")
    return OUT


if __name__ == "__main__":  # pragma: no cover - ручная пересборка
    print(write())
