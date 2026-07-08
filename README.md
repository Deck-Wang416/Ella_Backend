# ELLA Backend Service

FastAPI backend for:

- daily dashboard + diary content
- caregiver profile + login
- reminder and push notification delivery
- parent-mode audio recording
- robot-side story count and photo upload

## Run

```bash
cd /Users/wang/Desktop/Ella_Backend
conda activate ella
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips='*'
```

Health:
```bash
curl http://127.0.0.1:8000/api/health
```

## Required Config (.env)

```env
FIREBASE_DATABASE_URL=
FIREBASE_CREDENTIALS_PATH=
FIREBASE_STORAGE_BUCKET=
FIREBASE_DAILY_ROOT=dailyData
API_PREFIX=/api
INTERNAL_API_KEY=change_me
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=60
CORS_ALLOW_ALL=false
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
TRUSTED_HOSTS=*
WEB_PUSH_DRY_RUN=true
WEB_PUSH_VAPID_PUBLIC_KEY=
WEB_PUSH_VAPID_PRIVATE_KEY=
WEB_PUSH_VAPID_CLAIMS_SUB=mailto:you@example.com
MOBILE_PUSH_DRY_RUN=true
```

## Core API

Base: `/api`

- `GET /health`
- `POST /profiles/login`
- `GET /profiles/{caregiver_id}`
- `PUT /profiles/{caregiver_id}`
- `GET /daily/summaries`
- `GET /daily/{date}`
- `POST /daily/{date}/initialize`
- `PUT /daily/{date}`
- `GET/PUT /reminders/{caregiver_id}`
- `POST /internal/reminders/run-due` (`X-Internal-API-Key`)
- `POST /subscriptions`
- `GET /subscriptions/{caregiver_id}`
- `PUT /subscriptions/{id}`
- `DELETE /subscriptions/{id}`
- `POST /recordings/sessions`
- `GET /recordings/sessions/{session_id}`
- `POST /recordings/sessions/{session_id}/chunks`
- `POST /recordings/sessions/{session_id}/complete`
- `POST /internal/robot-story-count/increment` (`X-Internal-API-Key`)
- `GET /internal/robot-story-count/current-week` (`X-Internal-API-Key`)
- `POST /internal/robot-photo` (`X-Internal-API-Key`)
- `POST /internal/notifications/test-send` (`X-Internal-API-Key`)
- `GET /internal/notifications/logs` (`X-Internal-API-Key`)
- `GET /internal/notifications/deliveries` (`X-Internal-API-Key`)
- `GET /internal/notifications/metrics` (`X-Internal-API-Key`)

## Data Notes

- `dailyData` is still the main RTDB root for daily content.
- Robot story progress is stored separately under `robotStoryProgress/{caregiverId}/{weekStartDate}`.
- `userProfiles` stores username, password, themes, and condition ranges.
- `dayCount` is computed dynamically by the backend and is not stored in RTDB.
- Robot dashboard `recentPhotos` is computed dynamically from the current active robot period and is not stored in RTDB.

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

Set frontend API base URL to backend tunnel domain: `https://<backend-tunnel>/api`.

## Local Chunk Merge

Google Cloud SDK:

```bash
brew install --cask google-cloud-sdk
gcloud auth login
```

Export chunks:

```bash
gsutil -o "GSUtil:parallel_process_count=1" cp -r gs://ella-development-464ea.firebasestorage.app/audio/<username>/<YYYY-MM-DD>/<session_id>/ /path/to/output/
```

Merge chunks locally:

```bash
python3 merge_recording_chunks.py /path/to/output/<session_id>/
```
