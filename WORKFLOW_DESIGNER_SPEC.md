# GoKaatru Workflow Designer — Design Specification

## 1. Overview

A drag-and-drop visual workflow designer that **replaces** the current step-by-step sidebar navigation. Users build wind data analysis pipelines by connecting nodes on a React Flow canvas. All **200+ tools** (60 GoKaatru core + 142 WindKit) are available as draggable nodes. Completed workflows can be **forked from any node** into up to 4 parallel branches. A **full comparison dashboard** lets users compare results across branches side-by-side.

### Design Decisions (Confirmed)

| Decision | Choice |
|----------|--------|
| Replaces or augments current nav | **Replaces entirely** |
| Node granularity | **Hybrid** — high-level group nodes expand to sub-nodes |
| Parallel workflow model | **Fork from any point** (git-style branching) |
| Dataset handling | **Shared dataset pool** (upload once, reference anywhere) |
| Comparison view | **Full dashboard** (metrics table + overlay plots) |
| Canvas library | **React Flow** |
| Stack scope | **Full stack** (backend + frontend) |
| Execution model | **Both** (auto-pipeline + manual step-through) |

---

## 2. Architecture

### 2.1 Conceptual Model

```
┌─────────────────────────────────────────────────────────────┐
│                    DATASET POOL                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ HornsRev │  │ Boxkite  │  │ Launakal │    (upload once) │
│  └────┬─────┘  └────┬─────┘  └──────────┘                  │
└───────┼──────────────┼──────────────────────────────────────┘
        │              │
        ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│              WORKFLOW CANVAS (React Flow)                    │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │  Data     │───▶│  Site    │───▶│Reanalysis│              │
│  │ (group)   │    │ (group)  │    │ (group)  │              │
│  └──────────┘    └──────────┘    └─────┬─────┘              │
│                                        │                    │
│                                   ┌────┴────┐  FORK POINT   │
│                              ┌────▼───┐ ┌───▼────┐          │
│                              │ LTC-A  │ │ LTC-B  │          │
│                              │speedsrt│ │var_rat │          │
│                              └───┬────┘ └───┬────┘          │
│                              ┌───▼────┐ ┌───▼────┐          │
│                              │Results │ │Results │          │
│                              │  (A)   │ │  (B)   │          │
│                              └────────┘ └────────┘          │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              COMPARISON DASHBOARD                            │
│  ┌─────────┬─────────┬─────────┬─────────┐                  │
│  │ Branch A│ Branch B│ Branch C│ Branch D│   (up to 4)      │
│  ├─────────┼─────────┼─────────┼─────────┤                  │
│  │ P50: ..│ P50: ..│         │         │                  │
│  │ P75: ..│ P75: ..│         │         │                  │
│  ├─────────┴─────────┴─────────┴─────────┤                  │
│  │  Overlaid Weibull / Windrose / LTC    │                  │
│  └───────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Key Entities

| Entity | Description |
|--------|-------------|
| **Dataset** | An uploaded CSV+JSON pair. Lives in a shared pool. Immutable after upload. |
| **Workflow** | A DAG of connected nodes. Has a `main` branch by default. |
| **Branch** | A fork of a workflow. Shares ancestor nodes, diverges from fork point. Max 4 per workflow. |
| **GroupNode** | A collapsible container (Data, Site, Reanalysis, LTC, Results). |
| **OperationNode** | A single atomic operation inside a group (e.g., "Apply Range Check", "Calculate Shear"). |
| **Edge** | A directed connection between nodes. Carries data dependency. |
| **Execution** | A run of a branch. Records status per node (pending → running → done / error). |

---

## 3. Node Catalog

### 3.1 Group Nodes (Collapsible)

Each group node contains a configurable set of operation sub-nodes. When collapsed, shows a summary badge (e.g., "3/5 ops complete"). When expanded, reveals the individual operation nodes inside.

#### Group: **Dataset Source**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Select Dataset | — | `timeseries_df`, `sensor_mapping` | Dataset from pool picker |
| Parse Timeseries | raw CSV | `timeseries_df` | timestamp_col, separator, skip_rows |
| Parse Data Model | raw JSON | `sensor_mapping`, `heights` | — |
| Inspect Coverage | `timeseries_df`, `sensor_mapping` | `coverage_table` | — |

#### Group: **Data Cleaning**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Range Check | `timeseries_df` | `cleaned_df` | sensor, min, max |
| Icing Filter | `timeseries_df` | `cleaned_df` | sensor, temp_threshold_c |
| Stuck Sensor | `timeseries_df` | `cleaned_df` | sensor, consecutive_count |
| Tower Shadow | `timeseries_df` | `cleaned_df` | sensor, exclude_sectors [from, to] |
| Spike Filter | `timeseries_df` | `cleaned_df` | sensor, window_size, sigma_threshold |
| Gap Fill | `timeseries_df` | `cleaned_df` | — |
| Custom Exclude | `timeseries_df` | `cleaned_df` | start_date, end_date |

#### Group: **Vertical Extrapolation (Site)**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Calculate Shear | `cleaned_df`, `sensor_mapping` | `shear_timeseries_df` | height_sensors (multi-select) |
| Build Shear Table | `shear_timeseries_df` | `shear_table` (12×24) | aggregation: mean / median / momm |
| Extrapolate to Hub | `cleaned_df`, `shear_table` | `hub_height_series` | hub_height_m, shear_model: power_law / log_law |

#### Group: **Reanalysis**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Find ERA5 Nodes | config.location | `era5_nodes` (4 grid points) | latitude, longitude |
| Extract ERA5 | `era5_nodes` | `era5_data` (per node) | start_date, end_date |
| Interpolate to Site | `era5_data` | `era5_interpolated_df` | method: idw / linear |
| Homogeneity Test | `era5_interpolated_df` | `homogeneity_result` | method: annual / monthly |
| Apply Cutoff | `era5_interpolated_df` | `era5_trimmed_df` | cutoff_year |

#### Group: **Long-Term Correction (LTC)**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Linear Least Squares | `hub_height_series`, `era5_trimmed_df` | `ltc_result` | short_col, long_col |
| Total Least Squares | `hub_height_series`, `era5_trimmed_df` | `ltc_result` | short_col, long_col |
| Speedsort | `hub_height_series`, `era5_trimmed_df` | `ltc_result` | short_col, long_col, dir cols |
| Variance Ratio | `hub_height_series`, `era5_trimmed_df` | `ltc_result` | short_col, long_col |
| XGBoost | `hub_height_series`, `era5_trimmed_df` | `ltc_result` | short_col, long_col |
| Ensemble Blend | multiple `ltc_result` | `ensemble_df` | measured_col |

#### Group: **Post-Processing & Results**
| Sub-Node | Inputs | Outputs | Config |
|----------|--------|---------|--------|
| Clipping Analysis | `ensemble_df` or `ltc_result` | `clipping_report` | speed_col, source |
| Uncertainty (TR6) | `ltc_result`, config | `uncertainty` (P50/P75/P90/P99) | meas_unc%, shear_method, iav%, etc. |
| Plot: Windrose | data | Plotly JSON | — |
| Plot: Weibull | data | Plotly JSON | — |
| Plot: LTC Comparison | `ltc_results` | Plotly JSON | — |
| Plot: Uncertainty Tornado | `uncertainty` | Plotly JSON | — |
| Export CSV | any result df | downloadable file | — |

### 3.2 WindKit Node Catalog (142 Tools)

All 142 WindKit tools are exposed as individual draggable operation nodes, organized into WindKit-specific groups. All WindKit tools accept/return serialized xarray Datasets/DataArrays, GeoJSON, or JSON arrays as strings.

#### Group: **WindKit — Wind (13 tools)**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Wind Speed | u, v | Speed from u,v components |
| Wind Direction | u, v | Direction from u,v components |
| Wind Speed & Direction | u, v | Both speed and direction |
| Wind Vectors | ws, wd | u,v vectors from speed/direction |
| Direction Difference | wd_obs, wd_mod | Circular distance between directions |
| Direction to Sector | wd, sectors=12, output_type | Convert to sector indices |
| V-Interp Direction | wind_direction_data, height | Vertical interpolation of direction |
| V-Interp Speed | wind_speed_data, height, method=log | Vertical interpolation of speed |
| REWS | wind_speed_data, wind_direction_data, hub_height, rotor_diameter | Rotor Equivalent Wind Speed |
| Shear Extrapolate | wind_speed_data, height, method=power_law | Shear-extrapolate to new heights |
| Shear Exponent | wind_speed_data | Compute shear exponent from profiles |
| Veer Extrapolate | wind_direction_data, height | Extrapolate direction with veer |
| Wind Veer | wind_direction_data | Calculate wind veer with height |

#### Group: **WindKit — Climate (30 tools)**

**Time Series Wind Climate (TSWC) — 6 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate TSWC | dataset | Validate TSWC Dataset |
| Is TSWC | dataset | Check if valid TSWC |
| Create TSWC | we, sn, h, crs, freq | Create empty TSWC |
| Read TSWC | filename, file_format | Read TSWC from file |
| TSWC from DataFrame | dataframe_json, we, sn, h, crs | Create TSWC from DataFrame |
| TSWC Resample | dataset, freq | Resample TSWC to frequency |

**Binned Wind Climate (BWC) — 8 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate BWC | dataset | Validate BWC Dataset |
| Is BWC | dataset | Check if valid BWC |
| Create BWC | we, sn, h, crs, n_sectors, n_wsbins | Create empty BWC |
| Read BWC | filename, crs, file_format | Read BWC from file |
| BWC from TSWC | tswc_dataset, wsbin_width, n_wsbins, n_sectors | Create BWC from TSWC |
| BWC to File | dataset, filename, file_format | Write BWC to file |
| Combine BWCs | datasets | Combine multiple BWCs |
| Weibull Fit (BWC) | bwc_dataset, include_met_fields | Fit Weibull from BWC |

**Weibull Wind Climate (WWC) — 8 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate WWC | dataset | Validate WWC Dataset |
| Is WWC | dataset | Check if valid WWC |
| Create WWC | we, sn, h, crs, n_sectors | Create empty WWC |
| Read WWC | filename, file_format | Read WWC from file |
| Read Multi-File WWC | filenames, file_format | Read multiple WWC files |
| WWC to File | dataset, filename, file_format | Write WWC to file |
| WWC to BWC | dataset, ws_bins | Convert WWC to BWC |
| Weibull Combined | wwc_dataset | Get combined Weibull A,k |

**Generalized Wind Climate (GWC) — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate GWC | dataset | Validate GWC Dataset |
| Is GWC | dataset | Check if valid GWC |
| Create GWC | we, sn, h, crs, n_sectors | Create empty GWC |
| Read GWC | filename, crs, file_format | Read GWC from file |
| GWC to File | dataset, filename, file_format | Write GWC to file |

**Geostrophic Wind Climate (GeoWC) — 2 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate GeoWC | dataset | Validate GeoWC Dataset |
| Is GeoWC | dataset | Check if valid GeoWC |

#### Group: **WindKit — Climate Statistics (7 tools)**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Create Met Fields | we, sn, h, crs, n_sectors | Create met_fields dataset |
| Mean WS Moment | wc_dataset, moment=1, bysector | N-th moment of wind speed |
| Wind Speed CDF | wc_dataset, bysector | Cumulative distribution function |
| Frequency > Mean | wc_dataset, bysector | Fraction of time above mean |
| Mean Wind Speed | wc_dataset, bysector | Mean wind speed from climate |
| Mean Power Density | wc_dataset, bysector, air_density=1.225 | Power density (W/m²) |
| Cross Predictions | wcs_dataset, wcs_src_dataset | Cross-prediction between climates |

#### Group: **WindKit — Topography (18 tools)**

**Landcover — 8 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Get Landcover Table | dataset, table | Get LandCoverTable from map |
| Add Landcover Table | geojson_data, lctable | Attach LandCoverTable to GeoDF |
| Roughness→Landcover | roughness_dataset | Convert roughness to landcover map |
| Landcover→Roughness | geojson_data, lctable | Convert landcover to roughness map |
| Read Roughness Map | filename, crs | Read roughness map from file |
| Read Landcover Map | filename, crs | Read landcover map from file |
| Write Landcover Map | geojson_data, filename | Write landcover map to file |
| Write Roughness Map | geojson_data, filename | Write roughness map to file |

**Elevation & Raster/Vector — 6 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Read Elevation Map | filename, crs | Read elevation raster |
| Write Elevation Map | dataset, filename | Write elevation raster |
| Create Raster Map | we, sn, h, crs, resolution | Create raster DataArray |
| Get Raster Map | bbox, dataset=copernicus_dem_30 | Download DEM raster |
| Create Vector Map | bbox, map_type=elevation | Create vector map |
| Get Vector Map | bbox, dataset, source | Download vector map |

**Map Conversion — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Lines→Polygons | geojson_data, check_errors | Convert line geometries to polygons |
| Polygons→Lines | geojson_data, lctable, map_type | Convert polygon geometries to lines |
| Snap to Layer | geojson_data, tolerance | Snap geometries to nearest |
| Check Dead Ends | geojson_data | Detect dead-end lines |
| Check Lines Cross | geojson_data | Detect crossing lines |

#### Group: **WindKit — Wind Farm (16 tools)**

**Wind Turbines — 6 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate Wind Turbines | dataset | Validate wind turbine dataset |
| Is Wind Turbines | dataset | Check if valid wind turbines |
| Check WTG Keys | wind_turbines_dataset, wtg_dict | Validate WTG key mapping |
| Turbines from DataFrame | dataframe_json | Create wind turbines from DF |
| Turbines from Arrays | we, sn, h, crs, wtg_keys | Create from coordinate arrays |
| Turbines to GeoDataFrame | dataset | Convert to GeoDataFrame |

**WTG Curves — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate WTG | dataset | Validate WTG dataset |
| Is WTG | dataset | Check if valid WTG |
| Estimate Regulation | wtg_dataset | Estimate regulation type (stall/pitch) |
| Read WTG | filename, file_format | Read WTG from file |
| WTG Power | wtg_dataset, ws, interp_method | Get power output curve |
| WTG Cp | wtg_dataset, ws, air_density | Get power coefficient curve |
| WTG Ct | wtg_dataset, ws, interp_method | Get thrust coefficient curve |

**Losses & Uncertainty — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Validate Uncertainty Table | table_json | Validate uncertainty table schema |
| Get Uncertainty Table | table_name | Get standard uncertainty template |
| Total Uncertainty | table_json | Calculate RSS total uncertainty |
| Uncertainty Table Summary | table_json | Print formatted summary |
| Total Uncertainty Factor | table_json | Calculate P-factor from table |

#### Group: **WindKit — Spatial (31 tools)**

**CRS — 3 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Get CRS | dataset | Get CRS from spatial object |
| Set CRS | dataset, crs | Set CRS on spatial object |
| CRS Are Equal | dataset_a, dataset_b | Check if two CRS match |

**Create Spatial Objects — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Create Dataset | we, sn, h, crs | Create dataset from locations |
| Create Raster | we, sn, crs | Create raster grid |
| Create Point | we, sn, h, crs | Create single point |
| Create Stacked Point | we, sn, h, crs | Create multi-height point |
| Create Cuboid | we, sn, h, crs | Create 3D cuboid |

**Validate — 4 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Is Point | dataset | Check if point type |
| Is Stacked Point | dataset | Check if stacked point |
| Is Cuboid | dataset | Check if cuboid type |
| Is Raster | dataset | Check if raster type |

**Convert — 6 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| To Point | dataset | Convert to point |
| To Cuboid | dataset | Convert to cuboid |
| To Stacked Point | dataset | Convert to stacked point |
| To Raster | dataset | Convert to raster |
| GeoDF→Dataset | geojson_data, height, struct | GeoDataFrame to xarray |
| Dataset→GeoDF | dataset, include_height | xarray to GeoDataFrame |

**Interpolation — 3 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Interp Structured Like | source_dataset, target_dataset | Interpolate to structured grid |
| Interp Unstructured | dataset, we, sn | Interpolate to unstructured points |
| Interp Unstructured Like | source_dataset, target_dataset | Interpolate to target locations |

**Comparison — 3 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Are Spatially Equal | dataset_a, dataset_b | Check spatial equality |
| Equal Spatial Shape | dataset_a, dataset_b | Check shape match |
| Covers | dataset_a, dataset_b | Check if A covers B |

**Operations — 7 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Clip | dataset, mask_geojson | Clip with GeoJSON mask |
| Clip with Margin | dataset, clipper_dataset, margin | Clip with buffer margin |
| Mask | dataset, mask_geojson | Apply spatial mask |
| Nearest Points | ref_dataset, target_dataset | Find nearest point pairs |
| Reproject | dataset, to_crs | Reproject coordinates only |
| Warp | dataset, to_crs, resolution | Warp with data interpolation |
| Count Spatial Points | dataset | Count spatial points |

#### Group: **WindKit — MCP / LTC (2 tools)**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| LinReg MCP | measured_dataset, reference_dataset, ws_cutoff, n_sectors | Linear regression MCP |
| VarRat MCP | measured_dataset, reference_dataset, fit_intercept, ws_cutoff, n_sectors | Variance ratio MCP |

#### Group: **WindKit — Weibull & Utilities (14 tools)**

**Weibull Distribution — 8 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Fit Weibull (M1,M3,FGTM) | m1, m3, fgtm | Fit from moments + freq>mean |
| Fit Weibull (M1,M3) | m1, m3 | Fit from moments only |
| Fit Weibull (k, sumlog) | sumlogm | Fit shape parameter |
| Weibull Moment | A, k, n=1 | Calculate n-th moment |
| Weibull PDF | A, k, x | Probability density function |
| Weibull CDF | A, k, x | Cumulative distribution function |
| Weibull Freq>Mean | A, k | Fraction of time above mean |
| Weibull Probability | A, k, speed_range | Probability for speed bins |

**I/O & Coordinates — 5 tools**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Read CFDRes | filename, crs | Read WAsP .cfdres file |
| Create Sector Coords | bins=12, start=0 | Create sector coordinate array |
| Create WSBin Coords | bins=30, width=1.0 | Create wind speed bin coords |
| Get ERA5 | datetime_range, bbox, source | Download ERA5 reanalysis |
| Get Tutorial Data | name | Download WindKit tutorial dataset |
| Load Tutorial Data | name | Load cached tutorial dataset |

#### Group: **WindKit — Plotting (9 tools)**
| Sub-Node | Key Params | Description |
|----------|-----------|-------------|
| Plot Histogram | bwc_dataset, style=bar, weibull | Speed histogram from BWC |
| Plot Histogram Lines | bwc_dataset | Distribution & wind rose lines |
| Plot Operational Curves | wtg_dataset | WTG power/thrust curves |
| Plot Raster | data_array, contour | Raster map visualization |
| Plot Roughness Rose | dataset, style=bar | Roughness rose diagram |
| Plot Time Series | tswc_dataset, range_slider | Interactive time series |
| Plot Vertical Profile | data_array | Vertical profile chart |
| Plot Wind Rose | bwc_dataset, wind_speed_bins, style | Wind rose diagram |
| Plot Landcover Map | geojson_data, column | Interactive landcover map |

---

## 4. Frontend Architecture

### 4.1 New Component Tree

```
<App>
├── <WorkflowDesigner>                    ← NEW: replaces AppShell
│   ├── <TopBar>                          ← project name, session, run controls
│   │   ├── <RunControls>                 ← [▶ Run All] [⏭ Step] [⏸ Pause] [🔀 Fork]
│   │   ├── <BranchTabs>                  ← [main] [branch-A] [branch-B] [+ Fork]
│   │   └── <CompareButton>              ← opens comparison dashboard
│   │
│   ├── <LeftPanel>                       ← node palette + dataset pool
│   │   ├── <NodePalette>                 ← draggable node catalog (accordion by group)
│   │   │   ├── <PaletteGroup label="Dataset Source">
│   │   │   ├── <PaletteGroup label="Data Cleaning">
│   │   │   ├── <PaletteGroup label="Vertical Extrapolation">
│   │   │   ├── <PaletteGroup label="Reanalysis">
│   │   │   ├── <PaletteGroup label="LTC">
│   │   │   ├── <PaletteGroup label="Post-Processing">
│   │   │   ├── <PaletteGroup label="WindKit — Wind">
│   │   │   ├── <PaletteGroup label="WindKit — Climate">
│   │   │   ├── <PaletteGroup label="WindKit — Climate Stats">
│   │   │   ├── <PaletteGroup label="WindKit — Topography">
│   │   │   ├── <PaletteGroup label="WindKit — Wind Farm">
│   │   │   ├── <PaletteGroup label="WindKit — Spatial">
│   │   │   ├── <PaletteGroup label="WindKit — MCP/LTC">
│   │   │   ├── <PaletteGroup label="WindKit — Weibull & Util">
│   │   │   └── <PaletteGroup label="WindKit — Plotting">
│   │   │
│   │   └── <DatasetPool>                ← list of uploaded datasets, drag to canvas
│   │       ├── <DatasetCard name="HornsRev" />
│   │       ├── <DatasetCard name="Boxkite" />
│   │       └── <UploadButton />
│   │
│   ├── <Canvas>                          ← React Flow canvas (center)
│   │   ├── <ReactFlow>
│   │   │   ├── <GroupNode />             ← collapsible container
│   │   │   ├── <OperationNode />         ← individual op with status badge
│   │   │   ├── <DatasetNode />           ← linked dataset source
│   │   │   ├── <ForkNode />              ← visual fork indicator
│   │   │   └── <CustomEdge />            ← animated data flow edge
│   │   ├── <MiniMap />
│   │   ├── <Controls />                  ← zoom, fit, lock
│   │   └── <Background />
│   │
│   └── <RightPanel>                      ← node inspector / config editor
│       ├── <NodeInspector>               ← config form for selected node
│       │   ├── <NodeHeader>              ← icon, name, status, run button
│       │   ├── <ConfigForm>              ← dynamic form fields per node type
│       │   ├── <InputPorts>              ← shows what flows in
│       │   ├── <OutputPreview>           ← data preview table / mini plot
│       │   └── <ExecutionLog>            ← stdout, timing, errors
│       └── <RunConfigSummary>            ← collapsible runconfig viewer
│
├── <ComparisonDashboard>                 ← NEW: modal/fullscreen overlay
│   ├── <BranchSelector>                  ← checkboxes: which branches to compare
│   ├── <MetricsTable>                    ← side-by-side P50/P75/P90 etc.
│   │   ├── columns: [Metric, Branch A, Branch B, Branch C, Branch D, Δ max]
│   │   └── rows: [LT mean speed, P50, P75, P90, P99, total_unc%, each component]
│   ├── <OverlayPlots>                    ← multi-trace interactive plots
│   │   ├── <WeibullOverlay />            ← N Weibull curves on one chart
│   │   ├── <WindroseOverlay />           ← side-by-side windroses (up to 4)
│   │   ├── <LtcScatterOverlay />         ← regression lines overlaid
│   │   ├── <UncertaintyTornado />        ← grouped bar chart, one group per branch
│   │   └── <TimeseriesOverlay />         ← corrected series overlaid
│   ├── <ConfigDiff>                      ← tree diff of runconfig between branches
│   │   └── highlights only changed keys (e.g., hub_height: 100→150)
│   └── <ExportComparison>               ← download as PDF / CSV / JSON
│
└── <DatasetUploadDialog>                 ← modal for uploading new datasets to pool
    ├── <FileDropzone accept=".csv,.json,.xlsx" />
    ├── <ParsingOptions>                  ← timestamp format, separator, skip rows
    └── <DataPreview>                     ← first 20 rows + column types
