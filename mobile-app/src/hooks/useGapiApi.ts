/**
 * useGapiApi — central hook for all GAPI REST API calls.
 *
 * Reads the server URL from ServerConfigContext and exposes typed
 * wrappers for every endpoint used by the app.
 */
import {useCallback, useState} from 'react';
import {useServerConfig} from '../context/ServerConfigContext';

export interface Game {
  name: string;
  appid: string | number;
  game_id: string;
  platform: string;
  playtime_forever: number;
  img_icon_url?: string;
  tags?: string[];
  genres?: {description: string}[];
}

export interface PickResult {
  game: Game | null;
  reason?: string;
  error?: string;
}

export interface LibraryResult {
  games: Game[];
  total: number;
  error?: string;
}

export interface HistoryEntry {
  id: number;
  game_name: string;
  game_id: string;
  platform: string;
  picked_at: string;
  playtime_at_pick?: number;
}

/** Mode passed to POST /api/pick */
export type PickMode = 'random' | 'unplayed' | 'barely_played';

export function useGapiApi() {
  const {serverUrl} = useServerConfig();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const _fetch = useCallback(
    async <T>(path: string, options?: RequestInit): Promise<T | null> => {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(`${serverUrl}${path}`, {
          headers: {'Content-Type': 'application/json'},
          credentials: 'include',
          ...options,
        });
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(
            (data as {error?: string}).error ?? `HTTP ${resp.status}`,
          );
        }
        return data as T;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [serverUrl],
  );

  /** POST /api/pick — pick a random game */
  const pickGame = useCallback(
    async (mode: PickMode = 'random'): Promise<PickResult> => {
      const data = await _fetch<{game: Game; reason?: string}>('/api/pick', {
        method: 'POST',
        body: JSON.stringify({mode}),
      });
      if (!data) {
        return {game: null, error: error ?? 'Unknown error'};
      }
      return {game: data.game, reason: data.reason};
    },
    [_fetch, error],
  );

  /** GET /api/library — full game library */
  const getLibrary = useCallback(
    async (
      search?: string,
      platform?: string,
    ): Promise<LibraryResult> => {
      const params = new URLSearchParams();
      if (search) {
        params.set('search', search);
      }
      if (platform && platform !== 'all') {
        params.set('platform', platform);
      }
      const qs = params.toString() ? `?${params.toString()}` : '';
      const data = await _fetch<{games: Game[]; total: number}>(
        `/api/library${qs}`,
      );
      if (!data) {
        return {games: [], total: 0, error: error ?? 'Unknown error'};
      }
      return {games: data.games ?? [], total: data.total ?? 0};
    },
    [_fetch, error],
  );

  /** GET /api/history — recent picks */
  const getHistory = useCallback(async (): Promise<HistoryEntry[]> => {
    const data = await _fetch<{history: HistoryEntry[]}>('/api/history');
    return data?.history ?? [];
  }, [_fetch]);

  return {pickGame, getLibrary, getHistory, loading, error};
}
