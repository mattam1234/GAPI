/**
 * PickScreen — main "Pick a Game" screen.
 *
 * Shows the currently picked game (name, platform badge, playtime) with a
 * large Pick button.  Supports three modes via a segmented picker:
 *   Random | Unplayed | Barely Played
 */
import React, {useState, useCallback} from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  Alert,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useGapiApi, Game, PickMode} from '../hooks/useGapiApi';
import {useServerConfig} from '../context/ServerConfigContext';
import GameCard from '../components/GameCard';
import PlatformBadge from '../components/PlatformBadge';

const MODES: {label: string; value: PickMode}[] = [
  {label: '🎲 Random', value: 'random'},
  {label: '🆕 Unplayed', value: 'unplayed'},
  {label: '⏱ Barely Played', value: 'barely_played'},
];

export default function PickScreen(): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const {isConnected, checkConnection} = useServerConfig();
  const {pickGame, loading, error} = useGapiApi();

  const [pickedGame, setPickedGame] = useState<Game | null>(null);
  const [reason, setReason] = useState<string>('');
  const [mode, setMode] = useState<PickMode>('random');

  const handlePick = useCallback(async () => {
    if (!isConnected) {
      await checkConnection();
    }
    const result = await pickGame(mode);
    if (result.game) {
      setPickedGame(result.game);
      setReason(result.reason ?? '');
    } else if (result.error) {
      Alert.alert('Could not pick a game', result.error);
    }
  }, [pickGame, mode, isConnected, checkConnection]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[
        styles.content,
        {paddingBottom: insets.bottom + 16},
      ]}>
      {/* Connection status */}
      <View style={styles.statusRow}>
        <View
          style={[
            styles.statusDot,
            isConnected ? styles.online : styles.offline,
          ]}
        />
        <Text style={styles.statusText}>
          {isConnected ? 'Connected to GAPI' : 'Not connected — check Settings'}
        </Text>
      </View>

      {/* Mode selector */}
      <View style={styles.modeRow}>
        {MODES.map(m => (
          <TouchableOpacity
            key={m.value}
            style={[
              styles.modeBtn,
              mode === m.value && styles.modeBtnActive,
            ]}
            onPress={() => setMode(m.value)}
            accessibilityRole="button"
            accessibilityState={{selected: mode === m.value}}>
            <Text
              style={[
                styles.modeBtnText,
                mode === m.value && styles.modeBtnTextActive,
              ]}>
              {m.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Game card area */}
      <View style={styles.cardArea}>
        {pickedGame ? (
          <GameCard game={pickedGame} reason={reason} />
        ) : (
          <View style={styles.placeholder}>
            <Text style={styles.placeholderEmoji}>🎮</Text>
            <Text style={styles.placeholderText}>
              Tap "Pick a Game" to get started!
            </Text>
          </View>
        )}
      </View>

      {/* Error message */}
      {error && !loading && (
        <Text style={styles.errorText}>{error}</Text>
      )}

      {/* Action buttons */}
      <TouchableOpacity
        style={[styles.pickBtn, loading && styles.pickBtnDisabled]}
        onPress={handlePick}
        disabled={loading}
        accessibilityRole="button"
        accessibilityLabel="Pick a Game">
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.pickBtnText}>🎮  Pick a Game</Text>
        )}
      </TouchableOpacity>

      {pickedGame && (
        <View style={styles.secondaryBtns}>
          <TouchableOpacity
            style={styles.secondaryBtn}
            onPress={handlePick}
            disabled={loading}
            accessibilityRole="button"
            accessibilityLabel="Reroll">
            <Text style={styles.secondaryBtnText}>↺  Reroll</Text>
          </TouchableOpacity>
          <PlatformBadge platform={pickedGame.platform} />
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0d1117'},
  content: {padding: 20},
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  statusDot: {width: 10, height: 10, borderRadius: 5, marginRight: 8},
  online: {backgroundColor: '#3fb950'},
  offline: {backgroundColor: '#f85149'},
  statusText: {color: '#8b949e', fontSize: 13},
  modeRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 20,
  },
  modeBtn: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#161b22',
    alignItems: 'center',
  },
  modeBtnActive: {
    borderColor: '#58a6ff',
    backgroundColor: '#1c2433',
  },
  modeBtnText: {
    color: '#8b949e',
    fontSize: 12,
    textAlign: 'center',
  },
  modeBtnTextActive: {color: '#58a6ff', fontWeight: '700'},
  cardArea: {
    minHeight: 160,
    justifyContent: 'center',
    marginBottom: 20,
  },
  placeholder: {alignItems: 'center', paddingVertical: 40},
  placeholderEmoji: {fontSize: 48, marginBottom: 12},
  placeholderText: {color: '#8b949e', fontSize: 15, textAlign: 'center'},
  errorText: {
    color: '#f85149',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 12,
  },
  pickBtn: {
    backgroundColor: '#238636',
    borderRadius: 10,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  pickBtnDisabled: {backgroundColor: '#21262d'},
  pickBtnText: {color: '#fff', fontSize: 18, fontWeight: '700'},
  secondaryBtns: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  secondaryBtn: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
    backgroundColor: '#161b22',
  },
  secondaryBtnText: {color: '#e6edf3', fontSize: 15},
});
