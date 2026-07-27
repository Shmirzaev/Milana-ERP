import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, ViewStyle } from "react-native";

import { colors, radii, spacing } from "../constants/theme";
import type { IconName } from "../data/modules";

type Props = {
  label: string;
  onPress: () => void;
  icon?: IconName;
  disabled?: boolean;
  tone?: "primary" | "secondary" | "accent" | "danger";
  style?: ViewStyle;
};

export function AppButton({ label, onPress, icon, disabled, tone = "primary", style }: Props) {
  const isPrimary = tone === "primary";
  const isAccent = tone === "accent";
  const isDanger = tone === "danger";
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        isPrimary && styles.primary,
        isAccent && styles.accent,
        isDanger && styles.danger,
        tone === "secondary" && styles.secondary,
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed,
        style,
      ]}
    >
      {icon ? (
        <Ionicons
          name={icon}
          size={16}
          color={isPrimary || isAccent || isDanger ? colors.primaryText : colors.secondaryLabel}
          style={styles.icon}
        />
      ) : null}
      <Text style={[styles.label, (isPrimary || isAccent || isDanger) && styles.lightLabel]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: "center",
    borderColor: colors.separatorStrong,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radii.sm,
    flexDirection: "row",
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: spacing.md,
  },
  accent: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  danger: {
    backgroundColor: colors.danger,
    borderColor: colors.danger,
  },
  disabled: {
    opacity: 0.55,
  },
  icon: {
    marginRight: spacing.sm,
  },
  label: {
    color: colors.label,
    fontSize: 13,
    fontWeight: "600",
  },
  lightLabel: {
    color: "#FFFFFF",
  },
  pressed: {
    opacity: 0.68,
  },
  primary: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  secondary: {
    backgroundColor: colors.card,
  },
});
