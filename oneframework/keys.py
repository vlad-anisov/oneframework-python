"""Подпись издателя: чей это код и чей это конверт.

Отпечаток отвечает на вопрос «байты не побились». Он **не** отвечает на вопрос
«их положил тот, кому это позволено», и разница между двумя вопросами -- это вся
разница между испорченной сетью и чужим сервером. Пока модули клал только тот,
кто собирал приложение, второго вопроса не возникало; как только модуль поехал
по сети, он стал единственным, который имеет значение: исполняемый код,
приехавший неизвестно от кого, -- это не «немного риска», это чужая программа на
устройстве человека.

Отсюда три решения.

**Ed25519, и ничего своего.** Подписи делает ``cryptography`` на питоне и
``crypto.subtle`` в браузере -- обе реализации чужие и проверенные. Ed25519
выбран не за моду: у него ключ 32 байта, подпись 64, проверка не требует ни
параметров кривой, ни выбора хеша, и он есть **в обоих** местах, где нам нужен,
без единой зависимости. RSA потребовал бы ключ на порядок длиннее и выбор
дополнения, а любой выбор здесь -- это способ ошибиться.

**Ключ у сборки, а не у устройства.** Приватный ключ лежит файлом вне репозитория
и называется переменной окружения. Отсутствует -- сборка говорит об этом вслух и
не подписывает; молчаливая сборка без подписи хуже отказа, потому что её
результат неотличим от подписанного, пока устройство не откажется его исполнять.

**Область у каждой подписи своя.** Подписывается не голое сообщение, а сообщение
с приставкой (:data:`MODULE`, :data:`ENVELOPE`). Без приставки подпись модуля
годилась бы как подпись конверта и наоборот: одна и та же строка, подписанная для
одной цели, принималась бы для другой. Это не теоретическая придирка -- отпечаток
модуля и есть строка, и он ездит открытым текстом.

Чего подпись **не** решает, записано в ``docs/signing.md``. Коротко: она говорит
«это положил владелец ключа» и ровно ничего больше -- ни о правах пользователей,
ни о том, что именно владелец ключа положил.
"""

from __future__ import annotations

import json
import os

from .errors import OneFrameworkError

__all__ = ["ENV_PRIVATE_KEY", "PUBLISHER_META", "MODULE", "ENVELOPE",
           "SigningError", "canonical", "generate", "load_private",
           "private_from_pem", "public_hex", "publisher_key", "set_publisher_key",
           "sign", "verify", "signer_from_env", "write_private"]

#: Где лежит приватный ключ издателя. Переменная, а не путь в исходниках: один и
#: тот же репозиторий собирается и на машине разработчика, и на сборочной, и
#: ключ у них разный -- а тот, что в исходниках, не приватный по определению.
ENV_PRIVATE_KEY = "PYAPP_SIGNING_KEY"

#: Где устройство держит публичный ключ издателя. В ``_oneframework_meta``, а не в
#: обычной таблице, и это существенно: служебные таблицы в changeset не попадают
#: (``sync._PRIVATE``), поэтому ключ нельзя подменить тем же путём, каким
#: приезжает подписанное им. Ключ, приезжающий вместе с подписью, не проверяет
#: ничего.
PUBLISHER_META = "publisher:key"

#: Приставки областей. Подпись, сделанная для одной, недействительна для другой.
MODULE = b"oneframework/module/v1\n"
ENVELOPE = b"oneframework/envelope/v1\n"


class SigningError(OneFrameworkError):
    """Подписать или проверить невозможно -- и почему именно."""


def _backend():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - зависит от машины
        raise SigningError(
            "Для подписи нужен пакет cryptography: pip install 'oneframework[sign]'. "
            "Своей криптографии здесь нет и не будет."
        ) from exc
    return ed25519


