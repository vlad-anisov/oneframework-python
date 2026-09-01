"""One fully-populated record, so every widget has something to show."""

from app import Category, Profile, Sample


def seed(db):
    work = db.create(Category, {"name": "Work", "color": "#1565c0"})
    db.create(Category, {"name": "Home", "color": "#2e7d32"})
    profile = db.create(Profile, {"nickname": "ann", "bio": "Designer"})

    db.create(Sample, {
        "title": "Everything at once", "notes": "A plain text note.",
        "article": "<b>Rich</b> text", "secret": "hunter2",
        "mail": "ann@example.com", "tel": "+7 900 000-00-00",
        "site": "https://example.com", "sku": "4600051000057",
        "count": 3, "ratio": 1.5, "price": 249.99, "done_pct": 65,
        "spent": 5400, "stars": 4, "active": True, "state": "review",
        "accent": "#8e24aa",
        "due": "2026-09-01", "at": "09:30", "place": [55.7558, 37.6173],
        "category": work, "profile": profile,
    })
    db.create(Sample, {"title": "Empty one", "state": "draft"})