```

### 4.2 React Flow Node Types

```typescript
// ── Node Types ──────────────────────────────────────────

type NodeStatus = "idle" | "pending" | "running" | "done" | "error" | "skipped";

type DatasetNodeData = {
  kind: "dataset";
  datasetId: string;          // references pool
  datasetName: string;
  sensorCount: number;
  coveragePct: number;
};

type GroupNodeData = {
  kind: "group";
  groupType: "data" | "cleaning" | "site" | "reanalysis" | "ltc" | "results";
  label: string;
  collapsed: boolean;
  childNodeIds: string[];     // operation nodes inside
  status: NodeStatus;         // aggregate: worst child status
};

type OperationNodeData = {
  kind: "operation";
  operationType: string;      // e.g., "range_check", "calculate_shear"
  label: string;
  config: Record<string, unknown>;  // user-configured params
  status: NodeStatus;
  result?: {
    summary: string;          // e.g., "127 records removed"
    timing_ms: number;
    output_keys: string[];    // what data this node produces
  };
  error?: string;
};

type ForkNodeData = {
  kind: "fork";
  branchIds: string[];        // which branches diverge here
};

// ── Edge Types ──────────────────────────────────────────

type DataFlowEdge = {
  id: string;
  source: string;
  target: string;
  animated: boolean;          // true while data is flowing
  data: {
    dataKeys: string[];       // what data passes through this edge
    status: "idle" | "active" | "done";
  };
};
```

### 4.3 Workflow State (New Zustand Store)

```typescript
type WorkflowState = {
  // ── Workflow identity ──
  workflowId: string;
  workflowName: string;

  // ── Branches ──
  branches: Branch[];               // max 4
  activeBranchId: string;           // which branch is shown on canvas

  // ── Canvas state per branch ──
  branchStates: Record<string, BranchState>;

  // ── Dataset Pool ──
  datasets: DatasetEntry[];

  // ── Execution ──
  executionMode: "auto" | "manual";
  isExecuting: boolean;
  executionQueue: string[];         // node IDs to run (topological order)

  // ── Comparison ──
  comparisonOpen: boolean;
  comparedBranchIds: string[];      // which branches are being compared

  // ── Actions ──
  addNode: (branchId: string, node: WorkflowNode) => void;
  removeNode: (branchId: string, nodeId: string) => void;
  connectNodes: (branchId: string, edge: DataFlowEdge) => void;
  updateNodeConfig: (branchId: string, nodeId: string, config: Record<string, unknown>) => void;
  forkBranch: (fromBranchId: string, forkNodeId: string, name: string) => Branch;
  deleteBranch: (branchId: string) => void;
  executeWorkflow: (branchId: string) => Promise<void>;
  executeNode: (branchId: string, nodeId: string) => Promise<void>;
  addDataset: (dataset: DatasetEntry) => void;
  toggleComparison: () => void;
};

