from contacts.models import Person

from .models import Task


def seed(db):
    people = db.all(Person)
    ann = people[0]["id"] if people else None
    for i, (title, state) in enumerate([
        ("Draft the proposal", "doing"),
        ("Review designs", "todo"),
        ("Ship release", "todo"),
    ]):
        db.create(Task, {"title": title, "state": state, "priority": 3 - i,
                         "assignee": ann, "sequence": (i + 1) * 10})
