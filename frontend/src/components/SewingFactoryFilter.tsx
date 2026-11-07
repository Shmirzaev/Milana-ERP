"use client";

import { useT } from "@/lib/i18n";
import { packageIdentityText, sewingFactories } from "@/lib/packageIdentity";

export default function SewingFactoryFilter({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { lang } = useT();
  const copy = packageIdentityText[lang];
  return (
    <label className="block">
      <span className="label">{copy.factory}</span>
      <select className="input" value={value} onChange={event => onChange(event.target.value)}>
        <option value="">{copy.all}</option>
        {Object.entries(sewingFactories).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
      </select>
    </label>
  );
}
