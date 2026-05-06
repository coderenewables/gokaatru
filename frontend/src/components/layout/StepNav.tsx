import clsx from "clsx";
import { NavLink } from "react-router-dom";
import { useEffect, useRef } from "react";

import { workflowSteps, isWorkflowStepComplete } from "../../lib/workflow";
import type { SessionSummaryResponse } from "../../lib/types";
import { StatusBadge } from "../common/StatusBadge";

type StepNavProps = {
  summary?: SessionSummaryResponse;
};

export function StepNav({ summary }: StepNavProps) {
  const stepsWithRequired = workflowSteps.filter((step) => step.requiredSteps.length > 0);
  const completedCount = stepsWithRequired.filter((step) => isWorkflowStepComplete(summary, step)).length;
  const totalTracked = stepsWithRequired.length;
  const progressPct = totalTracked > 0 ? Math.round((completedCount / totalTracked) * 100) : 0;
  const progressBarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    progressBarRef.current?.style.setProperty("--progress-width", `${progressPct}%`);
  }, [progressPct]);

  return (
    <nav className="step-nav">
      <div className="step-nav-progress">
        <div className="step-nav-progress-header">
          <span className="step-nav-progress-label">Progress</span>
          <span className="step-nav-progress-value">{completedCount}/{totalTracked}</span>
        </div>
        <div className="step-nav-progress-bar-track">
          <div
            ref={progressBarRef}
            className="step-nav-progress-bar-fill"
          />
        </div>
      </div>
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