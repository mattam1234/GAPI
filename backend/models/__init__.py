"""FastAPI-era ORM models for newly-built feature domains.

These extend the *same* SQLAlchemy ``Base`` declared in the legacy ``database``
module, so they share one metadata/engine. One module per domain keeps feature
work conflict-free during parallel development.

Models register on ``database.Base.metadata`` simply by being imported; each
feature router imports its own model module, and ``backend.main.create_app``
runs an idempotent ``create_all`` after all routers load, so the tables exist.
Do NOT add imports here — import model modules from their routers instead, to
keep this file collision-free.
"""
