"""ASGI entry point; launch with uvicorn main:app."""

from application.factory import create_app

app = create_app()
