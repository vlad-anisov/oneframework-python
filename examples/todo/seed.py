"""Sample data for the Todo demo.

Seeding is app-specific, so it lives next to ``app.py`` rather than inside the
framework. oneframework runs ``seed(db)`` exactly once, the first time an app starts
against an empty database, and records a marker so it never runs again.
"""

from app import Tag, TodoLine

TAGS = [
    ("Работа", "#1e88e5"),
    ("Личное", "#8e24aa"),
    ("Покупки", "#43a047"),
    ("Учёба", "#fb8c00"),
]

LINES = [
    ("Купить молоко", "2 литра, обезжиренное", "Покупки", False),
    ("Позвонить в сервис", "Уточнить статус ремонта", "Личное", False),
    ("Оплатить интернет", "До 15 числа", "Личное", True),
    ("Подготовить отчёт", "Квартальные показатели", "Работа", False),
    ("Записаться к врачу", "", "Личное", False),
    ("Прочитать книгу", "Осталось две главы", "Учёба", True),
]


def seed(db):
    tag_ids = {}
    for name, color in TAGS:
        tag_ids[name] = db.create(Tag, {"name": name, "color": color})

    for index, (text, description, tag, completed) in enumerate(LINES):
        db.create(
            TodoLine,
            {
                "text": text,
                "description": description,
                "tag": tag_ids.get(tag),
                "completed": completed,
                "sequence": (index + 1) * 10,
            },
        )
