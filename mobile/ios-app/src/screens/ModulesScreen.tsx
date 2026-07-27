import { Ionicons } from "@expo/vector-icons";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { FlatList, Linking, Pressable, SectionList, StyleSheet, Text, View } from "react-native";
import { useMemo, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../components/EmptyState";
import { ListRow } from "../components/ListRow";
import { Screen } from "../components/Screen";
import { SearchBox } from "../components/SearchBox";
import { colors, radii, spacing } from "../constants/theme";
import { modules, type ModuleConfig } from "../data/modules";
import type { RootStackParamList } from "../types/navigation";
import { buildErpWebUrl } from "../utils/webLinks";

type Section = {
  title: ModuleConfig["section"];
  data: ModuleConfig[];
};

const sectionOrder: ModuleConfig["section"][] = [
  "Overview",
  "Sales",
  "PLM",
  "Planning",
  "Purchasing",
  "Inventory",
  "Cutting",
  "Printing",
  "Sewing",
  "Packaging",
  "Payroll",
  "Storage",
  "Waste",
  "Finance",
  "Admin",
];

const sectionIcons: Record<ModuleConfig["section"], keyof typeof Ionicons.glyphMap> = {
  Overview: "bar-chart-outline",
  Sales: "receipt-outline",
  PLM: "shirt-outline",
  Planning: "calendar-outline",
  Purchasing: "bag-outline",
  Inventory: "layers-outline",
  Cutting: "cut-outline",
  Printing: "color-palette-outline",
  Sewing: "git-branch-outline",
  Packaging: "cube-outline",
  Payroll: "calculator-outline",
  Storage: "storefront-outline",
  Waste: "trash-outline",
  Finance: "cash-outline",
  Admin: "shield-checkmark-outline",
};

export function ModulesScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { apiBaseUrl } = useAuth();
  const [query, setQuery] = useState("");
  const [activeSection, setActiveSection] = useState<"All" | ModuleConfig["section"]>("All");

  const filtered = useMemo(
    () =>
      modules.filter((module) => {
        const matchesSection = activeSection === "All" || module.section === activeSection;
        const haystack = `${module.title} ${module.description} ${module.section}`.toLowerCase();
        return matchesSection && haystack.includes(query.trim().toLowerCase());
      }),
    [activeSection, query],
  );

  const sections = useMemo(
    () =>
      sectionOrder.reduce<Section[]>((acc, title) => {
        const data = filtered.filter((module) => module.section === title);
        if (data.length) acc.push({ title, data });
        return acc;
      }, []),
    [filtered],
  );

  const chips = useMemo(
    () => [
      { label: "All", value: "All" as const, count: modules.length, icon: "apps-outline" as const },
      ...sectionOrder.map((section) => ({
        label: section,
        value: section,
        count: modules.filter((module) => module.section === section).length,
        icon: sectionIcons[section],
      })),
    ],
    [],
  );

  function openModule(module: ModuleConfig) {
    if (module.endpoint) {
      navigation.navigate("ModuleList", { moduleId: module.id });
      return;
    }
    if (module.webPath) {
      void Linking.openURL(buildErpWebUrl(apiBaseUrl, module.webPath));
    }
  }

  return (
    <Screen scroll={false} padded={false}>
      <View style={styles.header}>
        <SearchBox value={query} onChangeText={setQuery} placeholder="Find an ERP module" />
        <FlatList
          contentContainerStyle={styles.chips}
          data={chips}
          horizontal
          keyExtractor={(item) => item.value}
          renderItem={({ item }) => {
            const selected = item.value === activeSection;
            return (
              <Pressable
                accessibilityRole="button"
                onPress={() => setActiveSection(item.value)}
                style={({ pressed }) => [styles.chip, selected && styles.selectedChip, pressed && styles.pressedChip]}
              >
                <Ionicons name={item.icon} size={16} color={selected ? colors.accent : colors.secondaryLabel} />
                <Text style={[styles.chipText, selected && styles.selectedChipText]}>{item.label}</Text>
                <Text style={[styles.chipCount, selected && styles.selectedChipCount]}>{item.count}</Text>
              </Pressable>
            );
          }}
          showsHorizontalScrollIndicator={false}
          style={styles.chipList}
        />
        <View style={styles.summaryLine}>
          <Text style={styles.summaryText}>
            {filtered.length} {filtered.length === 1 ? "module" : "modules"}
          </Text>
          <Text style={styles.summaryText}>{activeSection}</Text>
        </View>
      </View>

      <SectionList
        contentContainerStyle={styles.list}
        keyExtractor={(item) => item.id}
        ListEmptyComponent={<EmptyState icon="search-outline" title="No matching modules" message="Try another keyword or section." />}
        renderItem={({ item, index, section }) => (
          <ListRow
            compact
            groupPosition={section.data.length === 1 ? "only" : index === 0 ? "first" : index === section.data.length - 1 ? "last" : "middle"}
            icon={item.icon}
            meta={item.permissionHints?.join(" / ")}
            mutedMeta
            onPress={() => openModule(item)}
            subtitle={item.description}
            title={item.title}
          />
        )}
        renderSectionHeader={({ section }) => <Text style={styles.section}>{section.title}</Text>}
        sections={sections}
        stickySectionHeadersEnabled={false}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  chip: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    gap: spacing.xs,
    minHeight: 36,
    paddingHorizontal: spacing.md,
  },
  chipCount: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    fontWeight: "600",
    marginLeft: 2,
  },
  chipList: {
    flexGrow: 0,
    maxWidth: "100%",
  },
  chipText: {
    color: colors.secondaryLabel,
    fontSize: 13,
    fontWeight: "600",
  },
  chips: {
    gap: spacing.sm,
    paddingRight: spacing.lg,
  },
  header: {
    gap: spacing.md,
    maxWidth: "100%",
    overflow: "hidden",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    width: "100%",
  },
  list: {
    paddingBottom: 96,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  pressedChip: {
    opacity: 0.72,
  },
  section: {
    color: colors.secondaryLabel,
    fontSize: 13,
    fontWeight: "600",
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  selectedChip: {
    backgroundColor: colors.accentMuted,
    borderColor: colors.accent,
  },
  selectedChipCount: {
    color: colors.accent,
  },
  selectedChipText: {
    color: colors.label,
  },
  summaryLine: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  summaryText: {
    color: colors.secondaryLabel,
    fontSize: 12,
    fontWeight: "600",
  },
});
