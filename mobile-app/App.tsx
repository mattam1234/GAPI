/**
 * GAPI Mobile App — Root entry point
 *
 * React Native application wrapping the NavigationContainer and global
 * ServerConfig context so every screen can reach the configured GAPI server.
 */
import React from 'react';
import {NavigationContainer} from '@react-navigation/native';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {ServerConfigProvider} from './src/context/ServerConfigContext';
import AppNavigator from './src/AppNavigator';

export default function App(): React.JSX.Element {
  return (
    <SafeAreaProvider>
      <ServerConfigProvider>
        <NavigationContainer>
          <AppNavigator />
        </NavigationContainer>
      </ServerConfigProvider>
    </SafeAreaProvider>
  );
}
