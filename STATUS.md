# MEDSI Care — статус проекта

## 1. Текущий этап

10 ноября 2026 года: этап 2 по календарю ТЗ ещё не закрыт. Backend-вертикальный
срез, AI-адаптеры, RBAC и исследовательский каркас существуют; основной P0-сценарий
пока не завершён из-за отсутствия trends, demo-loader и safety-правил.

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

Живая проверка PostgreSQL в текущем sandbox заблокирована запретом на socket
и остановленным системным сервисом. Миграция и repository проверены на SQLite,
а живой PostgreSQL smoke-тест этого кода выполнялся до сброса окружения.

P0.3 завершена в коде:

- [x] отдельный endpoint исправления текста;
- [x] extraction использует `corrected_text`, если он сохранён;
- [x] correction без фактов остаётся статусом `awaiting_analysis`;
- [x] frontend показывает и редактирует факты;
- [x] frontend вызывает confirm и передаёт только разрешённые поля;
- [x] подтверждённые факты участвуют в monitoring-анализе.

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
- 16 backend-тестов.

## 4. Что проверено тестами

- `pytest -q` — 16 тестов;
- `python -m compileall -q backend experiments`;
- `alembic check` на PostgreSQL;
- миграция `0003_events_notifications` на SQLite и repository round-trip;
- frontend production build;
- реальный PostgreSQL HTTP smoke-тест для RBAC и подтверждения фактов;
- mock-тесты GigaChat/ASR и локальная загрузка faster-whisper base.

## 5. Что не реализовано

- таблица и API `audit_events`;
- сохранение результата анализа и восстановление истории событий;
- trends API и графики сна, активности и пульса;
- demo-loader для 14–28 дней;
- safety rules для потенциально экстренных жалоб;
- диапазоны и проверка будущих дат измерений;
- frontend/API integration tests;
- production-аутентификация и приглашения доверенных лиц.

## 6. Подтверждённые P0-проблемы

- нет графиков и trends;
- нет воспроизводимого demo-loader;
- нет аварийного safety-сценария;
- неполная валидация измерений;
- README не гарантировал запуск через `.venv`.

## 7. Подтверждённые P1-проблемы

- анализ использует только последнее наблюдение;
- отсутствуют baselines/audit tables из полной модели ТЗ;
- нет rate limit и prompt-injection тестов;
- нет ограничения длительности аудио;
- нет offline fallback для extraction;
- нет Python lock-файла.

## 8. Следующая задача

Добавить воспроизводимый demo-loader и trends API, затем закрыть safety rules и
диапазонную валидацию измерений.

## 9. Известные ограничения и технический долг

- demo identities используют synthetic credentials и не являются production auth;
- Docker Compose поднимает только PostgreSQL;
- результаты эксперимента Method C нельзя публиковать как доказательство, пока
  extractor не отделён от эталонных меток;
- Python-зависимости пока задаются диапазонами без lock-файла;
- реальные медицинские данные, FHIR, wearable API, TTS и Ollama исключены.

## 10. Приблизительная инженерная оценка готовности

Около **45% MVP**. Оценка не является метрикой качества и будет пересмотрена
после demo-сценария, trends, safety и полного пользовательского пути.