type Branch = {
  id: string;
  name: string;
  color: string;                    // visual color for this branch
  forkPoint: {
    parentBranchId: string;
    nodeId: string;                 // which node was the fork point
  } | null;                         // null = main branch
  sessionId: string;                // backend session ID for this branch
  createdAt: string;
};

type BranchState = {
  nodes: WorkflowNode[];
  edges: DataFlowEdge[];
  viewport: { x: number; y: number; zoom: number };
};

type DatasetEntry = {
  id: string;
  name: string;
  timeseriesFile: string;
  datamodelFile: string;
  uploadedAt: string;
  sensorCount: number;
  dateRange: { start: string; end: string };
  coverageSummary: Record<string, number>;  // sensor → coverage %
};
```

---

## 5. Backend Changes

### 5.1 New API Endpoints

#### Dataset Pool

```
POST   /api/datasets                  Upload dataset (CSV + JSON) to shared pool
GET    /api/datasets                  List all datasets in pool
GET    /api/datasets/{id}             Get dataset metadata + preview
DELETE /api/datasets/{id}             Remove dataset from pool
```

#### Workflow Management

```
POST   /api/workflows                 Create new workflow
GET    /api/workflows                 List all workflows
GET    /api/workflows/{id}            Get workflow (branches, nodes, edges)
PUT    /api/workflows/{id}            Save workflow state (auto-save on change)
DELETE /api/workflows/{id}            Delete workflow + all branches
```

#### Branch Management

```
POST   /api/workflows/{id}/branches                Fork a new branch
GET    /api/workflows/{id}/branches                List branches
GET    /api/workflows/{id}/branches/{bid}          Get branch state
DELETE /api/workflows/{id}/branches/{bid}           Delete branch
POST   /api/workflows/{id}/branches/{bid}/fork      Fork from existing branch
```

#### Execution

```
POST   /api/workflows/{id}/branches/{bid}/execute           Execute entire branch pipeline
POST   /api/workflows/{id}/branches/{bid}/execute/{nodeId}  Execute single node
GET    /api/workflows/{id}/branches/{bid}/status             Execution status per node
POST   /api/workflows/{id}/branches/{bid}/stop               Cancel running execution
```

#### Comparison

```
POST   /api/workflows/{id}/compare    Compare selected branches
  Request:  { branch_ids: ["main", "branch-A", "branch-B"] }
  Response: {
    metrics: [
      { name: "LT Mean Speed", unit: "m/s", values: { "main": 8.42, "branch-A": 7.91 } },
      { name: "P50", unit: "–", values: { "main": 1.000, "branch-A": 1.000 } },
      { name: "P75", unit: "–", values: { "main": 0.942, "branch-A": 0.938 } },
      ...
    ],
    config_diff: {
      "main↔branch-A": [
        { key: "hub_height_m", a: 150, b: 120 },
        { key: "ltc_source", a: "speedsort", b: "variance_ratio" },
      ]
    },
    plots: {
      weibull: { /* Plotly JSON with N traces */ },
      windrose: [ /* one Plotly JSON per branch */ ],
      ltc_scatter: { /* overlaid */ },
      uncertainty_tornado: { /* grouped bars */ },
    }
  }
