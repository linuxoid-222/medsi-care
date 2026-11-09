# MEDSI Care

Исследовательский прототип для работы только с синтетическими данными.

## Текущий срез

Текущий срез содержит доменную логику baseline, API ручного ввода,
PostgreSQL-слой, GigaChat/faster-whisper adapters и минимальный RBAC. События,
уведомления, trends и safety rules находятся в следующем P0-блоке.

## План запуска

Первичная настройка backend:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
```

Первичная настройка frontend:

```bash
cd frontend
npm install
cd ..
```

Для режима PostgreSQL:

```bash
cp .env.example .env
set -a && source .env && set +a
docker compose up -d db
.venv/bin/alembic upgrade head
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --app-dir backend --reload
```

В синтетической демоверсии доступны две роли:

```text
demo-user / demo-user          пользователь, чтение и запись
demo-caregiver / demo-caregiver доверенное лицо, только чтение summary
```

Токен bearer подписывается backend-секретом `MEDSI_AUTH_SECRET`. Эти учётные
данные предназначены только для локальной демоверсии; production-аутентификация
и управление приглашениями находятся за пределами MVP.

Проверка доменного ядра не требует базы данных:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest -q
```

Если `MEDSI_STORAGE` не задан, API использует временное in-memory-хранилище
только для локального smoke-теста. Для демонстрации и интеграционных проверок
используется `MEDSI_STORAGE=postgres`.

## Demo-сценарий

Loader доступен только при `MEDSI_DEMO_MODE=true` и требует bearer-токен
`demo-user`. Он очищает профиль и загружает повторяемую synthetic-историю:
21 день, 14 дней baseline и 7 дней с падением сна/активности и повышенным
пульсом. Повторный вызов с тем же seed даёт те же идентификаторы и значения.

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"user_id":"demo-user","password":"demo-user"}' | \
  .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST http://127.0.0.1:8000/api/v1/demo/load-scenario \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"seed":20261110,"days":21,"reset":true}'
```

Параметр `reset=true` удаляет synthetic observations, check-ins, facts, events
и notifications профиля перед повторной загрузкой.

Запуск frontend:

```bash
cd frontend
npm run dev
```

Все настройки внешних провайдеров должны задаваться через переменные окружения;
секреты не коммитятся.

## GigaChat

Для локальной проверки адаптера добавьте в игнорируемый файл `.env` ключ,
полученный в кабинете GigaChat API, и модель, доступную для этого аккаунта:

```bash
GIGACHAT_AUTH_KEY=локальное_значение_без_коммита
GIGACHAT_MODEL=модель_из_GET_v1_models
```

`GIGACHAT_AUTH_KEY` — это Authorization Key из Studio: проект GigaChat API →
«Настройки API» → «Получить ключ». Это не access token и не ключ ChatGPT.

Для TLS-соединения нужен корневой сертификат НУЦ Минцифры. В текущем `.venv`
он добавлен в certifi bundle; для нового окружения следуйте официальной
инструкции GigaChat и не отключайте проверку сертификатов.

Точную модель для `GIGACHAT_MODEL` нужно получить у API через `GET /v1/models`
с access token. Например, `GigaChat-2` может быть идентификатором Lite-модели,
но в конфигурацию следует помещать именно значение, доступное аккаунту.
Для физического лица обычно используется `GIGACHAT_SCOPE=GIGACHAT_API_PERS`;
scope зависит от типа проекта.

Ключ не нужно передавать в чат. Без него проходят mock-тесты адаптера, но live
запрос к GigaChat возвращает контролируемую ошибку конфигурации.

## faster-whisper

Параметры локального распознавания задаются в `.env`:

```bash
FASTER_WHISPER_MODEL=base
FASTER_WHISPER_DEVICE=cpu
FASTER_WHISPER_COMPUTE_TYPE=int8
FASTER_WHISPER_LANGUAGE=ru
```

Модель не скачивается во время тестов. При первом реальном запросе faster-whisper
может загрузить выбранную модель в локальный кэш; результат транскрипции сначала
поступает на ручную проверку пользователя.
