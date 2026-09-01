"""Заметки на питоне: дополнительный интерпретатор на устройстве.

Три приложения этой тройки одинаковы снаружи: те же модели, тот же экран, та
же кнопка и тот же ответ. Различается ровно одно -- на чём написано приложение
и чем исполняется его логика на устройстве:

* `notes-python` -- в приложение кладётся **дополнительный интерпретатор**
  (Pyodide, 13 МБ), и он исполняет исходник;
* `notes-js`     -- исполняет **встроенный** движок webview, класть нечего;
* `notes-kotlin` -- на сборке получается **скомпилированный модуль** `.wasm`,
  и он инстанцируется как машинный код.

Одинаковы они не на глаз: объявления всех трёх дают побайтово одни и те же
документы моделей и видов, и это закреплено `tests/test_three_languages.py`.

    oneframework build web examples/notes-python/app.py
"""

from oneframework import (
    App, Boolean, Button, Create, Delete, List, Model, Row, Save,
    String, Text, View,
)


class Note(Model):
    _label = "Заметка"
    title = String("Текст", required=True)
    details = Text("Подробности")
    done = Boolean("Выполнено")

    def summary(self):
        """Пересчитать сводку по тексту заметки.

        `self` -- набор записей, по которым действие позвали. Правка --
        обычное присваивание; возвращать ничего не надо, изменённое найдут
        сами.

        Считает ровно то же, что два других приложения, и теми же словами:
        одинаковость тройки проверяется прогоном (`tests/test_three_languages`),
        а не обещанием в README.

        Слова режет **сторонний** `python-slugify` -- пакет с PyPI, приехавший
        колесом вместе с приложением. В MicroPython он не заработает: ему нужны
        полноценные `re`, `unicodedata` и `text-unidecode`.

        Расширения на C (`regex`) сюда не годятся, и сборка отказывает внятно:
        с PyPI такое колесо в Pyodide не поедет -- ему нужна пересборка под
        emscripten, а её делает сам Pyodide, а не мы. Пакеты без колеса вообще
        (`titlecase` издан только исходником) отвергаются там же и по той же
        причине: на устройстве собирать нечем.
        """
        from slugify import slugify

        for record in self:
            words = slugify(record.title, separator=" ", allow_unicode=True).split()
            first = " ".join(word.capitalize() for word in words[:5])
            record.details = f"{len(words)} слов: {first}"


class Line(View):
    model = Note

    def ui(self, record):
        return Row(
            record.done(widget="toggle"),
            record.title(widget="title"),
            Button(icon="delete", action=record.delete()),
        )


class Card(View):
    model = Note
    # Карточка -- работа, а не шаг пути: путь сюда весь состоит из списка,
    # из которого пришли, и цепочка из двух звеньев повторила бы стрелку
    # «назад» в том же баре.
    crumbs = False

    def ui(self, record):
        return (
            # Сохранение объявляется явно: карточка открывается черновиком, и
            # до сохранения записи ещё нет -- звать логику не о чем.
            Button("Сохранить", action=record.save(), place="navbar",
                   enabled=record.title),
            record.title(),
            record.details(widget="textarea"),
            record.done(),
            # Метод записи прямо в кнопке: ни строки с именем, ни обёртки.
            # Скобки значат «на этой записи», а не «прямо сейчас». Что за
            # методом стоит -- питон, JavaScript или скомпилированный модуль --
            # отсюда не видно, и это главное.
            Button("Пересчитать сводку", action=record.summary()),
        )


class Board(View):
    _title = "Заметки"

    def ui(self, record):
        return (
            List(Note, item=Line, open=Card,
                 empty=("Пусто", "Нажмите +, чтобы добавить")),
            Button(place="fab", action=Note.create(open=Card, draft=True)),
        )


app = App(Board, title="Заметки (питон)", color="#4a6b45",
          locale="ru",
          # Колесо едет на устройство вместе с приложением: в webview сети
          # может не быть, и ставить оттуда нечего.
          python_packages=["python-slugify"])
