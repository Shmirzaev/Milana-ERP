import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useMemo, useState } from "react";
import { FlatList, Linking, RefreshControl, StyleSheet, Text, View } from "react-native";

import { useApiResource } from "../api/useApiResource";
import { useAuth } from "../auth/AuthContext";
import { AppButton } from "../components/AppButton";
import { EmptyState } from "../components/EmptyState";
import { ListRow } from "../components/ListRow";
import { LoadingState } from "../components/LoadingState";
import { Screen } from "../components/Screen";
import { SearchBox } from "../components/SearchBox";
import { SegmentedControl } from "../components/SegmentedControl";
import { colors, spacing } from "../constants/theme";
import { getModule, resolveDetailWebPath } from "../data/modules";
import type { Entity } from "../types/api";
import type { RootStackParamList } from "../types/navigation";
import { formatValue, matchesQuery, normalizeRows } from "../utils/format";
import { buildErpWebUrl } from "../utils/webLinks";

type Props = NativeStackScreenProps<RootStackParamList, "ModuleList">;

function appendQuery(path: string, key: string, value: string) {
  const delimiter = path.includes("?") ? "&" : "?";
  return `${path}${delimiter}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

export function ModuleListScreen({ navigation, route }: Props) {
  const module = getModule(route.params.moduleId);
  const { apiBaseUrl } = useAuth();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");

  const endpoint = useMemo(() => {
    if (!module.endpoint) return null;
    let path = module.endpoint;
    if (status !== "all") path = appendQuery(path, "status", status);
    if (query && module.searchParam) path = appendQuery(path, module.searchParam, query);
    return path;
  }, [module.endpoint, module.searchParam, query, status]);

  const { data, error, loading, refreshing, reload } = useApiResource<unknown>(endpoint);
  const rows = useMemo(() => {
    const normalized = normalizeRows(data);
    return module.searchParam ? normalized : normalized.filter((row) => matchesQuery(row, query));
  }, [data, module.searchParam, query]);

  function titleFor(row: Entity) {
    return module.getTitle?.(row) || formatValue(row.id);
  }

  function openWeb(path?: string) {
    if (!path) return;
    void Linking.openURL(buildErpWebUrl(apiBaseUrl, path));
  }

  function openRow(row: Entity) {
    if (module.detailEndpoint && row.id) {
      navigation.navigate("Detail", {
        title: titleFor(row),
        endpoint: module.detailEndpoint.replace("{id}", String(row.id)),
        moduleId: module.id,
      });
      return;
    }
    if (module.actions?.length && row.id) {
      navigation.navigate("Detail", {
        title: titleFor(row),
        initialData: row,
        moduleId: module.id,
      });
      return;
    }
    openWeb(resolveDetailWebPath(module, row));
  }

  const canOpenRows = Boolean(module.detailEndpoint || module.actions?.length || module.detailWebPath || module.webPath);

  if (loading) return <LoadingState label={`Loading ${module.title}`} />;

  return (
    <Screen scroll={false} padded={false}>
      <View style={styles.header}>
        <SearchBox value={query} onChangeText={setQuery} placeholder={`Search ${module.title.toLowerCase()}`} />
        {module.statusOptions?.length ? (
          <SegmentedControl
            onChange={setStatus}
            options={[{ label: "All", value: "all" }, ...module.statusOptions.map((item) => ({ label: item.replace(/_/g, " "), value: item }))]}
            value={status}
          />
        ) : null}
        <View style={styles.actions}>
          {module.webPath ? <AppButton icon="open-outline" label="ERP page" onPress={() => openWeb(module.webPath)} tone="secondary" style={styles.actionButton} /> : null}
          {module.createWebPath ? <AppButton icon="add-outline" label="New" onPress={() => openWeb(module.createWebPath)} tone="secondary" style={styles.actionButton} /> : null}
        </View>
        <Text style={styles.resultCount}>
          {rows.length} {rows.length === 1 ? "record" : "records"}
        </Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </View>

      <FlatList
        contentContainerStyle={styles.list}
        data={rows}
        keyExtractor={(item, index) => String(item.id || index)}
        ListEmptyComponent={<EmptyState icon={module.icon} title={`No ${module.title.toLowerCase()} found`} />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={reload} />}
        renderItem={({ item, index }) => (
          <ListRow
            compact
            groupPosition={rows.length === 1 ? "only" : index === 0 ? "first" : index === rows.length - 1 ? "last" : "middle"}
            icon={module.icon}
            meta={module.getMeta?.(item)}
            onPress={canOpenRows ? () => openRow(item) : undefined}
            status={typeof item.status === "string" ? item.status : undefined}
            subtitle={module.getSubtitle?.(item)}
            title={titleFor(item)}
          />
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  actionButton: {
    flex: 1,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
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
  resultCount: {
    color: colors.secondaryLabel,
    fontSize: 12,
    fontWeight: "600",
  },
});
