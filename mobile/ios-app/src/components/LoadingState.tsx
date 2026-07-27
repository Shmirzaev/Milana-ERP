import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "../constants/theme";

type Props = {
  label?: string;
};

export function LoadingState({ label = "Loading" }: Props) {
  return (
    <View style={styles.container}>
      <ActivityIndicator color={colors.primary} />
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    backgroundColor: colors.background,
    flex: 1,
    justifyContent: "center",
    padding: spacing.xxl,
  },
  label: {
    color: colors.secondaryLabel,
    fontSize: 14,
    marginTop: spacing.md,
  },
});
