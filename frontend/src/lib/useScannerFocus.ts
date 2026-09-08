"use client";

import { useEffect, type RefObject } from "react";

const editable = (element: Element | null) => element instanceof HTMLElement && (
  element.isContentEditable || !!element.closest("input, textarea, select, [contenteditable='true'], [role='combobox']")
);

/** Keep a keyboard-wedge scanner ready without taking over other form fields. */
export function useScannerFocus(input: RefObject<HTMLInputElement>, enabled: boolean, append: (character: string) => void) {
  useEffect(() => {
    if (!enabled) return;
    const blocked = () => document.visibilityState === "hidden" || document.body.style.overflow === "hidden"
      || !!document.querySelector('[role="dialog"], [aria-modal="true"]');
    const focus = () => {
      if (!blocked() && !editable(document.activeElement)) input.current?.focus({ preventScroll: true });
    };
    let timer: ReturnType<typeof setTimeout>;
    const afterPointer = () => { clearTimeout(timer); timer = setTimeout(focus, 0); };
    const onKey = (event: KeyboardEvent) => {
      const field = input.current;
      if (!field || field.disabled || blocked() || event.defaultPrevented || event.isComposing || event.ctrlKey || event.altKey || event.metaKey) return;
      if (event.target === field) {
        // Some warehouse scanners use Tab instead of Enter as their suffix.
        if (event.key === "Tab" && !event.shiftKey && field.value.trim()) {
          event.preventDefault();
          field.form?.requestSubmit();
        }
        return;
      }
      if (editable(event.target instanceof Element ? event.target : null)) return;
      if (event.key.length === 1) {
        // The first character targets the old focus; preserve it explicitly.
        event.preventDefault();
        field.focus({ preventScroll: true });
        append(event.key);
      }
    };
    focus();
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerup", afterPointer);
    window.addEventListener("focus", focus);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerup", afterPointer);
      window.removeEventListener("focus", focus);
    };
  }, [input, enabled, append]);
}
