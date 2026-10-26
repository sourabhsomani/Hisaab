"""Compatibility utilities for enum types."""

from enum import Enum


class StrEnum(str, Enum):
    """String-valued enum with consistent ``str()`` behavior across Python versions."""

    __str__ = str.__str__
