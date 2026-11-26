import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, unwrap } from "../api";
import { CAMPAIGN_KINDS, describeSite, formatChange, kindLabel, timezoneNotice } from "./helpers";
import { InlineEdit } from "./InlineEdit";

interface Summary {
  id: string;
  name: string;
  site_name: string;
  updated_at: string;
}

function AddCampaign({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("mast");
  const trigger = useRef<HTMLButtonElement>(null);
  const returning = useRef(false);
  useEffect(() => {
    if (!open && returning.current) {
      returning.current = false;
      trigger.current?.focus();
    }
  }, [open]);
  const close = () => {
    returning.current = true;
    setOpen(false);
  };
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/projects/{project_id}/campaigns", {
          params: { path: { project_id: projectId } },
          body: { name, kind },
        }),
      ),
    onSuccess: async () => {
      setName("");
      close();
      await Promise.all([
        client.invalidateQueries({ queryKey: ["projects"] }),
        client.invalidateQueries({ queryKey: ["project", projectId] }),
      ]);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };
  if (!open) {
    return (
      <button
        ref={trigger}
        type="button"
        className="gk-button"
        onClick={() => {
          add.reset();
          setOpen(true);
        }}
      >
        Add campaign
      </button>
    );
  }
  return (
    <form
      className="gk-inline-form"
      aria-label="Add campaign"
      onSubmit={submit}
      onKeyDown={(event) => event.key === "Escape" && close()}
    >
      <label className="gk-field">
        <span>Campaign name</span>
        <input autoFocus value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="gk-field">
        <span>Kind</span>
        <select value={kind} onChange={(event) => setKind(event.target.value)}>
          {CAMPAIGN_KINDS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="gk-button gk-button-primary" disabled={add.isPending}>
        Save campaign
      </button>
      <button type="button" className="gk-button" onClick={close}>
        Cancel
      </button>
      {add.isError && (
        <p role="alert" className="gk-form-error">
          {add.error.message}
        </p>
      )}
    </form>
  );
}

/** One project: its names, its campaigns with their own site, and the actions on them. */
export function ProjectCard({ project }: { project: Summary }) {
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["project", project.id],
    queryFn: async () =>
      unwrap(await api.GET("/api/projects/{project_id}", { params: { path: { project_id: project.id } } })),
  });
  const changed = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["projects"] }),
      client.invalidateQueries({ queryKey: ["project", project.id] }),
    ]);
  const renameProject = async (values: Record<string, string>) => {
    unwrap(
      await api.PATCH("/api/projects/{project_id}", {
        params: { path: { project_id: project.id } },
        body: { name: values.name, site_name: values.site },
      }),
    );
    await changed();
  };
  const renameCampaign = async (sessionId: string, name: string) => {
    unwrap(
      await api.PATCH("/api/projects/{project_id}/campaigns/{session_id}", {
        params: { path: { project_id: project.id, session_id: sessionId } },
        body: { name },
      }),
    );
    await changed();
  };
  const campaigns = detail.data?.campaigns ?? [];
  return (
    <li className="gk-project">
      <h2>{project.name}</h2>
      <p className="gk-muted">
        {project.site_name || "No site name"} · changed {formatChange(project.updated_at)}
      </p>
      <InlineEdit
        action="Rename project"
        fields={[
          { key: "name", label: "Project name", value: project.name },
          { key: "site", label: "Site name", value: project.site_name },
        ]}
        onSave={renameProject}
      />
      {detail.isError && <p role="alert">The campaigns could not be read: {detail.error.message}</p>}
      {detail.data?.timezones_differ && (
        <p className="gk-notice" role="status">
          {timezoneNotice(campaigns)}
        </p>
      )}
      {campaigns.length === 0 && detail.isSuccess && <p className="gk-muted">No campaigns yet.</p>}
      <ul aria-label={`Campaigns of ${project.name}`} className="gk-campaigns">
        {campaigns.map((campaign) => (
          <li key={campaign.session_id}>
            <div className="gk-campaign-line">
              <a href={`/workbench/?project=${project.id}&campaign=${campaign.session_id}`}>{campaign.name}</a>
              <span className="gk-muted">{kindLabel(campaign.kind)}</span>
              <InlineEdit
                action={`Rename ${campaign.name}`}
                fields={[{ key: "name", label: "Campaign name", value: campaign.name }]}
                onSave={(values) => renameCampaign(campaign.session_id, values.name)}
              />
            </div>
            <p className="gk-muted gk-campaign-site">{describeSite(campaign)}</p>
          </li>
        ))}
      </ul>
      <AddCampaign projectId={project.id} />
    </li>
  );
}
