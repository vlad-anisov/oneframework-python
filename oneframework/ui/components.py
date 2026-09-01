"""Public names for the Component IR.

``Row``/``List``/``Button``/``Search``/``Filter``/``Sort`` *are* IR nodes -- the
DSL builds the IR directly, with no intermediate representation to keep in sync.
"""

from __future__ import annotations

from .nodes import (
    AccordionNode,
    ButtonNode,
    ColNode,
    DeleteAction,
    FilterNode,
    GroupNode,
    IconNode,
    ListNode,
    LogicAction,
    MenuNode,
    CreateAction,
    SaveAction,
    OpenAction,
    RepeatNode,
    RowNode,
    SearchNode,
    PillNode,
    SectionNode,
    SetAction,
    SortNode,
    TabNode,
    TextNode,
    TabsNode,
)

__all__ = [
    "Repeat",
    "Row", "Col", "Group", "Accordion", "Section", "Tabs", "Tab", "Pill", "Label", "Icon",
    "Set",
    "List", "Button", "Search", "Filter", "Sort", "Delete", "Menu", "Open", "Create", "Save",
    "Logic",
]

Repeat = RepeatNode
Row = RowNode
Col = ColNode
Group = GroupNode
Accordion = AccordionNode
Section = SectionNode
Tabs = TabsNode
Tab = TabNode
Pill = PillNode
#: `Text` is a field type; a piece of text in a title is a `Label`.
Label = TextNode
#: And a glyph in one is an `Icon`.
Icon = IconNode
Set = SetAction
List = ListNode
Menu = MenuNode
Open = OpenAction
Create = CreateAction
Save = SaveAction
Button = ButtonNode
Search = SearchNode
Filter = FilterNode
Sort = SortNode
Delete = DeleteAction
#: Позвать логику, лежащую в базе модулем WASM. Имя действия -- всё, что вид
#: о ней знает: на каком языке она написана, документ вида знать не должен.
Logic = LogicAction
