/**
 * ServerConfigContext — stores and persists the GAPI server URL across
 * app sessions using AsyncStorage.
 */
import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = '@gapi_server_url';
const DEFAULT_URL = 'http://localhost:5000';

interface ServerConfig {
  serverUrl: string;
  setServerUrl: (url: string) => Promise<void>;
  isConnected: boolean;
  checkConnection: () => Promise<void>;
}

const ServerConfigContext = createContext<ServerConfig>({
  serverUrl: DEFAULT_URL,
  setServerUrl: async () => {},
  isConnected: false,
  checkConnection: async () => {},
});

export function ServerConfigProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const [serverUrl, _setServerUrl] = useState<string>(DEFAULT_URL);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  // Load persisted URL on mount
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then(stored => {
      if (stored) {
        _setServerUrl(stored);
      }
    });
  }, []);

  // Check connection whenever URL changes
  useEffect(() => {
    checkConnection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverUrl]);

  const checkConnection = useCallback(async () => {
    try {
      const resp = await fetch(`${serverUrl}/api/health`, {
        cache: 'no-store',
      });
      setIsConnected(resp.ok);
    } catch {
      setIsConnected(false);
    }
  }, [serverUrl]);

  const setServerUrl = useCallback(
    async (url: string) => {
      const trimmed = url.trim().replace(/\/$/, '') || DEFAULT_URL;
      _setServerUrl(trimmed);
      await AsyncStorage.setItem(STORAGE_KEY, trimmed);
      setIsConnected(false);
      // Re-check after setting
    },
    [],
  );

  return (
    <ServerConfigContext.Provider
      value={{serverUrl, setServerUrl, isConnected, checkConnection}}>
      {children}
    </ServerConfigContext.Provider>
  );
}

export function useServerConfig(): ServerConfig {
  return useContext(ServerConfigContext);
}
