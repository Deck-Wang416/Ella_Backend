# ELLA Backend Service

FastAPI backend for diary submission and reminder notifications.

## Run

```bash
cd /Users/wang/Desktop/Ella_Backend
conda activate ella
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips='*'
```

Health:
```bash
curl http://127.0.0.1:8000/api/v1/health
```

## Required Config (.env)

```env
DATABASE_URL=sqlite:///./ella.db
API_PREFIX=/api/v1
INTERNAL_API_KEY=change_me
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=60
CORS_ALLOW_ALL=false
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
TRUSTED_HOSTS=*
WEB_PUSH_DRY_RUN=true
MOBILE_PUSH_DRY_RUN=true
```

## Core API

Base: `/api/v1`

- `GET/PUT /diary/{child_id}/{date}`
- `GET/PUT /reminders/{caregiver_id}`
- `POST /internal/reminders/run-due` (`X-Internal-API-Key`)
- `POST /notifications/subscriptions`
- `GET /internal/notifications/logs` (`X-Internal-API-Key`)
- `GET /internal/notifications/deliveries` (`X-Internal-API-Key`)
- `GET /internal/notifications/metrics` (`X-Internal-API-Key`)

## Scheduler Rules

- Check every minute (`SCHEDULER_INTERVAL_SECONDS`)
- Timezone-aware by caregiver setting
- Trigger only when local time hits configured slot and today diary is unsubmitted
- Idempotent per `(caregiver_id, child_id, local_date, slot_time)`

## Mobile HTTPS Test (Tunnel)

```bash
cloudflared tunnel --url http://localhost:8000
cloudflared tunnel --url http://localhost:5173
```

Set frontend API base URL to backend tunnel domain: `https://<backend-tunnel>/api/v1`.

## Quick Validation

```bash
bash scripts/notification_e2e_check.sh
```
