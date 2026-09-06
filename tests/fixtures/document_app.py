"""Образец для `tests/test_document.py`: два свойства, которых нет у соседа."""

from oneframework import App, Boolean, Model, Row, Screen, String, Text, View, expr, record

class Заметка(Model):
    _label = "Заметка"

    name = String("Название", required=True)
    body = Text("Текст")
    done = Boolean("Готова")

class Карточка(View):
    model = Заметка

    def _title(заметка):
        return "Новая заметка" if заметка is None else "Правка заметки"

    def ui(self, record):
        return (record.name(), record.body())

class Черновик(View):
    """Состояние экрана, объявленное типом. В документе у него стоит `ftype`."""
    model = Заметка

    body_shown = Boolean()
    done_shown = Boolean()

    def ui(self, record):
        return (
            record.name(),
            record.body(visible=expr("view.body_shown")),
            record.done(widget="checkbox", visible=expr("view.done_shown")),
        )

class Строка(View):
    model = Заметка

    def ui(self, record):
        return Row(record.name(widget="title"), record.done(widget="checkbox"))

class Список(View):
    def ui(self, record):
        from oneframework import List

        return (List(Заметка, item=Строка, open=Карточка),)

app = App(Screen(Список), title="Документы")
