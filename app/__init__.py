"""
GAPI application package.

Introduces a layered architecture:

  app/repositories/  — pure I/O: loading from and persisting to JSON files.
  app/services/      — business logic: validation, transformation, domain rules.

``GamePicker`` (in ``gapi.py``) is the integration point: it creates repository
and service instances in ``__init__`` and exposes them as public attributes
(e.g. ``picker.review_service``).  Route handlers in ``gapi_gui.py`` can use
these services directly instead of calling ``picker.xxx_method()``, giving a
clean separation between the HTTP layer and the domain.
"""
