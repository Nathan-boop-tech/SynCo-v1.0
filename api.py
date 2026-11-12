"""Compatibility import for deployments that still run ``uvicorn api:app``."""

from server import app

__all__ = ["app"]
