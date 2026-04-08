type HelpTooltipProps = {
  text: string;
};

export function HelpTooltip({ text }: HelpTooltipProps) {
  return (
    <span className="help-tooltip" title={text} aria-hidden="true">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" fill="none" />
        <text x="8" y="12" textAnchor="middle" fontSize="10" fill="currentColor">
          ?
        </text>
      </svg>
    </span>
  );
}