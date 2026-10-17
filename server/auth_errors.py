"""Expected, safe login refusals; storage and programming errors stay separate."""
from tio.protocol.login import LoginFailureStatus


class LoginRejected(ValueError):
    def __init__(self, category, status, message):
        self.category = category
        self.status = LoginFailureStatus(status)
        super().__init__(message)
