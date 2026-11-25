import {
  type CollisionDetection,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { useState } from "react";

import { type Chip, MEASUREMENT_TYPES, edit, levelLabel, levels, parseLevel, parseNumber, unplaced } from "./spec";

interface ChipDrag {
  kind: "mast-chip";
  name: string;
}

function BoomField({ chip, onCommit }: { chip: Chip; onCommit: (boom: number | null) => void }) {
  const shown = chip.boom === null ? "" : String(chip.boom);
  const [text, setText] = useState(shown);
  const [seen, setSeen] = useState(shown);
  if (shown !== seen) {
    setSeen(shown);
    setText(shown);
  }
  const commit = () => {
    const value = parseNumber(text);
    if (value === null) onCommit(null);
    else if (!Number.isNaN(value)) onCommit(value);
  };
  return (
    <label className="gk-mast-field">
      <span>Boom °</span>
      <input
        type="text"
        inputMode="decimal"
        value={text}
        aria-label={`Boom orientation of ${chip.name} in degrees`}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
      />
    </label>
  );
}

function ChipRow({ chip, heights, onChange }: { chip: Chip; heights: number[]; onChange: (next: Partial<Chip>) => void }) {
  const data: ChipDrag = { kind: "mast-chip", name: chip.name };
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `mast:${chip.name}`, data });
  const [fresh, setFresh] = useState("");
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  const placeAtNew = () => {
    const height = parseLevel(fresh);
    if (height === null) return;
    onChange({ height });
    setFresh("");
  };
  return (
    <li ref={setNodeRef} style={style} className={isDragging ? "gk-mast-chip gk-mast-chip-dragging" : "gk-mast-chip"}>
      <div className="gk-mast-chip-main">
        <button
          type="button"
          className="gk-mast-handle"
          {...listeners}
          {...attributes}
          aria-label={`Drag ${chip.name} to a level`}
          aria-roledescription="draggable channel"
        >
          <span aria-hidden="true">⠿</span>
        </button>
        <span className="gk-channel-name">{chip.name}</span>
        <select
          aria-label={`Type of ${chip.name}`}
          value={chip.type}
          onChange={(event) => onChange({ type: event.target.value })}
        >
          {!(chip.type in MEASUREMENT_TYPES) && <option value={chip.type}>{chip.type}</option>}
          {Object.entries(MEASUREMENT_TYPES).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label={`Height of ${chip.name}`}
          value={chip.height === null ? "" : String(chip.height)}
          onChange={(event) => event.target.value !== "" && onChange({ height: Number(event.target.value) })}
        >
          {chip.height === null && <option value="">No height</option>}
          {heights.map((height) => (
            <option key={height} value={String(height)}>
              {levelLabel(height)}
            </option>
          ))}
        </select>
        <BoomField chip={chip} onCommit={(boom) => onChange({ boom })} />
      </div>
      {chip.statistics.length > 0 && (
        <p className="gk-mast-statistics gk-muted">
          Standard deviation: {chip.statistics.map((statistic) => statistic.column_name).join(", ")}
        </p>
      )}
      {chip.height === null && (
        <div className="gk-mast-new-level">
          {chip.reason && <p className="gk-muted">{chip.reason}</p>}
          <label className="gk-mast-field">
            <span>New level (m)</span>
            <input
              type="text"
              inputMode="decimal"
              value={fresh}
              aria-label={`New level for ${chip.name} in metres`}
              onChange={(event) => setFresh(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  placeAtNew();
                }
              }}
            />
          </label>
          <button type="button" onClick={placeAtNew} disabled={parseLevel(fresh) === null}>
            Place {chip.name}
          </button>
        </div>
      )}
    </li>
  );
}

function Level({ height, chips, heights, onChange }: { height: number; chips: Chip[]; heights: number[]; onChange: (name: string, next: Partial<Chip>) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: `level:${height}`, data: { height } });
  return (
    <div
      ref={setNodeRef}
      role="group"
      aria-label={`Mast level ${levelLabel(height)}`}
      className={isOver ? "gk-mast-level gk-mast-level-over" : "gk-mast-level"}
    >
      <span className="gk-mast-height">{levelLabel(height)}</span>
      <ul className="gk-mast-chips">
        {chips.map((chip) => (
          <ChipRow key={chip.name} chip={chip} heights={heights} onChange={(next) => onChange(chip.name, next)} />
        ))}
      </ul>
    </div>
  );
}

// The level under the pointer; the keyboard has no pointer, so it falls back to overlap.
const collision: CollisionDetection = (args) => {
  const within = pointerWithin(args);
  return within.length > 0 ? within : rectIntersection(args);
};

/** The mast: one level per height, highest at the top, each column a chip at its level. A
 * chip moves by dragging its handle onto a level (the keyboard sensor lifts it with Space)
 * or by its height field; a column with no height waits in the highlighted tray. */
export function MastEditor({ chips, onChange }: { chips: Chip[]; onChange: (next: Chip[]) => void }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );
  const heights = levels(chips);
  const waiting = unplaced(chips);
  const change = (name: string, next: Partial<Chip>) => onChange(edit(chips, name, next));
  const onDragEnd = (event: DragEndEvent) => {
    const source = event.active.data.current as ChipDrag | undefined;
    const target = event.over?.data.current as { height: number } | undefined;
    if (source?.kind === "mast-chip" && target) change(source.name, { height: target.height });
  };
  return (
    <DndContext sensors={sensors} collisionDetection={collision} onDragEnd={onDragEnd}>
      <div className="gk-mast">
        {waiting.length > 0 && (
          <div role="group" aria-label="No height yet" className="gk-mast-unplaced">
            <h3>No height yet</h3>
            <p className="gk-muted">Heights are never guessed. Drag each onto a level, or give it one.</p>
            <ul className="gk-mast-chips">
              {waiting.map((chip) => (
                <ChipRow key={chip.name} chip={chip} heights={heights} onChange={(next) => change(chip.name, next)} />
              ))}
            </ul>
          </div>
        )}
        <div className="gk-mast-pole">
          {heights.map((height) => (
            <Level
              key={height}
              height={height}
              heights={heights}
              chips={chips.filter((chip) => chip.height === height)}
              onChange={change}
            />
          ))}
        </div>
      </div>
    </DndContext>
  );
}
