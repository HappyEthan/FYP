"""Versioned, phase-aware XY templates. No invented time or magnetic targets."""
from .schema import validate_annotation, validate_template
from .geometry import adapt_stroke, build_template

__all__ = ['validate_annotation', 'validate_template', 'adapt_stroke', 'build_template']
