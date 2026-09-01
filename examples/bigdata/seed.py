"""500 records, so paging and virtualisation are exercised for real."""

from app import Entry


def seed(db):
    for i in range(1, 501):
        db.create(Entry, {
            "label": f"Entry number {i:03d}",
            "done": i % 7 == 0,
            "weight": i % 10,
            "position": i * 10,
        })
