# MEDSI Care — статус проекта

## 1. Текущий этап

10 ноября 2026 года: этап 2 по календарю ТЗ ещё не закрыт. Backend-вертикальный
срез, AI-адаптеры, RBAC, demo-loader, trends и safety/validation блок существуют;
сквозной MVP ещё требует отдельных интеграционных проверок и финальной шлифовки.

## 2. Дата последнего обновления

2026-11-10.

## 2a. Проверка текущей P0-задачи

P0.2 считается завершённой в коде:

- [x] миграция `0003_events_notifications`;
- [x] persistence и round-trip тесты событий/уведомлений;
- [x] API событий, уведомлений и `read`;
- [x] caregiver UI для событий и уведомлений;
- [x] анализ сохраняет событие с evidence, period, ruleset version и source IDs;
- [x] `pytest` и frontend build проходят.

Для исторической проверки P0.2 live PostgreSQL был недоступен в прежнем sandbox;
в рамках P0.8 текущий системный PostgreSQL проверен на чистой базе.

P0.3 завершена в коде:

- [x] отдельный endpoint исправления текста;
- [x] extraction использует `corrected_text`, если он сохранён;
- [x] correction без фактов остаётся статусом `awaiting_analysis`;
- [x] frontend показывает и редактирует факты;
- [x] frontend вызывает confirm и передаёт только разрешённые поля;
- [x] подтверждённые факты участвуют в monitoring-анализе.

P0.4 завершена в коде:

- [x] trends API для сна, активности и пульса;
- [x] baseline points рассчитываются по предыдущей истории;
- [x] frontend LineChart показывает факт и baseline;
- [x] события доступны через сохранённые event IDs.

P0.5 завершена в коде:

- [x] отдельный demo-loader endpoint;
- [x] фиксированный seed и 14–28 дней;
- [x] заранее заданное изменение с обнаруживаемым падением метрик;
- [x] reset очищает observations, check-ins, facts, events и notifications;
- [x] synthetic/demo режим явно ограничен `MEDSI_DEMO_MODE=true`;
- [x] повторяемость покрыта тестами и smoke-проверкой.

P0.6 завершена в коде:

- [x] серверная техническая валидация значений, единиц, source, quality и будущих дат;
- [x] технические границы сна 0–24 h, активности 0–1440 min, пульса 20–250 bpm,
  систолического давления 50–250 mmHg и диастолического 30–150 mmHg;
- [x] согласованность систолического и диастолического давления для одной даты;
- [x] отдельный deterministic safety module версии `safety-v1`;
- [x] подтверждённые safety-факты сохраняются как события уровня `safety` с evidence;
- [x] safety-событие создаёт notification пользователю и доверенному лицу;
- [x] неподтверждённые и обычные жалобы не создают safety-событие;
- [x] обновлены API-схема, миграция `0004_observation_quality`, README и `docs/SAFETY.md`.

P0.7 интеграционная проверка полного сценария завершена:

- [x] интеграционный тест FastAPI-маршрутов и хранилища покрывает login,
  demo-loader, observations, check-ins, trends, extraction, correction,
  confirmation, analysis, events, notifications, caregiver и reset;
- [x] проверено, что до confirmation событие не создаётся;
- [x] safety-сценарий подтверждённого факта создаёт отдельное событие и
  notification без повторного вызова LLM;
- [x] проверены 403 для caregiver write и 422 для несогласованного давления;
- [x] API smoke по loopback прошёл на локальном FastAPI-сервере;
- [x] UI smoke в браузере прошёл для user/caregiver, графика, анализа и
  отметки уведомления прочитанным;
- [x] frontend использует API для observations, check-ins, trends, analysis,
  events и notifications; фиктивных данных в UI не добавлено;
- [x] frontend показывает понятные ошибки 403/422 и контролируемые ошибки API.

P0.8 clean-run и PostgreSQL live-проверка завершены:

- [x] создан временный Git worktree из `HEAD` с применением текущего снимка
  изменений; исходная рабочая копия после проверки восстановлена без временных
  файлов;
- [x] в чистом worktree выполнены `python3 -m venv .venv` и
  `.venv/bin/pip install --disable-pip-version-check -e 'backend[dev]'`;
- [x] frontend установлен через `npm ci` по `package-lock.json`;
- [x] `alembic upgrade head` применил все четыре миграции с нуля в PostgreSQL;
- [x] backend запущен против PostgreSQL, frontend запущен через `npm run dev`,
  HTTP-загрузка frontend подтверждена;
- [x] clean-run API smoke прошёл на PostgreSQL: loader, reset, observations,
  check-ins, trends, analysis, events, notifications и safety;
- [x] PostgreSQL repository smoke проверил round-trip observation/check-in/facts,
  safety event, notification/read и reset;
- [x] `alembic check` на PostgreSQL сообщил `No new upgrade operations detected`.

Docker CLI и Compose установлены, но `docker info` и `docker compose up -d db`
завершились ошибкой доступа к `/var/run/docker.sock`. Это ограничение доступа
окружения; PostgreSQL live-проверка выполнена через доступный системный сервис.

Исследовательский протокол Method C исправлен:

- [x] введена версия протокола `research-v2`;
- [x] генератор создаёт независимые `ground_truth_event`, `ground_truth_facts`,
  `scenario_type` и `change_start_day`;
- [x] labels используются только evaluator и не передаются extractor/Method C;
- [x] добавлены Pydantic-схемы `ExtractedFact`/`ExtractorResult` и контракт
  `FactExtractor`;