```

### 5.2 New Backend Models

```python
# ── server/state/workflow.py ──

@dataclass
class WorkflowNode:
    id: str
    kind: Literal["dataset", "group", "operation", "fork"]
    operation_type: str | None       # e.g., "range_check", "calculate_shear"
    label: str
    config: dict[str, Any]
    position: dict[str, float]       # { x, y } on canvas
    parent_group_id: str | None      # if inside a group node
    status: Literal["idle", "pending", "running", "done", "error", "skipped"]
    result: dict | None
    error: str | None

@dataclass
class WorkflowEdge:
    id: str
    source: str
    target: str
    data_keys: list[str]

@dataclass
class Branch:
    id: str
    name: str
    color: str
    fork_point: dict | None          # { parent_branch_id, node_id }
    session_id: str                  # links to backend SessionState
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    created_at: str

@dataclass
class Workflow:
    id: str
    name: str
    branches: list[Branch]           # max 4
    dataset_ids: list[str]           # which datasets are used
    created_at: str
    updated_at: str
```

### 5.3 Session Forking (Key Implementation Detail)

When a user forks a branch, the backend:

1. **Creates a new session** (`SessionManager.create_session()`)
2. **Deep-copies ancestor state** from the parent branch's session up to the fork node:
   - `timeseries_df`, `sensor_mapping` (if fork is after Data)
   - `shear_timeseries_df`, `shear_table` (if fork is after Site)
   - `era5_interpolated_df` (if fork is after Reanalysis)
   - `runconfig` (always copied, then user modifies diverging keys)
3. **Marks shared ancestor nodes** as "done" in the new branch (no re-execution)
4. **Marks downstream nodes** from fork point as "idle" (need fresh execution)

```python
# Pseudocode
def fork_branch(workflow_id: str, parent_branch_id: str, fork_node_id: str, name: str) -> Branch:
    parent = get_branch(workflow_id, parent_branch_id)
    parent_session = session_manager.get_session(parent.session_id)

    # Create new session with copied state
    new_session = session_manager.create_session()
    copy_session_state(parent_session, new_session, up_to_node=fork_node_id)

    # Build new branch: ancestor nodes = done, downstream = idle
    ancestor_nodes = get_ancestors(parent, fork_node_id)  # topological
    downstream_nodes = get_descendants(parent, fork_node_id)

    new_branch = Branch(
        id=generate_id(),
        name=name,
        color=next_branch_color(),
        fork_point={"parent_branch_id": parent_branch_id, "node_id": fork_node_id},
        session_id=new_session.session_id,
        nodes=[
            *[n.copy(status="done") for n in ancestor_nodes],
            *[n.copy(status="idle") for n in downstream_nodes],
        ],
        edges=parent.edges.copy(),
    )
    return new_branch
