"""Питон на устройстве: рантайм и чужие колёса едут в сборку файлами.

Зачем это вообще. Язык приложения переводится в SQL, и почти всё, что пишут в
формуле, туда переводится. Но не всё: словарной морфологии, разбора PDF или
чужого формата в SQL нет и не будет. Такой код объявляется **устройственным**:
едет исходником и выполняется настоящим питоном у пользователя.

Почему файлами, а не установкой на месте. ``micropip`` умеет ставить с PyPI, и
в вебе это сработало бы -- но webview у пользователя может быть без сети, а
приложение обязано работать офлайн. Поэтому колёса кладутся в сборку рядом с
рантаймом и ставятся из локальных адресов: то же самое ``micropip``, но
источник свой.

Цена названа прямо: рантайм это ~13 МБ распакованными, и он приезжает вместе с
приложением. Сборка без объявленных пакетов его не тянет вовсе.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

#: Файлы рантайма Pyodide, без которых он не поднимется.
RUNTIME_FILES = (
    "pyodide.mjs",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
)

#: Куда всё это кладётся внутри сборки.
FOLDER = "python"


def vendor(root: Path, packages) -> dict:
    """Положить рантайм и колёса в ``web/public/python``.

    Возвращает опись: что именно уехало в сборку. Опись читает устройство --
    ставить оно будет ровно перечисленное и ничего сверх.
    """
    target = root / "web" / "public" / FOLDER
    if not packages:
        # Пакетов не объявили -- ничего не везём. Приложение остаётся прежним
        # по весу, и это важнее удобства: питон на устройстве нужен единицам.
        if target.exists():
            shutil.rmtree(target)
        return {"packages": [], "wheels": []}

    source = root / "node_modules" / "pyodide"
    if not source.exists():
        raise FileNotFoundError(
            "Нет node_modules/pyodide, а приложение объявило питоновские "
            "пакеты. Поставьте его: npm install pyodide"
        )
    (target / "wheels").mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        src = source / name
        if src.exists():
            shutil.copy2(src, target / name)

    wheels, видели = [], set()
    очередь = list(packages)
    while очередь:
        spec = очередь.pop(0)
        имя = spec.partition("==")[0].lower().replace("_", "-")
        if имя in видели:
            continue
        видели.add(имя)
        файл, зависимости = _fetch_wheel(spec, target / "wheels")
        wheels.append(файл)
        # Зависимости тянутся здесь же: на устройстве сети может не быть, а
        # `micropip` без неё пошёл бы за ними на PyPI и споткнулся.
        очередь.extend(зависимости)
    опись = {"packages": list(packages), "wheels": wheels}
    (target / "packages.json").write_text(
        json.dumps(опись, ensure_ascii=False, indent=2), encoding="utf-8")
    return опись


def _fetch_wheel(spec: str, into: Path) -> str:
    """Скачать колесо с PyPI -- один раз, на сборке.

    Только ``py3-none-any`` и подобные: колесо с C-расширением под обычную
    платформу на устройстве не заработает, и молча положить его в сборку
    значило бы отложить отказ до пользователя.
    """
    name, _, version = spec.partition("==")
    url = f"https://pypi.org/pypi/{name}/json" if not version else \
        f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as ответ:
            данные = json.load(ответ)
    except urllib.error.HTTPError as exc:
        raise LookupError(f"нет такого пакета на PyPI: {spec}") from exc

    подходящие = [f for f in данные["urls"]
                  if f["packagetype"] == "bdist_wheel"
                  and f["filename"].endswith(("-any.whl",))]
    if not подходящие:
        raise LookupError(
            f"у пакета {spec} нет чистого колеса (py3-none-any). "
            "На устройстве работает только чистый питон: с C-расширением "
            "колесо туда не поедет."
        )
    колесо = подходящие[0]
    файл = into / колесо["filename"]
    if not файл.exists():
        with urllib.request.urlopen(колесо["url"], timeout=120) as ответ:
            файл.write_bytes(ответ.read())
    return колесо["filename"], _required(данные["info"].get("requires_dist"))


def _required(requires):
    """Обязательные зависимости. Дополнительные и платформенные -- мимо.

    ``extra ==`` -- то, что ставят по желанию; ``python_version <`` и прочие
    метки -- то, что этому питону не нужно. Тащить их значило бы возить в
    сборке пакеты, которые никогда не импортируются.
    """
    out = []
    for строка in requires or []:
        имя, _, хвост = строка.partition(";")
        if "extra ==" in хвост:
            continue
        if "platform_python_implementation" in хвост:
            continue
        имя = имя.split("[")[0].split("(")[0]
        for знак in ("<", ">", "=", "!", "~", " "):
            имя = имя.split(знак)[0]
        if имя.strip():
            out.append(имя.strip())
    return out
