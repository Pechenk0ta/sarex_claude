"""Signed tokens for the «Подтверждаю ознакомление» button in emails."""

import uuid

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Settings

_SALT = "notification-ack"
MAX_AGE_SECONDS = 180 * 24 * 3600


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key.get_secret_value(), salt=_SALT)


def make_ack_token(settings: Settings, notification_id: uuid.UUID) -> str:
    return _serializer(settings).dumps(str(notification_id))


def read_ack_token(settings: Settings, token: str) -> uuid.UUID | None:
    try:
        value = _serializer(settings).loads(token, max_age=MAX_AGE_SECONDS)
        return uuid.UUID(str(value))
    except (BadSignature, ValueError):
        return None


def ack_url(settings: Settings, notification_id: uuid.UUID) -> str:
    return f"{settings.app_base_url.rstrip('/')}/ack/{make_ack_token(settings, notification_id)}"
