"""``oneframework`` command line.

    oneframework dev            examples/todo/app.py     # web development server
    oneframework serve          examples/todo/app.py     # exchange point + built client
    oneframework build web      examples/todo/app.py     # production PWA
    oneframework build android  examples/todo/app.py     # PWA -> Capacitor -> APK
    oneframework build ios      examples/todo/app.py     # PWA -> Capacitor -> .app
    oneframework check          examples/todo/app.py     # validate the DSL only
    oneframework inspect        examples/todo/app.py     # look at it without a browser

Builders live in ``oneframework/cli/builders`` and are selected by name: a new target
is a new module plus one entry in ``BUILDERS`` -- no changes to the CLI itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from .. import core
from ..errors import OneFrameworkError
from . import assets, inspect, sources
from .builders import android as android_builder
from .builders import ios as ios_builder
from .builders import web as web_builder

BUILDERS = {
    "web": lambda app_file, app, args: web_builder.build(app_file, app),
    "android": lambda app_file, app, args: android_builder.build(
        app_file, app, install=args.install
    ),
    "ios": lambda app_file, app, args: ios_builder.build(
        app_file, app, install=args.install
    ),
}


def load_app(app_file: Path):
    """Приложение из файла -- на любом языке, какой умеет :mod:`.sources`.

    Раньше здесь стоял ``importlib``, и это была единственная причина, по
    которой приложение обязано было быть питоновским. Теперь выбор дороги
    делается по расширению: ``.py`` -- импорт, ``.mjs`` -- запуск ``node``,
    ``.kt`` -- сборка и запуск, ``.json`` -- готовый пакет объявления.
    """
    return sources.load(app_file)


def cmd_check(args):
    """Собрать документ каждого вида -- то же, что делает выкладка.

    Метод ``ui`` -- это исполняемый питон, поэтому один только импорт файла не
    доказывает почти ничего: неизвестное поле, виджет, которого тип не даёт,
    строка списка, привязанная к чужой модели, -- всё это вылезает при сборке
    дерева. Она здесь и делается.

    Собирается именно **документ**, а не кадр. До 21.08.2026 здесь поднимался
    питоновский рантайм и каждый вид рисовался на живом кадре. Так проверялось
    больше, чем нужно, и меньше, чем следует: вид, который читает ``self``,
    кадр принимал -- а до устройства такой вид не доезжает вовсе, потому что
    туда едут документы. Сборка документа отвечает ровно на тот вопрос, от
    которого зависит, поедет ли приложение.
    """
    from ..declaration import Bundle, DeclarationError, declare
    from ..model.defs import SKIPPED

    app = load_app(Path(args.app))
    if isinstance(app, Bundle):
        # Пакет проверять исполнением нечем и незачем: виды в нём уже
        # документы, а не программы. Проверяется то, что о нём вообще можно
        # проверить, -- связность, -- и она проверена при чтении.
        return _check_bundle(app)

    # Печать пакета -- и есть исполнение видов: `declare` строит каждый
    # документ и записывает в `SKIPPED` тот, что остался программой. Раньше
    # здесь стоял свой обход с `build_ui`, и он проверял **не то**, что поедет:
    # приложение проходило проверку, а потом отвергалось при сборке пакета --
    # корневого вида не оказывалось в списке. Теперь проверка спрашивает ровно
    # то, от чего зависит выкладка.
    SKIPPED.clear()
    try:
        пакет = Bundle(declare(app))
    except DeclarationError as отказ:
        print(f"FAIL  {отказ}")
        return 1

    if SKIPPED:
        # Одна ошибка доходит сюда дважды -- от экрана, который не смог
        # нарисоваться, и от вида, которому он принадлежит, -- поэтому
        # называется один раз, тем видом, чьё имя уже стоит в сообщении.
        for сообщение in dict.fromkeys(SKIPPED.values()):
            имя = next(н for н, с in SKIPPED.items() if с == сообщение)
            print(f"FAIL  {имя}\n      {сообщение}")
        return 1

    return _check_bundle(пакет)


def _check_bundle(bundle):
    """Что можно сказать о пакете, не исполняя его."""
    print(f"OK  {bundle}")
    print(f"    views : {', '.join(v['name'] for v in bundle.view_docs)}")
    print(f"    models: {', '.join(m['name'] for m in bundle.model_docs)}")
    for модель in bundle.model_docs:
        поля = ", ".join(f"{f['name']}:{f['ftype']}" for f in модель["fields"])
        print(f"      {модель['name']}({поля})")
    for запись in bundle.logic_modules():
        for действие in запись.get("actions") or []:
            print(f"    логика: {действие['name']}  ({действие.get('language', '?')})")
    return 0


def cmd_declare(args):
    """Напечатать пакет объявления -- то, что читает сборка.

    Симметрично `npx oneframework declare` у JavaScript и `main()` у Kotlin:
    у каждого языка своя дорога к одному и тому же JSON. Полезна и сама по
    себе -- увидеть, чем приложение является для сборки, не собирая его.
    """
    from ..declaration import Bundle, declare

    app = load_app(Path(args.app))
    doc = app.doc if isinstance(app, Bundle) else declare(app)
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args):
    """Обмен и веб-клиент с одного адреса.

    Одна команда поднимает домен целиком: точка обмена, статика из ``dist`` и
    паспорт стенда в корневом ответе. Сборки нет -- значит её надо сделать, и
    это тоже делается здесь, чтобы команда осталась одной.
    """
    app_file = Path(args.app).resolve()
    app = load_app(app_file)
    root = assets.project_root()
    dist = Path(args.dist).resolve() if args.dist else root / "dist"
    if args.build or not (dist / "index.html").exists():
        print(f"Собираю веб-клиент в {dist}…")
        web_builder.build(app_file, app)
    if not (dist / "index.html").exists():
        raise SystemExit(f"Нет собранного веб-клиента в {dist}.")

    data = Path(args.data).resolve()
    data.mkdir(parents=True, exist_ok=True)
    # Сервер обмена -- на JavaScript (`libs/js/src/http.mjs`). Питоновский убран
    # 20.08.2026: он был второй реализацией всего, что касается данных, а
    # браузерная половина и так работает под node -- ей не пришлось писать
    # заново ни обмен, ни хранилище, ни часы.
    #
    # Команда осталась одной: она по-прежнему собирает клиент, заводит каталог
    # и поднимает домен целиком. Сменился только тот, кто отвечает.
    запуск = core.файл("src", "cli-serve.mjs")
    окружение = dict(os.environ)
    окружение.update({
        "OF_DB": str(data / "server.db"),
        "OF_DIST": str(dist),
        "OF_HOST": args.host,
        "OF_PORT": str(args.port),
        "OF_TITLE": getattr(app, "title", None) or app_file.parent.name,
    })
    try:
        raise SystemExit(subprocess.call(["node", str(запуск)], env=окружение))
    except FileNotFoundError:
        raise SystemExit(
            "Для `serve` нужен node: сервер обмена написан на JavaScript "
            "(`libs/js/src/http.mjs`), и своего питоновского у нас больше нет.",
        ) from None
    return 0


def cmd_keygen(args):
    """Пара ключей издателя. Приватный -- файлом, публичный -- на экран.

    Отдельной командой, а не втихую при первой сборке: ключ, созданный сам
    собой, лежит непонятно где и заменяется непонятно на что. Здесь видно, куда
    он лёг, и сразу сказано, что дальше с ним делать.
    """
    from .. import keys

    path = Path(args.path).resolve()
    if path.exists() and not args.force:
        raise SystemExit(
            f"{path} уже существует. Перезаписать -- --force, но учтите: старый "
            "ключ восстановить нельзя, а всё подписанное им перестанет "
            "приниматься устройствами, которые знают только его."
        )
    public = keys.write_private(keys.generate(), path)
    print(f"Приватный ключ: {path}  (права 0600)")
    print(f"Публичный ключ: {public}")
    print()
    print("Держите файл вне репозитория и назовите его сборке:")
    print(f"    export {keys.ENV_PRIVATE_KEY}={path}")
    print()
    print("Сборка с этой переменной подписывает модули логики и кладёт публичный")
    print("ключ на устройство; сборка без неё остаётся прежней -- неподписанной.")
    return 0


def cmd_dev(args):
    app_file = Path(args.app).resolve()
    app = load_app(app_file)
    web_builder.dev(app_file, app, port=args.port, open_browser=args.open)
    return 0


def cmd_build(args):
    app_file = Path(args.app).resolve()
    app = load_app(app_file)
    builder = BUILDERS.get(args.target)
    if builder is None:
        raise SystemExit(
            f"Unknown target {args.target!r}. Available: {', '.join(BUILDERS)}"
        )
    builder(app_file, app, args)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="oneframework", description="Build local-first apps from declarative Python."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dev = sub.add_parser("dev", help="run the web development server")
    p_dev.add_argument("app", help="path to your app.py")
    p_dev.add_argument("--port", type=int, default=5173)
    p_dev.add_argument("--open", action="store_true", help="open a browser")
    p_dev.set_defaults(func=cmd_dev)

    p_build = sub.add_parser("build", help="produce a production build")
    p_build.add_argument("target", choices=sorted(BUILDERS), help="build target")
    p_build.add_argument("app", help="path to your app.py")
    p_build.add_argument(
        "--install", action="store_true",
        help="android/ios: install and launch on a running device/emulator",
    )
    p_build.set_defaults(func=cmd_build)

    p_serve = sub.add_parser(
        "serve", help="serve the exchange point and the built web client")
    p_serve.add_argument("app", help="path to your app.py")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--data", default=".oneframework-server",
                         help="directory for the server database")
    p_serve.add_argument("--dist", default=None,
                         help="built web client (default: <root>/dist)")
    p_serve.add_argument("--build", action="store_true",
                         help="rebuild the web client before serving")
    p_serve.set_defaults(func=cmd_serve)

    p_keygen = sub.add_parser(
        "keygen", help="create the publisher signing key (Ed25519)")
    p_keygen.add_argument("path", help="where to write the private key (PEM)")
    p_keygen.add_argument("--force", action="store_true",
                          help="overwrite an existing key file")
    p_keygen.set_defaults(func=cmd_keygen)

    p_declare = sub.add_parser(
        "declare", help="print the declaration bundle the builder reads")
    p_declare.add_argument("app", help="path to your app")
    p_declare.set_defaults(func=cmd_declare)

    p_check = sub.add_parser("check", help="validate the DSL without building")
    p_check.add_argument("app", help="path to your app.py")
    p_check.set_defaults(func=cmd_check)

    inspect.add_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
