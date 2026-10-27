"use client";

import { Minus, Plus } from "lucide-react";

type Props = {
  value: string;
  max: number;
  onChange: (value: string) => void;
  decreaseLabel: string;
  increaseLabel: string;
  allLabel: string;
};

export default function SimpleQuantityControl({
  value,
  max,
  onChange,
  decreaseLabel,
  increaseLabel,
  allLabel,
}: Props) {
  const current = Number.isFinite(Number(value)) ? Number(value) : 0;
  const setNumber = (next: number) => onChange(String(Math.max(0, Math.min(max, Math.round(next)))));

  return (
    <div className="flex flex-wrap items-stretch gap-2">
      <button
        type="button"
        className="btn h-14 w-14 p-0"
        aria-label={decreaseLabel}
        onClick={() => setNumber(current - 1)}
        disabled={current <= 0}
      >
        <Minus className="h-6 w-6" />
      </button>
      <input
        className="input h-14 min-w-28 flex-1 text-center text-2xl font-semibold"
        type="number"
        inputMode="numeric"
        min={0}
        max={max}
        value={value}
        onChange={(event) => setNumber(Number(event.target.value))}
      />
      <button
        type="button"
        className="btn h-14 w-14 p-0"
        aria-label={increaseLabel}
        onClick={() => setNumber(current + 1)}
        disabled={current >= max}
      >
        <Plus className="h-6 w-6" />
      </button>
      <button type="button" className="btn h-14 px-5 text-base" onClick={() => setNumber(max)} disabled={max <= 0}>
        {allLabel}
      </button>
    </div>
  );
}
