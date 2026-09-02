"""Build-time asset preparation shared by every builder.

Three jobs, none of which depend on the target platform:

* copy the Pyodide distribution out of ``node_modules`` (never a CDN),
* zip the ``oneframework`` package together with the user's app into one archive that
  Pyodide unpacks at boot,
* generate the PWA manifest and icons if the project has none.
"""

#: Манифест, значки, адрес обмена и запись базы делает ядро
#: (`libs/js/src/build/assets.mjs`), правила -- в `tests/js/assets.test.mjs`.

from __future__ import annotations

from pathlib import Path

from .. import core
from ..errors import OneFrameworkError


def project_root() -> Path:
    """Куда собирается приложение -- корень **ядра**.

    Там лежат страница, оболочка и настройки сборки: `web/index.html`,
    `package.json`, `vite.config.js`. Искать «над питоновским пакетом» нельзя:
    это верно ровно в одном дереве, где всё лежит вместе, а у разложенных по
    репозиториям поиск упрётся в `pyproject.toml`, над которым нет `web/`.

    Спрашивается у искателя (`oneframework.core`): он знает про переменную,
    установленный пакет и соседний каталог, и отказывает вслух, называя все
    три места.
    """
    ядро = core.корень()
    # От ядра вверх, а не от питоновского пакета. Две раскладки, и обе живые:
    # в отдельном репозитории `web/` лежит в корне ядра, в общем дереве --
    # выше него, рядом с привязками. Разница ровно в глубине, поэтому подъём.
    for где in (ядро, *ядро.parents):
        if (где / "web" / "index.html").exists() and (где / "package.json").exists():
            return где
    raise OneFrameworkError(
        f"Ядро найдено ({ядро}), но ни в нём, ни выше нет web/index.html "
        "рядом с package.json.\nПохоже, это привязка, а не ядро, либо ядро "
        "другой версии.")

def write_app_db(app, seed_fn, out: Path, поверх: bool = False):
    """План от питона -> файл SQLite, написанный сборщиком на node.

    Отдельной работой, потому что зовут её двое: сборка и ``inspect``. Обе
    обязаны получать **одну и ту же** базу -- иначе `inspect` показывал бы не
    то приложение, которое поедет на устройство.

    ``поверх`` -- открыть существующий файл, а не начать с чистого. Так ходит
    ``inspect --db``: он выкладывает приложение поверх базы, которая у
    пользователя уже есть, и определения в ней надо обновить, а не потерять
    вместе с данными.

    Сборке нужно обратное, и умолчание здесь стоит именно поэтому. Собранный
    подряд второй пример ложился поверх первого: база копила модели и виды всех
    приложений сразу -- двадцать моделей вместо двух, -- и приложение на
    устройстве видело чужие экраны. Ошибка молчаливая: сборка проходит, файл
    растёт, а замечает это первый же запуск.
    """
    import json as _json
    import subprocess

    корень = Path(__file__).resolve().parents[2]
    if not поверх and out.exists():
        out.unlink()
    # План строит ядро: писателю едет **пакет объявления**. Второй записи
    # правила здесь быть не должно -- она держалась бы сверкой, а сверять
    # нечем: сборку ведёт ядро.
    пакет = dict(_пакетом(app, seed_fn).doc)
    пакет["file"] = str(out)
    готово = subprocess.run([core.node(), str(core.файл("src", "build-db.mjs"))],
                            input=_json.dumps(пакет, ensure_ascii=False, default=str),
                            capture_output=True, text=True, encoding="utf-8", cwd=str(корень))
    if готово.returncode != 0:
        raise OneFrameworkError(
            "Сборщик базы не запустился. Нужен node:\n" + (готово.stderr or "").strip())
    ответ = _json.loads(готово.stdout)
    if "error" in ответ:
        raise OneFrameworkError(
            f"Сборщик базы отказал: {ответ['error']}\n{ответ.get('stack', '')}")
    return out

# --------------------------------------------------------------------------
# PWA manifest + icons
# --------------------------------------------------------------------------

#: Рантайм питона кладёт `cli/python_runtime.py`; личность устройства стирает
#: сборщик на JS до выгрузки байтов; пакет объявления собирается по общему плану.


def _пакетом(app, seed_fn):
    """Приложение -> пакет объявления. Сборка ходит только этой дорогой.

    Питоновское приложение здесь ничем не привилегированнее Kotlin: и то и
    другое сперва печатает пакет. Если пакет чего-то не несёт, сборка это
    увидит сразу, а не на чужой машине без питона.
    """
    from ..declaration import Bundle, declare

    return app if hasattr(app, "model_docs") else Bundle(declare(app, seed_fn))
