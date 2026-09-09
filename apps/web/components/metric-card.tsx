import type { LucideIcon } from "lucide-react";

type MetricCardProps = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone?: "violet" | "blue" | "amber" | "teal";
};

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "violet",
}: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>
        <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
      </div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-detail">{detail}</div>
    </article>
  );
}
