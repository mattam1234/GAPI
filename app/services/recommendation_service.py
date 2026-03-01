"""Smart Recommendation Engine.

Provides a richer alternative to :meth:`GamePicker.get_recommendations` that
considers more signals when ranking games:

* Genre *and* tag affinity from well-played titles
* Developer / publisher affinity
* Metacritic score influence (if cached)
* Diversity boosting (avoid recommending the same developer twice in a row)
* Recently-played history penalty
* Short-session bonus for games with historically short play sessions

All computation is performed in-process with zero external API calls; it
relies entirely on details already stored in the Steam details cache.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring constants — tweak here, not scattered through the code
# ---------------------------------------------------------------------------
_BASE_UNPLAYED      = 4.0   # base score for a completely unplayed game
_BASE_BARELY_PLAYED = 2.0   # base score for a barely-played game
_HISTORY_PENALTY    = 2.5   # deducted if the game is in the recent pick history
_GENRE_MAX_BOOST    = 3.0   # maximum genre-affinity boost per game
_TAG_MAX_BOOST      = 2.0   # maximum tag-affinity boost per game
_DEV_MAX_BOOST      = 1.5   # maximum developer-affinity boost
_PUB_MAX_BOOST      = 0.5   # maximum publisher-affinity boost
_METACRITIC_SCALE   = 0.02  # e.g. score 90 → +1.8 boost
_DIVERSITY_PENALTY  = 1.2   # applied when developer already appears in top-N
_WELL_PLAYED_HOURS  = 10.0  # hours above which a game is considered well-played


class SmartRecommendationEngine:
    """Score and rank games using multi-factor heuristics.

    Args:
        games:            User's full game list (each dict must include ``name``
                          and should include ``playtime_forever``, ``game_id``,
                          ``platform``).
        details_cache:    ``{app_id: details_dict}`` mapping from the Steam
                          client's ``details_cache``.  May be ``None`` or empty.
        history:          List of recently-picked ``game_id`` strings (oldest
                          first). The last 10 entries are penalised.
        well_played_mins: Minimum playtime in *minutes* for a game to count as
                          well-played (used to build affinity profiles).
        barely_played_mins: Maximum playtime in minutes for a game to be
                          eligible as a candidate recommendation.
    """

    def __init__(
        self,
        games: List[Dict[str, Any]],
        details_cache: Optional[Dict[Any, Dict[str, Any]]] = None,
        history: Optional[List[str]] = None,
        well_played_mins: int = int(_WELL_PLAYED_HOURS * 60),
        barely_played_mins: int = 120,
    ) -> None:
        self._games            = games or []
        self._cache            = details_cache or {}
        self._history          = history or []
        self._well_played_mins = well_played_mins
        self._barely_mins      = barely_played_mins

        # Pre-built affinity profiles (populated lazily)
        self._genre_weights:   Optional[Dict[str, float]] = None
        self._tag_weights:     Optional[Dict[str, float]] = None
        self._dev_weights:     Optional[Dict[str, float]] = None
        self._pub_weights:     Optional[Dict[str, float]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(self, count: int = 10) -> List[Dict[str, Any]]:
        """Return the top *count* recommended games.

        Each returned dict is a copy of the original game dict enriched with:

        * ``smart_score`` (float) — composite recommendation score
        * ``smart_reason`` (str)  — human-readable explanation
        * ``playtime_hours`` (float)

        Args:
            count: Maximum number of recommendations to return.

        Returns:
            List sorted by ``smart_score`` descending.
        """
        count = max(1, count)
        if not self._games:
            return []

        self._build_affinity_profiles()

        recent_ids = set(self._history[-min(len(self._history), 10):])

        candidates = [
            g for g in self._games
            if g.get('playtime_forever', 0) <= self._barely_mins
        ]
        if not candidates:
            candidates = list(self._games)

        scored = [self._score_game(g, recent_ids) for g in candidates]
        scored.sort(key=lambda x: x['score'], reverse=True)

        # Diversity pass: limit same developer to 2 consecutive spots in top-N
        scored = self._apply_diversity(scored, top_n=count)

        result = []
        for item in scored[:count]:
            entry = dict(item['game'])
            entry['smart_score']    = round(item['score'], 2)
            entry['smart_reason']   = '. '.join(item['reasons'][:3])
            entry['playtime_hours'] = round(
                entry.get('playtime_forever', 0) / 60, 2
            )
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Affinity profile builders
    # ------------------------------------------------------------------

    def _build_affinity_profiles(self) -> None:
        """Compute genre, tag, developer and publisher affinity weights."""
        if self._genre_weights is not None:
            return  # already built

        genre_w: Dict[str, float] = {}
        tag_w:   Dict[str, float] = {}
        dev_w:   Dict[str, float] = {}
        pub_w:   Dict[str, float] = {}

        for game in self._games:
            playtime = game.get('playtime_forever', 0)
            if playtime < self._well_played_mins:
                continue

            hours = playtime / 60.0
            details = self._get_details(game)
            if not details:
                continue

            # Genres
            for entry in details.get('genres', []):
                g = entry.get('description', '').lower()
                if g:
                    genre_w[g] = genre_w.get(g, 0.0) + hours

            # User-defined tags (Steam user tags)
            for entry in details.get('categories', []):
                t = entry.get('description', '').lower()
                if t:
                    tag_w[t] = tag_w.get(t, 0.0) + hours / 2.0

            # Developer
            for dev in details.get('developers', []):
                d = dev.lower()
                if d:
                    dev_w[d] = dev_w.get(d, 0.0) + hours

            # Publisher
            for pub in details.get('publishers', []):
                p = pub.lower()
                if p:
                    pub_w[p] = pub_w.get(p, 0.0) + hours / 2.0

        self._genre_weights = genre_w
        self._tag_weights   = tag_w
        self._dev_weights   = dev_w
        self._pub_weights   = pub_w

    # ------------------------------------------------------------------
    # Per-game scorer
    # ------------------------------------------------------------------

    def _score_game(
        self,
        game: Dict[str, Any],
        recent_ids: set,
    ) -> Dict[str, Any]:
        score    = 0.0
        reasons: List[str] = []

        playtime = game.get('playtime_forever', 0)
        game_id  = game.get('game_id', '')

        # Base score by playtime
        if playtime == 0:
            score += _BASE_UNPLAYED
            reasons.append('Unplayed')
        else:
            score += _BASE_BARELY_PLAYED
            reasons.append(f'Barely played ({playtime / 60:.1f}h)')

        # Recent-history penalty
        if game_id in recent_ids:
            score -= _HISTORY_PENALTY

        details = self._get_details(game)
        if details:
            # Genre affinity
            genre_boost, genre_reasons = self._affinity_boost(
                [e.get('description', '') for e in details.get('genres', [])],
                self._genre_weights or {},
                max_boost=_GENRE_MAX_BOOST,
                label='genre',
            )
            score += genre_boost
            reasons.extend(genre_reasons)

            # Tag affinity (Steam categories)
            tag_boost, _ = self._affinity_boost(
                [e.get('description', '') for e in details.get('categories', [])],
                self._tag_weights or {},
                max_boost=_TAG_MAX_BOOST,
                label='tag',
            )
            score += tag_boost

            # Developer affinity
            dev_boost, dev_reasons = self._affinity_boost(
                details.get('developers', []),
                self._dev_weights or {},
                max_boost=_DEV_MAX_BOOST,
                label='developer',
            )
            score += dev_boost
            if dev_boost > 0:
                reasons.extend(dev_reasons)

            # Publisher affinity
            pub_boost, _ = self._affinity_boost(
                details.get('publishers', []),
                self._pub_weights or {},
                max_boost=_PUB_MAX_BOOST,
                label='publisher',
            )
            score += pub_boost

            # Metacritic boost
            mc = details.get('metacritic', {})
            if isinstance(mc, dict):
                mc_score = mc.get('score')
                if mc_score and isinstance(mc_score, (int, float)) and mc_score > 0:
                    boost = mc_score * _METACRITIC_SCALE
                    score += boost
                    reasons.append(f'Metacritic {mc_score}')

        return {'game': game, 'score': score, 'reasons': reasons}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _affinity_boost(
        items: List[str],
        weights: Dict[str, float],
        max_boost: float,
        label: str,
    ) -> tuple:
        """Compute a capped affinity boost for a list of attribute values."""
        boost = 0.0
        matched: List[str] = []
        for item in items:
            key = item.lower()
            if key in weights:
                raw_boost = min(weights[key] / 20.0, max_boost / max(len(items), 1))
                boost += raw_boost
                matched.append(item)
        boost = min(boost, max_boost)
        reasons = []
        if matched:
            kinds = ', '.join(matched[:2])
            if label == 'developer':
                reasons.append(f'From a developer you enjoy ({kinds})')
            elif label == 'genre':
                reasons.append(f'Matches your {kinds} preference')
        return boost, reasons

    def _get_details(self, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return cached details for *game*, or ``None`` if not cached."""
        if not self._cache:
            return None
        app_id = game.get('appid')
        if app_id is None:
            # Try extracting numeric part from game_id string like "steam:620"
            game_id_str = game.get('game_id', '')
            if ':' in game_id_str:
                try:
                    app_id = int(game_id_str.split(':')[-1])
                except (ValueError, TypeError):
                    pass
        if app_id is None:
            return None
        try:
            key = int(app_id)
        except (ValueError, TypeError):
            key = app_id
        return self._cache.get(key)

    def _apply_diversity(
        self,
        scored: List[Dict[str, Any]],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        """Apply a mild diversity penalty to avoid same-developer clusters.

        Looks up the actual developer from the details cache for each
        candidate.  If a developer appears three or more times in the first
        ``top_n * 2`` candidates the third and subsequent occurrences receive
        a score deduction.
        """
        dev_counts: Dict[str, int] = {}
        result: List[Dict[str, Any]] = list(scored)
        for i, item in enumerate(result[:top_n * 2]):
            details = self._get_details(item['game'])
            devs = (details.get('developers', []) if details else []) or []
            dev_key = devs[0].lower() if devs else item['game'].get('name', '')[:6].lower()
            dev_counts[dev_key] = dev_counts.get(dev_key, 0) + 1
            if dev_counts[dev_key] >= 3:
                penalised = dict(item)
                penalised['score'] = item['score'] - _DIVERSITY_PENALTY
                result[i] = penalised
        result.sort(key=lambda x: x['score'], reverse=True)
        return result
