/**
 * PlatformBadge — small coloured label showing the game's platform.
 */
import React from 'react';
import {View, Text, StyleSheet} from 'react-native';

interface Props {
  platform: string;
  small?: boolean;
}

const PLATFORM_COLORS: Record<string, {bg: string; text: string; label: string}> = {
  steam:    {bg: '#1b2838', text: '#c7d5e0', label: 'STEAM'},
  epic:     {bg: '#2d2d2d', text: '#ffffff', label: 'EPIC'},
  gog:      {bg: '#8b008b', text: '#ffffff', label: 'GOG'},
  xbox:     {bg: '#107c10', text: '#ffffff', label: 'XBOX'},
  psn:      {bg: '#003087', text: '#ffffff', label: 'PSN'},
  nintendo: {bg: '#e4000f', text: '#ffffff', label: 'NSW'},
};

const DEFAULT_PLATFORM = {bg: '#21262d', text: '#8b949e', label: ''};

export default function PlatformBadge({platform, small = false}: Props): React.JSX.Element {
  const key = (platform ?? '').toLowerCase();
  const config = PLATFORM_COLORS[key] ?? {
    ...DEFAULT_PLATFORM,
    label: platform?.toUpperCase() ?? '?',
  };

  return (
    <View
      style={[
        styles.badge,
        {backgroundColor: config.bg},
        small && styles.badgeSmall,
      ]}>
      <Text
        style={[
          styles.text,
          {color: config.text},
          small && styles.textSmall,
        ]}>
        {config.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  badgeSmall: {paddingHorizontal: 6, paddingVertical: 2},
  text: {fontSize: 11, fontWeight: '700', letterSpacing: 0.5},
  textSmall: {fontSize: 10},
});
