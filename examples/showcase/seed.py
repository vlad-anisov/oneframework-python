"""Demo data for the showcase app."""

from app import Project, Task

PROJECTS = [("Website", "#1565c0"), ("Mobile", "#6a1b9a"), ("Infra", "#2e7d32")]
TASKS = [
    ("Redesign landing", "<b>Above the fold</b> first", "Website", True, 8, 40, "2026-09-01"),
    ("Fix crash on boot", "Only on cold start", "Mobile", True, 3, 10, "2026-08-20"),
    ("Rotate certificates", "", "Infra", False, 1, 0, "2026-08-15"),
    ("Write release notes", "Short and factual", "Website", False, 2, 75, None),
]


def seed(db):
    ids = {name: db.create(Project, {"name": name, "color": color})
           for name, color in PROJECTS}
    for i, (summary, notes, project, urgent, estimate, progress, due) in enumerate(TASKS):
        db.create(Task, {
            "summary": summary, "notes": notes, "project": ids[project],
            "urgent": urgent, "estimate": estimate, "progress": progress,
            "due": due, "rank": (i + 1) * 10,
        })
