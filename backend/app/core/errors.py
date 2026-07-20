"""Application errors rendered in Revora's stable API envelope."""


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: object = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)
