import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors, radii, spacing } from "../constants/theme";

type Option = {
  label: string;
  value: string;
};

type Props = {
  options: Option[];
  value: string;
  onChange: (value: string) => void;
};

export function SegmentedControl({ options, value, onChange }: Props) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.track}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="button"
            onPress={() => onChange(option.value)}
            style={[styles.segment, selected && styles.selected]}
          >
            <Text style={[styles.label, selected && styles.selectedLabel]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  label: {
    color: colors.secondaryLabel,
    fontSize: 12,
    fontWeight: "600",
  },
  segment: {
    borderRadius: radii.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  selected: {
    backgroundColor: colors.card,
    borderColor: colors.separatorStrong,
    borderWidth: StyleSheet.hairlineWidth,
  },
  selectedLabel: {
    color: colors.label,
  },
  track: {
    backgroundColor: colors.cardMuted,
    borderColor: colors.separatorStrong,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    gap: spacing.xs,
    padding: spacing.xs,
  },
});
