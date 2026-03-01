/**
 * AppNavigator — bottom-tab navigation with four tabs.
 *
 * Tabs:
 *   Pick     — Quick-pick screen (home)
 *   Library  — Full game library with search/filter
 *   History  — Recent picks
 *   Settings — Server URL and preferences
 */
import React from 'react';
import {createBottomTabNavigator} from '@react-navigation/bottom-tabs';
import {Text} from 'react-native';
import PickScreen from './screens/PickScreen';
import LibraryScreen from './screens/LibraryScreen';
import HistoryScreen from './screens/HistoryScreen';
import SettingsScreen from './screens/SettingsScreen';

const Tab = createBottomTabNavigator();

function TabIcon({name, focused}: {name: string; focused: boolean}): React.JSX.Element {
  const icons: Record<string, string> = {
    Pick: '🎮',
    Library: '📚',
    History: '🕒',
    Settings: '⚙️',
  };
  return (
    <Text style={{fontSize: 20, opacity: focused ? 1 : 0.5}}>
      {icons[name] ?? '•'}
    </Text>
  );
}

export default function AppNavigator(): React.JSX.Element {
  return (
    <Tab.Navigator
      screenOptions={({route}) => ({
        headerStyle: {backgroundColor: '#0d1117'},
        headerTintColor: '#e6edf3',
        headerTitleStyle: {fontWeight: 'bold'},
        tabBarStyle: {backgroundColor: '#161b22', borderTopColor: '#30363d'},
        tabBarActiveTintColor: '#58a6ff',
        tabBarInactiveTintColor: '#8b949e',
        tabBarIcon: ({focused}) => (
          <TabIcon name={route.name} focused={focused} />
        ),
      })}>
      <Tab.Screen
        name="Pick"
        component={PickScreen}
        options={{title: 'GAPI Game Picker'}}
      />
      <Tab.Screen name="Library" component={LibraryScreen} />
      <Tab.Screen name="History" component={HistoryScreen} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>
  );
}
