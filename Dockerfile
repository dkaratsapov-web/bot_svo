FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow

WORKDIR /app

# Сертификаты (в т.ч. корневой Минцифры) можно добавить при сборке —
# положите .crt-файлы в ./certs и раскомментируйте строки ниже.
# COPY certs/*.crt /usr/local/share/ca-certificates/
# RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
#     && update-ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/backups

# Применяем миграции и запускаем бота.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
