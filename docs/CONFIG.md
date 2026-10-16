# Pravah: cloud config values (from S0 setup, 15 Oct 2026)

Hand this to the coding agents. Nothing here is a secret: the browser key is
referrer-restricted and the server key lives only in Secret Manager.

| Setting | Value |
|---|---|
| GCP project ID (`GOOGLE_CLOUD_PROJECT`, `EE_PROJECT`) | `project-0fd9c4ae-bf90-452f-a80` |
| Project number | `265255051442` |
| Region | `asia-south1` |
| Service account | `pravah-backend@project-0fd9c4ae-bf90-452f-a80.iam.gserviceaccount.com` |
| GCS bucket (`GCS_BUCKET`) | `pravah-dss-data-project-0fd9c4ae-bf90-452f-a80` |
| Firestore | `(default)`, Native mode, `asia-south1` |
| Server key secret name | `maps-server-key` (Secret Manager) |
| Browser key (`VITE_GOOGLE_MAPS_API_KEY`) | `AIzaSyAjSk75kDH5TYNN9yPvXKnkwBSh8SY_Rnc` |
| Map ID (`VITE_MAP_ID`) | `75bfaebed3e13b2e41422807` |
| Earth Engine | noncommercial, individual, Community tier |

## Done in S0 (Cloud Console / Cloud Shell)
S0.1 project and billing, S0.2 APIs, S0.3 Earth Engine, S0.4 service account,
S0.5 bucket and Firestore, S0.6 both API keys, S0.7 Map ID, S0.8 budget (₹9,000 alerts).

## Decided / done after S0
- Browser key referrers: localhost:5173, localhost:4173, `project-0fd9c4ae-bf90-452f-a80.web.app`, `.firebaseapp.com` (done 15 Oct).
- Gemini: only `gemini-3.8-flash` on Vertex `global`; FAST = thinking LOW, PRO = thinking HIGH (MINIMAL unsupported).
- Cloud Run service: `pravah-backend`, `https://pravah-backend-265255051442.asia-south1.run.app` (public).
- Firebase Hosting: `https://project-0fd9c4ae-bf90-452f-a80.web.app`, `/api/**` rewrites to Cloud Run.
- Weather API key: read from env `MAPS_SERVER_KEY` (Cloud Run secret mapping) or Secret Manager `maps-server-key` locally.
- Overpass endpoints (public, flaky): overpass-api.de, maps.mail.ru, overpass.kumi.systems, overpass.private.coffee (tried in
  that order; private.coffee began refusing automated clients on 16 Oct). Demo areas are cached, so demos never call Overpass.
- Maps server key (`maps-server-key`) is also used for the Geocoding API (search box, web-lead markers); local test passed.
- Cloud Run CORS: `CORS_ORIGINS` = the two Firebase domains (set by `scripts/deploy_backend.sh`).
- Gemini requests time out after 120 s and fall back (advisory -> rules brief). Vertex returned one transient 429 on 16 Oct.
- Earth Engine community assets in use (verified access): NASA GLC, GRIP4 South-East-Asia roads, FABDEM.

- Sign-in and roles (17 Oct, policy review): code ready, **off by default** (`AUTH_REQUIRED=false`). To switch on:
  1. Register a Firebase web app: `~/.npm-global/bin/firebase apps:create WEB pravah-web --project project-0fd9c4ae-bf90-452f-a80`,
     then `~/.npm-global/bin/firebase apps:sdkconfig WEB <appId> --project project-0fd9c4ae-bf90-452f-a80` for `apiKey` and `authDomain`.
  2. Firebase console -> Authentication -> Sign-in method -> enable **Google**; add the hosting domains under Authorized domains.
  3. Frontend `.env.local` (and the build environment): `VITE_FIREBASE_API_KEY=...`, `VITE_FIREBASE_AUTH_DOMAIN=project-0fd9c4ae-bf90-452f-a80.firebaseapp.com`.
  4. Cloud Run env: `AUTH_REQUIRED=true`, `ADMIN_EMAILS=<your email>`, `DEFAULT_ROLE=analyst` (judges who sign in can run scenarios;
     only admins/approvers approve). Other roles: Firestore `users/{email}` with `role` = viewer | field | analyst | approver | admin.
- Official warnings: IMD and CWC have no public APIs we may use, so staff type the IMD district colour and CWC gauge levels
  (stored on the AOI with name and time); the page links to mausam.imd.gov.in, ffs.india-water.gov.in and Google Flood Hub.

## Still open
- Redeploy backend + frontend with S1-S19 (see `docs/PROGRESS.md` hand-off), then run `scripts/smoke_test.sh`.
- Weather API caching period for hourly/daily data not confirmed (we keep raw responses in memory 10 min only).
- Licence terms to confirm: NASA Global Landslide Catalog, GRIP4 roads (both shown as "terms being confirmed" on Methods).
- Grounding with Google Search: we show the Search suggestions HTML returned by Gemini; confirm display requirements.
- Enable sign-in for the deployed demo (steps above) or leave it open for judges (approvals then record typed, unverified names).
