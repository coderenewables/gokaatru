# 0014. The workbench's Prepare: flags from selections, linked views, projects of campaigns

**Status:** Accepted (owner), 2026-11-25. Built in Phase 2.

## Context

Phase 2 builds the new shell and its Prepare screen: loading files, the mast diagram, the
timeline, scatter, wind rose and profile, flagging by drawing, the inspector, and undo
(plan §3.3). Phase 1 left the pieces under it: selections resolved on the server
([0011](0011-selections-on-the-server.md)), cleaning flags and the operation log
([0010](0010-project-store-and-flags.md)), series windows as Arrow, and the generated client
([0012](0012-frontend-stack.md)). Each choice below was put to the owner with its
alternatives.

## Decision

1. **A flag drawn on a chart is a new rule, `exclude_selection`,** that stores a frozen copy of
   the selection definition (never its name, which can be edited later) and resolves it with
   the same code the charts use. A period, a lasso, sectors and their combinations are all
   one rule. The log shows a readable description of the definition. Where an older rule
   expresses the same records (`custom_period_exclude` for a period, `expression_filter` for
   a box, `tower_shadow` for sectors on the paired vane), the two give the same flags, record
   for record, and a test holds them to it.
2. **A flag covers the whole instrument by default:** the drawn channel and the other
   statistics of the same anemometer or vane (mean, standard deviation, minimum, maximum).
   The analyst changes the ticked columns before applying; one flag action is one log entry
   and one undo step, whatever the number of columns.
3. **Reason codes are a fixed list with a note:** icing, maintenance, instrument fault, mast
   or boom effect, logger or transfer fault, suspect (unexplained), other. The note is
   optional, and required for "other". The list is declared once and carried into the flag
   table and the exports.
4. **Lasso is a selection kind:** a polygon over two named channels, resolved on the server
   and checked against an independent point-in-polygon oracle.
5. **Views are linked as a crossfilter.** Each view holds one term (timeline periods, rose
   sectors, scatter region) and the shared selection is their intersection. Shift adds to a
   view's own term, Escape clears it, and the inspector shows each term.
6. **The operation log and Ctrl+Z cover data changes only:** flags, data-model edits,
   sensor removal, configuration and saved selections. Brushing is view state, sent with each
   request as an inline definition and never logged.
7. **Prepare's scope at the Phase 2 gate:** data loading, mast diagram, timeline, scatter,
   rose, profile, flags, inspector, undo, and reanalysis acquisition (BrightHub and
   EarthDataHub, with progress). Sensor overview tables and the shear and extrapolation
   stages stay in the old interface until Phase 3.
8. **The mast diagram edits only a data model drafted from CSV headers.** A campaign's own
   uploaded Task 43 document is shown and never changed by the tool.
9. **The new shell is served at `/workbench`** from the same application; the old interface
   stays at `/` until the Phase 3 gate. Both talk to the same server and see the same data.
10. **The working frame stays stored beside its flags.** Deriving it from raw data and flags
    on every read is deferred: Phase 1 proved the two identical, no Phase 2 interaction needs
    it, and undoing a single flag still replays the later rules because rules depend on
    their order.
11. **A project holds several campaigns** (a mast and a lidar at one site, for example). The
    project holds its name, a site name and one reanalysis node cache: nodes are downloaded
    once and each campaign interpolates them to its own coordinates. Each campaign keeps its
    own data, data model, coordinate, UTC offset, flags, operation log, undo, selections,
    results and sweeps, and stays one session, so the old interface opens it by its id. A
    UTC offset that differs between campaigns is shown, not reconciled.
12. **One campaign is open at a time.** Comparing campaigns in one view (time alignment, a
    selection across campaigns, mast-to-lidar checks) gets its own design note and lands in
    Phase 6 with the lidar work.
13. **Work split:** architecture, server work and integration inline; self-contained,
    well-specified components handed to a Sonnet agent in a separate worktree and verified on
    return.

## Consequences

- The `selection` parameter of the 24 selectable operations takes either a saved name or an
  inline definition. The MCP surface changes only in that parameter's description.
- Sensor removal and data-model edits become operations with undo notes; until now sensor
  removal was HTTP-only.
- Projects add a level above sessions on disk and in the API. Existing sessions are not
  migrated into projects (owner, 2026-11-17).
