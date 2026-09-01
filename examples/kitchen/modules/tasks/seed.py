from tasks.models import Label, Person, Task

PEOPLE = [
    ("Аня Ли", "anna@example.com"),
    ("Борис Рей", "boris@example.com"),
    ("Вера Ким", "vera@example.com"),
]

LABELS = [("Дизайн", "#7D5260"), ("Бэкенд", "#006A6A"), ("Срочно", "#B3261E")]

TASKS = [
    ("Свести макеты", "doing", 5, 60, 90, "2026-08-20", False),
    ("Собрать APK", "todo", 3, 20, 240, "2026-08-25", False),
    ("Написать тесты", "todo", 4, 10, 180, "2026-08-18", False),
    ("Отдать в ревью", "done", 2, 100, 45, "2026-08-05", True),
    ("Обновить README", "todo", 1, 0, 30, None, False),
]


def seed(db):
    people = [db.create(Person, {"name": n, "email": e}) for n, e in PEOPLE]
    labels = [db.create(Label, {"name": n, "color": c}) for n, c in LABELS]
    field = Task._fields["labels"]
    for index, (title, state, priority, progress, estimate, due, done) in enumerate(TASKS):
        task = db.create(
            Task,
            {
                "title": title,
                "state": state,
                "priority": priority,
                "progress": progress,
                "estimate": estimate,
                "due": due,
                "done": done,
                "assignee": people[index % len(people)],
                "sequence": (index + 1) * 10,
                "notes": f"<p>Заметка к задаче <b>{title}</b>.</p>",
            },
        )
        db.set_many2many(field, task, labels[: (index % len(labels)) + 1])
