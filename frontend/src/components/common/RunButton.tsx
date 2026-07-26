// Run button (spec §2.6): standard CTA bound to the global busyLabel.
import clsx from "clsx";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";

interface RunButtonProps {
  label: string;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  /** Render as a secondary styling variant. */
  variant?: "primary" | "secondary";
  /** Hide the busy indicator even when the store is busy (default false). */
  silent?: boolean;
  type?: "button" | "submit";
}

export function RunButton({
  label,
  onClick,
  disabled = false,
  variant = "primary",
  silent = false,
  type = "button",
}: RunButtonProps) {
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const isBusy = silent ? false : Boolean(busyLabel);
  const showSpinner = isBusy && !disabled;

  return (
    <button
      type={type}
      className={clsx("run-button", `run-button-${variant}`, { busy: showSpinner })}
      onClick={() => void onClick()}
      disabled={disabled || isBusy}
    >
      {showSpinner ? <span className="busy-dot" aria-hidden="true" /> : null}
      <span>{showSpinner ? (busyLabel ?? "Working…") : label}</span>
    </button>
  );
}
