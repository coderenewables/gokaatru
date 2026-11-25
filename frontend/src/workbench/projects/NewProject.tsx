import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, unwrap } from "../api";

/** The form that makes a project; the server's refusal (a blank name) is shown inline. */
export function NewProject() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/projects", { body: { name, site_name: site } })),
    onSuccess: async () => {
      setName("");
      setSite("");
      await client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <form className="gk-inline-form gk-new-project" onSubmit={submit} aria-label="New project">
      <label className="gk-field">
        <span>Project name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="gk-field">
        <span>Site name (optional)</span>
        <input value={site} onChange={(event) => setSite(event.target.value)} />
      </label>
      <button type="submit" className="gk-button gk-button-primary" disabled={create.isPending}>
        New project
      </button>
      {create.isError && (
        <p role="alert" className="gk-form-error">
          {create.error.message}
        </p>
      )}
    </form>
  );
}
