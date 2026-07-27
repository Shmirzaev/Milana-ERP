import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "../constants/theme";
import type { IconName } from "../data/modules";
import { StatusBadge } from "./StatusBadge";

type Props = {
  title: string;
  subtitle?: string;
  meta?: string;
  status?: string;
  icon?: IconName;
  onPress?: () => void;
  compact?: boolean;
  mutedMeta?: boolean;
  groupPosition?: "first" | "middle" | "last" | "only";
};

export function ListRow({
  title,
  subtitle,
  meta,
  status,
  icon = "document-text-outline",
  onPress,
  compact = false,
  mutedMeta = false,
  groupPosition = "only",
}: Props) {
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : undefined}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        compact && styles.compactRow,
        groupPosition === "first" && styles.groupFirst,
        groupPosition === "middle" && styles.groupMiddle,
        groupPosition === "last" && styles.groupLast,
        pressed && onPress && styles.pressed,
      ]}
    >
      <View style={[styles.iconBox, compact && styles.compactIconBox]}>
        <Ionicons name={icon} size={compact ? 18 : 20} color={colors.accent} />
      </View>
      <View style={styles.content}>
        <View style={styles.titleLine}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {status ? <StatusBadge value={status} /> : null}
        </View>
        {subtitle ? (
          <Text style={styles.subtitle} numberOfLines={2}>
            {subtitle}
          </Text>
        ) : null}
        {meta ? (
          <Text style={[styles.meta, mutedMeta && styles.mutedMeta]} numberOfLines={1}>
            {meta}
          </Text>
        ) : null}
      </View>
      {onPress ? <Ionicons name="chevron-forward" size={18} color={colors.tertiaryLabel} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: {
    flex: 1,
    minWidth: 0,
  },
  iconBox: {
    alignItems: "center",
    backgroundColor: colors.primaryMuted,
    borderRadius: radii.sm,
    height: 40,
    justifyContent: "center",
    width: 40,
  },
  compactIconBox: {
    height: 36,
    width: 36,
  },
  compactRow: {
    minHeight: 72,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  meta: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    marginTop: spacing.xs,
  },
  pressed: {
    backgroundColor: colors.surfaceHover,
  },
  row: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radii.lg,
    flexDirection: "row",
    gap: spacing.md,
    padding: spacing.md,
  },
  groupFirst: {
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  groupLast: {
    borderTopLeftRadius: 0,
    borderTopRightRadius: 0,
    borderTopWidth: 0,
  },
  groupMiddle: {
    borderRadius: 0,
    borderTopWidth: 0,
  },
  subtitle: {
    color: colors.secondaryLabel,
    fontSize: 13,
    lineHeight: 19,
    marginTop: spacing.xs,
  },
  title: {
    color: colors.label,
    flex: 1,
    fontSize: 14,
    fontWeight: "600",
  },
  titleLine: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  mutedMeta: {
    color: colors.tertiaryLabel,
    fontSize: 11,
  },
});
