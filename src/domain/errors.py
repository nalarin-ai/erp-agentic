class DomainError(ValueError):
    """Safe base error for invalid domain input."""


class InvalidDomainValue(DomainError):
    """A domain value failed canonical validation."""
