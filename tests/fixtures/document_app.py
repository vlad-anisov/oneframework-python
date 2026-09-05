"""Образец для `tests/test_document.py`: два свойства, которых нет у соседа.

`parity_app` рядом задевает все семнадцать родов узлов, и на нём проверяется
широта. Но двух вещей у него нет намеренно -- он сверяется побайтно с
близнецами на JavaScript и Kotlin, и всё, чего те не умеют, в него класть
нельзя:

* **заголовок-функция.** Вид, у которого `_title` -- это ещё программа, а не
  строка. Такой обязан быть посчитан, а не спрятан: молча потерянный заголовок
  уводит экран без имени, и причину потом не найти нигде;
* **состояние вида с объявленным типом.** `Boolean()` на самом виде -- это не
  поле модели, а память экрана, и в документе у неё обязан стоять тип.

Образец свой, а не витринный. Витрина живёт в отдельном репозитории, и сюита,
которая её требует, там, где привязку издают, не запускается вовсе -- ровно на
этом питоновский репозиторий уезжал со 147 красными.
"""

from oneframework import App, Boolean, Model, Row, Screen, String, Text, View, expr, record


class Заметка(Model):
    _label = "Заметка"

    name = String("Название", required=True)
    body = Text("Текст")
    done = Boolean("Готова")


class Карточка(View):
    """Заголовок -- функция от записи: у новой и у существующей он разный."""

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
    """Корневой: с него начинается приложение."""

    def ui(self, record):
        from oneframework import List

        return (List(Заметка, item=Строка, open=Карточка),)


app = App(Screen(Список), title="Документы")
