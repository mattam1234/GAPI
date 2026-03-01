/**
 * SettingsScreen — configure GAPI server URL and check connectivity.
 */
import React, {useState} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  ScrollView,
  Linking,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useServerConfig} from '../context/ServerConfigContext';

export default function SettingsScreen(): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const {serverUrl, setServerUrl, isConnected, checkConnection} =
    useServerConfig();

  const [urlDraft, setUrlDraft] = useState(serverUrl);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    await setServerUrl(urlDraft);
    await checkConnection();
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleOpenBrowser = async () => {
    const url = serverUrl;
    const supported = await Linking.canOpenURL(url);
    if (supported) {
      await Linking.openURL(url);
    } else {
      Alert.alert('Cannot open URL', `Cannot open: ${url}`);
    }
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[
        styles.content,
        {paddingBottom: insets.bottom + 24},
      ]}>
      <Text style={styles.sectionTitle}>Server Connection</Text>

      {/* Status */}
      <View style={styles.statusRow}>
        <View
          style={[
            styles.statusDot,
            isConnected ? styles.online : styles.offline,
          ]}
        />
        <Text style={styles.statusText}>
          {isConnected
            ? `Connected to ${serverUrl}`
            : 'Not connected'}
        </Text>
      </View>

      {/* Server URL input */}
      <Text style={styles.label}>GAPI Server URL</Text>
      <TextInput
        style={styles.input}
        value={urlDraft}
        onChangeText={setUrlDraft}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder="http://localhost:5000"
        placeholderTextColor="#484f58"
        accessibilityLabel="GAPI Server URL"
      />
      <Text style={styles.hint}>
        The URL of your running GAPI web server.
      </Text>

      <TouchableOpacity
        style={styles.saveBtn}
        onPress={handleSave}
        accessibilityRole="button"
        accessibilityLabel="Save server URL">
        <Text style={styles.saveBtnText}>
          {saved ? '✓ Saved!' : 'Save & Test Connection'}
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.testBtn}
        onPress={checkConnection}
        accessibilityRole="button"
        accessibilityLabel="Test connection">
        <Text style={styles.testBtnText}>⟳  Re-test Connection</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.openBtn}
        onPress={handleOpenBrowser}
        accessibilityRole="link"
        accessibilityLabel="Open GAPI in browser">
        <Text style={styles.openBtnText}>Open GAPI in Browser ↗</Text>
      </TouchableOpacity>

      {/* App info */}
      <View style={styles.divider} />
      <Text style={styles.sectionTitle}>About</Text>
      <Text style={styles.aboutText}>
        GAPI Game Picker{'\n'}
        Version 1.0.0{'\n\n'}
        A companion app for the GAPI random game picker.{'\n'}
        Visit github.com/mattam1234/GAPI for more information.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0d1117'},
  content: {padding: 20},
  sectionTitle: {
    color: '#e6edf3',
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 12,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 20,
    backgroundColor: '#161b22',
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: '#30363d',
  },
  statusDot: {width: 10, height: 10, borderRadius: 5, marginRight: 10},
  online: {backgroundColor: '#3fb950'},
  offline: {backgroundColor: '#f85149'},
  statusText: {color: '#8b949e', fontSize: 13, flex: 1},
  label: {color: '#8b949e', fontSize: 12, marginBottom: 6},
  input: {
    backgroundColor: '#161b22',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
    color: '#e6edf3',
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    marginBottom: 6,
  },
  hint: {color: '#6e7681', fontSize: 11, marginBottom: 16},
  saveBtn: {
    backgroundColor: '#238636',
    borderRadius: 8,
    paddingVertical: 13,
    alignItems: 'center',
    marginBottom: 10,
  },
  saveBtnText: {color: '#fff', fontSize: 15, fontWeight: '700'},
  testBtn: {
    backgroundColor: '#21262d',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#30363d',
    paddingVertical: 11,
    alignItems: 'center',
    marginBottom: 10,
  },
  testBtnText: {color: '#8b949e', fontSize: 14},
  openBtn: {alignItems: 'center', paddingVertical: 10},
  openBtnText: {color: '#58a6ff', fontSize: 13},
  divider: {
    height: 1,
    backgroundColor: '#30363d',
    marginVertical: 24,
  },
  aboutText: {color: '#8b949e', fontSize: 13, lineHeight: 20},
});
