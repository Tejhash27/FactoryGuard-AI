# FactoryGuard AI

An explainable machine-monitoring hackathon prototype. React + Vite + Tailwind, FastAPI, SQLite and Isolation Forest. All telemetry is **simulated**. Financial impacts are **estimates**. No failure probabilities or actual sensor integration are claimed.

## Try it

The published website is a standalone browser demonstration. It uses the transparent threshold engine and localStorage; it does **not** run Python or share a database. Open Settings to connect a deployed FastAPI backend. The banner always identifies the current mode; API failures never silently switch to browser data.

## Run entirely in GitHub Codespaces

Open this repository → Code → Codespaces → Create codespace. The cloud VM consumes your GitHub quota; no development installation or full-project download is required on your laptop. In its browser terminal:

```bash
npm ci
python -m pip install -r backend/requirements-dev.txt
npm run dev:full
```

Open forwarded port 3000. Both Vite and FastAPI start together. In the app's Settings, enter `auto` as Backend origin and save. Vite proxies `/api` to FastAPI on port 8000; this works through the single Codespaces URL. Keep ports private for development. `npm run dev` or `npm run dev:frontend` runs the browser demo alone.

```bash
npm test
python -m pytest tests/test_api.py -q
npm run build
```

To serve the built frontend from FastAPI on a single origin:

```bash
VITE_API_URL=auto npm run build
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Open forwarded port 8000. SQLite records persist in `data/factoryguard.db` in the cloud workspace, excluded from git. A rebuilt or deleted Codespace can lose unbacked runtime data.

## Features

- Five seeded machines; 5-second synthetic telemetry; sensor history capped at 120 samples per machine by default.
- Add, edit, search, filter and delete machines. Deletion cascades linked demo readings, alerts and tasks.
- Low / Medium / High risk, threshold explanations and inspection suggestions. Python trains a 64-tree Isolation Forest from 480 synthetic normal samples at startup; threshold rules work without scikit-learn. Decision scores are not probabilities.
- Scenario injection and recovery; active alert deduplication, acknowledgment and resolution. Resolved alert history is capped at 300 in FastAPI, total history at 300 in browser mode.
- Editable INR loss assumptions. Loss = hours × units/hour × profit/unit. Total = loss + repair cost.
- Scheduled maintenance, priorities, completion timestamps and persisted task history. Completion does not silently repair a machine.
- Context-aware assistant over current records, using deterministic intent rules rather than an external LLM.
- Four CSV reports, formula-injection neutralization and printable health snapshot.
- Lazy-loaded charts and CSS factory geometry with five selectable assets, zoom and a 2D toggle. No downloaded imagery, datasets or 3D models.

## Deployment

**Frontend on Vercel:** import the repository, use the root directory and included `vercel.json` (build `npm run build`, output `dist`). Without `VITE_API_URL`, it remains the self-contained browser demonstration. To connect Python, set `VITE_API_URL=https://your-backend-origin` and rebuild, or use Settings.

**Backend on Render:** create a Blueprint from `render.yaml`, or a Python web service with build `pip install -r backend/requirements.txt` and start `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1`. Set `FACTORYGUARD_ORIGINS` to the exact HTTPS frontend origin. Copy the generated `FACTORYGUARD_API_KEY` into the app Settings (session-only storage; do not bake it into public source). API documentation is `/docs` and health is `/api/health`.

The provided `/tmp/factoryguard.db` setting is explicitly **ephemeral**. For persistence, provision a host-supported volume, mount at `/var/data`, and change `FACTORYGUARD_DB=/var/data/factoryguard.db`. Do not call an ephemeral instance durable. Hosting plans can have quota, sleep/cold-start or paid-volume limits; check the provider's current plan before deploying. This project does not create or pay for hosting services automatically.

Environment template: `.env.example`. The Python app reads environment variables from the hosting environment or shell; it does not automatically load `.env` files. No Firestore integration is implemented. SQLite is the supported database for this prototype. One backend worker owns the simulation loop.

## API

`GET /api/health`, `/api/state`, `/api/machines`, `/api/machines/{id}/readings`, `/api/machines/{id}/analysis`, `/api/alerts`, `/api/tasks`, `/api/analytics`, `/api/reports/{machines|alerts|maintenance|loss}`.

`POST /api/machines`, `/api/machines/{id}/readings`, `/api/simulation/scenario`, `/api/alerts/{id}/acknowledge`, `/api/tasks`, `/api/loss`, `/api/assistant`.

`PUT /api/machines/{id}`, `/api/tasks/{id}`; `DELETE /api/machines/{id}`. Configure `FACTORYGUARD_API_KEY` for shared hosting. This is a shared demo key, not production user authentication.

## 90-second demo

1. Show Overview and select M-02. The initial fleet has 3 healthy machines, 1 warning and 1 critical.
2. Run the fault scenario. Open AI fault detection and explain the temperature / vibration / power thresholds.
3. Schedule an inspection. Change its status to Completed in Maintenance; reload to verify persistence.
4. Use the loss calculator: 4 × 180 × ₹95 + ₹12,000 = **₹80,400**. Save to update the dashboard, reports and assistant.
5. Restore normal readings in Monitoring; show alert resolution and ask the assistant which machine has the highest risk.
6. Download a health report or print the snapshot from Reports.

## Engineering limits

A one-student demonstration, not an industrial safety system. Illustrative thresholds are temperature 80/95 °C, vibration 4.5/7.1 mm/s, power 125/150% of each machine's baseline. Health indexes 96/62/24 are display bands, not validated remaining life. Availability is the fraction of retained simulated samples below critical temperature/vibration limits, not measured plant uptime. Rules and a synthetic model require real equipment data and calibration before any real use.

React Router was replaced with native hash navigation to keep routing buildless at the hosting boundary and use available offline packages. Backend and browser modes share threshold configuration; the browser mode deliberately omits the trained Python model. Browser storage is per origin/device, is not synchronized between tabs, and can be cleared by the user. The server simulator continues while a client pauses its display; browser simulation advances only while polling the open demo.

Source, lockfiles and tests are committed. `node_modules`, build outputs, SQLite databases, caches and training artifacts are excluded. No laptop software installation is required.
