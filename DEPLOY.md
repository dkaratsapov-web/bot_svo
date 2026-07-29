# Развёртывание: рег.облако (REG.RU) + GHCR + Watchtower

Схема: пуш в `main` → GitHub Actions собирает Docker-образ и публикует в
**GHCR** → **Watchtower** на сервере сам подхватывает новый образ и
перезапускает бота. HTTPS для webhook выдаёт **Caddy** (Let's Encrypt,
автопродление). Минцифры-сертификат не требуется.

Сервер — отдельная виртуальная машина в **рег.облаке** (REG.RU), не связанная
с той, где уже размещён основной сайт. Это исключает конфликты портов
80/443 и делит нагрузку.

```
Claude Code → git push main → GitHub Actions → GHCR (образ)
                                                   │
                                       Watchtower (сервер) тянет образ
                                                   │
                                        docker compose up -d (bot)
                                                   │
                                     Caddy (TLS) ← HTTPS ← MAX webhook
```

---

## 0. Что понадобится

- Аккаунт в **рег.облаке** (reg.ru).
- Домен, на котором уже размещён основной сайт — под бота выделяем
  **поддомен** (`bot.вашдомен.ру`), корневой домен и сайт не трогаем.
- Токен бота MAX (от @MasterBot).
- Доступ к репозиторию на GitHub (`dkaratsapov-web/bot_svo`).

---

## 1. Заказать отдельный виртуальный сервер в рег.облаке

1. Панель рег.облака → **Виртуальные серверы** → **+ Новый ресурс**.
2. ОС: **Ubuntu 22.04 LTS**.
3. Тариф: подойдёт `HP C1-M1-D10` (**1 vCPU / 1 ГБ / 10 ГБ**) — стек в него
   укладывается (бот ~150 МБ + Redis + Caddy + Watchtower + Docker + ОС
   ≈ 400–600 МБ), но **обязательно настройте swap** (шаг 3) и не отключайте
   заданные в compose лимиты памяти и ротацию логов.
   Комфортнее — `HP C2-M2-D40` (2 vCPU / 2 ГБ / 40 ГБ): запас по памяти и
   заметно больше места под БД, бэкапы и образы.
4. Регион: подойдёт тот же, что у сайта (например, Москва-2).
5. Дождитесь создания, запишите **публичный IP** сервера.

Во вкладке **«Сеть»** карточки сервера настройте доступ (firewall/правила):
откройте входящие порты `22` (SSH), `80` и `443` (HTTP/HTTPS для Caddy).
Порт `8080` наружу открывать **не нужно** — бот доступен только через Caddy.

> Это **новый, отдельный** сервер — сервер с сайтом не трогаем и его
> конфигурацию не меняем.

## 2. Направить поддомен на новый сервер

В панели управления DNS вашего домена (там же, где настроен сайт) добавьте
**A-запись только для поддомена**:

```
bot.вашдомен.ру  →  <публичный IP НОВОГО сервера>
```

Существующую A/CNAME-запись для корневого домена (сайта) не изменяйте.
Дождитесь распространения DNS (обычно минуты, иногда до часа). Проверка:
`ping bot.вашдомен.ру` должен показывать IP именно нового сервера.

## 3. Настроить swap (обязательно на 1 ГБ RAM)

Без swap на тарифе с 1 ГБ памяти OOM-killer может внезапно убить бота или
Redis. Подключитесь по SSH и создайте swap-файл 2 ГБ:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # автоподключение после перезагрузки

# Реже выгружать в swap (swap как страховка, а не основной режим)
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf
sudo sysctl -p /etc/sysctl.d/99-swappiness.conf

free -h   # проверка: в строке Swap должно быть 2.0Gi
```

> На тарифе с 2 ГБ и выше swap тоже полезен, но уже не критичен.

## 4. Установить Docker на сервере

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker   # docker без sudo
```

## 5. Опубликовать первый образ (GitHub Actions)

1. Смёржите рабочую ветку в `main` (или переименуйте её в `main`) — workflow
   `.github/workflows/docker-publish.yml` запускается на пуш в `main`.
2. Дождитесь зелёного прогона в **Actions**. Образ появится в
   **Packages** репозитория: `ghcr.io/dkaratsapov-web/bot_svo:latest`.
3. **Сделайте пакет публичным** (проще всего): GitHub → репозиторий →
   *Packages* → пакет `bot_svo` → *Package settings* → *Change visibility* →
   **Public**. Тогда Watchtower тянет образ без авторизации.

   > Если пакет должен остаться приватным — на сервере выполните
   > `docker login ghcr.io` (username = GitHub-логин, password =
   > Personal Access Token с правом `read:packages`) и раскомментируйте в
   > `docker-compose.prod.yml` монтирование `~/.docker/config.json` в
   > контейнер `watchtower`.

