import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "../constants/theme";

type Props = {
  label: string;
  value: string;
  detail?: string;
};

export function MetricTile({ label, value, detail }: Props) {
  return (
    <View style={styles.tile}>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
      <Text style={styles.value} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      {detail ? (
        <Text style={styles.detail} numberOfLines={1}>
          {detail}
        </Text>
      ) : null}
      <View style={styles.rule} />
    </View>
  );
}

const styles = StyleSheet.create({
  detail: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    marginTop: spacing.xs,
  },
  label: {
    color: colors.tertiaryLabel,
    fontSize: 11,
    fontWeight: "600",
  },
  rule: {
    backgroundColor: colors.accent,
    bottom: 0,
    height: 3,
    left: 0,
    position: "absolute",
    right: 0,
  },
  tile: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radii.lg,
    flex: 1,
    overflow: "hidden",
    minHeight: 96,
    padding: spacing.lg,
  },
  value: {
    color: colors.label,
    fontSize: 24,
    fontWeight: "700",
    marginTop: spacing.sm,
  },
});
