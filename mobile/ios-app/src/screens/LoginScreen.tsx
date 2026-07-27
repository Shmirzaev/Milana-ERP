import { useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AppButton } from "../components/AppButton";
import { BrandLockup } from "../components/BrandLockup";
import { colors, radii, spacing } from "../constants/theme";
import { useAuth } from "../auth/AuthContext";

export function LoginScreen() {
  const { apiBaseUrl, signIn } = useAuth();
  const [baseUrl, setBaseUrl] = useState(apiBaseUrl);
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await signIn(baseUrl, email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.container}>
        <View style={styles.brand}>
          <BrandLockup />
          <View style={styles.rule} />
          <Text style={styles.subtitle}>Factory operations, scanning, stock, and approvals.</Text>
        </View>

        <View style={styles.form}>
          <Text style={styles.label}>API server</Text>
          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            onChangeText={setBaseUrl}
            placeholder="https://api.example.com"
            placeholderTextColor={colors.tertiaryLabel}
            style={styles.input}
            value={baseUrl}
          />
          <Text style={styles.label}>Email</Text>
          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            onChangeText={setEmail}
            placeholder="you@company.com"
            placeholderTextColor={colors.tertiaryLabel}
            style={styles.input}
            value={email}
          />
          <Text style={styles.label}>Password</Text>
          <TextInput
            onChangeText={setPassword}
            placeholder="Password"
            placeholderTextColor={colors.tertiaryLabel}
            secureTextEntry
            style={styles.input}
            value={password}
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <AppButton disabled={submitting || !email || !password || !baseUrl} icon="log-in-outline" label={submitting ? "Signing in" : "Sign in"} onPress={submit} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  brand: {
    gap: spacing.sm,
  },
  container: {
    flex: 1,
    justifyContent: "center",
    padding: spacing.lg,
  },
  error: {
    color: colors.danger,
    fontSize: 13,
    lineHeight: 18,
  },
  form: {
    gap: spacing.md,
    marginTop: spacing.xl,
  },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.separatorStrong,
    borderRadius: radii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    color: colors.label,
    fontSize: 14,
    minHeight: 42,
    paddingHorizontal: spacing.md,
  },
  label: {
    color: colors.tertiaryLabel,
    fontSize: 12,
    fontWeight: "600",
  },
  rule: {
    backgroundColor: colors.accent,
    height: 3,
    marginTop: spacing.sm,
    width: 72,
  },
  safe: {
    backgroundColor: colors.background,
    flex: 1,
  },
  subtitle: {
    color: colors.secondaryLabel,
    fontSize: 15,
    lineHeight: 22,
    maxWidth: 300,
  },
});