def canonical(payload) -> bytes:
    """Сообщение из словаря -- одинаково на обеих сторонах.

    Ключи сортируются, пробелов нет: подпись считается по байтам, и словарь,
    сериализованный в другом порядке, -- это другие байты. Разошлись бы стороны
    здесь, и отказ выглядел бы как подделка, хотя подделки нет.

    Дробные числа отвергаются, и это не придирка, а замер: ``3.0`` питон пишет
    как ``3.0``, а ``JSON.stringify`` -- как ``3``. Одно и то же значение, разные
    байты, разная подпись -- и ни одна сторона об этом не узнает. В конверте
    обмена дробных чисел сегодня нет; отказ стоит здесь затем, чтобы первое
    появившееся было названо, а не подписано двумя разными способами.
    """
    _no_floats(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _no_floats(value, path="конверт"):
    if isinstance(value, float):
        raise SigningError(
            f"{path}: дробное число {value!r} в подписываемом сообщении. Питон "
            "и JavaScript пишут такие числа по-разному (3.0 против 3), и подпись "
            "разошлась бы молча. Целое, строка или отдельное поле -- любой из "
            "трёх ответов годится, догадка -- нет."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _no_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _no_floats(item, f"{path}[{i}]")


def _message(domain: bytes, payload) -> bytes:
    if isinstance(payload, bytes):
        return domain + payload
    if isinstance(payload, str):
        return domain + payload.encode("utf-8")
    return domain + canonical(payload)


# --------------------------------------------------------------------------
# ключи
# --------------------------------------------------------------------------
def generate():
    """Новая пара. Отдаётся приватный ключ -- публичный выводится из него."""
    return _backend().Ed25519PrivateKey.generate()


def write_private(private, path) -> str:
    """Записать приватный ключ файлом. Возвращает публичный шестнадцатеричным.

    PKCS#8 PEM -- то, что умеют читать все остальные инструменты. Права 0600
    ставятся здесь, а не оставляются на человека: ключ, созданный доступным на
    чтение всем, остаётся таким навсегда, потому что никто больше на него не
    посмотрит.
    """
    from pathlib import Path

    from cryptography.hazmat.primitives import serialization

    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = Path(path)
    path.write_bytes(pem)
    os.chmod(path, 0o600)
    return public_hex(private)


def private_from_pem(data: bytes):
    from cryptography.hazmat.primitives import serialization

    _backend()
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:
        raise SigningError(f"Это не приватный ключ в PEM: {exc}") from exc
    if not isinstance(key, _backend().Ed25519PrivateKey):
        raise SigningError(
            f"Ключ типа {type(key).__name__}, а нужен Ed25519. Другие здесь не "
            "принимаются намеренно: выбор алгоритма -- это способ ошибиться."
        )
    return key


def load_private(path=None):
    """Приватный ключ издателя, либо внятный отказ.

    *path* -- явный путь; без него берётся ``PYAPP_SIGNING_KEY``. Отказ
    называет, чего именно не хватило: «подпись не получилась» без причины
    заставляет угадывать между «переменной нет», «файла нет» и «файл не тот».
    """
    from pathlib import Path

    if path is None:
        path = os.environ.get(ENV_PRIVATE_KEY)
    if not path:
        raise SigningError(
            f"Ключ издателя не назван: переменная {ENV_PRIVATE_KEY} пуста. "
            f"Создать пару -- `oneframework keygen <файл>`, затем "
            f"`export {ENV_PRIVATE_KEY}=<файл>`. Файл ключа хранится вне "
            "репозитория: ключ, попавший в историю, перестал быть приватным."
        )
    path = Path(path).expanduser()
    if not path.exists():
        raise SigningError(
            f"{ENV_PRIVATE_KEY} указывает на {path}, а такого файла нет. "
            "Создать пару -- `oneframework keygen <файл>`."
        )
    return private_from_pem(path.read_bytes())


def signer_from_env(path=None):
    """Ключ, если он назван, и ``None``, если не назван вовсе.

    Разница с :func:`load_private` в том, что «переменной нет» здесь не отказ, а
    ответ: сборка без ключа -- это прежняя сборка, и она обязана собираться. А
    вот ключ, названный и негодный, отказ: молча собрать неподписанное вместо
    подписанного значит выдать одно за другое.
    """
    if path is None and not os.environ.get(ENV_PRIVATE_KEY):
        return None
    return load_private(path)


def public_hex(private) -> str:
    """Публичный ключ -- 64 шестнадцатеричных знака (32 байта).

    Шестнадцатеричным, а не PEM: этот ключ едет на устройство и попадает в
    ``crypto.subtle.importKey("raw", ...)``, которому нужны голые 32 байта.
    """
    from cryptography.hazmat.primitives import serialization

    return private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def publisher_key(db):
    """Ключ издателя, каким его знает **это** устройство. ``None`` -- не знает."""
    return db.get_meta(PUBLISHER_META) or None


def set_publisher_key(db, public_key_hex):
    """Записать ключ издателя на устройство. Пустое значение -- забыть его."""
    db.set_meta(PUBLISHER_META, public_key_hex or "")


def _public_from_hex(value: str):
    ed25519 = _backend()
    try:
        raw = bytes.fromhex(str(value))
    except ValueError as exc:
        raise SigningError(f"Публичный ключ {value!r} не шестнадцатеричный.") from exc
    if len(raw) != 32:
        raise SigningError(
            f"Публичный ключ длиной {len(raw)} байт, а у Ed25519 он ровно 32."
        )
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


# --------------------------------------------------------------------------
# подпись и проверка
# --------------------------------------------------------------------------
def sign(private, domain: bytes, payload) -> str:
    """Подпись -- 128 шестнадцатеричных знаков. *payload*: bytes, str или dict."""
    return private.sign(_message(domain, payload)).hex()


def verify(public_key_hex, domain: bytes, payload, signature) -> None:
    """Проверить или отказать, назвав причину.

    Отказ -- исключение, а не ``False``. Проверка, которую можно забыть
    прочитать, ничем не отличается от отсутствующей, а здесь цена забывчивости
    -- чужой код на устройстве.
    """
    from cryptography.exceptions import InvalidSignature

    if not signature:
        raise SigningError(
            "Подписи нет вовсе. Сборка с ключом издателя подписывает всё, что "
            "кладёт; неподписанное приехало не от неё."
        )
    key = _public_from_hex(public_key_hex)
    try:
        raw = bytes.fromhex(str(signature))
    except ValueError as exc:
        raise SigningError(f"Подпись {signature!r} не шестнадцатеричная.") from exc
    try:
        key.verify(raw, _message(domain, payload))
    except InvalidSignature as exc:
        raise SigningError(
            "Подпись не сходится с ключом издателя. Либо содержимое поменяли "
            "после подписи, либо подписал не издатель -- различить эти два "
            "случая нечем, и оба означают одно: исполнять это нельзя."
        ) from exc