- [x] основной эксперимент использует `DeterministicRuExtractor` версии
  `deterministic-ru-v1`, который обрабатывает present/absent/uncertain;
- [x] добавлен необязательный `LlmExtractorAdapter` без обязательного GigaChat;
- [x] held-out split выполняется по profile ID с фиксированным seed;
- [x] добавлена абляция `method_c_no_text`;
- [x] добавлены detection latency, extractor metrics, ошибки отрицания и
  неопределённости;
- [x] конфигурация, split, версии правил/extractor и метрики сохраняются в
  результате эксперимента;
- [x] защитные тесты проверяют отсутствие leakage и повторяемость.

## 3. Что реализовано

- модульный монолит FastAPI + React + PostgreSQL;
- Alembic-миграции для profiles, observations, check-ins и symptom_facts;
- ручной ввод наблюдений и текстовых check-in;
- baseline на медиане/MAD и детерминированный анализ;
- GigaChat-адаптер с OAuth, JSON Schema и проверкой evidence;
- локальный faster-whisper adapter и browser MediaRecorder;
- подтверждение фактов с сохранением в PostgreSQL;
- минимальный signed-token RBAC с user/caregiver и read-only summary;
- сохраняемые monitoring_events и notifications с read/read-only API;
- синтетический генератор и Baseline A/B/Method C;
- исследовательский протокол `research-v2` и `docs/RESEARCH.md`;
- 33 backend-теста.

## 4. Что проверено тестами

- `.venv/bin/pytest -q` — 33 теста, включая интеграционный API-сценарий,
  диапазонную валидацию, safety, confirmation и caregiver notification;
- `.venv/bin/python -m compileall -q backend experiments`;
- `DATABASE_URL=sqlite:///... .venv/bin/alembic upgrade head` и `alembic check` —
  миграции до `0004_observation_quality` проходят;
- frontend production build через `npm run build`;
- demo/reset smoke: 21 день, 63 observations, 21 check-in, повторная загрузка
  с тем же seed воспроизводима, reset удаляет events/notifications;
- `git diff --check`;
- clean-run bootstrap: backend `venv` + editable install, frontend `npm ci`;
- clean-run backend/frontend startup и HTTP-загрузка Vite;
- PostgreSQL from-scratch migrations and repository smoke;
- полный эксперимент `research-v2` на 100 профилях × 28 днях, seed 42, split 80/20;
- повторный запуск эксперимента с тем же seed даёт идентичный результат;
- API smoke: login → demo-loader → observations/check-ins/trends → check-in →
  extraction через тестовый provider → confirmation → analysis → caregiver
  summary → read notification → safety confirmation → reset;
- UI smoke: login user/caregiver, загрузка данных API, сохранение check-in,
  запуск анализа, отображение события/уведомления и отметка `Прочитано`;
- реальный PostgreSQL HTTP smoke-тест для RBAC и подтверждения фактов;
- mock-тесты GigaChat/ASR и локальная загрузка faster-whisper base.

PostgreSQL live-проверка для P0.8 выполнена на отдельной чистой базе.

Фактический held-out результат `research-v2` (synthetic only):

| Метод | Precision | Recall | F1 | False alerts/100 person-days | Latency, days | Insufficient |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline A | 0.963 | 0.333 | 0.495 | 0.357 | 1.125 | 0.000 |
| Baseline B | 0.658 | 0.641 | 0.649 | 9.286 | 0.118 | 0.252 |
| Method C без текста | 0.658 | 0.641 | 0.649 | 9.286 | 0.118 | 0.252 |
| Method C | 0.711 | 0.821 | 0.762 | 9.286 | 0.000 | 0.252 |

Deterministic extractor на том же held-out наборе: precision 1.000, recall
1.000, F1 1.000, ошибок отрицания 0, ошибок неопределённости 0. Это ожидаемо
для шаблонного synthetic-текста и не является оценкой реальной модели.

## 5. Что не реализовано

- таблица и API `audit_events`;
- сохранение результата анализа и восстановление истории событий;
- production-аутентификация и приглашения доверенных лиц.

## 6. Подтверждённые P0-проблемы

P0-блокирующих проблем по clean-run и PostgreSQL live-проверке не осталось.
Ограничение Docker socket относится к текущему окружению, а не к приложению.

## 7. Подтверждённые P1-проблемы

- анализ использует только последнее наблюдение;
- отсутствуют baselines/audit tables из полной модели ТЗ;
- нет rate limit и prompt-injection тестов;
- нет ограничения длительности аудио;
- нет offline fallback для extraction;
- нет Python lock-файла.

## 8. Следующая задача

Method C protocol v2 завершён. Результаты можно использовать в конкурсной
работе только как синтетический инженерный эксперимент с явным описанием
ограничений; клиническими доказательствами они не являются. Следующая задача —
подготовить исследовательский раздел и графики с независимой проверкой описаний,
не добавляя новые продуктовые функции.

## 9. Известные ограничения и технический долг

- demo identities используют synthetic credentials и не являются production auth;
- Docker Compose поднимает только PostgreSQL;
- результаты Method C допустимо показывать только как synthetic engineering
  experiment; они не являются клиническим доказательством;
- Python-зависимости пока задаются диапазонами без lock-файла;
- реальные медицинские данные, FHIR, wearable API, TTS и Ollama исключены.

## 10. Приблизительная инженерная оценка готовности

Около **70% MVP**. Оценка не является метрикой качества; инфраструктурный
clean-run и PostgreSQL live-путь проверены, остаётся исследовательская часть.
