"""GAPI FastAPI backend (modernization target).

See ``docs/MODERNIZATION_BRIEF.md`` for the architecture and migration plan.
During the strangler-fig migration this package is the ASGI entrypoint and
mounts the legacy Flask app (``gapi_gui:app``) as a WSGI fallback.
"""
