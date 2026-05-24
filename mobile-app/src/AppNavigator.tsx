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
import {StyleSheet, Text, View} from 'react-native';
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
    <View style={[styles.tabIconWrap, focused && styles.tabIconWrapFocused]}>
      <Text style={[styles.tabIcon, !focused && styles.tabIconInactive]}>
        {icons[name] ?? '•'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    backgroundColor: '#1e1f22',
  },
  headerTitle: {
    fontWeight: '700',
  },
  tabBar: {
    backgroundColor: '#2b2d31',
    borderTopColor: 'transparent',
    height: 72,
    paddingTop: 8,
    paddingBottom: 10,
    paddingHorizontal: 10,
    elevation: 0,
    shadowColor: '#000000',
    shadowOpacity: 0.18,
    shadowRadius: 16,
    shadowOffset: {width: 0, height: -6},
  },
  tabBarItem: {
    marginHorizontal: 4,
    marginVertical: 6,
    borderRadius: 18,
  },
  tabBarLabel: {
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 4,
  },
  tabIconWrap: {
    minWidth: 40,
    height: 34,
    paddingHorizontal: 10,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
  },
  tabIconWrapFocused: {
    backgroundColor: 'rgba(88, 101, 242, 0.16)',
  },
  tabIcon: {
    fontSize: 18,
    opacity: 1,
  },
  tabIconInactive: {
    opacity: 0.72,
  },
});

export default function AppNavigator(): React.JSX.Element {
  return (
    <Tab.Navigator
      screenOptions={({route}) => ({
        headerStyle: styles.header,
        headerTintColor: '#f2f3f5',
        headerTitleStyle: styles.headerTitle,
        tabBarStyle: styles.tabBar,
        tabBarItemStyle: styles.tabBarItem,
        tabBarActiveBackgroundColor: 'rgba(88, 101, 242, 0.12)',
        tabBarActiveTintColor: '#f2f3f5',
        tabBarInactiveTintColor: '#949ba4',
        tabBarLabelStyle: styles.tabBarLabel,
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
