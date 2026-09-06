"""Рубеж на выкладке: документ вида обязан сходиться с договором."""

from __future__ import annotations

import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "protocol" / "document.json"

_КОНТРАКТ = None

def contract():
    global _КОНТРАКТ
    if _КОНТРАКТ is None:
        _КОНТРАКТ = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return _КОНТРАКТ

def _узлы(node, путь="doc", где="nodes"):
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            yield путь, node, где
        for ключ, значение in node.items():
            yield from _узлы(значение, f"{путь}.{ключ}",
                             "actions" if ключ == "action" else где)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _узлы(item, f"{путь}[{i}]", где)

def problems(doc, contract_=None):
    договор = contract_ or contract()
    # Узлы и действия договор описывает **порознь**, и различает их не тип, а
    # место: действие лежит под ключом `action`.
    формы = {"nodes": договор["nodes"], "actions": договор["actions"]}
    беды = []
    for путь, узел, где in _узлы(doc):
        тип = узел["type"]
        форма = формы[где].get(тип)
        если_нет = "действие" if где == "actions" else "узел"
        if форма is None:
            беды.append(f"{путь}: {если_нет} типа {тип!r} договору неизвестен")
            continue
        нет = [к for к in форма["required"] if к not in узел]
        if нет:
            беды.append(
                f"{путь}: у {если_нет}а {тип!r} нет обязательных ключей: "
                f"{', '.join(sorted(нет))}",
            )
    return беды
