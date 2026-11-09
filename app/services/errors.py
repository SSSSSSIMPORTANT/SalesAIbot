"""Transport-independent service errors, translated at the API boundary."""


class ServiceError(Exception):
    def __init__(self, *, status_code: int, detail: str | dict):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