```

### 5.4 Execution Engine

```python
# ── server/core/executor.py ──

class WorkflowExecutor:
    """Executes a branch's nodes in topological order."""

    async def execute_branch(self, branch: Branch) -> None:
        """Auto-pipeline: run all idle/pending nodes in dependency order."""
        ordered = topological_sort(branch.nodes, branch.edges)
        for node in ordered:
            if node.status in ("done", "skipped"):
                continue
            await self.execute_node(branch, node)

    async def execute_node(self, branch: Branch, node: WorkflowNode) -> None:
        """Execute a single operation node."""
        node.status = "running"
        try:
            session = session_manager.get_session(branch.session_id)
            result = await self._dispatch(node.operation_type, node.config, session)
            node.result = result
            node.status = "done"
        except Exception as e:
            node.error = str(e)
            node.status = "error"
            # In auto mode, stop pipeline. Manual mode continues.
            raise

    async def _dispatch(self, op_type: str, config: dict, session: SessionState) -> dict:
        """Route operation to the correct tool function."""
        router = {
            "parse_timeseries": tools.parse_timeseries,
            "parse_datamodel": tools.parse_datamodel,
            "range_check": tools.apply_cleaning_rule,
            "icing_filter": tools.apply_cleaning_rule,
            "calculate_shear": tools.calculate_shear_timeseries,
            "build_shear_table": tools.build_shear_table,
            "extrapolate_to_hub": tools.extrapolate_to_hub_height,
            "find_era5_nodes": tools.find_era5_nodes,
            "extract_era5": tools.extract_era5_data,
            "interpolate_era5": tools.interpolate_era5_to_site,
            "linear_least_squares": tools.run_ltc,
            "total_least_squares": tools.run_ltc,
            "speedsort": tools.run_ltc,
            "variance_ratio": tools.run_ltc,
            "xgboost": tools.run_ltc,
            "ensemble_blend": tools.run_ensemble,
            "calculate_uncertainty": tools.calculate_uncertainty,
            # ... all operations mapped
        }
        handler = router[op_type]
        return await handler(config, session)
