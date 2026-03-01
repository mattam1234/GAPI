"""
ml_recommendation_service.py
=============================
Machine-Learning–based game recommendations using in-process numpy.

Two complementary models are available:

1. **Item-based Collaborative Filtering (CF)** — builds a user–item playtime
   matrix, normalises it, and finds games similar to the user's well-played
   titles via cosine similarity on the item feature vectors.  Because GAPI
   has data for only *one* user the "items" are genres/tags and the "users"
   are games; similarity is computed in the genre feature space.

2. **ALS-style Matrix Factorization (MF)** — factorizes the genre-game
   implicit feedback matrix with Alternating Least Squares, then scores
   unplayed games by the dot product of their latent factor and the user's
   preference vector.

Both models are pure-numpy; no external ML library is required.  If numpy is
not installed the service gracefully falls back to the basic genre-affinity
scorer.

Usage
-----
::

    from app.services.ml_recommendation_service import MLRecommendationEngine

    engine = MLRecommendationEngine(
        games=picker.games,
        details_cache=steam_client.details_cache,
        history=picker.history,
    )
    recs = engine.recommend(count=10, method="cf")   # or "mf"
"""
from __future__ import annotations

import logging
import math
import random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import numpy; fall back gracefully if not available
# ---------------------------------------------------------------------------
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    logger.info("numpy not installed — MLRecommendationEngine will use heuristic fallback")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WELL_PLAYED_HOURS   = 10.0       # hours considered "well played"
_BARELY_PLAYED_HOURS = 2.0        # max hours for a candidate recommendation
_HISTORY_PENALTY     = 2.5        # score penalty for recently-picked games
_ALS_FACTORS         = 16         # latent factor dimensionality
_ALS_ITERATIONS      = 15         # ALS iteration count
_ALS_REGULARIZATION  = 0.1        # ALS regularization lambda
_ALS_CONFIDENCE_ALPHA = 40.0      # implicit feedback confidence scale


