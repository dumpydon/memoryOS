"""Safe provider failures exposed to the ingestion service."""


class ProviderError(RuntimeError):
    """Base class for provider failures without provider payloads."""


class ProviderOutputInvalid(ProviderError):
    """A provider returned malformed, incomplete, or unsafe structured output."""


class ProviderUnavailable(ProviderError):
    """A provider could not be reached or configured."""


class ProviderTimeout(ProviderError):
    """A provider exceeded its configured request timeout."""


class UnsupportedDemoInput(ProviderError):
    """The finite demo catalog does not contain the requested input."""


__all__ = [
    "ProviderError",
    "ProviderOutputInvalid",
    "ProviderTimeout",
    "ProviderUnavailable",
    "UnsupportedDemoInput",
]
