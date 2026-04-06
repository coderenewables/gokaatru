import clsx from "clsx";
import { NavLink } from "react-router-dom";

import { workflowSteps, isWorkflowStepComplete } from "../../lib/workflow";
import type { SessionSummaryResponse } from "../../lib/types";
import { StatusBadge } from "../common/StatusBadge";

type StepNavProps = {
  summary?: SessionSummaryResponse;
};

export function StepNav({ summary }: StepNavProps) {
  return (
    <nav className="step-nav">
      {workflowSteps.map((step) => {
        const complete = isWorkflowStepComplete(summary, step);
        return (
          <NavLink key={step.path} className={({ isActive }) => clsx("step-link", isActive && "step-link-active")} to={step.path}>
            <span className="step-copy">
              <strong>{step.label}</strong>
              <small>{step.description}</small>
            </span>
            <StatusBadge tone={complete ? "ok" : "idle"} text={complete ? "Ready" : "Pending"} />
          </NavLink>
        );
      })}
    </nav>
  );
}