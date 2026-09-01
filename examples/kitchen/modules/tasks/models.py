from oneframework import (
    Boolean,
    Color,
    Date,
    Duration,
    Integer,
    Many2many,
    Many2one,
    Model,
    Percent,
    Rating,
    Selection,
    String,
    Text,
)


class Person(Model):
    name = String("Имя", required=True)
    email = String("Почта")


class Label(Model):
    name = String("Метка", required=True)
    color = Color("Цвет")


class Task(Model):
    title = String("Задача", required=True)
    notes = Text("Описание")
    state = Selection(
        [("todo", "К работе"), ("doing", "В работе"), ("done", "Готово")],
        "Статус",
        default="todo",
    )
    priority = Rating("Приоритет", maximum=5)
    progress = Percent("Прогресс")
    estimate = Duration("Оценка")
    due = Date("Срок")
    done = Boolean("Выполнено")
    assignee = Many2one(Person, "Исполнитель")
    labels = Many2many(Label, "Метки")
    sequence = Integer()
