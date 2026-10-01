"""Process-wide logging setup, shared by every entry point.

It lives outside `cli.py` because `uvicorn jobscout.api.app:app` and a gunicorn or Docker
invocation never import the CLI: configuring logging there left those entry points at the
root logger's WARNING default, and let a bad LOG_LEVEL start the server.
"""

import logging

from pydantic import ValidationError

from jobscout.config import Settings, get_settings


def load_settings() -> Settings:
    """Settings, or a one-line exit when the operator config is invalid."""
    try:
        return get_settings()
    except ValidationError as exc:
        # Bad operator config should read as a message, not a traceback from import time.
        raise SystemExit(f"Invalid configuration: {exc}") from None


def configure_logging() -> Settings:
    """Validate the operator config and apply LOG_LEVEL. Safe to call more than once.

    `basicConfig` does nothing when the root logger already has handlers, so `jobscout serve`
    (which configures here via the CLI, then imports the app) configures exactly once.
    """
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    return settings
