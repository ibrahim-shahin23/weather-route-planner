"""Domain-level errors. Each carries an HTTP status so the API layer can map it
without the domain knowing anything about HTTP frameworks."""


class DomainError(Exception):
    code = "domain_error"
    http_status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidRequest(DomainError):
    code = "invalid_request"
    http_status = 400


class GeocodingError(DomainError):
    code = "geocoding_failed"
    http_status = 422


class RoutingError(DomainError):
    code = "routing_failed"
    http_status = 422


class UpstreamUnavailable(DomainError):
    """A third-party API (routing / geocoding / weather) failed or timed out."""

    code = "upstream_unavailable"
    http_status = 502
