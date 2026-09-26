from email_validator import EmailNotValidError, validate_email

from app.services.errors import ValidationError


def clean_text(value: str, field: str, label: str, max_length: int = 255) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValidationError(f"Заполните поле «{label}».", field)
    if len(value) > max_length:
        raise ValidationError(f"«{label}»: не длиннее {max_length} символов.", field)
    return value


def clean_optional_text(value: str | None, max_length: int = 500) -> str | None:
    value = " ".join((value or "").split())
    return value[:max_length] or None


def clean_email(value: str, field: str = "email") -> str:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValidationError("Проверьте адрес электронной почты.", field) from exc
