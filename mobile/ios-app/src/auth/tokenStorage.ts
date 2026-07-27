import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const options = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

function canUseWebStorage() {
  return Platform.OS === "web" && typeof window !== "undefined" && Boolean(window.localStorage);
}

export async function getStoredValue(key: string) {
  if (canUseWebStorage()) return window.localStorage.getItem(key);
  return SecureStore.getItemAsync(key);
}

export async function setStoredValue(key: string, value: string) {
  if (canUseWebStorage()) {
    window.localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, options);
}

export async function deleteStoredValue(key: string) {
  if (canUseWebStorage()) {
    window.localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}
