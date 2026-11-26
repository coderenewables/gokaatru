import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

export interface Field {
  key: string;
  label: string;
  value: string;
}

export interface InlineEditProps {
  /** Names the trigger, e.g. "Rename project". */
  action: string;
  fields: Field[];
  /** Resolves when saved; a rejection's message is shown beside the fields. */
  onSave: (values: Record<string, string>) => Promise<unknown>;
}

/** A button that opens labelled fields in place: Enter saves, Escape cancels, focus comes back. */
export function InlineEdit({ action, fields, onSave }: InlineEditProps) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const returning = useRef(false);
  const errorId = useId();

  useEffect(() => {
    if (editing) first.current?.focus();
    else if (returning.current) {
      returning.current = false;
      trigger.current?.focus();
    }
  }, [editing]);

  const open = () => {
    setValues(Object.fromEntries(fields.map((field) => [field.key, field.value])));
    setError(null);
    setEditing(true);
  };
  const close = () => {
    returning.current = true;
    setEditing(false);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await onSave(values);
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };

  if (!editing) {
    return (
      <button ref={trigger} type="button" className="gk-button" onClick={open}>
        {action}
      </button>
    );
  }
  return (
    <form className="gk-inline-form" onSubmit={submit} onKeyDown={onKeyDown} aria-label={action}>
      {fields.map((field, index) => (
        <label key={field.key} className="gk-field">
          <span>{field.label}</span>
          <input
            ref={index === 0 ? first : undefined}
            value={values[field.key] ?? ""}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}
          />
        </label>
      ))}
      <button type="submit" className="gk-button gk-button-primary" disabled={busy}>
        Save
      </button>
      <button type="button" className="gk-button" onClick={close}>
        Cancel
      </button>
      {error && (
        <p id={errorId} role="alert" className="gk-form-error">
          {error}
        </p>
      )}
    </form>
  );
}