## 6. Развернуть на сервере

```bash
git clone https://github.com/dkaratsapov-web/bot_svo.git
cd bot_svo

cp .env.example .env
nano .env   # заполните переменные (см. ниже)

docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f bot
```

Минимальный боевой `.env`:

```
BOT_TOKEN=<токен от @MasterBot>
IMAGE=ghcr.io/dkaratsapov-web/bot_svo:latest

MODE=webhook
DOMAIN=bot.вашдомен.ру
ACME_EMAIL=you@вашдомен.ру
WEBHOOK_URL=https://bot.вашдомен.ру/max/webhook
WEBHOOK_SECRET=<случайная строка 16+ символов>
WEBHOOK_PATH=/max/webhook

REDIS_URL=redis://redis:6379/0

ADMIN_USER_IDS=<ваш max_user_id>
ADMIN_CHAT_DEFAULT_ID=<id чата операторов>
# при желании — по направлениям:
# ADMIN_CHAT_JOIN_ID, ADMIN_CHAT_JOB_ID, ADMIN_CHAT_PSY_ID, ADMIN_CHAT_LAW_ID, ADMIN_CHAT_OTHER_ID

ORG_PHONE=+7...
ORG_EMAIL=info@вашдомен.ру
PRIVACY_POLICY_URL=https://вашдомен.ру/privacy
```

При старте бот сам зарегистрирует webhook в MAX (`POST /subscriptions`), а Caddy
выпустит TLS-сертификат для `DOMAIN`.

## 7. Проверить

```bash
curl https://bot.вашдомен.ру/healthz
# {"db": true, "redis": true}  и код 200
```

Напишите боту `/start` в MAX — должно прийти меню с двумя кнопками.

## 8. Как теперь работает автодеплой

Дальше вам (и ИИ) достаточно **пушить изменения в `main`**:

1. Claude Code вносит правки и пушит ветку, вы мёржите PR в `main`
   (или ИИ пушит прямо в `main`, если так настроите).
2. GitHub Actions собирает новый образ и кладёт в GHCR.
3. **Watchtower** (интервал 300 с) видит новый `:latest`, скачивает его и
   пересоздаёт контейнер `bot` — со сбросом на новую версию без ручных действий.

Миграции БД применяются автоматически при старте контейнера
(`docker-entrypoint.sh` → `alembic upgrade head`).

### Полезные команды на сервере

```bash
docker compose -f docker-compose.prod.yml ps            # статус
docker compose -f docker-compose.prod.yml logs -f bot   # логи бота
docker compose -f docker-compose.prod.yml pull bot && \
  docker compose -f docker-compose.prod.yml up -d bot    # ручное обновление
docker compose -f docker-compose.prod.yml restart caddy # перечитать Caddyfile
```

## Частые вопросы

- **Нужен ли сертификат Минцифры?** Нет. Let's Encrypt — доверенный УЦ,
  подходит для webhook MAX. Минцифры — только под отдельное регуляторное
  требование; при необходимости меняется в `Caddyfile`.
- **Watchtower не обновляет.** Проверьте, что пакет GHCR публичный (или
  настроена авторизация), и что у контейнера `bot` есть метка
  `com.centurylinklabs.watchtower.enable=true` (она уже в compose).
- **Caddy не выпускает сертификат.** Убедитесь, что A-запись поддомена
  указывает на новый сервер и порты 80/443 открыты в правилах доступа
  («Сеть» в карточке сервера в рег.облаке).
- **Потеря данных при пересоздании.** БД и бэкапы лежат в томах `./data` и
  `./backups` на хосте — обновление образа их не трогает.
- **Контейнер падает / перезапускается на 1 ГБ RAM.** Проверьте swap
  (`free -h`) — он должен быть включён (шаг 3). Посмотрите, не убил ли процесс
  OOM-killer: `dmesg | grep -i "killed process"`. В `docker stats` видно
  реальное потребление. Если упирается в лимиты — перейдите на `HP C2-M2-D40`.
- **Кончается место на диске (10 ГБ).** Проверьте `df -h` и
  `docker system df`. Освободить: `docker system prune -af --volumes`
  (осторожно: удалит неиспользуемые тома) и почистите старые бэкапы в
  `./backups` (скрипт сам держит только 30 дней).
