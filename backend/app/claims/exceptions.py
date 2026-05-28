class InvalidTransitionError(Exception):
    """Raised when a requested status transition is not in the allowed set."""


class DuplicateTransitionError(Exception):
    """Raised when a transition to a given status has already been recorded for this claim."""


class ValidationFailedError(Exception):
    """Raised when the rules engine blocks the CREATED → VALIDATED transition."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors
