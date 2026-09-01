from oneframework import (
    App, Boolean, Button, Color, Create, Delete, Filter, Integer, List, Many2one,
    Model, Row, Search, Sort, String, Text, View, view,
)


class Tag(Model):
    name = String("Название", required=True)
    color = Color("Цвет")


class TodoLine(Model):
    text = String("Задача", required=True)
    description = Text("Описание")
    tag = Many2one(Tag, "Тег")
    completed = Boolean("Выполнено")
    sequence = Integer()


class TodoLineItem(View):
    model = TodoLine

    def ui(self, record):
        return Row(
            record.sequence(widget="handle"),
            record.completed(widget="toggle"),
            record.text(widget="title"),
            record.tag(widget="tag"),
            Button(icon="delete", action=record.delete()),
        )


class TodoLineDetail(View):
    model = TodoLine
    # Карточка -- работа, а не шаг пути: путь сюда весь состоит из списка,
    # из которого пришли, и цепочка из двух звеньев повторила бы стрелку
    # «назад» в том же баре.
    crumbs = False

    def ui(self, record):
        return (
            record.text(),
            record.description(widget="textarea"),
            record.tag(),
            record.completed(),
            Button("Удалить", action=record.delete()),
        )


class Todo(View):
    tag = Many2one(Tag, "Тег")

    def ui(self, record):
        return (
            view.tag(widget="chips"),
            Button(place="fab", action=TodoLine.create(open=TodoLineDetail,
                                              values={"tag": view.tag})),

            List(
                TodoLine,
                item=TodoLineItem,
                open=TodoLineDetail,
                domain=record.tag == view.tag,

                search=Search(
                    record.text,
                    Filter("Осталось", ~record.completed, default=True),
                    Filter("Выполнено", record.completed),
                    Sort("По порядку", record.sequence, default=True),
                    Sort("Сначала новые", record.created_at.desc()),
                ),
            ),
        )


app = App(Todo)
