"""Typed exception hierarchy for Matcha 2.0 (strategy §15.1).

All Matcha-specific errors derive from :class:`MatchaError` so callers can
catch the whole tree with one `except MatchaError`, or narrow to a
specific subsystem. No bare `except:` is allowed anywhere in the codebase.
"""


class MatchaError(Exception):
    """Base class for all Matcha errors."""


class ConfigError(MatchaError):
    """Configuration loading or validation failed."""


class SourceError(MatchaError):
    """A job source failed to acquire data."""


class BackendError(MatchaError):
    """An upstream backend failed to run or respond."""


class ParseError(MatchaError):
    """Parsing of scraped data failed."""


class FilterError(MatchaError):
    """A centralized filter rejected or failed on a job."""


class EnrichmentError(MatchaError):
    """Enrichment of a job posting failed."""