class MLRecommendationEngine:
    """Recommend games using machine-learning techniques.

    Args:
        games:             User's full game list.
        details_cache:     ``{app_id: details_dict}`` from the Steam client.
        history:           List of recently-picked ``game_id`` strings.
        well_played_mins:  Minutes above which a game is well-played.
        barely_played_mins: Maximum minutes for a recommendation candidate.
    """

    def __init__(
        self,
        games: List[Dict[str, Any]],
        details_cache: Optional[Dict[Any, Dict[str, Any]]] = None,
        history: Optional[List[str]] = None,
        well_played_mins: int = int(_WELL_PLAYED_HOURS * 60),
        barely_played_mins: int = int(_BARELY_PLAYED_HOURS * 60),
    ) -> None:
        self._games            = games or []
        self._cache            = details_cache or {}
        self._history          = history or []
        self._well_mins        = well_played_mins
        self._barely_mins      = barely_played_mins

        # Populated during _build_matrices()
        self._genre_index: Optional[Dict[str, int]] = None
        self._game_feature_matrix: Optional[Any] = None   # numpy array
        self._game_index_map: Optional[Dict[str, int]] = None
        self._built = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def recommend(
        self,
        count: int = 10,
        method: str = 'cf',
    ) -> List[Dict[str, Any]]:
        """Return the top *count* recommended games.

        Args:
            count:  Maximum number of results.
            method: ``"cf"`` for item-based collaborative filtering,
                    ``"mf"`` for ALS matrix factorization,
                    ``"hybrid"`` for a weighted combination of both.

        Returns:
            List of game dicts enriched with ``ml_score`` (float),
            ``ml_reason`` (str), and ``playtime_hours`` (float).
        """
        count = max(1, count)
        if not self._games:
            return []

        if not _HAS_NUMPY:
            return self._heuristic_fallback(count)

        self._build_matrices()

        recent_ids = set(self._history[-min(len(self._history), 10):])
        candidates = [
            g for g in self._games
            if g.get('playtime_forever', 0) <= self._barely_mins
        ]
        if not candidates:
            candidates = list(self._games)

        if method == 'cf':
            scores = self._score_cf(candidates)
        elif method == 'mf':
            scores = self._score_mf(candidates)
        else:  # hybrid
            cf_scores = self._score_cf(candidates)
            mf_scores = self._score_mf(candidates)
            # Weighted blend: 60% CF + 40% MF (CF tends to be more interpretable)
            cf_max = max((s for _, s in cf_scores), default=1.0) or 1.0
            mf_max = max((s for _, s in mf_scores), default=1.0) or 1.0
            norm_cf = {i: s / cf_max for i, s in cf_scores}
            norm_mf = {i: s / mf_max for i, s in mf_scores}
            all_idx = set(norm_cf) | set(norm_mf)
            scores   = [
                (i, 0.6 * norm_cf.get(i, 0) + 0.4 * norm_mf.get(i, 0))
                for i in all_idx
            ]

        # Apply history penalty and sort
        penalised: List[Tuple[int, float]] = []
        for idx, score in scores:
            game   = candidates[idx]
            gid    = game.get('game_id', '')
            if gid in recent_ids:
                score -= _HISTORY_PENALTY
            penalised.append((idx, score))
        penalised.sort(key=lambda x: x[1], reverse=True)

        result: List[Dict[str, Any]] = []
        for idx, score in penalised[:count]:
            game  = candidates[idx]
            entry = dict(game)
            entry['ml_score']      = round(score, 3)
            entry['ml_reason']     = self._reason(game, method)
            entry['playtime_hours'] = round(game.get('playtime_forever', 0) / 60, 2)
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Matrix construction
    # ------------------------------------------------------------------

    def _build_matrices(self) -> None:
        """Build the genre-feature matrix for all games (once)."""
        if self._built:
            return

        # Collect all genres
        genre_set: set = set()
        for game in self._games:
            for g in self._get_genres(game):
                genre_set.add(g.lower())

        genre_index = {g: i for i, g in enumerate(sorted(genre_set))}
        n_genres  = len(genre_index)
        n_games   = len(self._games)

        if n_genres == 0 or n_games == 0:
            self._genre_index        = genre_index
            self._game_feature_matrix = np.zeros((n_games, 1)) if _HAS_NUMPY else None
            self._game_index_map      = {g.get('game_id', str(i)): i for i, g in enumerate(self._games)}
            self._built = True
            return

        # Build game × genre matrix (values = log1p(playtime hours))
        mat = np.zeros((n_games, n_genres), dtype=np.float32)
        for g_idx, game in enumerate(self._games):
            playtime = game.get('playtime_forever', 0)
            hours    = playtime / 60.0
            weight   = math.log1p(hours) if hours > 0 else 0.0
            for genre in self._get_genres(game):
                col = genre_index.get(genre.lower())
                if col is not None:
                    mat[g_idx, col] = weight

        self._genre_index         = genre_index
        self._game_feature_matrix = mat
        self._game_index_map      = {g.get('game_id', str(i)): i for i, g in enumerate(self._games)}
        self._built = True

    # ------------------------------------------------------------------
    # CF scoring
    # ------------------------------------------------------------------

    def _score_cf(
        self,
        candidates: List[Dict[str, Any]],
    ) -> List[Tuple[int, float]]:
        """Item-based CF: score each candidate by cosine similarity to
        well-played games in genre space.

        Returns:
            List of ``(candidate_index, score)`` tuples.
        """
        mat  = self._game_feature_matrix
        if mat is None or mat.shape[1] == 0:
            return [(i, 0.0) for i in range(len(candidates))]

        # User profile = sum of well-played game genre vectors
        profile = np.zeros(mat.shape[1], dtype=np.float32)
        for game in self._games:
            if game.get('playtime_forever', 0) >= self._well_mins:
                g_idx = self._game_index_map.get(game.get('game_id', ''))
                if g_idx is not None:
                    profile += mat[g_idx]

        profile_norm = np.linalg.norm(profile)
        if profile_norm < 1e-8:
            # No well-played games — fall back to pure unplayed bias
            return [
                (i, 3.0 if g.get('playtime_forever', 0) == 0 else 1.0)
                for i, g in enumerate(candidates)
            ]

        profile_unit = profile / profile_norm

        scores: List[Tuple[int, float]] = []
        for c_idx, game in enumerate(candidates):
            row_idx = self._game_index_map.get(game.get('game_id', ''))
            if row_idx is None:
                scores.append((c_idx, 0.0))
                continue
            row  = mat[row_idx]
            norm = np.linalg.norm(row)
            if norm < 1e-8:
                # Game has no genre data — small unplayed bonus
                scores.append((c_idx, 0.5 if game.get('playtime_forever', 0) == 0 else 0.0))
            else:
                similarity = float(np.dot(row / norm, profile_unit))
                # Unplayed base bonus
                base = 3.0 if game.get('playtime_forever', 0) == 0 else 1.0
                scores.append((c_idx, base + similarity * 5.0))
        return scores

    # ------------------------------------------------------------------
    # MF scoring (ALS implicit feedback)
    # ------------------------------------------------------------------

    def _score_mf(
        self,
        candidates: List[Dict[str, Any]],
    ) -> List[Tuple[int, float]]:
        """ALS matrix factorization: score candidates via latent factors.

        Treats the game × genre playtime matrix as implicit feedback, runs a
        miniaturised ALS to get item and user factor matrices, then scores
        each candidate by the dot product of its item factor and the aggregate
        user factor (sum over well-played games).

        Returns:
            List of ``(candidate_index, score)`` tuples.
        """
        mat = self._game_feature_matrix
        if mat is None or mat.shape[1] == 0 or mat.shape[0] == 0:
            return [(i, 0.0) for i in range(len(candidates))]

        n_items, n_features = mat.shape
        k = min(_ALS_FACTORS, n_features, n_items)
        if k == 0:
            return [(i, 0.0) for i in range(len(candidates))]

        # Confidence matrix C = 1 + alpha * R
        C = 1.0 + _ALS_CONFIDENCE_ALPHA * mat  # (n_items, n_features)

        # Random initialization — use a fixed seed so results are reproducible
        rng = np.random.default_rng(seed=42)
        X = rng.standard_normal((n_items, k)).astype(np.float32) * 0.01
        Y = rng.standard_normal((n_features, k)).astype(np.float32) * 0.01

        reg = _ALS_REGULARIZATION * np.eye(k, dtype=np.float32)

        for _ in range(_ALS_ITERATIONS):
            # Update item factors
            YtY = Y.T @ Y
            for i in range(n_items):
                c_i = C[i]         # confidence weights (n_features,)
                d_i = mat[i]       # preference binary (n_features,)
                # Use element-wise scaling instead of a full diagonal matrix
                A = YtY + (Y * c_i[:, None]).T @ Y + reg
                b = Y.T @ (c_i * d_i)
                try:
                    X[i] = np.linalg.solve(A, b)
                except np.linalg.LinAlgError:
                    pass

            # Update feature factors
            XtX = X.T @ X
            for f in range(n_features):
                c_f = C[:, f]
                d_f = mat[:, f]
                # Use element-wise scaling instead of a full diagonal matrix
                A = XtX + (X * c_f[:, None]).T @ X + reg
                b = X.T @ (c_f * d_f)
                try:
                    Y[f] = np.linalg.solve(A, b)
                except np.linalg.LinAlgError:
                    pass

        # User latent vector = mean of well-played game factors
        well_rows = [
            self._game_index_map.get(g.get('game_id', ''))
            for g in self._games
            if g.get('playtime_forever', 0) >= self._well_mins
        ]
        well_rows = [r for r in well_rows if r is not None]
        if not well_rows:
            user_vec = np.mean(X, axis=0)
        else:
            user_vec = np.mean(X[well_rows], axis=0)

        scores: List[Tuple[int, float]] = []
        for c_idx, game in enumerate(candidates):
            row_idx = self._game_index_map.get(game.get('game_id', ''))
            if row_idx is None:
                scores.append((c_idx, 0.0))
                continue
            item_vec = X[row_idx]
            dot      = float(np.dot(user_vec, item_vec))
            base     = 3.0 if game.get('playtime_forever', 0) == 0 else 1.0
            scores.append((c_idx, base + dot))
        return scores

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_genres(self, game: Dict[str, Any]) -> List[str]:
        """Return genre strings for *game* from the details cache."""
        details = self._get_details(game)
        if not details:
            return []
        return [
            e.get('description', '')
            for e in details.get('genres', [])
            if e.get('description')
        ]

    def _get_details(self, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._cache:
            return None
        app_id = game.get('appid')
        if app_id is None:
            gid = game.get('game_id', '')
            if ':' in gid:
                try:
                    app_id = int(gid.split(':')[-1])
                except (ValueError, TypeError):
                    pass
        if app_id is None:
            return None
        try:
            key = int(app_id)
        except (ValueError, TypeError):
            key = app_id
        return self._cache.get(key)

    def _reason(self, game: Dict[str, Any], method: str) -> str:
        genres = self._get_genres(game)
        parts: List[str] = []
        if game.get('playtime_forever', 0) == 0:
            parts.append('Unplayed')
        else:
            hours = game['playtime_forever'] / 60
            parts.append(f'Barely played ({hours:.1f}h)')
        if genres:
            parts.append(f'Genre match: {", ".join(genres[:2])}')
        method_label = {'cf': 'item-CF', 'mf': 'matrix factorization', 'hybrid': 'hybrid ML'}.get(method, method)
        parts.append(f'Method: {method_label}')
        return '. '.join(parts)

    # ------------------------------------------------------------------
    # Heuristic fallback (no numpy)
    # ------------------------------------------------------------------

    def _heuristic_fallback(self, count: int) -> List[Dict[str, Any]]:
        """Simple playtime-based ranker used when numpy is not available."""
        recent = set(self._history[-10:])
        candidates = [
            g for g in self._games
            if g.get('playtime_forever', 0) <= self._barely_mins
        ] or list(self._games)

        scored = []
        for game in candidates:
            score = 3.0 if game.get('playtime_forever', 0) == 0 else 1.0
            if game.get('game_id', '') in recent:
                score -= _HISTORY_PENALTY
            scored.append((game, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        result = []
        for game, score in scored[:count]:
            entry = dict(game)
            entry['ml_score']       = round(score, 3)
            entry['ml_reason']      = 'Heuristic (numpy not available)'
            entry['playtime_hours'] = round(game.get('playtime_forever', 0) / 60, 2)
            result.append(entry)
        return result
