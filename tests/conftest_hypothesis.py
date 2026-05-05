"""Hypothesis profiles for property-based tests."""

from hypothesis import settings

settings.register_profile("ci", max_examples=200)
settings.register_profile("dev", max_examples=50)
settings.load_profile("dev")
