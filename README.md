# ELLA FastAPI Backend (MVP -> Extensible)

面向 ELLA 前端（React + PWA）的后端，当前实现目标：
- 家长问卷（Diary）提交状态管理
- 后端驱动的定时提醒（默认 18:00 / 21:00）
- 按用户时区判断“今天”
- 同一 child 同一天同一时段防重复提醒

## Phase 进度

### Phase 1: MVP（已完成）
- [x] FastAPI 工程初始化（Python 3.11+）
- [x] SQLAlchemy 2.x + SQLite 数据模型
- [x] Alembic 初始迁移
- [x] Diary / Reminder / Internal API
- [x] APScheduler 每分钟扫描提醒
- [x] NotificationService 占位发送（日志 + DB 记录）

### Phase 2: 可扩展版本（已预留结构，待扩展）
- [ ] Web Push (VAPID) 实际发送实现
- [ ] React Native 推送 (FCM/APNs)
- [ ] 鉴权体系（JWT/Session）与 RBAC
- [ ] PostgreSQL 切换与索引优化
- [ ] 失败重试、死信、可观测性（metrics/tracing）

## 目录结构

```txt
app/
  api/
    caregivers.py
    diary.py
    reminders.py
    internal.py
    notifications.py
    router.py
  core/
    config.py
    database.py
    scheduler.py
    security.py
  models/
    caregiver.py
    child.py
    diary_entry.py
    reminder_setting.py
    notification_subscription.py
    notification_log.py
  schemas/
    caregiver.py
    diary.py
    reminder.py
    internal.py
    notification.py
  services/
    reminder_service.py
    notification_service.py
  main.py
alembic/
  env.py
  versions/20260217_0001_init.py
requirements.txt
.env.example
alembic.ini
```

## 环境变量

复制 `.env.example` 为 `.env`，主要项：
- `DATABASE_URL`：默认 `sqlite:///./ella.db`，后续可切 PostgreSQL
- `SCHEDULER_ENABLED`：是否启用定时任务
- `SCHEDULER_INTERVAL_SECONDS`：默认 `60`
- `INTERNAL_API_KEY`：保护 `/internal/*` 接口
- `CORS_ORIGINS`：前端域名列表（逗号分隔）

## 安装与运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

数据库迁移：
```bash
alembic upgrade head
```

启动：
```bash
uvicorn app.main:app --reload --port 8000
```

访问健康检查：
```bash
curl http://127.0.0.1:8000/api/v1/health
```

## Alembic 常用命令

```bash
# 创建新迁移（模型更新后）
alembic revision --autogenerate -m "add_xxx"

# 升级到最新
alembic upgrade head

# 回滚一步
alembic downgrade -1
```

## 数据模型（MVP）

- `caregivers`: 家长账号（含 timezone）
- `children`: 家长关联孩子
- `diary_entries`: 每个 child 每天一条问卷（submitted/responses）
- `reminder_settings`: 家长提醒配置（默认 18:00/21:00）
- `notification_subscriptions`: 推送订阅占位（Web Push/移动端扩展）
- `notification_logs`: 提醒发送记录（用于防重 + 审计）

## API Contract（核心）

Base URL: `http://127.0.0.1:8000/api/v1`

### 0) 初始化（联调用）

#### `POST /caregivers`
请求：
```json
{
  "name": "Alice",
  "email": "alice@example.com",
  "timezone": "Asia/Shanghai"
}
```
响应：
```json
{
  "id": 1,
  "name": "Alice",
  "email": "alice@example.com",
  "timezone": "Asia/Shanghai",
  "created_at": "2026-02-17T10:30:00"
}
```

#### `POST /caregivers/children`
请求：
```json
{
  "caregiver_id": 1,
  "name": "Ella"
}
```
响应：
```json
{
  "id": 1,
  "caregiver_id": 1,
  "name": "Ella",
  "created_at": "2026-02-17T10:31:00"
}
```

### 1) Diary 提交状态

#### `GET /diary/{child_id}/{date}`
说明：`date` 格式 `YYYY-MM-DD`。
- 若当天无记录，返回 `submitted=false` 的默认体。

示例响应：
```json
{
  "id": null,
  "child_id": 1,
  "entry_date": "2026-02-17",
  "submitted": false,
  "submitted_at": null,
  "updated_at": null,
  "responses": null
}
```

#### `PUT /diary/{child_id}/{date}`
说明：
- 仅允许更新“家长时区下的今天”，否则返回 `400`。
- `submitted=true` 时自动写 `submitted_at`。

请求：
```json
{
  "submitted": true,
  "responses": {
    "mood": "good",
    "sleep_hours": 8
  }
}
```

响应：
```json
{
  "id": 1,
  "child_id": 1,
  "entry_date": "2026-02-17",
  "submitted": true,
  "submitted_at": "2026-02-17T10:45:00+00:00",
  "updated_at": "2026-02-17T10:45:00+00:00",
  "responses": {
    "mood": "good",
    "sleep_hours": 8
  }
}
```

### 2) Reminder 设置

