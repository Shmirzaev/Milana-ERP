import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "../constants/theme";
import type { IconName } from "../data/modules";

type Props = {
  icon?: IconName;
  title: string;
  message?: string;
};

export function EmptyState({ icon = "file-tray-outline", title, message }: Props) {
  return (
    <View style={styles.container}>
      <Ionicons name={icon} size={28} color={colors.accent} />
      <Text style={styles.title}>{title}</Text>
      {message ? <Text style={styles.message}>{message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xxl,
  },
  message: {
    color: colors.secondaryLabel,
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  title: {
    color: colors.label,
    fontSize: 16,
    fontWeight: "600",
    marginTop: spacing.md,
    textAlign: "center",
  },
});
