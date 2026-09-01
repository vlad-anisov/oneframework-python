from widgets.models import Sample

SAMPLES = [
    {
        "title": "Полный образец",
        "notes": "Обычный многострочный текст.",
        "article": "<p>А это <b>Html</b> с <i>разметкой</i>.</p>",
        "secret": "hunter2",
        "mail": "sample@example.com",
        "tel": "+7 900 000-00-00",
        "site": "https://example.com",
        "sku": "4600051000057",
        "count": 7,
        "ratio": 3.14,
        "price": 1990.5,
        "done_pct": 64,
        "spent": 155,
        "stars": 4,
        "active": True,
        "state": "review",
        "accent": "#6750A4",
        "due": "2026-09-01",
        "at": "09:30",
        "stamp": "2026-08-11 12:00:00",
        "place": "55.755814,37.617635",
        # Картинка нужна не для красоты: без значения виджет смотрелки
        # (`binary:browser`) не открывается вовсе, и проверить его нечем.
        "photo": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DwnwEJMKFxadAAAOOcA9GKBhWLAAAAAElFTkSuQmCC",
    },
    {"title": "Пустой образец", "state": "draft"},
]


def seed(db):
    for values in SAMPLES:
        db.create(Sample, values)
