/**
 * LibraryScreen — browse and search the full game library.
 *
 * Features:
 *   • Real-time search (debounced 300ms)
 *   • Platform filter (All / Steam / Epic / GOG / Xbox / PSN / Nintendo)
 *   • FlatList with pull-to-refresh
 *   • Each row shows name, platform badge, and formatted playtime
 */
import React, {useState, useEffect, useCallback, useRef} from 'react';
import {
  View,
  Text,
  TextInput,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useGapiApi, Game} from '../hooks/useGapiApi';
import PlatformBadge from '../components/PlatformBadge';
import {formatPlaytime} from '../utils/formatters';

const PLATFORMS = ['all', 'steam', 'epic', 'gog', 'xbox', 'psn', 'nintendo'];

export default function LibraryScreen(): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const {getLibrary, loading} = useGapiApi();

  const [games, setGames] = useState<Game[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('all');
  const [refreshing, setRefreshing] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadGames = useCallback(
    async (q: string, p: string) => {
      const result = await getLibrary(q, p);
      setGames(result.games);
      setTotal(result.total);
    },
    [getLibrary],
  );

  // Initial load
  useEffect(() => {
    loadGames(search, platform);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      loadGames(search, platform);
    }, 300);
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [search, platform, loadGames]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadGames(search, platform);
    setRefreshing(false);
  }, [loadGames, search, platform]);

  const renderGame = useCallback(
    ({item}: {item: Game}) => (
      <View style={styles.row}>
        <View style={styles.rowLeft}>
          <Text style={styles.gameName} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={styles.gamePlay}>
            {formatPlaytime(item.playtime_forever)}
          </Text>
        </View>
        <PlatformBadge platform={item.platform} small />
      </View>
    ),
    [],
  );

  return (
    <View
      style={[
        styles.container,
        {paddingTop: 8, paddingBottom: insets.bottom},
      ]}>
      {/* Search bar */}
      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search games…"
          placeholderTextColor="#484f58"
          value={search}
          onChangeText={setSearch}
          autoCorrect={false}
          clearButtonMode="while-editing"
          accessibilityLabel="Search games"
        />
      </View>

      {/* Platform filter chips */}
      <FlatList
        data={PLATFORMS}
        horizontal
        showsHorizontalScrollIndicator={false}
        keyExtractor={item => item}
        style={styles.filterRow}
        renderItem={({item}) => (
          <TouchableOpacity
            style={[
              styles.chip,
              platform === item && styles.chipActive,
            ]}
            onPress={() => setPlatform(item)}
            accessibilityRole="button"
            accessibilityState={{selected: platform === item}}>
            <Text
              style={[
                styles.chipText,
                platform === item && styles.chipTextActive,
              ]}>
              {item === 'all' ? 'All' : item.toUpperCase()}
            </Text>
          </TouchableOpacity>
        )}
      />

      {/* Game count */}
      <Text style={styles.countText}>
        {loading
          ? 'Loading…'
          : `${total.toLocaleString()} game${total !== 1 ? 's' : ''}`}
      </Text>

      {/* Game list */}
      {loading && games.length === 0 ? (
        <ActivityIndicator color="#58a6ff" style={styles.spinner} />
      ) : (
        <FlatList
          data={games}
          keyExtractor={item => item.game_id}
          renderItem={renderGame}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor="#58a6ff"
            />
          }
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          ListEmptyComponent={
            <Text style={styles.emptyText}>No games found.</Text>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0d1117'},
  searchRow: {paddingHorizontal: 16, paddingVertical: 8},
  searchInput: {
    backgroundColor: '#161b22',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
    color: '#e6edf3',
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
  },
  filterRow: {paddingHorizontal: 12, paddingBottom: 4},
  chip: {
    paddingVertical: 5,
    paddingHorizontal: 12,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#161b22',
    marginRight: 8,
    marginVertical: 4,
  },
  chipActive: {borderColor: '#58a6ff', backgroundColor: '#1c2433'},
  chipText: {color: '#8b949e', fontSize: 12},
  chipTextActive: {color: '#58a6ff', fontWeight: '700'},
  countText: {
    color: '#6e7681',
    fontSize: 12,
    paddingHorizontal: 16,
    paddingBottom: 4,
  },
  spinner: {marginTop: 40},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  rowLeft: {flex: 1, marginRight: 8},
  gameName: {color: '#e6edf3', fontSize: 15, fontWeight: '500'},
  gamePlay: {color: '#8b949e', fontSize: 12, marginTop: 2},
  separator: {height: 1, backgroundColor: '#21262d', marginHorizontal: 16},
  emptyText: {
    textAlign: 'center',
    color: '#8b949e',
    marginTop: 40,
    fontSize: 14,
  },
});
