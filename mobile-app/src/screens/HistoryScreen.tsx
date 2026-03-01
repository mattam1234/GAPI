/**
 * HistoryScreen — list of recent game picks.
 *
 * Displays game name, platform, pick time, and playtime at time of pick.
 * Pull-to-refresh support.
 */
import React, {useState, useCallback, useEffect} from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useGapiApi, HistoryEntry} from '../hooks/useGapiApi';
import PlatformBadge from '../components/PlatformBadge';
import {formatPlaytime, formatRelativeTime} from '../utils/formatters';

export default function HistoryScreen(): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const {getHistory, loading} = useGapiApi();
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadHistory = useCallback(async () => {
    const data = await getHistory();
    setHistory(data);
  }, [getHistory]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadHistory();
    setRefreshing(false);
  }, [loadHistory]);

  const renderItem = useCallback(
    ({item, index}: {item: HistoryEntry; index: number}) => (
      <View style={styles.row}>
        <View style={styles.indexBadge}>
          <Text style={styles.indexText}>{index + 1}</Text>
        </View>
        <View style={styles.rowMid}>
          <Text style={styles.gameName} numberOfLines={1}>
            {item.game_name}
          </Text>
          <Text style={styles.meta}>
            {formatRelativeTime(item.picked_at)}
            {item.playtime_at_pick != null
              ? `  ·  ${formatPlaytime(item.playtime_at_pick)}`
              : ''}
          </Text>
        </View>
        <PlatformBadge platform={item.platform} small />
      </View>
    ),
    [],
  );

  return (
    <View
      style={[styles.container, {paddingBottom: insets.bottom}]}>
      <Text style={styles.header}>Recent Picks</Text>
      {loading && history.length === 0 ? (
        <ActivityIndicator color="#58a6ff" style={styles.spinner} />
      ) : (
        <FlatList
          data={history}
          keyExtractor={item => String(item.id)}
          renderItem={renderItem}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor="#58a6ff"
            />
          }
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          ListEmptyComponent={
            <Text style={styles.emptyText}>No picks yet.</Text>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0d1117'},
  header: {
    color: '#e6edf3',
    fontSize: 18,
    fontWeight: '700',
    padding: 16,
    paddingBottom: 8,
  },
  spinner: {marginTop: 40},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  indexBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#21262d',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  indexText: {color: '#8b949e', fontSize: 12, fontWeight: '700'},
  rowMid: {flex: 1, marginRight: 8},
  gameName: {color: '#e6edf3', fontSize: 15, fontWeight: '500'},
  meta: {color: '#8b949e', fontSize: 12, marginTop: 2},
  separator: {height: 1, backgroundColor: '#21262d', marginHorizontal: 16},
  emptyText: {
    textAlign: 'center',
    color: '#8b949e',
    marginTop: 40,
    fontSize: 14,
  },
});
