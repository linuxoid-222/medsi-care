# MEDSI Care — статус проекта

## 1. Текущий этап

9 ноября 2026 года: этап 2 по календарю ТЗ ещё не закрыт. Backend-вертикальный
срез, AI-адаптеры, RBAC и исследовательский каркас существуют; основной P0-сценарий
пока не завершён из-за отсутствия сохраняемых событий, уведомлений, trends,
demo-loader и safety-правил.

## 2. Дата последнего обновления

2026-11-09.

## 3. Что реализовано

- модульный монолит FastAPI + React + PostgreSQL;
- Alembic-миграции для profiles, observations, check-ins и symptom_facts;
- ручной ввод наблюдений и текстовых check-in;
- baseline на медиане/MAD и детерминированный анализ;
- GigaChat-адаптер с OAuth, JSON Schema и проверкой evidence;
- локальный faster-whisper adapter и browser MediaRecorder;
- подтверждение фактов с сохранением в PostgreSQL;
- минимальный signed-token RBAC с user/caregiver и read-only summary;
- синтетический генератор и Baseline A/B/Method C;
- 16 backend-тестов.

## 4. Что проверено тестами

- `pytest -q` — 16 тестов;
- `python -m compileall -q backend experiments`;
- `alembic check` на PostgreSQL;
- frontend production build;
- реальный PostgreSQL HTTP smoke-тест для RBAC и подтверждения фактов;
- mock-тесты GigaChat/ASR и локальная загрузка faster-whisper base.

## 5. Что не реализовано

- таблицы и API `monitoring_events`, `notifications`, `audit_events`;
- сохранение результата анализа и восстановление истории событий;
- trends API и графики сна, активности и пульса;
- demo-loader для 14–28 дней;
- safety rules для потенциально экстренных жалоб;
- полная связка подтверждённых symptom facts с monitoring endpoint;
- frontend extraction/confirmation flow;
- диапазоны и проверка будущих дат измерений;
- frontend/API integration tests;
- production-аутентификация и приглашения доверенных лиц.

## 6. Подтверждённые P0-проблемы

- исходники не были зафиксированы в Git;
- отсутствуют сохраняемые события и уведомления;
- подтверждённые факты не передаются в анализ;
- нет frontend подтверждения фактов;
- нет графиков и trends;
- нет воспроизводимого demo-loader;
- нет аварийного safety-сценария;
- неполная валидация измерений;
- README не гарантировал запуск через `.venv`.

## 7. Подтверждённые P1-проблемы

- анализ использует только последнее наблюдение;
- исправленный текст не используется в extraction;
- status check-in смешивает correction и confirmation;
- отсутствуют baselines/audit tables из полной модели ТЗ;
- нет rate limit и prompt-injection тестов;
- нет ограничения длительности аудио;
- нет offline fallback для extraction;
- нет Python lock-файла.

## 8. Следующая задача

Зафиксировать текущий проект в Git, затем добавить `monitoring_events` и
`notifications` с миграцией, API и тестами. После этого связать сохранённые
факты с анализом.

## 9. Известные ограничения и технический долг

- demo identities используют synthetic credentials и не являются production auth;
- Docker Compose поднимает только PostgreSQL;
- результаты эксперимента Method C нельзя публиковать как доказательство, пока
  extractor не отделён от эталонных меток;
- Python-зависимости пока задаются диапазонами без lock-файла;
- реальные медицинские данные, FHIR, wearable API, TTS и Ollama исключены.

## 10. Приблизительная инженерная оценка готовности

Около **40% MVP**. Оценка не является метрикой качества и будет пересмотрена
после сохранения событий, demo-сценария и полного пользовательского пути.
