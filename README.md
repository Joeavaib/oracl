# Orchestrator UI v0.1

Minimalistische UI für das Backend-Orchester (Validator → Planner → Validator → Coder) mit FastAPI, Jinja2 und HTMX.

## Starten

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Optional (für HTML-Form-Uploads in `/ui`):

```bash
pip install python-multipart
```

## UI-Routen

- `GET /ui` – Dashboard mit Formular
- `GET /ui/runs` – Liste der Runs
- `GET /ui/runs/{run_id}` – Detailansicht
- `GET /ui/runs/{run_id}/events` – HTML-Partial (Events Tail)

## API-Routen

- `POST /api/runs` – startet einen Stub-Run (JSON oder HTML-Form), Redirect bei HTML
- `GET /api/runs` – listet Runs
- `GET /api/runs/{run_id}` – Run-Details inkl. Artefakt-Vorschauen
- `GET /api/runs/{run_id}/events?tail=200` – Events (Tail)
- `GET /api/runs/{run_id}/artifact?name=<file>` – Artefakt-Download

## Hinweise

- Artefakt-Vorschauen sind auf 200 KB begrenzt.
- Artefakte liegen unter `runs/<run_id>/` (z. B. `input.json`, `events.jsonl`).

## Curl Beispiele

```bash
curl -X POST http://localhost:8000/api/runs \\
  -H 'Content-Type: application/json' \\
  -d '{"goal":"UI Smoke","user_prompt":"Check UI","repo_root":"/workspace/oracl","constraints":["no refactors"]}'
```

```bash
curl http://localhost:8000/api/runs
```

```bash
curl http://localhost:8000/api/runs/<run_id>
```

```bash
curl http://localhost:8000/api/runs/<run_id>/events?tail=200
```
