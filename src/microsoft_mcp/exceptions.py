from typing import NamedTuple


class AuthenticationError(Exception):
    pass


class DeviceCodeAuthRequired(AuthenticationError):
    pass


class TokenAcquisitionError(AuthenticationError):
    pass


class GraphAPIError(Exception):
    pass


class RateLimitError(GraphAPIError):
    pass


class ResourceNotFoundError(GraphAPIError):
    pass


class PermissionDeniedError(GraphAPIError):
    pass


class DeviceCodeFlow(NamedTuple):
    verification_uri: str
    user_code: str
    message: str
