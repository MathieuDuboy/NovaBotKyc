class InterlaceError(Exception):
    """Base exception class for Interlace API client errors."""
    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data

    def __str__(self):
        base = super().__str__()
        details = []
        if self.status_code:
            details.append(f"Status Code: {self.status_code}")
        if self.response_data:
            details.append(f"Response: {self.response_data}")
        if details:
            return f"{base} ({', '.join(details)})"
        return base


class AuthenticationError(InterlaceError):
    """Exception raised for authentication errors."""
    pass


class APIError(InterlaceError):
    """Exception raised for general API errors (non-2xx status codes)."""
    pass 