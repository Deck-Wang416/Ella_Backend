# Firebase Migration Snapshots

## Daily Content Seed
- `firebase_daily_seed.json`
  - Source: `data/daily/*.json`
  - Target node: `dailyData`
  - Purpose: initial daily content import to Realtime Database

## Notification State Seed
- `firebase_notification_state_seed.json`
  - Source: local SQLite (`ella.db`) notification-related tables
  - Target node: `notificationState`
  - Purpose: migrate reminder/subscription/dispatch state to Realtime Database
