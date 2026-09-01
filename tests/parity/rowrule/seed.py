from app import Memo

ROWS = [
    ("Раз", False, 0, "2026-02-01"),
    ("Два", True, 5, None),
    ("Три", False, 2, None),
    ("Четыре", True, 0, "2026-03-01"),
]


def seed(db):
    for title, done, rank, due in ROWS:
        db.create(Memo, {"title": title, "done": done, "rank": rank, "due": due})
