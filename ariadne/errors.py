class AriadneError(Exception):
    """Stable errors shared by library calls and JSON interfaces."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}

    @classmethod
    def invalid(cls, message: str):
        return cls("VALIDATION_ERROR", message)


Error = AriadneError
