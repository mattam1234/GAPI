/**
 * GameCard — displays a picked game with name, platform, and playtime.
 */
import React from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {Game} from '../hooks/useGapiApi';
import PlatformBadge from './PlatformBadge';
import {formatPlaytime} from '../utils/formatters';

interface Props {
  game: Game;
  reason?: string;
}

export default function GameCard({game, reason}: Props): React.JSX.Element {
  return (
    <View style={styles.card}>
      <View style={styles.topRow}>
        <Text style={styles.name} numberOfLines={2}>
          {game.name}
        </Text>
        <PlatformBadge platform={game.platform} />
      </View>

      <Text style={styles.playtime}>
        {formatPlaytime(game.playtime_forever)}
      </Text>

      {reason ? (
        <View style={styles.reasonBox}>
          <Text style={styles.reasonText}>💡 {reason}</Text>
        </View>
      ) : null}

      {game.genres && game.genres.length > 0 && (
        <View style={styles.genreRow}>
          {game.genres.slice(0, 4).map(g => (
            <View key={g.description} style={styles.genreChip}>
              <Text style={styles.genreText}>{g.description}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#161b22',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#30363d',
    padding: 16,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  name: {
    color: '#e6edf3',
    fontSize: 20,
    fontWeight: '700',
    flex: 1,
    marginRight: 8,
  },
  playtime: {
    color: '#8b949e',
    fontSize: 13,
    marginBottom: 10,
  },
  reasonBox: {
    backgroundColor: '#1c2433',
    borderRadius: 6,
    padding: 10,
    marginBottom: 10,
  },
  reasonText: {color: '#79c0ff', fontSize: 13},
  genreRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 6},
  genreChip: {
    backgroundColor: '#21262d',
    borderRadius: 12,
    paddingVertical: 3,
    paddingHorizontal: 10,
  },
  genreText: {color: '#8b949e', fontSize: 11},
});
