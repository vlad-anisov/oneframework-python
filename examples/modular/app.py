"""Entry point: load every module folder, then start.

There is no manifest and no install state -- a folder with an __init__.py is
a module, and that is the whole rule.
"""

from pathlib import Path

from oneframework import App, load_all

modules = load_all(Path(__file__).parent / "modules")

app = App(modules=modules, title="Modular", color="#00696E")
