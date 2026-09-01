from pathlib import Path

from oneframework import App, load_all

modules = load_all(Path(__file__).parent / "modules")

app = App(modules=modules, title="Задачи", color="#4a6b45",
          # Согласие, а не замена: зелёный остаётся лицом приложения
          # везде, а на Android 12+ его перебивает цвет обоев.
          dynamic_color=True,
          locale="ru",
          # Морфология русского в SQL не выражается: «задачами -> задача» знает
          # словарь, а не правило. Объявленный пакет едет на устройство вместе
          # с настоящим CPython и работает там без сети.
          python_packages=["pymorphy3", "pymorphy3-dicts-ru"])
