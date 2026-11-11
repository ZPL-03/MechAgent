import { useI18n } from "../i18n/LocaleProvider";
import type { ReactNode } from "react";

export function PanelTitle({
  icon,
  title,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  actions?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="panel-title">
      <div className="panel-title-head">
        {icon ? (
          <span className="panel-title-icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <h2>{t(title)}</h2>
      </div>
      {actions ? <div className="panel-actions">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  text,
  actionLabel,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="empty-state">
      <span className="empty-state-icon" aria-hidden="true">
        {icon}
      </span>
      <strong>{t(title)}</strong>
      <span>{t(text)}</span>
      {actionLabel && onAction ? (
        <button className="empty-action" type="button" onClick={onAction}>
          {t(actionLabel)}
        </button>
      ) : null}
    </div>
  );
}

export function CompactEmpty({ text }: { text: string }) {
  const { t } = useI18n();
  return <p className="compact-empty">{t(text)}</p>;
}

export function Skeleton({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`skeleton-block ${className ?? ""}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <span className="skeleton-line" key={index} />
      ))}
    </div>
  );
}
