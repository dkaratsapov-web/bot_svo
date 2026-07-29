# Развёртывание и автодеплой

Цель — свести ручную работу к минимуму: **один раз** запустить установочный
скрипт на сервере, дальше всё обновляется само.

```
Claude Code / вы  ──push в main──►  GitHub Actions ──►  GHCR (образ)
                                                          │
                        ┌─────────────────────────────────┴────────────┐
                        ▼                                              ▼
              Watchtower (каждые 5 мин)                systemd-таймер (каждые 5 мин)
              обновляет образ бота                     git pull + docker compose up
                        └──────────────────┬───────────────────────────┘
                                           ▼
                                    Бот на сервере
```

Что обновляется автоматически:

| Изменение | Как попадает на сервер |
|---|---|
| Код бота (Python) | Actions собирает образ → **Watchtower** подменяет контейнер |
| compose-файлы, скрипты, Caddyfile | **systemd-таймер** делает `git pull` + `compose up -d` |
| Миграции БД | применяются при старте контейнера (`alembic upgrade head`) |
| `.env` (секреты) | только вручную — секреты намеренно не лежат в git |

---

## Установка одной командой

На чистом Ubuntu-сервере под root:

```bash
curl -fsSL https://raw.githubusercontent.com/dkaratsapov-web/bot_svo/main/scripts/install-server.sh | bash
```

Скрипт спросит **только `BOT_TOKEN`** (скрытым вводом) и сделает всё остальное:

1. swap 2 ГБ (обязателен на сервере с 1 ГБ RAM);
2. Docker + compose plugin;
3. клон репозитория в `/opt/bot_svo`;
4. `.env` с рабочими значениями по умолчанию (режим `polling`);
5. systemd-таймер автообновления;
6. запуск стека и вывод статуса.

Скрипт **идемпотентен** — повторный запуск ничего не сломает, просто доведёт
состояние до актуального. Если токен уже прописан, он его не тронет.

Предварительное условие: **пакет GHCR должен быть публичным** —
GitHub → репозиторий → *Packages* → пакет `bot_svo` → *Package settings* →
*Change visibility* → **Public**. Иначе сервер не сможет скачать образ.
(Альтернатива: `docker login ghcr.io` с PAT, имеющим право `read:packages`.)

### Вариант для нестабильного SSH

Если соединение с сервером рвётся (`Connection reset by peer`), запускайте
установку **в фоне на сервере** — тогда обрыв сессии ей не помешает. Три
независимые команды со своей машины, каждую можно повторять безопасно:

```bash
# 1. Передать токен на сервер (ввод скрытый, в историю команд не попадает)
read -rsp 'BOT_TOKEN: ' T && printf '%s' "$T" | \
  ssh -o ServerAliveInterval=15 root@СЕРВЕР 'umask 077; cat > /root/.bot_token' && \
  unset T && echo 'токен передан'

# 2. Запустить установку detached — живой терминал больше не нужен
ssh -o ServerAliveInterval=15 root@СЕРВЕР \
  'curl -fsSL https://raw.githubusercontent.com/dkaratsapov-web/bot_svo/main/scripts/install-server.sh -o /root/install.sh && chmod +x /root/install.sh && setsid nohup /root/install.sh >/root/install.log 2>&1 </dev/null & echo запущено'

# 3. Посмотреть, чем закончилось (повторяйте, пока не увидите "Установка завершена")
ssh root@СЕРВЕР 'tail -40 /root/install.log'
```

Скрипт сам подхватит токен из `/root/.bot_token` и **удалит файл** после
использования.

## Проверка после установки

```bash
cd /opt/bot_svo
docker compose -f docker-compose.prod.yml ps                    # все контейнеры Up
docker compose -f docker-compose.prod.yml logs --tail=30 bot    # bot_starting, health_server_started
systemctl status bot-svo-selfupdate.timer                       # active (waiting)
```

Напишите боту `/start` в MAX — должно прийти меню с двумя кнопками.

---

## Заказ сервера (рег.облако)

1. Панель → **Виртуальные серверы** → **+ Новый ресурс**.
2. ОС: **Ubuntu 22.04 LTS**.
3. Тариф: подойдёт `HP C1-M1-D10` (**1 vCPU / 1 ГБ / 10 ГБ**) — стек в него
   укладывается (бот ~150 МБ + Redis + Watchtower + Docker + ОС ≈ 400–600 МБ)
   при настроенном swap, который создаёт установочный скрипт.
   Комфортнее — `HP C2-M2-D40` (2 vCPU / 2 ГБ / 40 ГБ).
4. Обязательно **публичный IP** (без него у сервера нет интернета).
   Желательно статический/плавающий: при переезде на другой сервер не придётся
   менять DNS.
