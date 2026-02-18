#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000/api/v1}"
KEY="${KEY:-change_me}"
TODAY="${TODAY:-$(date +%F)}"

printf "\n[1/8] create caregiver\n"
curl -sS -X POST "$BASE/caregivers" \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","timezone":"Asia/Shanghai"}' | tee /tmp/ella_caregiver.json

printf "\n[2/8] create child\n"
curl -sS -X POST "$BASE/caregivers/children" \
  -H "Content-Type: application/json" \
  -d '{"caregiver_id":1,"name":"Ella"}' | tee /tmp/ella_child.json

printf "\n[3/8] upsert web_push subscription\n"
curl -sS -X POST "$BASE/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{"caregiver_id":1,"platform":"web_push","endpointOrToken":"https://push.example.test/abc","keys":{"p256dh":"demo","auth":"demo"}}' | tee /tmp/ella_sub_web.json

printf "\n[4/8] upsert fcm subscription\n"
curl -sS -X POST "$BASE/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{"caregiver_id":1,"platform":"fcm","endpointOrToken":"fcm_device_token_demo"}' | tee /tmp/ella_sub_fcm.json

printf "\n[5/8] confirm diary today not submitted\n"
curl -sS "$BASE/diary/1/$TODAY" | tee /tmp/ella_diary_before.json

printf "\n[6/8] run due reminders (or use test-send)\n"
curl -sS -X POST "$BASE/internal/notifications/test-send" \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: $KEY" \
  -d "{\"caregiver_id\":1,\"child_id\":1,\"local_date\":\"$TODAY\",\"slot_time\":\"18:00\",\"timezone\":\"Asia/Shanghai\",\"message\":\"Phase2 prototype test\"}" | tee /tmp/ella_test_send.json

printf "\n[7/8] inspect logs + deliveries\n"
curl -sS "$BASE/internal/notifications/logs?caregiver_id=1" -H "X-Internal-API-Key: $KEY" | tee /tmp/ella_logs.json
curl -sS "$BASE/internal/notifications/deliveries" -H "X-Internal-API-Key: $KEY" | tee /tmp/ella_deliveries.json

printf "\n[8/8] metrics\n"
curl -sS "$BASE/internal/notifications/metrics" -H "X-Internal-API-Key: $KEY" | tee /tmp/ella_metrics.json

printf "\nDone. Saved outputs to /tmp/ella_*.json\n"
