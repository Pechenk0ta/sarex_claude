class ValidationError(Exception):
    """A user input problem; `message` is shown to the user as is (in Russian)."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
