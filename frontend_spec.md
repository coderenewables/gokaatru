# Project Specification: Config-Driven Wind Data Analysis Frontend with AI Agent Layer

## 1. Project Overview

We are building a web-based frontend for a wind energy data analysis application. The core system processes wind data time series to produce long-term corrected (LTC) data for Energy Yield Assessments (EYA).

### The Architecture Strategy

1. **Config-Driven SSOT:** Every analytical decision is captured in a central JSON/YAML configuration file.
2. **MCP-Powered Backend:** The Python backend acts as an MCP (Model Context Protocol) server. It exposes endpoints (e.g., data loading, cleaning, shear calculation, LTC runs) as **Tools** and the active configuration/datasets as **Resources**.
3. **Bring-Your-Own-Key (BYOK) AI Agent:** The frontend includes an embedded LLM agent panel. Users can provide their own API keys (OpenAI, Anthropic, etc.). The agent interacts with the backend via the MCP server to inspect data, tweak configurations, rerun models, and explain differences using natural language.

---

## 2. Updated Tech Stack Recommendations

* **Frontend Framework:** React (Next.js or Vite) — *Highly recommended due to robust MCP SDK support.*
* **State Management:** Zustand (for the global configuration state and run history).
* **Canvas/Flowchart:** React Flow (xyflow) for the visual configuration graph.
* **MCP Integration:** `@modelcontextprotocol/sdk` (TypeScript) to communicate with your Python MCP server.
* **LLM Orchestration:** Vercel AI SDK or LangChain.js to handle the client-side BYOK agent logic and tool-calling loop.

---

## 3. The Three Pillars of the User Interface

### Pillar A: The Visual Workflow (Canvas & Dashboard)

* **The Linear Wizard (First Run):** A guided step-by-step UI for loading data (CSV/IEA JSON/BrightHub API), setting cleaning rules, choosing shear sensors, downloading ERA5/MERRA-2 nodes, and choosing an LTC model.
* **The Canvas Node Editor (Iterations):** Maps the current JSON config into a node-based flowchart. Users can click a node (e.g., "Shear") to manually alter parameters in a fly-out panel and trigger an on-demand re-run.

### Pillar B: The BYOK AI Copilot Panel

A collapsible sidebar chat interface dedicated to natural language analysis.

* **API Key Management:** A secure settings drawer where users input their own API keys (saved strictly in local storage/session cookies, never stored on a centralized database).
* **Context Awareness:** The LLM is fed the current active configuration file as a system resource.
* **Action Execution:** The LLM can autonomously invoke backend tasks via the MCP server tools.
* *Example User Prompt:* `"Hey, let's swap the shear calculation to use the 80m anemometer instead of the 100m one, rerun the LTC using SpeedSort, and tell me how the long-term mean wind speed changes."*
* *Agent Action:* The LLM mutates the config payload, triggers the backend tools, awaits the output, and prints a summary.



### Pillar C: Comparative Analytics Engine

* A dedicated dashboard pane to compare `Run Baseline` vs `Run 2` vs `Run 3`.
* Displays delta comparisons of configurations (what parameters changed) alongside data visualization differences (wind roses, scatter plots, time-series deltas, and clipping summaries).

---

## 4. Phased Implementation Plan

### Phase 1: Scaffolding, Core UI, & Global State

* Set up the frontend project and build the global state machine (Zustand) representing the wind analysis config JSON.
* Build the linear wizard UI steps (Data Load $\rightarrow$ Cleaning $\rightarrow$ Shear $\rightarrow$ Reanalysis Download $\rightarrow$ LTC models).
* Create a mock service layer for the backend calculations to test UI state updates.

### Phase 2: MCP Server Connection & Canvas Integration

* Implement the MCP client in the frontend to connect directly to your Python MCP server.
* Bind UI inputs directly to MCP tool schemas. Clicking "Run Analysis" should pass the state config payload to the backend execution tool.
* Implement React Flow to display the config as a visual workflow graph, allowing node-based edits.

### Phase 3: BYOK AI Agent Layer

* Build the encrypted local storage wallet for user API keys.
* Set up the client-side agent framework (e.g., Vercel AI SDK).
* Expose the frontend state and the backend MCP tools to the LLM agent runner.
* Implement streaming chat UI with rendering support for tool-calling indicators (e.g., *“Agent is running SpeedSort correction...”*).

### Phase 4: Comparative Analytics Dashboard

* Develop the run-history tracking state.
* Build split-screen and overlay charting components (using Plotly or ECharts) to visualize structural changes between different runs.
* Add automated "Diff" callouts showing config alterations vs. analytical output deltas.

---

## 5. Instructions for the AI Coding Assistant

* **Acknowledge Core Concepts:** Confirm that you understand the app is **config-driven**, uses an **MCP server architecture** for backend interactions, and features a **BYOK client-side AI agent**.
* **Start with State:** Help me design the comprehensive Typescript interface/schema for the central JSON wind analysis config object. It must capture variables for Mast properties, Hub heights, Shear sensors/methods, Cleaning thresholds, Reanalysis nodes, and LTC models.
* **Ask for Preferences:** Inquire about my preferred UI library components (e.g., shadcn/ui) and framework (e.g., Vite vs. Next.js) before writing boilerplate code.

---
