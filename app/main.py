"""ASGI entry point.

Run locally with:  uvicorn app.main:app --reload

Importing this module loads configuration from the environment and fails with
a ConfigurationError if a required variable (e.g. DATABASE_URL) is missing.
"""

from app.factory import create_app

app = create_app()
