import fs from "node:fs";

const sidebar = fs.readFileSync("src/components/Sidebar.tsx", "utf8");
const page = fs.readFileSync("src/app/(app)/processes/page.tsx", "utf8");

const sidebarFragments = [
  'titleKey: "section.ecoCottonTracking"',
  '{ href: "/processes?factory=ECO", labelKey: "nav.processes", icon: ClipboardList }',
  '"section.ecoCottonTracking"',
];
for (const fragment of sidebarFragments) {
  if (!sidebar.includes(fragment)) {
    throw new Error(`Eco Cotton process-tracking navigation is missing: ${fragment}`);
  }
}

const pageFragments = [
  'if (factory) params.set("factory", factory);',
  'buildProcessUrl({ factory,',
  'factory === "ECO" ? "page.processes.ecoTitle"',
  'factory === "ECO" ? "page.processes.ecoSubtitle"',
];
for (const fragment of pageFragments) {
  if (!page.includes(fragment)) {
    throw new Error(`Eco Cotton Process Tracking page scope is missing: ${fragment}`);
  }
}

for (const language of ["en", "ru", "uz"]) {
  const translations = fs.readFileSync(`src/lib/i18n/locales/${language}-supplemental.ts`, "utf8");
  for (const key of ["section.ecoCottonTracking", "page.processes.ecoTitle", "page.processes.ecoSubtitle"]) {
    if (!translations.includes(`"${key}"`)) {
      throw new Error(`${language} is missing ${key}`);
    }
  }
}

console.log("Eco Cotton Process Tracking contract passed.");
