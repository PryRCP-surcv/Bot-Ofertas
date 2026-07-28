import type { ButtonHTMLAttributes, ReactNode } from "react";

import { CloseIcon } from "./icons";

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "success" | "warning" | "danger" | "info" | "neutral";
}) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}

export function EmptyState({
  action,
  description,
  title,
}: {
  action?: ReactNode;
  description: string;
  title: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__mark" aria-hidden="true">
        B
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function LoadingBlock({ label = "Cargando información" }: { label?: string }) {
  return (
    <div className="loading-block" role="status">
      <span className="loading-block__dot" />
      <span>{label}</span>
    </div>
  );
}

export function Button({
  children,
  className = "",
  tone = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      className={`button button--${tone} ${className}`.trim()}
      {...props}
    >
      {children}
    </button>
  );
}

export function Modal({
  children,
  description,
  onClose,
  open,
  title,
}: {
  children: ReactNode;
  description?: string;
  onClose: () => void;
  open: boolean;
  title: string;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-describedby={description ? "modal-description" : undefined}
        aria-labelledby="modal-title"
        aria-modal="true"
        className="modal"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="modal__header">
          <div>
            <p className="section-kicker">Administración segura</p>
            <h2 id="modal-title">{title}</h2>
            {description ? <p id="modal-description">{description}</p> : null}
          </div>
          <button
            aria-label="Cerrar"
            className="icon-button"
            onClick={onClose}
            type="button"
          >
            <CloseIcon />
          </button>
        </header>
        <div className="modal__body">{children}</div>
      </section>
    </div>
  );
}

export function Toast({
  message,
  onDismiss,
  tone,
}: {
  message: string;
  onDismiss: () => void;
  tone: "success" | "error";
}) {
  return (
    <div className={`toast toast--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      <button aria-label="Cerrar mensaje" onClick={onDismiss} type="button">
        <CloseIcon />
      </button>
    </div>
  );
}
