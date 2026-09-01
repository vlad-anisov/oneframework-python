from contacts.models import Person          # another module's model
from oneframework import Boolean, Date, Integer, Many2one, Model, Rating, Selection, String


class Task(Model):
    title = String("Task", required=True)
    state = Selection(
        [("todo", "To do"), ("doing", "Doing"), ("done", "Done")], "State"
    )
    priority = Rating("Priority", maximum=3)
    due = Date("Due")
    done = Boolean("Done")
    assignee = Many2one(Person, "Assignee")
    sequence = Integer()