```

---

## 6. UI/UX Design Details

### 6.1 Canvas Interactions

| Action | Behavior |
|--------|----------|
| **Drag from palette** | Ghost node follows cursor → drop on canvas to place |
| **Connect nodes** | Drag from output port (●) to input port (○) of another node → edge created |
| **Select node** | Click → right panel shows inspector with config form |
| **Move node** | Drag on canvas. Group nodes move children with them. |
| **Collapse group** | Double-click group header → hides children, shows summary badge |
| **Expand group** | Double-click collapsed group → shows children |
| **Delete node** | Select → Delete key or right-click → "Remove" |
| **Fork** | Right-click any "done" node → "Fork from here" → name dialog → new branch tab |
| **Pan/zoom** | Scroll to zoom, drag background to pan, minimap in corner |
| **Run all** | Top bar ▶ button → auto-pipeline executes in topological order |
| **Step** | Top bar ⏭ button → executes next pending node only |
| **Keyboard shortcuts** | `Space` = run/pause, `F` = fit view, `Del` = remove, `Ctrl+Z` = undo |

### 6.2 Node Visual Design

```
┌─────────────────────────────┐
│ ● [icon]  Range Check    ✓  │  ← status badge (✓ done, ⟳ running, ✗ error)
│─────────────────────────────│
│ Sensor: Spd_100m            │  ← key config summary (2 lines max)
│ Range: 0.3 – 40.0 m/s      │
│─────────────────────────────│
│ ○ timeseries_df     ● out   │  ← input/output ports with labels
└─────────────────────────────┘
     Color: left border stripe matches branch color
     States:
       idle   → gray border, dim
       pending → yellow pulse
       running → blue animated border
       done   → green ✓
       error  → red ✗, click to see error
```

### 6.3 Branch Tabs

```
┌──────────────────────────────────────────────────────────┐
│ [main ●] [Branch A ●] [Branch B ●] [+ Fork]  │ 🔀 Compare│
│  ═══════                                       │          │
└──────────────────────────────────────────────────────────┘
  ● = branch color dot
  Underline = active branch
  Click tab = switch canvas to that branch's nodes/edges
  + Fork = fork from currently selected node (or last done node)
  Compare = opens ComparisonDashboard with all executed branches
