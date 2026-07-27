import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "../constants/theme";
import type { Entity } from "../types/api";
import { formatValue, humanizeKey } from "../utils/format";

type Props = {
  entity: Entity;
};

const hiddenKeys = new Set(["id", "password", "password_hash", "qr_code_url"]);

export function FieldList({ entity }: Props) {
  const entries = Object.entries(entity).filter(([key, value]) => {
    if (hiddenKeys.has(key)) return false;
    if (value === null || value === undefined || value === "") return false;
    if (typeof value === "object" && !Array.isArray(value)) return false;
    return true;
  });

  return (
    <View style={styles.card}>
      {entries.map(([key, value], index) => (
        <View key={key} style={[styles.row, index > 0 && styles.border]}>
          <Text style={styles.key}>{humanizeKey(key)}</Text>
          <Text style={styles.value} numberOfLines={3}>
            {formatValue(value)}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  border: {
    borderTopColor: colors.separator,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radii.lg,
    overflow: "hidden",
  },
  key: {
    color: colors.secondaryLabel,
    flex: 1,
    fontSize: 14,
  },
  row: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.md,
    minHeight: 48,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  value: {
    color: colors.label,
    flex: 1.3,
    fontSize: 14,
    fontWeight: "500",
    textAlign: "right",
  },
});
