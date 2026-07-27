import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { StyleSheet, Text, View } from "react-native";
import { useCallback, useEffect, useState } from "react";

import { request } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AppButton } from "../components/AppButton";
import { BrandLockup } from "../components/BrandLockup";
import { EmptyState } from "../components/EmptyState";
import { ListRow } from "../components/ListRow";
import { LoadingState } from "../components/LoadingState";
import { Screen } from "../components/Screen";
import { colors, spacing } from "../constants/theme";
import type { RootStackParamList } from "../types/navigation";
import { formatMoney, formatValue, normalizeRows } from "../utils/format";

type DashboardData = {
  management: Record<string, unknown>;
  planning: Record<string, unknown>;
  production: Record<string, unknown>;
  finance: Record<string, unknown>;
  active: Record<string, unknown>[];
};

function SummaryMetric({ detail, label, value }: { detail: string; label: string; value: string }) {
  return (
    <View style={styles.metricCell}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      <Text style={styles.metricDetail} numberOfLines={1}>
        {detail}
      </Text>
    </View>
  );
}

export function DashboardScreen() {
  const { apiBaseUrl, me, token } = useAuth();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setRefreshing(true);
    setError(null);
    try {
      const [management, planning, production, finance, active] = await Promise.all([
        request<Record<string, unknown>>("/api/dashboard/management", { token, baseUrl: apiBaseUrl }),
        request<Record<string, unknown>>("/api/dashboard/planning", { token, baseUrl: apiBaseUrl }),
        request<Record<string, unknown>>("/api/dashboard/production", { token, baseUrl: apiBaseUrl }),
        request<Record<string, unknown>>("/api/dashboard/finance", { token, baseUrl: apiBaseUrl }),
        request<unknown>("/api/dashboard/active-production", { token, baseUrl: apiBaseUrl }),
      ]);
      setData({ management, planning, production, finance, active: normalizeRows(active) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load dashboard");
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, [apiBaseUrl, token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingState label="Loading dashboard" />;

  const stageRows = [
    { name: "Cutting", value: Number(data?.production.cutting_output || 0) },
    { name: "Printing", value: Number(data?.production.printing_output || 0) },
    { name: "Sewing", value: Number(data?.production.sewing_output || 0) },
    { name: "Packaging", value: Number(data?.production.packaging_output || 0) },
  ];
  const maxStage = Math.max(1, ...stageRows.map((row) => row.value));

  return (
    <Screen refreshing={refreshing} onRefresh={load}>
      <View style={styles.header}>
        <BrandLockup compact />
        <View style={styles.headerMeta}>
          <Text style={styles.greeting}>Hello, {me?.name?.split(" ")[0] || "team"}</Text>
          <Text style={styles.caption}>{me?.department || me?.role || "Milana ERP"}</Text>
        </View>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.overviewPanel}>
        <View style={styles.overviewRow}>
          <SummaryMetric label="Active orders" value={formatValue(data?.management.active_orders)} detail="Confirmed + production" />
          <View style={styles.verticalDivider} />
          <SummaryMetric label="Late orders" value={formatValue(data?.management.late_orders)} detail="Needs attention" />
        </View>
        <View style={styles.horizontalDivider} />
        <View style={styles.overviewRow}>
          <SummaryMetric label="Production" value={formatValue(stageRows.reduce((sum, row) => sum + row.value, 0))} detail="Pieces processed" />
          <View style={styles.verticalDivider} />
          <SummaryMetric label="Stock value" value={formatMoney(data?.management.branded_stock_value)} detail="Branded goods" />
        </View>
      </View>

      <View style={styles.actions}>
        <AppButton label="Scan" icon="scan-outline" onPress={() => navigation.navigate("MainTabs", { screen: "Scan" })} style={styles.actionButton} />
        <AppButton label="Modules" icon="grid-outline" tone="secondary" onPress={() => navigation.navigate("MainTabs", { screen: "Modules" })} style={styles.actionButton} />
      </View>

      <View style={styles.stationCard}>
        <View style={styles.cardHeader}>
          <Text style={styles.sectionTitle}>Stations today</Text>
          <Text style={styles.caption}>Pieces processed by operation</Text>
        </View>
        <View style={styles.stageList}>
          {stageRows.map((row) => {
            const pct = Math.min(100, (row.value / maxStage) * 100);
            return (
              <View key={row.name} style={styles.stageRow}>
                <View style={styles.stageText}>
                  <Text style={styles.stageName}>{row.name}</Text>
                  <Text style={styles.stageValue}>{row.value.toLocaleString()}</Text>
                </View>
                <View style={styles.bar}>
                  <View style={[styles.barFill, row.name === "Sewing" && styles.accentBar, { width: `${pct}%` }]} />
                </View>
              </View>
            );
          })}
        </View>
      </View>

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Active production</Text>
        <Text style={styles.caption}>{data?.active.length || 0} orders in flight</Text>
      </View>
      {data?.active.length ? (
        <View style={styles.list}>
          {data.active.slice(0, 8).map((order, index, rows) => (
            <ListRow
              compact
              groupPosition={rows.length === 1 ? "only" : index === 0 ? "first" : index === rows.length - 1 ? "last" : "middle"}
              key={String(order.id)}
              icon="construct-outline"
              meta={`${formatValue(order.progress)}% · ${formatValue(order.deadline_label)}`}
              onPress={() =>
                navigation.navigate("Detail", {
                  title: String(order.order_no || "Order"),
                  endpoint: `/api/sales-orders/${order.id}`,
                  moduleId: "sales-orders",
                })
              }
              status={String(order.status || "")}
              subtitle={String(order.customer || order.type || "")}
              title={String(order.order_no || order.id)}
            />
          ))}
        </View>
      ) : (
        <EmptyState title="No active production" message="Confirmed and in-production orders will appear here." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  accentBar: {
    backgroundColor: colors.accent,
  },
  actionButton: {
    flex: 1,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.md,
  },
  bar: {
    backgroundColor: colors.cardMuted,
    height: 6,
    overflow: "hidden",
  },
  barFill: {
    backgroundColor: colors.primary,
    height: "100%",
  },
  caption: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    marginTop: spacing.xs,
  },
  cardHeader: {
    borderBottomColor: colors.separator,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  error: {
    color: colors.danger,
    fontSize: 13,
  },
  greeting: {
    color: colors.label,
    fontSize: 20,
    fontWeight: "700",
  },
  header: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.md,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xs,
  },
  headerMeta: {
    flex: 1,
    minWidth: 0,
  },
  list: {
    marginTop: -spacing.sm,
  },
  metricCell: {
    flex: 1,
    minWidth: 0,
    padding: spacing.lg,
  },
  metricDetail: {
    color: colors.tertiaryLabel,
    fontSize: 11,
    marginTop: spacing.xs,
  },
  metricLabel: {
    color: colors.secondaryLabel,
    fontSize: 12,
    fontWeight: "600",
  },
  metricValue: {
    color: colors.label,
    fontSize: 24,
    fontWeight: "700",
    marginTop: spacing.sm,
  },
  overviewPanel: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
  overviewRow: {
    flexDirection: "row",
  },
  horizontalDivider: {
    backgroundColor: colors.separator,
    height: StyleSheet.hairlineWidth,
  },
  verticalDivider: {
    backgroundColor: colors.separator,
    width: StyleSheet.hairlineWidth,
  },
  sectionHeader: {
    marginTop: spacing.sm,
  },
  sectionTitle: {
    color: colors.label,
    fontSize: 17,
    fontWeight: "600",
  },
  stageList: {
    gap: spacing.lg,
    padding: spacing.lg,
  },
  stageName: {
    color: colors.label,
    fontSize: 14,
    fontWeight: "600",
  },
  stageRow: {
    gap: spacing.sm,
  },
  stageText: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  stageValue: {
    color: colors.label,
    fontSize: 13,
    fontWeight: "700",
  },
  stationCard: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
});