```

### 6.4 Comparison Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│  COMPARISON: ☑ main  ☑ Branch A  ☐ Branch B  ☐ Branch C     │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─ CONFIG DIFF ─────────────────────────────────────────┐   │
│  │ Parameter           │ main      │ Branch A  │ Δ       │   │
│  │ hub_height_m        │ 150       │ 120       │ -30     │   │
│  │ shear_model         │ power_law │ log_law   │ changed │   │
│  │ ltc_source          │ speedsort │ var_ratio │ changed │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ KEY METRICS ─────────────────────────────────────────┐   │
│  │ Metric              │ main   │ Br-A   │ Δ      │ Δ%   │   │
│  │ LT Mean Speed (m/s) │ 8.42   │ 7.91   │ -0.51  │ -6.1%│   │
│  │ P50 factor          │ 1.000  │ 1.000  │  0     │  0%  │   │
│  │ P75 factor          │ 0.942  │ 0.938  │ -0.004 │-0.4% │   │
│  │ P90 factor          │ 0.885  │ 0.879  │ -0.006 │-0.7% │   │
│  │ P99 factor          │ 0.816  │ 0.808  │ -0.008 │-1.0% │   │
│  │ Total unc (%)       │ 8.7    │ 9.2    │ +0.5   │+5.7% │   │
│  │ Meas unc (%)        │ 2.0    │ 2.0    │  0     │  0%  │   │
│  │ Vert unc (%)        │ 3.5    │ 4.1    │ +0.6   │+17%  │   │
│  │ MCP unc (%)         │ 2.1    │ 2.5    │ +0.4   │+19%  │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ PLOTS ───────────────────────────────────────────────┐   │
│  │  [Weibull] [Windrose] [LTC Scatter] [Uncertainty]     │   │
│  │                                                       │   │
│  │  ┌───────────────────────────────────────────────┐    │   │
│  │  │  Weibull Distribution (2 traces: main, Br-A)  │    │   │
│  │  │         ╱╲                                    │    │   │
│  │  │        ╱  ╲    ╱╲                             │    │   │
│  │  │  ─────╱────╲──╱──╲───────                     │    │   │
│  │  │       main    Br-A                            │    │   │
│  │  └───────────────────────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  [Export PDF]  [Export CSV]  [Export JSON]                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. Data Flow & Dependency Resolution

### 7.1 Port System

Each operation node declares **input ports** (what data it needs) and **output ports** (what data it produces). The canvas enforces that edges only connect compatible ports.

```typescript
const NODE_PORT_REGISTRY: Record<string, { inputs: string[], outputs: string[] }> = {
  "select_dataset":     { inputs: [],                         outputs: ["timeseries_df", "sensor_mapping"] },
  "range_check":        { inputs: ["timeseries_df"],          outputs: ["timeseries_df"] },
  "icing_filter":       { inputs: ["timeseries_df"],          outputs: ["timeseries_df"] },
  "calculate_shear":    { inputs: ["timeseries_df", "sensor_mapping"], outputs: ["shear_timeseries_df"] },
  "build_shear_table":  { inputs: ["shear_timeseries_df"],    outputs: ["shear_table"] },
  "extrapolate_to_hub": { inputs: ["timeseries_df", "shear_table"],   outputs: ["hub_height_series"] },
  "find_era5_nodes":    { inputs: [],                         outputs: ["era5_nodes"] },
  "extract_era5":       { inputs: ["era5_nodes"],             outputs: ["era5_data"] },
  "interpolate_era5":   { inputs: ["era5_data"],              outputs: ["era5_interpolated_df"] },
  "speedsort":          { inputs: ["hub_height_series", "era5_interpolated_df"], outputs: ["ltc_result"] },
  "variance_ratio":     { inputs: ["hub_height_series", "era5_interpolated_df"], outputs: ["ltc_result"] },
  "ensemble_blend":     { inputs: ["ltc_result"],             outputs: ["ensemble_df"] },  // multi-input
  "calculate_uncertainty": { inputs: ["ltc_result"],          outputs: ["uncertainty"] },
  // ...
};
```

### 7.2 Validation Rules

| Rule | Enforcement |
|------|-------------|
| No cycles | Topological sort rejects cycles at edge creation time |
| Required inputs | Node shows warning if not all input ports are connected |
| Type compatibility | Only connect matching data types (port name match) |
| Max 4 branches | Fork button disabled when 4 branches exist |
| Fork requires execution | Can only fork from "done" nodes |
| Single dataset per branch | Each branch starts from exactly one dataset node |

### 7.3 Dirty Propagation

When a user changes config on a node that was already "done":
1. Mark that node as "idle" (needs re-execution)
2. Recursively mark all **downstream** nodes as "idle"
3. Show yellow "stale" indicator on affected nodes
4. Running the pipeline only re-executes stale nodes (skip still-valid ancestors)

---

## 8. Shared Dataset Pool

### 8.1 Storage

```
data/
├── datasets/                         ← NEW: shared pool
│   ├── {dataset_id}/
│   │   ├── metadata.json             ← name, upload time, sensors, date range
│   │   ├── timeseries.csv            ← original uploaded file
│   │   └── datamodel.json            ← original uploaded file
│   ├── {dataset_id}/
│   │   └── ...
├── sessions/                         ← existing: per-branch sessions
│   ├── {session_uuid}/
│   └── ...
```

### 8.2 Dataset Card (Left Panel)

```
┌─────────────────────────────┐
│ 📊 HornsRev-MAST            │
│ 5 sensors · 2003–2025        │
│ Coverage: 94.2%              │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │
│ [Drag to canvas]             │
└─────────────────────────────┘
```

Dragging a dataset card onto the canvas creates a **Dataset Source** group node pre-configured with that dataset's files.

---

## 9. Workflow Templates

Pre-built workflow templates for common analysis patterns:

| Template | Nodes | Description |
|----------|-------|-------------|
| **Standard MCP** | Data → Clean → Site → ERA5 → LTC (speedsort) → Uncertainty | IEC-standard single-algorithm analysis |
| **Multi-Algorithm Comparison** | Data → Clean → Site → ERA5 → [LTC×3] → Ensemble → Uncertainty | Run 3 LTC algorithms, blend |
| **Hub Height Sensitivity** | Data → Clean → Site (100m) ⥂ Site (120m) → ERA5 → LTC → Compare | Fork at hub height |
| **Dataset Comparison** | [Dataset A] → full pipe ∥ [Dataset B] → full pipe → Compare | Same workflow, different data |
| **Quick Explore** | Data → Stats (windrose, Weibull, diurnal) | No LTC, just data exploration |

---

## 10. Implementation Plan

### Phase 1: Foundation (Week 1-2)
- [x] Install React Flow, set up canvas in new `WorkflowDesigner` component
- [x] Implement `NodePalette` with draggable node types
- [x] Implement `GroupNode` and `OperationNode` custom React Flow node types
- [x] Implement `CustomEdge` with animated flow indicators
- [x] Create `workflowStore` (Zustand) for canvas state
- [x] Replace `AppShell` + router with `WorkflowDesigner` layout
- [x] Implement `RightPanel` / `NodeInspector` with config forms

### Phase 1.5: Full Registry Expansion
- [x] Replace starter node list with full core MCP tool registry
- [x] Replace starter WindKit list with complete WindKit tool registry
- [x] Group tools into palette sections aligned to architecture categories
- [x] Keep registry frontend-only (no execution wiring yet)

### Phase 2: Dataset Pool (Week 2-3)
- [x] Backend: `POST/GET/DELETE /api/datasets` endpoints
- [x] Backend: Dataset storage in `data/datasets/{id}/`
- [x] Frontend: `DatasetPool` panel with upload dialog
- [x] Frontend: Drag dataset card → canvas creates Dataset Source node
- [x] Migrate existing upload logic to dataset pool model

### Phase 3: Execution Engine (Week 3-4)
- [x] Backend: `WorkflowExecutor` with topological sort + dispatch
- [x] Backend: Session-scoped workflow execution endpoints (`/api/sessions/{session_id}/workflow/*`)
- [x] Backend: Per-node status tracking + SSE for live updates
- [x] Frontend: Run controls (▶ Run All, ⏭ Step, ⏸ Pause)
- [x] Frontend: Live node status updates (animate running → done/error)
- [x] Frontend: Execution log panel per node

### Phase 4: Branching (Week 4-5)
- [ ] Backend: Session forking (`copy_session_state` up to fork node)
- [ ] Backend: `POST /api/workflows/{id}/branches` endpoint
- [ ] Backend: Branch-scoped session isolation
- [ ] Frontend: `BranchTabs` component
- [x] Frontend: Fork context menu on done nodes
- [ ] Frontend: Branch color coding on nodes/edges
- [ ] Frontend: Dirty propagation on config changes

### Phase 5: Comparison Dashboard (Week 5-6)
- [x] Backend: `POST /api/workflows/{id}/compare` endpoint
- [x] Backend: Config diff computation
- [x] Backend: Multi-trace Plotly plot generation
- [x] Frontend: `ComparisonDashboard` overlay
- [x] Frontend: `MetricsTable` with delta columns
- [x] Frontend: `OverlayPlots` (Weibull, windrose, LTC scatter, uncertainty tornado)
- [x] Frontend: `ConfigDiff` tree view
- [x] Frontend: Export (PDF, CSV, JSON)

### Phase 6: Polish (Week 6-7)
- [x] Workflow templates (Standard MCP, Multi-Algorithm, etc.)
- [x] Undo/redo on canvas operations
- [x] Keyboard shortcuts
- [x] Auto-save workflow state
- [x] Workflow persistence (save/load to disk)
- [x] Error recovery (retry failed nodes)
- [x] Performance: virtualize large canvases

---

## 11. New Dependencies

### Frontend
```json
{
  "@xyflow/react": "^12.0.0",
  "@xyflow/system": "^0.0.46"
}
```

### Backend
No new backend dependencies needed — existing FastAPI + Pydantic + pandas stack is sufficient. SSE for live execution updates uses `sse-starlette` (already available in FastAPI ecosystem, or use raw `StreamingResponse`).

---

## 12. File Structure (New & Modified)

```
frontend/src/
├── components/
│   ├── workflow/                      ← NEW
│   │   ├── WorkflowDesigner.tsx       ← main layout (replaces AppShell routing)
│   │   ├── TopBar.tsx                 ← run controls, branch tabs, compare button
│   │   ├── Canvas.tsx                 ← React Flow wrapper
│   │   ├── NodePalette.tsx            ← left panel node catalog
│   │   ├── DatasetPool.tsx            ← left panel dataset list
│   │   ├── NodeInspector.tsx          ← right panel config forms
│   │   ├── nodes/
│   │   │   ├── GroupNode.tsx
│   │   │   ├── OperationNode.tsx
│   │   │   ├── DatasetNode.tsx
│   │   │   └── ForkNode.tsx
│   │   ├── edges/
│   │   │   └── DataFlowEdge.tsx
│   │   └── config-forms/              ← per-operation config forms
│   │       ├── RangeCheckForm.tsx
│   │       ├── ShearConfigForm.tsx
│   │       ├── LtcConfigForm.tsx
│   │       ├── Era5ConfigForm.tsx
│   │       ├── UncertaintyForm.tsx
│   │       └── index.ts              ← registry: operation_type → FormComponent
│   │
│   ├── comparison/                    ← NEW
│   │   ├── ComparisonDashboard.tsx
│   │   ├── MetricsTable.tsx
│   │   ├── ConfigDiff.tsx
│   │   ├── OverlayPlots.tsx
│   │   └── ExportComparison.tsx
│   │
│   ├── datasets/                      ← NEW
│   │   ├── DatasetUploadDialog.tsx
│   │   ├── DatasetCard.tsx
│   │   └── DatasetPreview.tsx
│   │
│   └── layout/                        ← EXISTING (deprecated, replaced)
│       ├── AppShell.tsx               ← replaced by WorkflowDesigner
│       └── StepNav.tsx                ← replaced by NodePalette + canvas
│
├── stores/
│   ├── workspaceStore.ts              ← EXISTING: keep for session prefs
│   └── workflowStore.ts              ← NEW: workflow, branches, nodes, edges
│
├── lib/
│   ├── workflow.ts                    ← EXISTING: refactor for node catalog
│   ├── nodeRegistry.ts               ← NEW: node types, ports, defaults
│   └── executor.ts                   ← NEW: client-side execution orchestration
│
├── hooks/
│   ├── useExecution.ts               ← NEW: SSE listener for node status
│   └── useWorkflow.ts                ← NEW: TanStack Query hooks for workflow CRUD
│
└── pages/                             ← EXISTING pages become node config forms
    ├── DataPage.tsx                   ← logic extracted to config-forms/
    ├── SitePage.tsx                   ← logic extracted to config-forms/
    └── ...

server/
├── api/
│   └── routes/
│       ├── datasets.py               ← NEW: dataset pool CRUD
│       ├── workflows.py              ← NEW: workflow + branch CRUD
│       └── execution.py              ← NEW: execute endpoints + SSE status
│
├── state/
│   ├── workflow.py                    ← NEW: Workflow, Branch, WorkflowNode models
│   ├── dataset_pool.py               ← NEW: DatasetPool manager
│   └── session.py                    ← EXISTING: add fork/copy helpers
│
├── core/
│   └── executor.py                   ← NEW: WorkflowExecutor (topological dispatch)
│
└── schemas/
    ├── workflow.py                    ← NEW: request/response schemas
    └── comparison.py                  ← NEW: comparison response schema
```

---

## 13. Open Questions / Future Enhancements

| Question | Status |
|----------|--------|
| Should workflows persist across server restarts? (Currently in-memory only) | Needs DB or JSON file persistence |
| Real-time collaboration — multiple users on same workflow? | Out of scope for v1 |
| Undo/redo — how deep? Per-branch or global? | Recommend per-branch, 50-step limit |
| Can a branch change its dataset source? | Yes — changing dataset node marks all downstream as stale |
| Should the Chat/LLM page remain accessible? | Yes — add as floating action button or side panel |
| WindKit 142 tools — all exposed as individual nodes | ✅ Included in v1 (see §3.2) |
