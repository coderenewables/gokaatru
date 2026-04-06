import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  detail: string;
  actions?: ReactNode;
};

export function PageHeader({ title, detail, actions }: PageHeaderProps) {
  return (
    <header className="section-header page-header-row">
      <div>
        <h2>{title}</h2>
        <p>{detail}</p>
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </header>
  );
}