# ELLA Reminder Backend Prototype (Phase1 + Phase2)

FastAPI 后端，服务 ELLA 前端（React + PWA），支持“家长问卷提交状态驱动提醒”。

## 当前状态

- `Phase1`：已完成
  - 按家长时区判断今天
  - 每分钟检查到点提醒（默认 18:00/21:00）
  - 仅今天未提交触发提醒
  - 同 child 同天同时段防重

- `Phase2`：已完成可测试 Prototype
  - 通知通道抽象：`web_push` / `fcm` / `apns`
  - 订阅管理 API（注册/查询/停用）
  - 投递重试（`NOTIFICATION_MAX_RETRIES`）
  - 投递明细记录（每次尝试入库）
  - 内部监控接口（logs/deliveries/metrics）

说明：默认是 `dry-run`，不依赖真实推送证书也可跑通端到端流程。

## 目录

```txt
app/
  api/
    caregivers.py
    diary.py
    reminders.py
    subscriptions.py
    internal.py
    notifications.py
  models/
    caregiver.py
    child.py
    diary_entry.py
    reminder_setting.py
    notification_subscription.py
    notification_log.py
    notification_delivery.py
  services/
    reminder_service.py
    notification_service.py
    notification_providers.py
  core/
    config.py
    database.py
    scheduler.py
    security.py
alembic/
  versions/
    20260217_0001_init.py
    20260218_0002_phase2_notifications.py
```

## 环境变量

复制 `.env.example` -> `.env`。

关键配置：
- `DATABASE_URL=sqlite:///./ella.db`
- `INTERNAL_API_KEY=change_me`
- `SCHEDULER_ENABLED=true`
- `NOTIFICATION_MAX_RETRIES=2`
- `WEB_PUSH_DRY_RUN=true`
- `MOBILE_PUSH_DRY_RUN=true`

可选真实 Web Push 配置（关闭 dry-run 时需要）：
- `WEB_PUSH_VAPID_PUBLIC_KEY`
- `WEB_PUSH_VAPID_PRIVATE_KEY`
- `WEB_PUSH_VAPID_CLAIMS_SUB`

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Health check:
```bash
curl http://127.0.0.1:8000/api/v1/health
```

## 核心 API

Base URL: `http://127.0.0.1:8000/api/v1`

### Diary
- `GET /diary/{child_id}/{date}`
- `PUT /diary/{child_id}/{date}`
  - 只允许更新家长时区下“今天”

### Reminder 设置
- `GET /reminders/{caregiver_id}`
- `PUT /reminders/{caregiver_id}`

### 订阅（Phase2）
- `POST /notifications/subscriptions`
- `GET /notifications/subscriptions/{caregiver_id}`
- `DELETE /notifications/subscriptions/{subscription_id}?caregiver_id=1`

### 内部任务
- `POST /internal/reminders/run-due`（需要 `X-Internal-API-Key`）

### 内部可观测（Phase2）
- `GET /internal/notifications/logs`
- `GET /internal/notifications/deliveries`
- `GET /internal/notifications/metrics`
- `POST /internal/notifications/test-send`

## 快速测试（Prototype）

假设：
```bash
BASE=http://127.0.0.1:8000/api/v1
KEY=change_me
TODAY=$(date +%F)
```

1) 创建 caregiver
```bash
curl -X POST "$BASE/caregivers" -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","timezone":"Asia/Shanghai"}'
```

2) 创建 child
```bash
curl -X POST "$BASE/caregivers/children" -H "Content-Type: application/json" \
  -d '{"caregiver_id":1,"name":"Ella"}'
```

3) 注册 Web Push 订阅（dry-run 也可）
```bash
curl -X POST "$BASE/notifications/subscriptions" -H "Content-Type: application/json" \
  -d '{
    "caregiver_id":1,
    "platform":"web_push",
    "endpoint":"https://push.example.test/abc",
    "keys":{"p256dh":"demo","auth":"demo"}
  }'
```

4) 手动测试发一条通知
```bash
curl -X POST "$BASE/internal/notifications/test-send" \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: $KEY" \
  -d "{\"caregiver_id\":1,\"child_id\":1,\"local_date\":\"$TODAY\",\"slot_time\":\"18:00\",\"timezone\":\"Asia/Shanghai\",\"message\":\"Phase2 test\"}"
```

5) 查看通知日志
```bash
curl "$BASE/internal/notifications/logs?caregiver_id=1" -H "X-Internal-API-Key: $KEY"
```

6) 查看投递尝试明细（重试记录）
```bash
curl "$BASE/internal/notifications/deliveries" -H "X-Internal-API-Key: $KEY"
```

7) 查看汇总指标
```bash
curl "$BASE/internal/notifications/metrics" -H "X-Internal-API-Key: $KEY"
```

也可以直接跑一键脚本：
```bash
bash scripts/phase2_demo.sh
```

## 迁移命令

```bash
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "your_change"
```

## 真实推送接入说明

当前 prototype 已具备 provider 架构：
- `web_push`: `pywebpush` 发送
- `fcm` / `apns`: 目前 dry-run 成功、真实 SDK 待接入

从 prototype 到生产：
1. 将 `WEB_PUSH_DRY_RUN=false` 并配置 VAPID。
2. 在 `notification_providers.py` 中替换 FCM/APNs provider 的 `send` 实现。
3. 将 SQLite 切换 PostgreSQL（仅修改 `DATABASE_URL` + 新迁移）。