5. Во вкладке **«Сеть»** откройте порты `22` (SSH), `80` и `443`
   (последние два — только если планируете webhook).

### Устойчивое SSH-подключение

Соединение с некоторыми ВМ рвётся по таймауту. Добавьте на своей машине
(один раз) — и обрывов не будет:

```bash
cat >> ~/.ssh/config <<'EOF'

Host 195.24.71.252
  User root
  ServerAliveInterval 30
  ServerAliveCountMax 6
  TCPKeepAlive yes
EOF
```

Длительные операции запускайте в `tmux`, чтобы они не прерывались при обрыве:
`tmux new -s deploy`, возврат — `tmux attach -t deploy`.

---

## Переход на webhook (когда появится домен)

Polling работает без домена и TLS. Webhook эффективнее и требуется ТЗ для
production, но нужен домен с HTTPS. Сертификат выдаёт Caddy через
**Let's Encrypt** автоматически — сертификат Минцифры не нужен.

1. Купите домен и создайте **A-запись** на IP сервера:
   `bot.вашдомен.ру → 195.24.71.252`.
2. Заполните в `/opt/bot_svo/.env`:
   ```
   MODE=webhook
   DOMAIN=bot.вашдомен.ру
   ACME_EMAIL=you@вашдомен.ру
   WEBHOOK_URL=https://bot.вашдомен.ру/max/webhook
   WEBHOOK_SECRET=<случайная строка 16+ символов>
   ```
3. Перезапустите с overlay-файлом Caddy:
   ```bash
   cd /opt/bot_svo
   docker compose -f docker-compose.prod.yml -f docker-compose.webhook.yml up -d
   ```

Дальше таймер автообновления сам подхватит режим `webhook` из `.env` и будет
применять оба файла. Проверка: `curl https://bot.вашдомен.ру/healthz` → `200`.

> Caddy лежит в отдельном файле `docker-compose.webhook.yml`, а не в
> compose-профиле: поведение профилей отличается между версиями Compose, и
> Caddy без заданного `DOMAIN` уходил в бесконечный рестарт.

---

## Заполнение остальных настроек

`ADMIN_USER_IDS` и чаты операторов можно оставить пустыми при первом запуске —
бот от этого не падает. Чтобы их узнать, напишите боту и посмотрите логи:

```bash
docker compose -f docker-compose.prod.yml logs bot | grep -i user_id
```

Затем впишите значения в `.env` и перезапустите бота:

```bash
docker compose -f docker-compose.prod.yml up -d bot
```

---

## Эксплуатация

```bash
cd /opt/bot_svo

docker compose -f docker-compose.prod.yml ps              # статус
docker compose -f docker-compose.prod.yml logs -f bot     # логи
journalctl -u bot-svo-selfupdate -n 50                    # лог автообновлений
systemctl list-timers bot-svo-selfupdate                  # когда следующий запуск
./scripts/selfupdate.sh                                   # обновить прямо сейчас
```

БД и бэкапы — в `/opt/bot_svo/data` и `/opt/bot_svo/backups`, обновление
образов их не затрагивает. Бэкап SQLite делается раз в сутки с ротацией
30 дней (сервис `backup`).

---

## Частые вопросы

- **Нужен ли сертификат Минцифры?** Нет. Let's Encrypt — доверенный УЦ,
  подходит для webhook MAX. Минцифры — только под отдельное регуляторное
  требование; меняется в `Caddyfile`.
- **Watchtower не обновляет.** Проверьте, что пакет GHCR публичный, и что у
  контейнера `bot` есть метка `com.centurylinklabs.watchtower.enable=true`
  (она уже в compose).
- **Бот падает при старте с `SettingsError`.** Раньше так проявлялось пустое
  `ADMIN_USER_IDS=`; исправлено — пустые и некорректные значения теперь
  игнорируются. Обновитесь до актуального образа.
- **Контейнер перезапускается на 1 ГБ RAM.** Проверьте swap (`free -h`) и
  `dmesg | grep -i "killed process"`. Если упирается в лимиты — перейдите на
  `HP C2-M2-D40`.
- **Кончается место (10 ГБ).** `df -h`, `docker system df`, очистка:
  `docker system prune -af`.
- **В polling-режиме бот не получает сообщений.** Возможно, осталась активная
  webhook-подписка (в логах: «БОТ ИГНОРИРУЕТ POLLING!»). Снять:
  ```bash
  docker compose -f docker-compose.prod.yml exec bot python -c \
    "import asyncio;from app.main import build_bot;from app.config import get_settings;asyncio.run(build_bot(get_settings()).delete_webhook())"
  ```
