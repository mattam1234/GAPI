"""Business logic for the tournaments domain.

This is a *real*, persistent feature (no longer mock data). It uses the shared
SQLAlchemy session factory ``database.SessionLocal`` and the ORM models in
``backend/models/tournaments.py``.

Status lifecycle
----------------
A tournament moves through::

    upcoming  ->  open  ->  active  ->  completed

  * ``upcoming``  — announced, registration not open yet.
  * ``open``      — registration is open; users may register.
  * ``active``    — registration closed, tournament is being played. A simple
                    seeded pairing list is derived from the registrations.
  * ``completed`` — finished; ``winner`` may be set.

Registration rules (enforced by :func:`register`)
-------------------------------------------------
  * The tournament must exist           -> otherwise ``404`` (``LookupError``).
  * Its status must be ``open``         -> otherwise ``409`` (``ConflictError``).
  * It must not be full (``max_players``
    reached, when set)                  -> otherwise ``409`` (``ConflictError``).
  * Double registration is **idempotent**: re-registering the same user returns
    the existing registration successfully (no error, no duplicate row). This is
    friendlier than 409 for a "register" button that may be clicked twice.

All public functions return plain ``dict`` objects (or raise) so the router has
no ORM coupling.
"""
from datetime import datetime
from typing import List, Optional

import database
from backend.models.tournaments import (
    FeatureTournament, FeatureTournamentRegistration,
)

# Status lifecycle, in order.
STATUS_UPCOMING = 'upcoming'
STATUS_OPEN = 'open'
STATUS_ACTIVE = 'active'
STATUS_COMPLETED = 'completed'
VALID_STATUSES = (STATUS_UPCOMING, STATUS_OPEN, STATUS_ACTIVE, STATUS_COMPLETED)


class LookupError404(LookupError):
    """Raised when a tournament does not exist (-> HTTP 404)."""


class ConflictError(Exception):
    """Raised on a registration rule violation (-> HTTP 409)."""


def _session():
    """Return a new DB session, or raise if the engine is unavailable."""
    factory = getattr(database, "SessionLocal", None)
    if factory is None:
        raise RuntimeError("Database not available")
    return factory()


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _tournament_to_dict(t: FeatureTournament, participant_count: int) -> dict:
    """Serialize a tournament for list/summary responses."""
    return {
        'id': str(t.id),
        'name': t.name,
        'game': t.game,
        'status': t.status,
        'starts_at': _isoformat(t.starts_at),
        'max_players': t.max_players,
        'created_by': t.created_by,
        'participants': participant_count,
        'created_at': _isoformat(t.created_at),
    }


