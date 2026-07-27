import { CameraView, type BarcodeScanningResult, useCameraPermissions } from "expo-camera";
import { useState } from "react";
import { Ionicons } from "@expo/vector-icons";
import { Alert, StyleSheet, Text, TextInput, View } from "react-native";

import { request } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AppButton } from "../components/AppButton";
import { EmptyState } from "../components/EmptyState";
import { FieldList } from "../components/FieldList";
import { Screen } from "../components/Screen";
import { SegmentedControl } from "../components/SegmentedControl";
import { colors, radii, spacing } from "../constants/theme";
import type { Entity, SearchResult } from "../types/api";

type Mode = "bundle" | "package" | "search";

export function ScanScreen() {
  const { apiBaseUrl, token } = useAuth();
  const [permission, requestPermission] = useCameraPermissions();
  const [mode, setMode] = useState<Mode>("bundle");
  const [manualCode, setManualCode] = useState("");
  const [lastCode, setLastCode] = useState("");
  const [result, setResult] = useState<Entity | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [busy, setBusy] = useState(false);

  async function lookup(code: string) {
    if (!token || !code.trim() || busy) return;
    setBusy(true);
    setLastCode(code.trim());
    setResult(null);
    setSearchResults([]);
    try {
      if (mode === "bundle") {
        setResult(await request<Entity>(`/api/bundles/lookup?code=${encodeURIComponent(code.trim())}`, { token, baseUrl: apiBaseUrl }));
      } else if (mode === "package") {
        setResult(await request<Entity>(`/api/packages/barcode/${encodeURIComponent(code.trim())}`, { token, baseUrl: apiBaseUrl }));
      } else {
        setSearchResults(await request<SearchResult[]>(`/api/search?q=${encodeURIComponent(code.trim())}`, { token, baseUrl: apiBaseUrl }));
      }
    } catch (err) {
      Alert.alert("Lookup failed", err instanceof Error ? err.message : "Could not read this code");
    } finally {
      setBusy(false);
    }
  }

  async function runAction(label: string, endpoint: string, body?: Record<string, unknown>) {
    if (!token || !result?.id) return;
    setBusy(true);
    try {
      const updated = await request<Entity>(endpoint.replace("{id}", String(result.id)), {
        method: "POST",
        body,
        token,
        baseUrl: apiBaseUrl,
        headers: {
          "Idempotency-Key": `scan-${mode}-${result.id}-${label}-${Date.now()}`,
        },
      });
      setResult(updated);
    } catch (err) {
      Alert.alert("Action failed", err instanceof Error ? err.message : "Could not complete action");
    } finally {
      setBusy(false);
    }
  }

  function onBarcodeScanned(scan: BarcodeScanningResult) {
    if (scan.data && scan.data !== lastCode && !busy) {
      void lookup(scan.data);
    }
  }

  if (!permission) {
    return <EmptyState title="Checking camera access" />;
  }

  return (
    <Screen scroll={false} padded={false}>
      <View style={styles.controls}>
        <SegmentedControl
          onChange={(value) => {
            setMode(value as Mode);
            setResult(null);
            setSearchResults([]);
          }}
          options={[
            { label: "Bundle", value: "bundle" },
            { label: "Package", value: "package" },
            { label: "Search", value: "search" },
          ]}
          value={mode}
        />
      </View>

      <View style={styles.content}>
        <View style={styles.cameraCard}>
          {permission.granted ? (
            <CameraView
              barcodeScannerSettings={{
                barcodeTypes: ["qr", "code128", "code39", "ean13"],
              }}
              onBarcodeScanned={busy ? undefined : onBarcodeScanned}
              style={styles.camera}
            />
          ) : (
            <View style={styles.permission}>
              <Text style={styles.permissionText}>Camera permission is needed for QR and barcode scanning.</Text>
              <AppButton icon="camera-outline" label="Allow camera" onPress={requestPermission} />
            </View>
          )}
          {permission.granted ? (
            <View style={styles.scanFrame}>
              <View style={[styles.corner, styles.cornerTopLeft]} />
              <View style={[styles.corner, styles.cornerTopRight]} />
              <View style={[styles.corner, styles.cornerBottomLeft]} />
              <View style={[styles.corner, styles.cornerBottomRight]} />
              <View style={styles.scanLabel}>
                <Ionicons name={mode === "search" ? "search-outline" : "qr-code-outline"} size={16} color="#FFFFFF" />
                <Text style={styles.scanLabelText}>{mode === "search" ? "Product search" : mode === "bundle" ? "Bundle label" : "Package label"}</Text>
              </View>
            </View>
          ) : null}
        </View>

        <View style={styles.manual}>
          <TextInput
            autoCapitalize="characters"
            autoCorrect={false}
            onChangeText={setManualCode}
            onSubmitEditing={() => lookup(manualCode)}
            placeholder="Enter barcode or QR payload"
            placeholderTextColor={colors.tertiaryLabel}
            style={styles.input}
            value={manualCode}
          />
          <AppButton disabled={busy || !manualCode.trim()} icon="search-outline" label="Lookup" onPress={() => lookup(manualCode)} />
        </View>

        {result ? (
          <View style={styles.result}>
            <FieldList entity={result} />
            {mode === "bundle" ? (
              <View style={styles.actionGrid}>
                <AppButton label="Send printing" icon="arrow-forward-circle-outline" tone="secondary" disabled={busy} onPress={() => runAction("send-printing", "/api/bundles/{id}/send-printing")} />
                <AppButton label="Receive printing" icon="download-outline" tone="secondary" disabled={busy} onPress={() => runAction("receive-printing", "/api/bundles/{id}/receive-printing")} />
                <AppButton label="Send sewing" icon="arrow-redo-outline" tone="secondary" disabled={busy} onPress={() => runAction("send-sewing", "/api/bundles/{id}/send-sewing")} />
                <AppButton label="Receive sewing" icon="checkmark-circle-outline" tone="secondary" disabled={busy} onPress={() => runAction("receive-sewing", "/api/bundles/{id}/receive-sewing")} />
              </View>
            ) : null}
            {mode === "package" ? (
              <View style={styles.actionGrid}>
                <AppButton label="Receive storage" icon="archive-outline" tone="secondary" disabled={busy} onPress={() => runAction("receive-storage", "/api/packages/{id}/receive-storage", {})} />
                <AppButton label="Reserve" icon="bookmark-outline" tone="secondary" disabled={busy} onPress={() => runAction("reserve", "/api/packages/{id}/reserve")} />
                <AppButton label="Ship" icon="paper-plane-outline" tone="secondary" disabled={busy} onPress={() => runAction("ship", "/api/packages/{id}/ship")} />
                <AppButton label="Delivered" icon="checkmark-done-outline" tone="secondary" disabled={busy} onPress={() => runAction("delivered", "/api/packages/{id}/mark-delivered")} />
              </View>
            ) : null}
          </View>
        ) : null}

        {searchResults.length ? (
          <View style={styles.searchResults}>
            {searchResults.map((item) => (
              <Text key={`${item.type}-${item.id}`} style={styles.searchResult}>
                {item.type}: {item.label}
              </Text>
            ))}
          </View>
        ) : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  actionGrid: {
    gap: spacing.sm,
  },
  camera: {
    flex: 1,
  },
  cameraCard: {
    aspectRatio: 1,
    backgroundColor: colors.primary,
    borderColor: colors.separatorStrong,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    maxHeight: 390,
    minHeight: 300,
    overflow: "hidden",
    position: "relative",
  },
  content: {
    gap: spacing.md,
    paddingBottom: 96,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  corner: {
    borderColor: "#FFFFFF",
    height: 34,
    position: "absolute",
    width: 34,
  },
  cornerBottomLeft: {
    borderBottomWidth: 3,
    borderLeftWidth: 3,
    bottom: spacing.xl,
    left: spacing.xl,
  },
  cornerBottomRight: {
    borderBottomWidth: 3,
    borderRightWidth: 3,
    bottom: spacing.xl,
    right: spacing.xl,
  },
  cornerTopLeft: {
    borderLeftWidth: 3,
    borderTopWidth: 3,
    left: spacing.xl,
    top: spacing.xl,
  },
  cornerTopRight: {
    borderRightWidth: 3,
    borderTopWidth: 3,
    right: spacing.xl,
    top: spacing.xl,
  },
  controls: {
    backgroundColor: colors.background,
    borderBottomColor: colors.separator,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingBottom: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.separatorStrong,
    borderRadius: radii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    color: colors.label,
    flex: 1,
    fontSize: 14,
    minHeight: 40,
    paddingHorizontal: spacing.md,
  },
  manual: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  permission: {
    alignItems: "center",
    flex: 1,
    gap: spacing.lg,
    justifyContent: "center",
    padding: spacing.xl,
  },
  permissionText: {
    color: colors.primaryText,
    fontSize: 15,
    lineHeight: 21,
    textAlign: "center",
  },
  result: {
    gap: spacing.md,
  },
  scanFrame: {
    alignItems: "center",
    bottom: 0,
    justifyContent: "flex-end",
    left: 0,
    paddingBottom: spacing.xxl,
    position: "absolute",
    right: 0,
    top: 0,
  },
  scanLabel: {
    alignItems: "center",
    backgroundColor: "rgba(20, 17, 11, 0.82)",
    borderRadius: radii.sm,
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  scanLabelText: {
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: "600",
  },
  searchResult: {
    color: colors.label,
    fontSize: 14,
    lineHeight: 21,
  },
  searchResults: {
    backgroundColor: colors.card,
    borderColor: colors.separator,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    gap: spacing.sm,
    padding: spacing.lg,
  },
});
