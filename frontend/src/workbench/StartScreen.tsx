import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import { useTheme } from "./theme/theme";

/** The projects on disk and their campaigns; opening a campaign opens the shell on it. */
export function StartScreen() {
  useTheme();
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => unwrap(await api.GET("/api/projects")).projects,
  });
  return (
    <div className="gk-start">
      <header className="gk-header">
        <span className="gk-brand">GoKaatru Workbench</span>
      </header>
      <main className="gk-start-main">
        <h1>Projects</h1>
        {projects.isPending && <p>Reading the projects…</p>}
        {projects.isError && <p role="alert">The projects could not be read: {projects.error.message}</p>}
        {projects.data?.length === 0 && <p>No projects yet.</p>}
        <ul className="gk-project-list">
          {projects.data?.map((project) => (
            <li key={project.id} className="gk-project">
              <h2>{project.name}</h2>
              {project.site_name && <p className="gk-muted">{project.site_name}</p>}
              <ul aria-label={`Campaigns of ${project.name}`}>
                {project.campaigns.map((campaign) => (
                  <li key={campaign.session_id}>
                    <a href={`/workbench/?project=${project.id}&campaign=${campaign.session_id}`}>{campaign.name}</a>
                    <span className="gk-muted"> {campaign.kind.replace("_", " ")}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
