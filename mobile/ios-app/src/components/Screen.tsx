import { PropsWithChildren } from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "../constants/theme";

type Props = PropsWithChildren<{
  scroll?: boolean;
  onRefresh?: () => void;
  padded?: boolean;
  refreshing?: boolean;
}>;

export function Screen({ children, onRefresh, padded = true, refreshing = false, scroll = true }: Props) {
  if (!scroll) {
    return (
      <SafeAreaView edges={["left", "right"]} style={styles.safe}>
        <View style={[styles.content, !padded && styles.noPadding]}>{children}</View>
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView edges={["left", "right"]} style={styles.safe}>
      <ScrollView
        contentContainerStyle={[styles.content, !padded && styles.noPadding]}
        keyboardShouldPersistTaps="handled"
        refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    gap: spacing.lg,
    maxWidth: "100%",
    padding: spacing.lg,
    width: "100%",
  },
  noPadding: {
    padding: 0,
  },
  safe: {
    backgroundColor: colors.background,
    flex: 1,
    maxWidth: "100%",
    overflow: "hidden",
    width: "100%",
  },
});
