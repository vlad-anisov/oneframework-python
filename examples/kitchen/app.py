"""Kitchen sink: every component the framework offers, in one installable app.

There is no manifest and no install list -- each folder under `modules/` is a
module, and each module that declares a SCREEN adds a section to the
navigation. Delete a folder and the section is gone.
"""

from pathlib import Path

from oneframework import App, load_all

modules = load_all(Path(__file__).parent / "modules")

app = App(modules=modules, title="Kitchen", color="#6750A4")
