import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import { NewProject } from "./projects/NewProject";
import { ProjectCard } from "./projects/ProjectCard";
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
        <span className="gk-brand">GoKaatru</span>
      </header>
      <main className="gk-start-main">
        <h1>Projects</h1>
        <NewProject />
        {projects.isPending && <p>Reading the projects…</p>}
        {projects.isError && <p role="alert">The projects could not be read: {projects.error.message}</p>}
        {projects.data?.length === 0 && (
          <p className="gk-muted">No projects yet. Name one above to start: a project holds the campaigns of one site.</p>
        )}
        <ul className="gk-project-list">
          {projects.data?.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </ul>
      </main>
    </div>
  );
}
