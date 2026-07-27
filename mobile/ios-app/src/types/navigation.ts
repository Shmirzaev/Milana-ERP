import type { NavigatorScreenParams } from "@react-navigation/native";

import type { ModuleId } from "../data/modules";

export type MainTabParamList = {
  Dashboard: undefined;
  Modules: undefined;
  Scan: undefined;
  Alerts: undefined;
  Profile: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  MainTabs: NavigatorScreenParams<MainTabParamList> | undefined;
  ModuleList: { moduleId: ModuleId };
  Detail: { title: string; endpoint?: string; moduleId?: ModuleId; initialData?: Record<string, unknown> };
};
