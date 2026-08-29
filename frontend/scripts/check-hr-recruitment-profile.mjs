import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/hr/recruitment/page.tsx", "utf8");
const hrUi = fs.readFileSync("src/components/hr/HrUi.tsx", "utf8");

const requiredPageFragments = [
  "Search name, phone, PINFL or passport",
  "View / edit",
  "date_of_birth: string | null",
  "passport_number: string | null",
  "passport_issued_by: string | null",
  "passport_expiry_date: string | null",
  "pinfl: string | null",
  "department_id: string",
  "candidatePayload(candidateToForm(candidate), stage)",
  'pattern="[0-9]{14}"',
  'type="datetime-local"',
  "Save candidate",
];

for (const fragment of requiredPageFragments) {
  if (!page.includes(fragment)) {
    throw new Error(`Recruitment page is missing the recovered candidate-profile contract: ${fragment}`);
  }
}

for (const fragment of [
  "HR_TRANSLATIONS",
  "Профиль кандидата",
  "Nomzod profili",
  "export function useHrT",
]) {
  if (!hrUi.includes(fragment)) {
    throw new Error(`HR translations are missing the recovered recruitment contract: ${fragment}`);
  }
}

console.log("HR recruitment candidate-profile UI contract passed.");
