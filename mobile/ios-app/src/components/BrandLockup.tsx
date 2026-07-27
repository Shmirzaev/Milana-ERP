import { Image, StyleSheet, View, ViewStyle } from "react-native";

type Props = {
  compact?: boolean;
  style?: ViewStyle;
};

export function BrandLockup({ compact = false, style }: Props) {
  return (
    <View style={[styles.wrap, compact && styles.compact, style]}>
      <Image
        accessibilityLabel="Milana ERP"
        resizeMode="contain"
        source={require("../../assets/milana-erp-logo.png")}
        style={[styles.logo, compact && styles.compactLogo]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  compact: {
    height: 42,
    width: 148,
  },
  compactLogo: {
    height: 38,
    width: 148,
  },
  logo: {
    height: 58,
    width: 214,
  },
  wrap: {
    alignItems: "flex-start",
    height: 62,
    justifyContent: "center",
    width: 220,
  },
});
