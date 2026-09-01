from oneframework import (
    Boolean, Date, Integer, Many2one, Model, One2many, String, Text,
)


class Board(Model):
    _label = "Список"

    name = String("Название списка", required=True)
    tasks = One2many("Task", "board", "Задачи")

    def _progress(self):
        """Доля выполненных задач списка, округлённая к ближайшему проценту.

        Цикла `for board in self`, как в Odoo, здесь нет намеренно: формула
        считается один раз на всю выборку, а не по разу на запись. Ровно этот
        цикл и стоил 194,8 мс на списке из трёхсот.

        `self.tasks` -- объявленная связь, а не имя модели строкой: связь уже
        описана полем выше, и повторять её в каждой формуле незачем. Лямбда в
        `filtered` выполняется один раз, на сборке, и получает не запись, а
        символ задачи -- поэтому `task.done` внутри читается обычным питоном, а
        наружу выходит условие запроса.

        Тело -- обычный питон, и читается как обычный питон. Разница в том,
        **когда** оно выполняется: один раз на сборке, и `total` в этот момент
        не число, а вопрос к базе. Поэтому `if` не выполняется, а записывается
        -- и превращается в ветвление внутри запроса. Невыбранная ветка в SQLite
        не вычисляется, так что деления на ноль у пустого списка не происходит
        вовсе.
        """
        total = len(self.tasks)
        if not total:
            return 0
        done = len(self.tasks.filtered(lambda task: task.done))
        return round(done * 100 / total)

    # Колонки у этого поля нет, и это главное в нём: готовность меняется от
    # правки *другой* записи, а число, положенное в колонку, об этом не узнает.
    progress = Integer("Готовность, %", compute=_progress)


class Task(Model):
    _label = "Задача"

    title = String("Задача", required=True)
    details = Text("Детали")
    date = Date("Дата")
    # Google keeps these apart: the day you mean to do it, and the day it stops
    # being useful. They sort differently and are set from different rows.
    deadline = Date("Крайний срок")
    starred = Boolean("Отмеченная")
    done = Boolean("Выполнено")
    finished = Date("Выполнено")
    board = Many2one(Board, "Список", ondelete="cascade")
    parent = Many2one("Task", "Подзадача к")
    sequence = Integer()
