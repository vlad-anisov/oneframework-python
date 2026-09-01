import random

from bigdata.models import Row_

REGIONS = ["n", "s", "e", "w"]


def seed(db):
    rng = random.Random(11082026)
    for index in range(500):
        db.create(
            Row_,
            {
                "code": f"POS-{index + 1:04d}",
                "region": REGIONS[index % len(REGIONS)],
                "amount": rng.randint(10, 99_000),
                "checked": index % 5 == 0,
                "seq": (index + 1) * 10,
            },
        )
