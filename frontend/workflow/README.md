# ArchitectureIQ Workflow Studio

React / TypeScript / React Flow browser client for the Studio API. All records come from `/api/studio`; no demo catalog, model outputs or GT are embedded.

From the repository root:

```sh
npm --prefix frontend/workflow ci
npm --prefix frontend/workflow test
npm --prefix frontend/workflow run build
npm --prefix frontend/workflow run dev
```

The development UI listens on `127.0.0.1:5174` and proxies `/api/studio` to `127.0.0.1:8094`. Set `STUDIO_API_TARGET` to a different local API or SSH-forwarded address before starting Vite. Deploy `dist/` together with the same-origin API for production.

The Chinese UI includes the registered question catalog, source import/upload, immutable question sets, verified model profiles, canonical generation jobs, a typed editable scientific workflow and durable run history. Request preview does not start inference. Evaluation supports multiple reachable or verified LLM services; the original scientific and paired research workflows inherit a single model with verified runtime identity. Evaluation token budgets cover the whole task, and submission requires a successful preview of the current settings. Per-call output limits come from the registered model parameters.

Workflow drafts use backend revisions, compare-and-swap updates and recovery backups shared across browsers. Import/export preserves the versioned graph and settings. Schema v2 rule-refinement drafts may save incomplete material routes; starting a run requires full server validation. See [rule refinement](../../docs/rule-refinement.md) for deterministic matching and model-free Task checks. The optional confirmation and evaluation switches update execution routes; invalid custom routing is rejected visibly. Enabling confirmation fixes the protocol to 48 independent datasets and ten GT seeds, and visibly raises the candidate-seed budget to at least 1600. Disabling the route retains edited budgets.

Run details distinguish preview, actual transport requests, raw responses and parsing/scoring. Unavailable fields are labelled as missing. Pause/resume delegates to server safe-boundary control; closing the browser does not cancel a job. API credentials remain server environment references.

Focused tests cover cross-page selection, exact prompt submission, graph JSON round trips, model readiness, optional-route semantics, and HTTP rejection handling. The production build includes strict TypeScript checking. Browser integration uses the actual server, with inference and training only on the designated execution host.
