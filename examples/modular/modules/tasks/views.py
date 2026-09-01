from oneframework import (
    Button, Create, Delete, Filter, Group, List, Row, Search, Sort, View,
)

from .models import Task


class TaskItem(View):
    model = Task

    def ui(self, record):
        return Row(
            record.sequence(widget="handle"),
            record.done(widget="toggle"),
            record.title(widget="title"),
            record.state(widget="pill"),         # from static/widgets.js
            Button(icon="delete", action=record.delete()),
        )


class TaskDetail(View):
    model = Task

    def ui(self, record):
        return (
            Group(record.title(), record.state(), record.priority(), record.due(),
                  record.assignee(), label="Task"),
            record.done(),
            Button("Delete", action=record.delete()),
        )


class Board(View):
    def ui(self, record):
        return (
            Button(place="fab", action=Task.create(open=TaskDetail)),
            List(
                Task,
                item=TaskItem,
                open=TaskDetail,
                search=Search(
                    record.title,
                    Filter("Open", ~record.done, default=True),
                    Filter("Done", record.done),
                    Sort("Manual", record.sequence, default=True),
                    Sort("Due first", record.due),
                ),
            ),
        )
