import { Ionicons } from "@expo/vector-icons";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useState } from "react";
import { Alert, Linking, StyleSheet, Text, View } from "react-native";

import { request } from "../api/client";
import { useApiResource } from "../api/useApiResource";
import { useAuth } from "../auth/AuthContext";
import { AppButton } from "../components/AppButton";
import { EmptyState } from "../components/EmptyState";
import { FieldList } from "../components/FieldList";
import { LoadingState } from "../components/LoadingState";
import { Screen } from "../components/Screen";
import { StatusBadge } from "../components/StatusBadge";
import { colors, radii, spacing } from "../constants/theme";
import { getModule, resolveDetailWebPath } from "../data/modules";
import type { Entity } from "../types/api";
import type { RootStackParamList } from "../types/navigation";
import { compactParts, formatValue } from "../utils/format";
import { buildErpWebUrl } from "../utils/webLinks";

type Props = NativeStackScreenProps<RootStackParamList, "Detail">;

export function DetailScreen({ route }: Props) {
  const { apiBaseUrl, token } = useAuth();
  const module = route.params.moduleId ? getModule(route.params.moduleId) : null;
  const [localData, setLocalData] = useState<Entity | null>((route.params.initialData as Entity | undefined) || null);
  const { data: remoteData, error, loading, reload } = useApiResource<Entity>(route.params.endpoint ?? null, Boolean(route.params.endpoint));
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const data = remoteData || localData;

  async function runAction(label: string, endpoint: string, body?: Record<string, unknown>) {
    if (!token || !data?.id) return;
    setBusyAction(label);
    try {
      const result = await request<Entity>(endpoint.replace("{id}", String(data.id)), {
        method: "POST",
        body,
        token,
        baseUrl: apiBaseUrl,
        headers: {
          "Idempotency-Key": `${route.params.moduleId || "detail"}-${data.id}-${label}-${Date.now()}`,
        },
      });
      if (route.params.endpoint) {
        await reload();
      } else if (result && typeof result === "object") {
        setLocalData({ ...data, ...result });
      }
    } catch (err) {
      Alert.alert("Action failed", err instanceof Error ? err.message : "Could not complete action");
    } finally {
      setBusyAction(null);
    }
  }

  function openWebRecord() {
    if (!module || !data) return;
    const path = resolveDetailWebPath(module, data);
    if (path) void Linking.openURL(buildErpWebUrl(apiBaseUrl, path));
  }

  if (loading && !data) return <LoadingState label="Loading details" />;
  if (error && !data) return <EmptyState icon="warning-outline" title="Could not load details" message={error} />;
  if (!data) return <EmptyState title="No detail data" />;

  const webPath = module ? resolveDetailWebPath(module, data) : undefined;

  return (
    <Screen>
      <View style={styles.summary}>
        <View style={styles.iconBox}>
          <Ionicons name={module?.icon || "document-text-outline"} size={22} color={colors.accent} />
        </View>
        <View style={styles.summaryText}>
          <Text style={styles.title}>{route.params.title}</Text>
          <Text style={styles.subtitle}>{compactParts([data.order_no, data.production_no, data.model_code, data.customer_name])}</Text>
        </View>
        {typeof data.status === "string" ? <StatusBadge value={data.status} /> : null}
      </View>

      <FieldList entity={data} />

      {webPath || module?.actions?.length ? (
        <View style={styles.actions}>
          <Text style={styles.sectionTitle}>Actions</Text>
          {webPath ? <AppButton icon="open-outline" label="Open in ERP" onPress={openWebRecord} tone="secondary" /> : null}
          {module?.actions?.map((action) => (
            <AppButton
              disabled={Boolean(busyAction)}
              icon={action.icon}
              key={action.label}
              label={busyAction === action.label ? "Working" : action.label}
              onPress={() => runAction(action.label, action.endpoint, action.body)}
              tone={action.tone || "secondary"}
            />
          ))}
        </View>
      ) : null}

      <Text style={styles.footer}>Record #{formatValue(data.id)}</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  actions: {
    gap: spacing.md,
  },
  footer: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    textAlign: "center",
  },
  iconBox: {
    alignItems: "center",
    backgroundColor: colors.accentMuted,
    borderRadius: radii.lg,
    height: 44,
    justifyContent: "center",
    width: 44,
  },
  sectionTitle: {
    color: colors.label,
    fontSize: 17,
    fontWeight: "600",
  },
  subtitle: {
    color: colors.secondaryLabel,
    fontSize: 13,
    lineHeight: 18,
  },
  summary: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    gap: spacing.md,
    padding: spacing.lg,
  },
  summaryText: {
    flex: 1,
    minWidth: 0,
  },
  title: {
    color: colors.label,
    fontSize: 17,
    fontWeight: "700",
  },
});
