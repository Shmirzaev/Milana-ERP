import { useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";

import { request } from "../api/client";
import { useApiResource } from "../api/useApiResource";
import { useAuth } from "../auth/AuthContext";
import { AppButton } from "../components/AppButton";
import { EmptyState } from "../components/EmptyState";
import { ListRow } from "../components/ListRow";
import { LoadingState } from "../components/LoadingState";
import { Screen } from "../components/Screen";
import { colors, spacing } from "../constants/theme";
import type { Entity } from "../types/api";
import { normalizeRows } from "../utils/format";

export function AlertsScreen() {
  const { apiBaseUrl, token } = useAuth();
  const { data, error, loading, refreshing, reload } = useApiResource<unknown>("/api/notifications?limit=50");
  const [marking, setMarking] = useState(false);
  const rows = normalizeRows(data);

  async function markAllRead() {
    if (!token) return;
    setMarking(true);
    try {
      await request("/api/notifications/read-all", { method: "POST", token, baseUrl: apiBaseUrl });
      await reload();
    } finally {
      setMarking(false);
    }
  }

  if (loading) return <LoadingState label="Loading alerts" />;

  return (
    <Screen scroll={false} padded={false}>
      <View style={styles.header}>
        <AppButton disabled={marking || !rows.length} icon="checkmark-done-outline" label="Mark all read" tone="secondary" onPress={markAllRead} />
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </View>
      <FlatList
        contentContainerStyle={styles.list}
        data={rows}
        keyExtractor={(item: Entity, index) => String(item.id || index)}
        ListEmptyComponent={<EmptyState icon="notifications-off-outline" title="No notifications" />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={reload} />}
        renderItem={({ item, index }) => (
          <ListRow
            compact
            groupPosition={rows.length === 1 ? "only" : index === 0 ? "first" : index === rows.length - 1 ? "last" : "middle"}
            icon={item.is_read ? "notifications-outline" : "notifications-circle-outline"}
            meta={String(item.created_at || item.timestamp || "")}
            status={item.is_read ? "read" : "unread"}
            subtitle={String(item.message || item.link || "")}
            title={String(item.title || "Notification")}
          />
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  caption: {
    color: colors.secondaryLabel,
    fontSize: 14,
    lineHeight: 20,
  },
  error: {
    color: colors.danger,
    fontSize: 13,
  },
  header: {
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  list: {
    paddingBottom: 96,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
});
