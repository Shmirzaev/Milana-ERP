import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "../constants/theme";

type Props = {
  value: string;
};

function tone(value: string) {
  const normalized = value.toLowerCase();
  if (["done", "delivered", "approved", "received_in_storage", "received_sewing"].includes(normalized)) {
    return { backgroundColor: colors.successMuted, color: colors.success };
  }
  if (["blocked", "damaged", "cancelled", "rejected"].includes(normalized)) {
    return { backgroundColor: colors.dangerMuted, color: colors.danger };
  }
  if (["waiting_material", "pending", "planning", "reserved"].includes(normalized)) {
    return { backgroundColor: colors.warningMuted, color: colors.warning };
  }
  return { backgroundColor: colors.infoMuted, color: colors.info };
}

export function StatusBadge({ value }: Props) {
  const style = tone(value);
  return (
    <View style={[styles.badge, { backgroundColor: style.backgroundColor, borderColor: style.color }]}>
      <Text style={[styles.text, { color: style.color }]} numberOfLines={1}>
        {value.replace(/_/g, " ")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: radii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    maxWidth: 130,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  text: {
    fontSize: 11,
    fontWeight: "600",
  },
});
