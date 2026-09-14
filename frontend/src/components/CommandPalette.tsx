// ⌘K command palette (design doc: "Ask or jump") — search-as-you-type over phases,
// pipeline stages, sweep presets, metrics and gates, all read from real data rather than
// hardcoded mockup entries; anything that doesn't match falls through to "Ask Copilot",
// delegating to the existing chat machinery instead of a second chat-rendering surface.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore, type PhaseId } from "../store/useWorkspaceStore";
import { SWEEP_PRESETS, useSweepStore } from "../store/useSweepStore";
import { STAGE_ORDER, STAGE_META } from "../lib/stages";
import { GATE_META, METRIC_COLUMNS, METRIC_META } from "../types/sweep";

interface Command {
  kind: "phase" | "stage" | "preset" | "metric" | "gate";
  label: string;
  hint: string;
  onSelect: () => void;
}

const PHASES: Array<{ id: PhaseId; label: string; hint: string }> = [
  { id: "prepare", label: "Prepare", hint: "phase" },
  { id: "run", label: "Run", hint: "phase" },
  { id: "interrogate", label: "Interrogate", hint: "phase" },
  { id: "canvas", label: "Canvas", hint: "phase" },
  { id: "copilot", label: "Copilot", hint: "phase" },
];

export function CommandPalette() {
  const paletteOpen = useWorkspaceStore((state) => state.paletteOpen);
  const setPaletteOpen = useWorkspaceStore((state) => state.setPaletteOpen);
  const setActivePhase = useWorkspaceStore((state) => state.setActivePhase);
  const setSelectedStage = useWorkspaceStore((state) => state.setSelectedStage);
  const setPrepareSection = useWorkspaceStore((state) => state.setPrepareSection);
  const sendChatMessage = useWorkspaceStore((state) => state.sendChatMessage);
  const applyPreset = useSweepStore((state) => state.applyPreset);
  const setMetric = useSweepStore((state) => state.setMetric);

  const [query, setQuery] = useState("");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        setQuery("");
        setPaletteOpen(!useWorkspaceStore.getState().paletteOpen);
        return;
      }
      if (event.key === "Escape" && useWorkspaceStore.getState().paletteOpen) {
        setPaletteOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setPaletteOpen]);

  const close = () => setPaletteOpen(false);

  const goToStage = (stage: (typeof STAGE_ORDER)[number]) => {
    setActivePhase("prepare");
    setSelectedStage(stage);
    setPrepareSection(stage === "data" ? "data" : "pipeline");
    close();
  };

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [];
    PHASES.forEach((phase) => {
      list.push({
        kind: "phase",
        label: phase.label,
        hint: phase.hint,
        onSelect: () => {
          setActivePhase(phase.id);
          close();
        },
      });
    });
    STAGE_ORDER.forEach((stage) => {
      list.push({
        kind: "stage",
        label: STAGE_META[stage].title,
        hint: "pipeline stage",
        onSelect: () => goToStage(stage),
      });
    });
    Object.keys(SWEEP_PRESETS).forEach((name) => {
      list.push({
        kind: "preset",
        label: `Preset · ${name}`,
        hint: "sweep axes",
        onSelect: () => {
          applyPreset(name);
          setActivePhase("run");
          close();
        },
      });
    });
    METRIC_COLUMNS.forEach((metric) => {
      list.push({
        kind: "metric",
        label: METRIC_META[metric].label,
        hint: METRIC_META[metric].unit || "metric",
        onSelect: () => {
          setMetric(metric);
          setActivePhase("interrogate");
          close();
        },
      });
    });
    Object.values(GATE_META).forEach((meta) => {
      list.push({
        kind: "gate",
        label: meta.label,
        hint: "admissibility gate",
        onSelect: () => {
          setActivePhase("interrogate");
          close();
        },
      });
    });
    return list;
  }, [applyPreset, setActivePhase, setMetric, setPrepareSection, setSelectedStage]);

  const trimmed = query.trim();
  const q = trimmed.toLowerCase();
  const visible = (
    q ? commands.filter((c) => `${c.label} ${c.kind} ${c.hint}`.toLowerCase().includes(q)) : commands
  ).slice(0, 40);

  const askCopilot = () => {
    if (!trimmed) return;
    void sendChatMessage(trimmed);
    setActivePhase("copilot");
    close();
  };

  if (!paletteOpen) return null;

  return (
    <div className="palette-overlay" role="presentation" onClick={close}>
      <div
        className="palette-card"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          className="palette-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Jump to a phase, stage, preset, metric or gate…"
          aria-label="Command palette search"
          autoFocus
        />
        <div className="palette-results">
          {visible.map((command, index) => (
            <button
              key={`${command.kind}-${command.label}-${index}`}
              type="button"
              className="palette-item"
              onClick={command.onSelect}
            >
              <span className="palette-kind">{command.kind}</span>
              <span className="palette-label">{command.label}</span>
              <span className="palette-hint">{command.hint}</span>
            </button>
          ))}
          {visible.length === 0 ? <div className="palette-empty">Nothing matches that.</div> : null}
        </div>
        {trimmed ? (
          <button type="button" className="palette-ask" onClick={askCopilot}>
            Ask Copilot: “{trimmed}”
          </button>
        ) : null}
      </div>
    </div>
  );
}
