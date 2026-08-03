from __future__ import annotations


class ConfluencePdfError(Exception):
    """Base exception for user-facing CLI errors."""


class ConfigError(ConfluencePdfError):
    """Raised when required configuration is missing or invalid."""


class ConfluenceApiError(ConfluencePdfError):
    """Raised when Confluence returns an unsuccessful response."""


class AuthenticationError(ConfluencePdfError):
    """Raised when Confluence does not recognise the supplied token."""


class PageLookupError(ConfluencePdfError):
    """Raised when a requested page title cannot be resolved exactly once."""


class PdfExportError(ConfluencePdfError):
    """Raised when a page cannot be exported as PDF."""
