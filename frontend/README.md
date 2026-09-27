# HMS web UI

React + TypeScript (Vite) interface for the HMS. It consumes the existing FastAPI backend only; it has no
backend of its own and no mock APIs.

## Run

```
npm install
HMS_API_TARGET=http://127.0.0.1:8000 npm run dev     # http://127.0.0.1:5173
npm run build && npm run preview                     # production build, same proxy
npm run lint                                         # oxlint
```

The dev/preview servers proxy `/api` and `/health` to `HMS_API_TARGET` (default `http://127.0.0.1:8000`), so the
browser talks to the backend same-origin — the backend deliberately has no CORS configuration. A production
deployment must serve the built `dist/` and the API from the same origin (e.g. behind one reverse proxy).

## Structure

```
src/
  styles/tokens.css      design tokens (colour, type, spacing, radii, elevation, motion, layers)
  styles/base.css        reset, typography defaults, layout helpers, a11y helpers
  components/ui/         the design system (import from components/ui)
  components/icons/      in-house stroke icon set
  components/shell/      application shell + navigation registry (navigation.ts)
  api/                   fetch client, typed endpoints, response types
  auth/                  session (token in sessionStorage), permissions (`can`) — display only
  hooks/                 useQuery (data loading), useOverlay/useDismiss (dialogs, popovers)
  pages/                 routes
```

Rules for later UI stages:

- Build pages from `components/ui`; add tokens rather than raw values.
- Register a module in `components/shell/navigation.ts` and give it a route — the shell does not change.
- Show where clinical information comes from with `ProvenanceTag` / `ProvenancePanel`
  (`record`, `system`, `ai`). AI output always uses the `ai` style and its review notice.
- `can()` only hides UI; the backend authorizes every request.
- `/design-system` (development builds only) renders every component for review.
