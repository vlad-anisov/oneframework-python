"""Ключи посева -- одни и те же на всякой сборке."""
from __future__ import annotations

from oneframework.model.ids import is_id, new_id, seeded_ids

def собрать(поток, сколько=5):
    with seeded_ids(поток):
        return [new_id() for _ in range(сколько)]

def test_two_seedings_give_the_same_keys():
    assert собрать("gtasks:tasks") == собрать("gtasks:tasks")

def test_different_streams_do_not_collide():
    assert set(собрать("gtasks:tasks")) & set(собрать("kitchen:tasks")) == set()

def test_the_keys_are_still_ours_and_ordered():
    ключи = собрать("gtasks:tasks", 40)
    assert all(is_id(k) for k in ключи)
    assert ключи == sorted(ключи)
    assert len(set(ключи)) == len(ключи)

def test_outside_the_seeding_keys_are_fresh():
    """Вне посева ключ по-прежнему случайный -- иначе записи слипались бы."""
    assert new_id() != new_id()
