"""
Logging utility for the geoDB Blender add-on.

Provides a centralized logger with configurable log levels,
URL sanitization, and sensitive data redaction.
"""

import logging
from urllib.parse import urlparse, urlunparse

# Create the geoDB logger
logger = logging.getLogger('geodb')
logger.setLevel(logging.WARNING)  # Default: only warnings and errors

# Create a console handler that outputs to Blender's console
_handler = logging.StreamHandler()
_handler.setLevel(logging.DEBUG)
_formatter = logging.Formatter('[geoDB] %(levelname)s: %(message)s')
_handler.setFormatter(_formatter)
logger.addHandler(_handler)

# Prevent log propagation to root logger (avoids duplicate messages)
logger.propagate = False


def set_debug_mode(enabled: bool):
    """Toggle debug logging on/off.

    Args:
        enabled: If True, sets log level to DEBUG. Otherwise, WARNING.
    """
    logger.setLevel(logging.DEBUG if enabled else logging.WARNING)


def sanitize_url(url: str) -> str:
    """Strip query parameters from a URL for safe logging.

    Query parameters may contain SAS tokens, API keys, or signatures
    that should never appear in logs.

    Args:
        url: The URL to sanitize.

    Returns:
        The URL with query parameters and fragment replaced with [REDACTED].
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.query or parsed.fragment:
            return urlunparse(parsed._replace(query="[REDACTED]", fragment=""))
        return url
    except Exception:
        return "[INVALID URL]"
