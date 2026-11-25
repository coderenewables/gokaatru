import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { ReactNode } from "react";

// Dragging a channel onto a chart (plan §3.3 "Any chart"). A draggable channel carries
// ``ChannelDrag``; a chart's drop zone carries ``ChartDrop``; the drop is resolved here, in
// one place, into the chart store. The keyboard sensor is the keyboard route to the same
// drop (Space to lift, arrows to move, Space to drop).

export interface ChannelDrag {
  kind: "channel";
  channel: string;
}

export type ChartDrop =
  | { kind: "timeline"; shown: string[] }
  | { kind: "scatter"; axis: "x" | "y"; shown: { x: string; y: string } }
  | { kind: "rose" };

export type DropHandler = (channel: string, target: ChartDrop) => void;

/** A method dragged from the Model palette onto the pipeline (plan §3.3 "Model"). */
export interface MethodDrag {
  kind: "method";
  operation: string;
}

export interface PipelineDrop {
  kind: "pipeline";
}

export function resolveMethodDrop(event: DragEndEvent, onMethod: (operation: string) => void): void {
  const source = event.active.data.current as MethodDrag | undefined;
  const target = event.over?.data.current as PipelineDrop | undefined;
  if (source?.kind !== "method" || target?.kind !== "pipeline") return;
  onMethod(source.operation);
}

export function resolveDrop(event: DragEndEvent, onDrop: DropHandler): void {
  const source = event.active.data.current as ChannelDrag | undefined;
  const target = event.over?.data.current as ChartDrop | undefined;
  if (source?.kind !== "channel" || !target) return;
  onDrop(source.channel, target);
}

export function WorkbenchDnd({
  children,
  onDrop,
  onMethodDrop,
}: {
  children: ReactNode;
  onDrop: DropHandler;
  onMethodDrop?: (operation: string) => void;
}) {
  const sensors = useSensors(
    // A few pixels of movement before a drag starts, so a click on a channel is still a click.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );
  return (
    <DndContext
      sensors={sensors}
      onDragEnd={(event) => {
        resolveDrop(event, onDrop);
        if (onMethodDrop) resolveMethodDrop(event, onMethodDrop);
      }}
    >
      {children}
    </DndContext>
  );
}
