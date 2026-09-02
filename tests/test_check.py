"""``oneframework check`` отвечает на один вопрос: поедет ли приложение.

Проверка идёт по той же дороге, что сборка, -- через пакет объявления. Это не
удобство, а требование: прежде `check` строил виды своим обходом
(`build_ui`), и приложение могло пройти проверку, а потом быть отвергнутым при
сборке пакета -- корневого вида не оказывалось в списке видов. Проверка,
отвечающая не на тот вопрос, хуже отсутствующей: на неё полагаются.

Отказ проверяется отдельно от успеха, потому что ломаются они по-разному: вид,
оставшийся программой, попадает в ``SKIPPED``, а несвязный пакет -- в
``DeclarationError``. Обе дороги обязаны кончаться кодом 1 и названным именем.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _проверить(каталог, файл="app.py"):
    """Запустить `check` подпроцессом -- как его запускает человек.

    Подпроцессом ещё и потому, что приложение ввозится по имени ``app``:
    реестр моделей глобален, и два приложения в одном процессе пишут строки в
    классы друг друга. Тот же довод в ``test_build_db.py``.
    """
    готово = subprocess.run(
        [sys.executable, "-c",
         "import sys; from oneframework.cli.main import main;"
         " sys.argv = ['oneframework', 'check', sys.argv[1]]; sys.exit(main())",
         str(каталог / файл)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
    )
    return готово.returncode, готово.stdout + готово.stderr


def test_a_working_app_passes():
    код, вывод = _проверить(ROOT / "examples" / "todo")
    assert код == 0, вывод
    assert "OK" in вывод
    # Названы именно те модели и виды, что поедут: проверка отчитывается о
    # пакете, а не о питоновских классах, из которых он напечатан.
    assert "TodoLine" in вывод and "Tag" in вывод


def test_a_view_that_stayed_a_program_is_named(tmp_path):
    """Вид, который не стал документом, обязан быть назван по имени.

    Корневой вид здесь **цел** -- и это важно: сломай его, и отказ пришёл бы
    другой дорогой, от связности пакета, а ветка пропуска осталась бы
    непроверенной. Замерено: с целым корнем снятая ветка оставляет проверку
    зелёной.

    Молчание здесь -- худший исход: приложение соберётся, а экран на устройстве
    окажется пустым, и связать пустоту с этим видом будет нечем.
    """
    (tmp_path / "app.py").write_text(textwrap.dedent('''
        from oneframework import App, Model, String
        from oneframework.ui.view import View


        class Note(Model):
            text = String()


        class Home(View):
            model = Note

            def ui(self, record):
                return (record.text,)


        class Broken(View):
            model = Note

            def ui(self, record):
                return (record.нет_такого_поля,)


        app = App(Home, title="Half broken")
    '''), encoding="utf-8")
    код, вывод = _проверить(tmp_path)
    assert код == 1, вывод
    assert "Broken" in вывод, вывод
    # Корень цел -- значит сработала именно ветка пропуска, а не связность.
    assert "Корневой вид" not in вывод, вывод


def test_an_app_without_a_root_view_is_refused(tmp_path):
    """Корневого вида нет -- отказ, а не пустой экран на устройстве.

    Этого прежняя проверка не ловила вовсе: свой обход видов о корне не знал,
    и приложение проходило `check`, а падало на сборке пакета.
    """
    (tmp_path / "app.py").write_text(textwrap.dedent('''
        from oneframework import App, Model, String
        from oneframework.ui.view import View


        class Note(Model):
            text = String()


        def _вид_в_функции():
            class Hidden(View):
                model = Note

                def ui(self, record):
                    return (record.text,)

            return Hidden


        app = App(_вид_в_функции(), title="Hidden root")
    '''), encoding="utf-8")
    код, вывод = _проверить(tmp_path)
    assert код == 1, вывод
    assert "Hidden" in вывод, вывод
