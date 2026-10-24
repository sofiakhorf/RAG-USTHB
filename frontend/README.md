# Frontend (React + TypeScript + Vite + Tailwind CSS)

Student-facing UI for RAG-USTHB. **Structure scaffold only** — no packages were
installed, no UI components implemented, no build configuration created in this pass.

## MVP feature pages (directory placeholders created)

- `src/pages/Home/` — landing page
- `src/pages/Login/` — authentication (via Keycloak, integrated by the backend)
- `src/pages/Register/` — registration
- `src/pages/Chatbot/` — chatbot interface
- `src/pages/Profile/` — student profile / chat history / logout

## Planned directories (placeholders created)

- `src/assets/` — static assets (images, icons, fonts)
- `src/components/` — reusable UI components
- `src/layouts/` — application layouts (auth/chat shells)
- `src/services/` — API service layer for Django REST Framework
- `src/hooks/` — custom React hooks
- `src/types/` — shared TypeScript type definitions
- `src/utils/` — pure utility functions
- `public/` — static files served by Vite

## Planned root files (not created — see "Manual steps")

- `src/App.tsx`, `src/main.tsx` — entry points (created during scaffolding)
- `package.json`, `vite.config.ts` — created by `npm create vite@latest`
- `tsconfig.json`, `tailwind.config.js`, `postcss.config.js`
- `README.md` — created together with the actual scaffold

## Manual steps (not performed in this structure-only pass)

1. Scaffold the app inside `frontend/` (from this directory):
   `npm create vite@latest . -- --template react-ts`
2. Install Tailwind CSS per the Vite guide.
3. Create the routes/pages listed above and the `services/` layer pointing at the
   Django REST Framework API (backend base URL via environment variable).
4. `frontend/README.md` will be replaced by the scaffold's README — merge this
   document's structure notes into it.

## Notes

- Remote branch `origin/FrontEnd` exists but its contents are identical to
  `origin/main` (preprocessing pipeline only) — no frontend project was found in it.
- Nothing was installed and no source files were written.
