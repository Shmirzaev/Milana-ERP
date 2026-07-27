# Milana ERP iOS App

Standalone Expo/React Native client for the existing Milana ERP FastAPI backend.

## What is included

- Secure bearer-token login against `POST /api/auth/token`
- iOS-style tab navigation for Dashboard, Modules, Scanner, Alerts, and Profile
- ERP module browser for sales, planning, production, warehouse, finance, HR, and admin data
- ERP web handoff buttons for deep workflows such as creating or editing complex records
- QR/barcode scanner flows for bundles and packages
- Pull-to-refresh list screens and authenticated detail/action screens
- EAS build profiles for iOS development, internal preview, and production builds

## Local setup

```powershell
cd C:\ERP\mobile\ios-app
copy .env.example .env
npm install
npm run start
```

Set `EXPO_PUBLIC_API_BASE_URL` to the backend URL reachable from the phone. Set `EXPO_PUBLIC_ERP_WEB_URL` to the existing ERP frontend URL used by the "Open in ERP" buttons. For a physical iPhone, `localhost` means the phone itself, so use your computer LAN IP or deployed URLs.

## iOS builds

```powershell
cd C:\ERP\mobile\ios-app
npx eas build --platform ios --profile preview
```

Use `--profile production` when App Store/TestFlight signing is ready.

## Notes

- This app does not modify the existing `frontend` or `backend` folders.
- The local preview can use `backend/data/mobile_preview.db` with seeded sample records.
- Camera access is configured through the `expo-camera` config plugin.
- Tokens are stored with `expo-secure-store`.
