"""План выкладки -- у ядра. Здесь перевод, а не вторая реализация.

Строит план `libs/js/src/build/plan.mjs`: пакет объявления -> схема,
определения, строки посева. Раньше то же правило было записано и здесь, на
питоне; две живые записи одного правила расходятся молча, и держались они
сверкой -- а сверять стало нечего, когда на ядро перешли и сборка, и
`inspect`.

Осталась дверь для питоновской стороны: проверкам и оснастке удобно спросить
план, не поднимая сборку целиком. За дверью -- то же ядро.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .. import core
from ..errors import OneFrameworkError

КОРЕНЬ = Path(__file__).resolve().parents[2]


def build_plan(app, seed=None):
    """Пакет объявления -> всё, что нужно положить в базу приложения.

    ``seed`` не принимается: посев записывается при печати пакета
    (`declaration.declare`). Отказ вслух, а не молчание -- иначе `--seed`
    проглатывался бы без следа.
    """
    if seed is not None:
        raise OneFrameworkError(
            "Посев записывается при печати пакета, а не здесь: "
            "`declare(app, seed)`. Отказ вслух, а не молчание: иначе `--seed` "
            "проглатывался бы без следа.",
        )
    doc = getattr(app, "doc", app)
    if not isinstance(doc, dict) or "models" not in doc:
        raise OneFrameworkError(
            "build_plan принимает пакет объявления, а не приложение. Напечатайте "
            "пакет: `Bundle(declare(app, seed))`. Дорога одна намеренно -- иначе "
            "у питона был бы свой путь мимо договора, и ядро без питоновской "
            "привязки собрало бы другое приложение.",
        )
    скрипт = (
        "import { readFileSync } from 'node:fs';\n"
        f"import {{ buildPlan }} from {json.dumps(str(core.файл('src', 'build', 'plan.mjs')))};\n"
        "process.stdout.write(JSON.stringify("
        "buildPlan(JSON.parse(readFileSync(process.argv[1], 'utf8')))));"
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as ф:
        json.dump(doc, ф, ensure_ascii=False, default=str)
        путь = ф.name
    готово = subprocess.run([core.node(), "--input-type=module", "-e", скрипт, путь],
                            capture_output=True, text=True, encoding="utf-8",
                            cwd=str(КОРЕНЬ))
    if готово.returncode != 0:
        raise OneFrameworkError(готово.stderr.strip())
    return json.loads(готово.stdout)