def _seed_bracket(participants: List[str]) -> List[dict]:
    """Build a simple seeded pairing list for an active tournament.

    Seeds are assigned by registration order (1-based). Players are paired
    1-vs-2, 3-vs-4, ...; an odd final player gets a bye.
    """
    seeded = [
        {'seed': i + 1, 'username': name}
        for i, name in enumerate(participants)
    ]
    pairings = []
    for i in range(0, len(seeded), 2):
        player_one = seeded[i]
        player_two = seeded[i + 1] if i + 1 < len(seeded) else None
        pairings.append({
            'match': (i // 2) + 1,
            'player_one': player_one,
            'player_two': player_two,  # None => bye
        })
    return pairings


def create_tournament(
    name: str,
    game: Optional[str] = None,
    status: str = STATUS_UPCOMING,
    starts_at: Optional[datetime] = None,
    max_players: Optional[int] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Create a tournament and return its summary dict.

    Raises ``ValueError`` for an empty name or an invalid status. Intended for
    admin routes, tests, and seeding (there is no public create route yet).
    """
    clean_name = (name or '').strip()
    if not clean_name:
        raise ValueError("Tournament name is required")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}")

    db = _session()
    try:
        tournament = FeatureTournament(
            name=clean_name,
            game=(game or None),
            status=status,
            starts_at=starts_at,
            max_players=max_players,
            created_by=(created_by or None),
        )
        db.add(tournament)
        db.commit()
        db.refresh(tournament)
        return _tournament_to_dict(tournament, participant_count=0)
    finally:
        db.close()


def list_tournaments(status: Optional[str] = None) -> List[dict]:
    """Return tournament summaries, optionally filtered by status.

    ``status=None`` (or ``'all'``) returns every tournament. The filter is
    case-insensitive. An unknown status simply yields an empty list.
    """
    db = _session()
    try:
        query = db.query(FeatureTournament)
        normalized = (status or '').strip().lower()
        if normalized and normalized != 'all':
            query = query.filter(FeatureTournament.status == normalized)
        tournaments = query.order_by(FeatureTournament.created_at.asc(),
                                     FeatureTournament.id.asc()).all()
        results = []
        for t in tournaments:
            count = db.query(FeatureTournamentRegistration).filter(
                FeatureTournamentRegistration.tournament_id == t.id).count()
            results.append(_tournament_to_dict(t, participant_count=count))
        return results
    finally:
        db.close()


def get_tournament(tournament_id: int) -> dict:
    """Return a tournament's detail dict including its participants.

    Raises :class:`LookupError404` when the tournament does not exist. When the
    tournament is ``active`` a simple seeded ``bracket`` (pairings) is included.
    """
    db = _session()
    try:
        tournament = db.query(FeatureTournament).filter(
            FeatureTournament.id == tournament_id).first()
        if tournament is None:
            raise LookupError404("Tournament not found")

        registrations = db.query(FeatureTournamentRegistration).filter(
            FeatureTournamentRegistration.tournament_id == tournament.id
        ).order_by(FeatureTournamentRegistration.registered_at.asc(),
                   FeatureTournamentRegistration.id.asc()).all()

        participants = [
            {
                'username': r.username,
                'registered_at': _isoformat(r.registered_at),
            }
            for r in registrations
        ]

        detail = _tournament_to_dict(tournament, participant_count=len(participants))
        detail['participants'] = participants  # full list overrides the count

        result = {'tournament': detail}
        if tournament.status == STATUS_ACTIVE:
            result['bracket'] = _seed_bracket([r.username for r in registrations])
        return result
    finally:
        db.close()


def register(tournament_id: int, username: str) -> dict:
    """Register ``username`` for the tournament.

    Returns a success dict. Raises:
      * :class:`LookupError404` — tournament missing (404).
      * :class:`ConflictError`  — tournament not ``open`` or full (409).

    Double registration is idempotent: an already-registered user gets a
    successful response (``already_registered: True``) and no duplicate row.
    """
    clean_username = (username or '').strip()
    if not clean_username:
        raise ValueError("username is required")

    db = _session()
    try:
        tournament = db.query(FeatureTournament).filter(
            FeatureTournament.id == tournament_id).first()
        if tournament is None:
            raise LookupError404("Tournament not found")

        existing = db.query(FeatureTournamentRegistration).filter(
            FeatureTournamentRegistration.tournament_id == tournament.id,
            FeatureTournamentRegistration.username == clean_username,
        ).first()
        if existing is not None:
            count = db.query(FeatureTournamentRegistration).filter(
                FeatureTournamentRegistration.tournament_id == tournament.id).count()
            return {
                'success': True,
                'message': 'Already registered for tournament',
                'already_registered': True,
                'tournament_id': str(tournament.id),
                'username': clean_username,
                'participants': count,
            }

        if tournament.status != STATUS_OPEN:
            raise ConflictError(
                "Tournament is not open for registration")

        current_count = db.query(FeatureTournamentRegistration).filter(
            FeatureTournamentRegistration.tournament_id == tournament.id).count()
        if tournament.max_players is not None and current_count >= tournament.max_players:
            raise ConflictError("Tournament is full")

        registration = FeatureTournamentRegistration(
            tournament_id=tournament.id,
            username=clean_username,
        )
        db.add(registration)
        db.commit()

        new_count = db.query(FeatureTournamentRegistration).filter(
            FeatureTournamentRegistration.tournament_id == tournament.id).count()
        return {
            'success': True,
            'message': 'Tournament registration successful',
            'already_registered': False,
            'tournament_id': str(tournament.id),
            'username': clean_username,
            'participants': new_count,
        }
    finally:
        db.close()
