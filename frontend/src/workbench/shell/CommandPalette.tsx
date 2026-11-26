import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  run: () => void;
  disabled?: boolean;
}

/** The commands whose label holds every word typed, in the order given. */
export function matching(commands: Command[], query: string): Command[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return commands.filter((command) => words.every((word) => command.label.toLowerCase().includes(word)));
}

/** Ctrl+K: every workbench command by name, for the keyboard (plan §3.3 "Anywhere"). A
 * combobox over a listbox: type to narrow, arrows to move, Enter to run, Escape to close. */
export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const shown = useMemo(() => matching(commands, query), [commands, query]);
  const current = shown[Math.min(active, shown.length - 1)];

  useEffect(() => input.current?.focus(), []);
  useEffect(() => setActive(0), [query]);

  const run = (command: Command | undefined) => {
    if (!command || command.disabled) return;
    onClose();
    command.run();
  };

  return (
    <div className="gk-palette-backdrop" onMouseDown={onClose}>
      <div
        className="gk-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input
          ref={input}
          role="combobox"
          aria-expanded="true"
          aria-controls="gk-palette-list"
          aria-activedescendant={current ? `gk-command-${current.id}` : undefined}
          aria-label="Command"
          placeholder="Type a command"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onClose();
            else if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((index) => Math.min(index + 1, shown.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              run(current);
            }
          }}
        />
        <ul id="gk-palette-list" role="listbox" aria-label="Commands">
          {shown.length === 0 && <li className="gk-muted">No command matches.</li>}
          {shown.map((command) => (
            <li
              key={command.id}
              id={`gk-command-${command.id}`}
              role="option"
              aria-selected={command === current}
              aria-disabled={command.disabled || undefined}
              className={command === current ? "gk-command gk-command-active" : "gk-command"}
              onMouseDown={(event) => {
                event.preventDefault();
                run(command);
              }}
            >
              {command.label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
