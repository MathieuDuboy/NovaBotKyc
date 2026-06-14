"""
Interlace API Client - Python wrapper for the Interlace Money API.

This package provides a client for interacting with the Interlace Money API
and includes modules for various endpoints like authentication, accounts,
funding, and payments.
"""

from interlace.client import InterlaceClient
from interlace.exceptions import InterlaceError, AuthenticationError, APIError

__all__ = ['InterlaceClient', 'InterlaceError', 'AuthenticationError', 'APIError'] 