#### `GET /reminders/{caregiver_id}`
- 若无设置，会自动创建默认值：`["18:00", "21:00"]`。

响应：
```json
{
  "id": 1,
  "caregiver_id": 1,
  "timezone": "Asia/Shanghai",
  "reminder_times": ["18:00", "21:00"],
  "enabled": true,
  "created_at": "2026-02-17T10:30:00",
  "updated_at": "2026-02-17T10:30:00"
}
```

#### `PUT /reminders/{caregiver_id}`
请求：
```json
{
  "timezone": "Asia/Shanghai",
  "reminder_times": ["18:00", "21:00"],
  "enabled": true
}
```

### 3) Reminder 内部任务

#### `POST /internal/reminders/run-due`
Headers:
- `X-Internal-API-Key: <INTERNAL_API_KEY>`（若配置了 key）

说明：
- 执行“到点且今天未提交”的提醒扫描。
- 同一 child 同一天同一时段只会记录一次（DB 唯一约束 + 幂等检查）。

响应：
```json
{
  "checked_caregivers": 1,
  "triggered_notifications": 1
}
```

#### `GET /internal/notifications/logs`
查询参数：
- `caregiver_id`（可选）
- `local_date`（可选）

说明：用于调试和验证提醒触发。

## 定时任务规则

- APScheduler 每分钟执行一次扫描。
- 仅 `current_local_time in reminder_times` 的家长会触发检查。
- 对家长每个 child 判断当天 `diary_entries.submitted`。
- 未提交才触发提醒（当前为占位发送：日志 + `notification_logs` 记录）。
- 防重策略：`(caregiver_id, child_id, local_date, slot_time)` 唯一约束。

## 与前端对接最小改动

1. 接口地址切换：
- `Diary`: `GET/PUT /api/v1/diary/{childId}/{yyyy-mm-dd}`
- `Reminders`: `GET/PUT /api/v1/reminders/{caregiverId}`

2. 字段映射：
- `isSubmitted` -> `submitted`
- `submitTime` -> `submitted_at`
- `formData` -> `responses`

3. 本地提醒迁移策略（平滑）：
- 保留前端本地提醒作为 fallback（短期）。
- 前端在进入 Dashboard 时调用 `GET /reminders/{id}` 展示服务端配置。
- 前端提交问卷后调用 `PUT /diary/...`；后端自动停止当天后续提醒（因为已 submitted）。
- 逐步下线本地定时逻辑，仅保留权限引导与 UI 状态。

## 最少 5 条 curl 示例

假设：
- `BASE=http://127.0.0.1:8000/api/v1`
- `KEY=change_me`
- 今天是 `2026-02-17`（请替换成你本地当天）

1) 创建 caregiver
```bash
curl -X POST "$BASE/caregivers" \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","timezone":"Asia/Shanghai"}'
```

2) 创建 child
```bash
curl -X POST "$BASE/caregivers/children" \
  -H "Content-Type: application/json" \
  -d '{"caregiver_id":1,"name":"Ella"}'
```

3) 获取今日 diary 状态
```bash
curl "$BASE/diary/1/2026-02-17"
```

4) 提交今日 diary
```bash
curl -X PUT "$BASE/diary/1/2026-02-17" \
  -H "Content-Type: application/json" \
  -d '{"submitted":true,"responses":{"mood":"good","sleep_hours":8}}'
```

5) 更新提醒设置
```bash
curl -X PUT "$BASE/reminders/1" \
  -H "Content-Type: application/json" \
  -d '{"timezone":"Asia/Shanghai","reminder_times":["18:00","21:00"],"enabled":true}'
```

6) 手动触发到点扫描（内部）
```bash
curl -X POST "$BASE/internal/reminders/run-due" \
  -H "X-Internal-API-Key: $KEY"
```

7) 查询提醒日志
```bash
curl "$BASE/internal/notifications/logs?caregiver_id=1" \
  -H "X-Internal-API-Key: $KEY"
```

## 验证流程（今天已提交/未提交）

1. 把提醒时间先临时设成当前分钟（例如 `10:48`）并 `enabled=true`。
2. 保持 today diary 为未提交，调用 `POST /internal/reminders/run-due`，应看到 `triggered_notifications > 0`。
3. 再次调用同接口，同一分钟同 child 不应重复触发（防重生效）。
4. 提交 today diary（`submitted=true`）。
5. 下一个提醒时点再次调用 `run-due`，应不再触发该 child。

## 关键实现说明

- `app/api/diary.py`
  - PUT 强制只允许更新“家长时区下的今天”。
- `app/services/reminder_service.py`
  - 核心规则：到点 + 今日未提交才触发。
- `app/services/notification_service.py`
  - 可替换发送适配层（当前写日志+DB，后续接 Web Push/FCM/APNs）。
- `app/models/notification_subscription.py`
  - 已预留订阅信息存储结构。

## 备注

当前执行环境无法联网安装依赖，所以我已完成代码与语法级校验，但未能在此环境跑起 `uvicorn` 与真实 `alembic upgrade`。你在本机联网环境执行上面的安装/运行命令即可完整验证。
