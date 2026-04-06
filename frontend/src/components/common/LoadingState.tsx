type LoadingStateProps = {
  label?: string;
};

export function LoadingState({ label = "Loading" }: LoadingStateProps) {
  return (
    <div className="loading-state" aria-live="polite">
      <span className="loading-dot" />
      <span>{label}</span>
    </div>
  );
}