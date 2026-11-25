import { api, unwrap } from "../api";
import { useDesign } from "../run/store";
import { usePhase } from "../shell/phase";
import { type Step, forServer, usePipeline } from "./store";

/** Load one sweep scenario into the campaign's pipeline and open Model (decisions/0015.1):
 * its steps are the operations the sweep's stages share, so run they reproduce its row. */
export async function loadScenario(sessionId: string, sweepId: string, configHash: string): Promise<void> {
  const loaded = unwrap(
    await api.POST("/api/sessions/{session_id}/operations/pipeline_from_scenario", {
      params: { path: { session_id: sessionId } },
      body: { sweep_id: sweepId, config_hash: configHash },
    }),
  );
  const pipeline = usePipeline.getState();
  pipeline.open(sessionId);
  pipeline.replace(loaded.steps as unknown as Step[], {
    sweepId,
    configHash,
    prefixMatches: loaded.prefix_matches,
    prefixNote: loaded.prefix_note,
  });
  usePhase.getState().goTo("model");
}

/** Fill the Run design with the pipeline's own choices and open Run ("Sweep around this").
 * A choice no sweep level expresses goes with it as a note, said beside the matrix. */
export async function sweepAround(sessionId: string, steps: Step[]): Promise<void> {
  const around = unwrap(
    await api.POST("/api/sessions/{session_id}/operations/sweep_spec_from_pipeline", {
      params: { path: { session_id: sessionId } },
      body: { steps: forServer(steps) as unknown as Record<string, unknown>[] },
    }),
  );
  useDesign.getState().setDesign(
    around.spec,
    around.unmatched.map((entry) => `${entry.axis.replace(/_/g, " ")}: ${entry.why}`),
  );
  usePhase.getState().goTo("run");
}
