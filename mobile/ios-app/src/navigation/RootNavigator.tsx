import { Ionicons } from "@expo/vector-icons";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { Platform } from "react-native";

import { useAuth } from "../auth/AuthContext";
import { colors } from "../constants/theme";
import { AlertsScreen } from "../screens/AlertsScreen";
import { DashboardScreen } from "../screens/DashboardScreen";
import { DetailScreen } from "../screens/DetailScreen";
import { LoadingState } from "../components/LoadingState";
import { LoginScreen } from "../screens/LoginScreen";
import { ModuleListScreen } from "../screens/ModuleListScreen";
import { ModulesScreen } from "../screens/ModulesScreen";
import { ProfileScreen } from "../screens/ProfileScreen";
import { ScanScreen } from "../screens/ScanScreen";
import { getModule } from "../data/modules";
import type { MainTabParamList, RootStackParamList } from "../types/navigation";

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<MainTabParamList>();

const navigationTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: colors.background,
    card: colors.card,
    primary: colors.primary,
    text: colors.label,
    border: colors.separator,
  },
};

function MainTabs() {
  return (
    <Tabs.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: colors.card },
        headerShadowVisible: false,
        headerTitleStyle: {
          color: colors.label,
          fontSize: 17,
          fontWeight: "700",
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.secondaryLabel,
        tabBarItemStyle: Platform.select({
          web: { outlineStyle: "none" } as any,
          default: undefined,
        }),
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: "600",
        },
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.separator,
          height: Platform.select({ web: 64, default: undefined }),
          paddingTop: 4,
        },
        tabBarIcon: ({ color, focused, size }) => {
          const icons: Record<keyof MainTabParamList, [keyof typeof Ionicons.glyphMap, keyof typeof Ionicons.glyphMap]> = {
            Dashboard: ["bar-chart", "bar-chart-outline"],
            Modules: ["grid", "grid-outline"],
            Scan: ["scan", "scan-outline"],
            Alerts: ["notifications", "notifications-outline"],
            Profile: ["person", "person-outline"],
          };
          return <Ionicons name={icons[route.name][focused ? 0 : 1]} size={size} color={color} />;
        },
      })}
    >
      <Tabs.Screen name="Dashboard" component={DashboardScreen} />
      <Tabs.Screen name="Modules" component={ModulesScreen} />
      <Tabs.Screen name="Scan" component={ScanScreen} options={{ title: "Scanner" }} />
      <Tabs.Screen name="Alerts" component={AlertsScreen} />
      <Tabs.Screen name="Profile" component={ProfileScreen} />
    </Tabs.Navigator>
  );
}

export function RootNavigator() {
  const { bootstrapping, token } = useAuth();

  if (bootstrapping) return <LoadingState label="Opening Milana ERP" />;

  return (
    <NavigationContainer theme={navigationTheme}>
      <Stack.Navigator>
        {token ? (
          <>
            <Stack.Screen name="MainTabs" component={MainTabs} options={{ headerShown: false }} />
            <Stack.Screen name="ModuleList" component={ModuleListScreen} options={({ route }) => ({ title: getModule(route.params.moduleId).title })} />
            <Stack.Screen name="Detail" component={DetailScreen} options={({ route }) => ({ title: route.params.title })} />
          </>
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
