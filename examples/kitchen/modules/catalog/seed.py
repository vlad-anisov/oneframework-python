import random

from catalog.models import Product

NAMES = [
    "Дрель", "Шуруповёрт", "Ключ рожковый", "Набор бит", "Ножовка",
    "Уровень", "Рулетка", "Стамеска", "Молоток", "Плоскогубцы",
    "Струбцина", "Напильник", "Отвёртка", "Ножницы по металлу", "Зубило",
]
KINDS = ["tool", "part", "kit"]


def seed(db):
    rng = random.Random(20260811)
    for index, name in enumerate(NAMES):
        db.create(
            Product,
            {
                "name": name,
                "sku": f"SKU-{1000 + index}",
                "kind": KINDS[index % len(KINDS)],
                "price": round(rng.uniform(199, 9900), 2),
                "stock": rng.randint(0, 60),
                "rating": rng.randint(1, 5),
                "active": index % 7 != 0,
            },
        )
