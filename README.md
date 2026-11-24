# ELLA Backend

FastAPI service for caregiver profiles, daily dashboards and diaries, reminders, Web Push and native push, parent recordings, and robot uploads. It uses Firebase Realtime Database and Storage; APScheduler runs reminder checks and recording-merge retries in the API process.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set the required Firebase values in `.env` or the deployment environment:

```env
FIREBASE_DATABASE_URL=https://YOUR_PROJECT-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_PATH=/absolute/path/to/service-account.json
FIREBASE_STORAGE_BUCKET=YOUR_PROJECT.firebasestorage.app
```

`FIREBASE_STORAGE_BUCKET` is needed for recording and photo storage. Keep the service account, APNs private key, internal API key, and VAPID private key out of Git. `GET /api/health` checks the server. Run tests with `python -m pytest -q` (install `pytest` if it is not already available). Recording merges require `ffmpeg` and `ffprobe` on `PATH`.

## Data and API

All routes below are under `/api`:

| Area | Routes | Notes |
| --- | --- | --- |
| Profiles | `POST /profiles/login`, `GET/PUT /profiles/{caregiver_id}` | Login returns the profile. Profile updates are themes-only; `dayCount` is computed, not stored. |
| Daily | `GET /daily/summaries`, `GET/PUT /daily/{date}` | Requires `caregiver_id` query parameter. `timezone` is optional; the frontend supplies `America/New_York`. |
| Reminders | `GET/PUT /reminders/{caregiver_id}` | Settings include the caregiver's timezone and reminder times. |
| Subscriptions | `POST /subscriptions`, `GET /subscriptions/{caregiver_id}`, `PUT/DELETE /subscriptions/{id}` | Web Push, APNs, and FCM device bindings. |
| Recordings | `POST /recordings/sessions`, `GET /recordings/sessions/{session_id}`, `POST /recordings/sessions/{session_id}/chunks`, `/complete`, `/cancel` | Parent mode only. |
| Robot integration | `GET /internal/robot-story-count/current-week`, `POST /internal/robot-story-count/increment`, `POST /internal/robot-photo` | Protected by `X-Internal-API-Key`. |

Internal reminder and notification test/diagnostic endpoints also require `X-Internal-API-Key`; see `app/api/`. Set `INTERNAL_API_KEY` in the deployment environment.

Profiles in `userProfiles/{caregiverId}` define the robot and parent date ranges. The backend creates today's daily content from the active range; daily content is stored under `dailyData/{caregiverId}/{date}`. Summaries exclude future dates. Detail is available for today or a past, submitted diary within the configured period; future dates and past unsubmitted diaries return 404. Only today's diary can be edited. The old `/daily/{date}/initialize` route remains for compatibility but rejects manual mode selection.

Robot story counts come from `robotStoryProgress`, not `dailyData.dashboard.storyCount`. Robot `recentPhotos` aggregates up to five photos from the active robot period, newest first. Weekly progress is computed on read: robot stories from story progress, parent reading minutes from completed recording sessions. The robot dashboard exposes photos, story count, recent photos, and weekly progress; the parent dashboard exposes weekly progress. Diary questions and their display conditions come from the daily response.

## Recording Pipeline

`POST /recordings/sessions` creates a new parent-mode session on each request. The default `chunkFormat` is `byte_stream` for Web `MediaRecorder`; native iOS and Android use `standalone` WAV segments. Both clients upload raw audio to `POST /recordings/sessions/{session_id}/chunks?chunkIndex=N&mimeType=...`. Chunk indexes start at 0; uploads may arrive out of order or concurrently. The backend verifies each chunk and accepts an identical retry of the same index. It rejects conflicting bytes or MIME types. The request body limit is 10 MB per chunk.

After all chunks are acknowledged, `POST /recordings/sessions/{session_id}/complete` takes `finalChunkIndex` and optional integer `durationSeconds`. Completion verifies contiguous indexes and marks the session `completed`; the audio merge then runs asynchronously. **Session `status=completed` does not mean the merge is finished.** `GET /recordings/sessions/{session_id}` exposes `mergeStatus` and `finalAudio`. The merge uses FFmpeg to produce a verified final file, then deletes temporary Storage chunks; failed merges retain their source chunks for retry. Native clients may delete app-private chunks after `/complete` succeeds because the backend has accepted all source chunks. `/cancel` can abandon an unfinished session and clean up its uploaded chunks.

## Notifications

APScheduler checks enabled reminder settings every `SCHEDULER_INTERVAL_SECONDS` (default 60). Each caregiver's configured timezone determines the local reminder slots; reminders are sent only within an active study period when that day's diary is unsubmitted. Configure each caregiver's reminder settings explicitly.

Web delivery uses VAPID-authenticated Web Push (`WEB_PUSH_VAPID_*`). iOS uses APNs (`APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_PRIVATE_KEY`, `APNS_BUNDLE_ID`, `APNS_USE_SANDBOX`); Android uses FCM through the Firebase service account. Set `WEB_PUSH_DRY_RUN=false` and/or `MOBILE_PUSH_DRY_RUN=false` only when the corresponding credentials and platform configuration are ready. Development-signed iOS builds use APNs sandbox; TestFlight/distributed builds use production. Notification subscriptions are deactivated on explicit logout or account switching, not merely because an app is refreshed.

Configure `CORS_ORIGINS` with the actual web origins (or use `CORS_ALLOW_ALL` only for temporary testing). On a multi-process deployment, ensure only one scheduler instance runs the periodic jobs.
