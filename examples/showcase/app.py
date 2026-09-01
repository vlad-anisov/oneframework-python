"""A second app, proving the framework is generic and exercising every widget
the Todo demo never reaches: ColorPicker, Stepper, Range, rich Calendar,
Autocomplete and swipe-to-delete.

Nothing here is Todo-specific -- different models, field names and labels.
"""

from oneframework import (
    App, Boolean, Button, Color, Create, Date, Delete, Filter, Integer, List, Many2one, Model,
    Row, Search, Sort, String, Text, View, view,
)


class Project(Model):
    name = String("Project", required=True)
    color = Color("Colour")


class Task(Model):
    summary = String("Summary", required=True)
    notes = Text("Notes")
    project = Many2one(Project, "Project")
    urgent = Boolean("Urgent")
    estimate = Integer("Estimate, h")
    progress = Integer("Progress, %")
    due = Date("Due date")
    rank = Integer()


class ProjectItem(View):
    model = Project

    def ui(self, record):
        return Row(
            record.color(),
            record.name(widget="title"),
            Button(icon="delete", action=record.delete()),
        )


class ProjectDetail(View):
    model = Project

    def ui(self, record):
        return (
            record.name(),
            record.color(),                           # ColorPicker
            Button("Delete project", action=record.delete()),
        )


class TaskItem(View):
    model = Task

    def ui(self, record):
        return Row(
            record.rank(widget="handle"),
            record.urgent(widget="toggle"),
            record.summary(widget="title"),
            record.project(widget="tag"),
            Button(icon="delete", action=record.delete(swipe=True)),
        )


class TaskDetail(View):
    model = Task

    def ui(self, record):
        return (
            record.summary(),
            record.notes(widget="rich"),              # TextEditor
            record.project(widget="autocomplete"),    # Autocomplete
            record.due(widget="calendar"),            # Calendar
            record.estimate(widget="stepper"),        # Stepper
            record.progress(widget="range"),          # Range
            record.urgent(),
            Button("Delete task", action=record.delete()),
        )


class Workspace(View):
    project = Many2one(Project, "Project")

    def ui(self, record):
        return (
            view.project(widget="chips"),

            Button(place="fab", action=Project.create(open=ProjectDetail)),
            List(Project, item=ProjectItem, open=ProjectDetail),

            List(
                Task,
                item=TaskItem,
                open=TaskDetail,
                domain=record.project == view.project,
                page_size=20,
                search=Search(
                    record.summary,
                    Filter("Urgent", record.urgent),
                    Sort("Manual", record.rank, default=True),
                    Sort("Newest", record.created_at.desc()),
                ),
            ),
        )


app = App(Workspace, title="Showcase", color="#386A20")
