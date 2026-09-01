from oneframework import Boolean, Integer, Model, Monetary, Rating, Selection, String


class Product(Model):
    name = String("Товар", required=True)
    sku = String("Артикул")
    kind = Selection(
        [("tool", "Инструмент"), ("part", "Деталь"), ("kit", "Набор")], "Тип"
    )
    price = Monetary("Цена", currency="₽")
    stock = Integer("Остаток")
    rating = Rating("Оценка", maximum=5)
    active = Boolean("В продаже")
