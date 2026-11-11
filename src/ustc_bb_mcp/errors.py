"""Safe, actionable errors: never return raw authenticated URLs or credentials."""


class BBError(Exception):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}
