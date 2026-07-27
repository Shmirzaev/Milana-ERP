import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors, radii, spacing } from "../constants/theme";

type Props = {
  value: string;
  onChangeText: (value: string) => void;
  placeholder?: string;
};

export function SearchBox({ value, onChangeText, placeholder = "Search" }: Props) {
  return (
    <View style={styles.wrapper}>
      <Ionicons name="search-outline" size={17} color={colors.tertiaryLabel} />
      <TextInput
        autoCapitalize="none"
        autoCorrect={false}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.tertiaryLabel}
        returnKeyType="search"
        style={styles.input}
        value={value}
      />
      {value ? (
        <Pressable accessibilityLabel="Clear search" accessibilityRole="button" hitSlop={8} onPress={() => onChangeText("")}>
          <Ionicons name="close-circle" size={17} color={colors.tertiaryLabel} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  input: {
    color: colors.label,
    flex: 1,
    fontSize: 15,
    minHeight: 42,
  },
  wrapper: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
  },
});
