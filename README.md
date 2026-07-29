# Чат-бот Ассоциации СВО Тверской области (мессенджер MAX)

Бот принимает заявки на **вступление в Ассоциацию** и на **консультацию** по
четырём направлениям (трудоустройство, психологическая и юридическая помощь,
индивидуальный вопрос). Все заявки сохраняются в БД, дублируются уведомлением
в чат ответственного оператора и выгружаются в XLSX.

Бот не консультирует по существу — он собирает контакт и передаёт его человеку.

## Стек

Python 3.12 · [`maxapi`](https://pypi.org/project/maxapi/) · SQLAlchemy 2.x
(async, SQLite + `aiosqlite`) · Alembic · aiohttp (webhook) · Redis (FSM +
идемпотентность) · openpyxl · pydantic-settings · structlog · Docker.

Обоснование выбора библиотеки — см. [`ADR.md`](ADR.md). Открытые вопросы к
заказчику — [`QUESTIONS.md`](QUESTIONS.md).

## Структура проекта

```
app/
  main.py            # точка входа: webhook | polling, healthz, graceful shutdown
  config.py          # pydantic-settings (.env)
  texts.py           # все тексты сообщений (правит заказчик)
  keyboards.py       # inline-клавиатуры
  states.py          # FSM-состояния
  logging_setup.py   # structlog (JSON), маскирование ФИО/телефонов
  runtime.py         # разделяемые зависимости
  handlers/          # common, consent, join, consult, admin
  services/          # applications, notifier, export, idempotency
  db/                # models, session, repo
  utils/             # validators, throttling, rate_limit, filters
  middlewares/       # идемпотентность, анти-флуд
migrations/          # Alembic
tests/               # pytest
scripts/backup.sh    # ежедневный бэкап SQLite с ротацией
```

## Быстрый старт (локально, polling)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# впишите BOT_TOKEN; для локали оставьте MODE=polling и пустой REDIS_URL

alembic upgrade head          # создать схему БД
python -m app.main            # запустить бота (long polling)
```

Тесты:

```bash
pytest -q
```

## Получение токена бота

1. В приложении MAX откройте диалог с системным ботом **@MasterBot**
   (создание и управление ботами).
2. Команда `/newbot` → задайте имя и username бота.
3. MasterBot выдаст **токен** — строку доступа к Bot API.
4. Впишите токен в `.env` (`BOT_TOKEN=...`). **Не коммитьте `.env`.**
5. Полезные команды MasterBot: `/mybots`, `/token` (перевыпуск),
   `/setcommands` (не обязательно — команды бот регистрирует сам при старте).

> Токен передаётся только в заголовке `Authorization: <token>`. Передача в
> query-параметрах API MAX не поддерживается — библиотека это учитывает.

## Переменные окружения

Полный список — в [`.env.example`](.env.example). Ключевые:

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен бота (обязателен) |
| `API_BASE_URL` | `https://platform-api2.max.ru` (старый `platform-api.max.ru` устарел) |
| `MODE` | `webhook` (production) или `polling` (dev) |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` / `WEBHOOK_PATH` | параметры webhook |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/bot.db` |
| `REDIS_URL` | FSM + идемпотентность (prod); пусто → in-memory (dev) |
| `ADMIN_USER_IDS` | id администраторов для `/stats`, `/export` |
| `ADMIN_CHAT_JOIN_ID`, `ADMIN_CHAT_{JOB,PSY,LAW,OTHER}_ID`, `ADMIN_CHAT_DEFAULT_ID` | чаты уведомлений |
| `ORG_PHONE`, `ORG_EMAIL`, `ORG_SITE_URL`, `PRIVACY_POLICY_URL` | контакты/политика |
| `CONSENT_VERSION`, `DUPLICATE_WINDOW_HOURS`, `ASK_FREE_TEXT_FOR_OTHER`, `RESPONSE_SLA_DAYS` | поведение |

## Запуск в Docker

```bash
cp .env.example .env   # заполните BOT_TOKEN и, для webhook, WEBHOOK_URL/SECRET
docker compose up -d --build
docker compose logs -f bot
```

`docker compose` поднимает три сервиса: `bot`, `redis` и `backup` (ежедневный
бэкап SQLite с ротацией 30 дней). При старте контейнер сам применяет миграции
(`alembic upgrade head`) — см. `docker-entrypoint.sh`.

> **Боевое развёртывание с автодеплоем** (рег.облако + GHCR + Watchtower +
> Caddy/Let's Encrypt) описано в [`DEPLOY.md`](DEPLOY.md): пуш в `main` →
> сборка образа в GitHub Actions → сервер сам подхватывает новую версию.

БД и бэкапы хранятся в томах `./data` и `./backups` (вне образа и вне
репозитория).

## Перевод на webhook (production)

Webhook в MAX принимается **только по HTTPS** с сертификатом от доверенного УЦ
(в т.ч. **корневого сертификата Минцифры**). Самоподписанные сертификаты
запрещены. Лимит платформы — **30 rps** (соблюдается глобальным
rate-limiter'ом).

### 1. Установка корневого сертификата Минцифры

Если ваш TLS-сертификат выпущен УЦ Минцифры, конечные клиенты (и сам сервер)
должны доверять его корню.

- Скачайте корневой и выпускающий сертификаты Минцифры с портала Госуслуг
  (раздел «Как установить сертификат»).
- **Linux (Debian/Ubuntu):**
  ```bash
  sudo cp russian_trusted_root_ca.crt russian_trusted_sub_ca.crt \
      /usr/local/share/ca-certificates/
  sudo update-ca-certificates
  ```
- **В Docker-образ:** положите `.crt` в `./certs/` и раскомментируйте
  соответствующие строки `COPY`/`update-ca-certificates` в `Dockerfile`.

### 2. HTTPS-терминация

Поднимите reverse-proxy (nginx/Caddy/Traefik) с валидным TLS-сертификатом и
проксируйте на контейнер `bot` (порт `8080`, путь из `WEBHOOK_PATH`).
Пример nginx:

```nginx
location /max/webhook {
    proxy_pass http://127.0.0.1:8080/max/webhook;
    proxy_set_header X-Max-Bot-Api-Secret $http_x_max_bot_api_secret;
}
location /healthz {
    proxy_pass http://127.0.0.1:8080/healthz;
}
```

### 3. Настройка и регистрация webhook

В `.env`:

```
MODE=webhook
WEBHOOK_URL=https://bot.example.ru/max/webhook
WEBHOOK_SECRET=<случайная строка 5..256 символов>
WEBHOOK_PATH=/max/webhook
```

При старте в режиме `webhook` бот сам вызывает `POST /subscriptions`
(`bot.subscribe_webhook`) с указанным URL и секретом. Секрет проверяется на
каждом входящем запросе через заголовок `X-Max-Bot-Api-Secret` (иначе 403).

Проверка живости: `GET https://bot.example.ru/healthz` — проверяет БД и Redis
(200 — здоров, 503 — деградация).

> Long polling (`GET /updates`) используйте только для локальной разработки.

## Команды бота

- `/start`, `/menu` — главное меню (две кнопки: «Вступить в Ассоциацию»,
  «Получить консультацию»).
- `/help` — краткое описание и контакты Ассоциации.
- `/cancel` — отменить текущую заявку (сброс состояния).

### Админ-команды (только `ADMIN_USER_IDS`)

- `/stats` — счётчики заявок за сегодня / 7 дней / всего и по направлениям.
- `/export` — XLSX со всеми заявками (листы «Вступление» и «Консультации»).
- `/export 01.01.2026 31.01.2026` — выгрузка за период (даты включительно).

## Данные и приватность

- В логах ФИО и телефоны маскируются (`Иванов И. И.`, `+7900***0011`); формат
  логов — JSON в stdout (structlog).
- Согласие на обработку ПДн (152-ФЗ) запрашивается один раз на пользователя;
  дата, время и версия текста политики сохраняются.
- Файл БД и бэкапы — вне репозитория (`.gitignore`).
- Все временные метки хранятся в UTC, оператору показываются в Europe/Moscow.

## Резервное копирование

`scripts/backup.sh` делает консистентную копию SQLite (`.backup`) в
`./backups` и удаляет копии старше `BACKUP_RETENTION_DAYS` (по умолчанию 30).
В `docker-compose.yml` запускается сервисом `backup` раз в сутки. Для хоста без
Docker можно повесить в cron:

```cron
0 3 * * * cd /opt/max-bot-svo && BACKUP_RETENTION_DAYS=30 ./scripts/backup.sh
```
