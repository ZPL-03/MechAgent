import type { ReactNode } from "react";

export function PanelTitle({
  icon,
  title,
  actions
}: {
  icon?: ReactNode;
  title: string;
  actions?: ReactNode;
}) {
  return (
    <div className="panel-title">
      <div className="panel-title-head">
        {icon ? (
          <span className="panel-title-icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <h2>{title}</h2>
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
  onAction
}: {
  icon: ReactNode;
  title: string;
  text: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon" aria-hidden="true">
        {icon}
      </span>
      <strong>{title}</strong>
      <span>{text}</span>
      {actionLabel && onAction ? (
        <button className="empty-action" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function CompactEmpty({ text }: { text: string }) {
  return <p className="compact-empty">{text}</p>;
}

export function Skeleton({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={`skeleton-block ${className ?? ""}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <span className="skeleton-line" key={index} />
      ))}
    </div>
  );
}
