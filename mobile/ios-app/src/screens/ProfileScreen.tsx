import { StyleSheet, Text, View } from "react-native";

import { AppButton } from "../components/AppButton";
import { BrandLockup } from "../components/BrandLockup";
import { FieldList } from "../components/FieldList";
import { Screen } from "../components/Screen";
import { colors, radii, spacing } from "../constants/theme";
import { useAuth } from "../auth/AuthContext";

export function ProfileScreen() {
  const { apiBaseUrl, me, refreshMe, signOut } = useAuth();

  return (
    <Screen>
      <View style={styles.profileCard}>
        <BrandLockup compact />
        <View style={styles.profileText}>
          <Text style={styles.name}>{me?.name}</Text>
          <Text style={styles.caption}>{me?.email}</Text>
          <Text style={styles.caption}>{me?.role || me?.department}</Text>
        </View>
      </View>

      <FieldList
        entity={{
          api_server: apiBaseUrl,
          role: me?.role,
          department: me?.department,
          permissions: me?.permissions?.length || 0,
        }}
      />

      <View style={styles.permissions}>
        <Text style={styles.sectionTitle}>Permissions</Text>
        <Text style={styles.permissionText}>{me?.permissions?.join(" · ") || "No permissions returned"}</Text>
      </View>

      <AppButton icon="refresh-outline" label="Refresh profile" tone="secondary" onPress={refreshMe} />
      <AppButton icon="log-out-outline" label="Sign out" tone="danger" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  caption: {
    color: colors.tertiaryLabel,
    fontSize: 13,
  },
  name: {
    color: colors.label,
    fontSize: 18,
    fontWeight: "700",
  },
  permissions: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    gap: spacing.sm,
    padding: spacing.lg,
  },
  permissionText: {
    color: colors.secondaryLabel,
    fontSize: 13,
    lineHeight: 20,
  },
  profileCard: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    gap: spacing.sm,
    padding: spacing.lg,
  },
  profileText: {
    gap: spacing.xs,
  },
  sectionTitle: {
    color: colors.label,
    fontSize: 17,
    fontWeight: "600",
  },
});
