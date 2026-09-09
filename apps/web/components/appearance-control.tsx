"use client";

import { Check, ChevronDown, Monitor, Moon, Sun } from "lucide-react";

import { useTheme, type ThemePreference } from "@/components/theme-provider";

const options: Array<{
  value: ThemePreference;
  label: string;
  icon: typeof Monitor;
}> = [
  { value: "system", label: "System", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

export function AppearanceControl() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  const ActiveIcon = preference === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun;

  return (
    <details className="appearance-control">
      <summary title="Appearance" aria-label="Appearance">
        <span className="appearance-summary-icon" aria-hidden="true">
          <ActiveIcon size={16} strokeWidth={1.8} />
        </span>
        <span className="appearance-summary-label">Appearance</span>
        <ChevronDown className="appearance-chevron" size={14} aria-hidden="true" />
      </summary>
      <div className="appearance-menu" role="radiogroup" aria-label="Appearance">
        {options.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={preference === value}
            className={preference === value ? "appearance-option selected" : "appearance-option"}
            onClick={() => setPreference(value)}
          >
            <Icon size={14} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
            {preference === value ? <Check className="appearance-check" size={14} aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
    </details>
  );
}
