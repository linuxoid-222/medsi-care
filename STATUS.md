# MEDSI Care — статус проекта

## 1. Текущий этап

10 ноября 2026 года: этап 2 по календарю ТЗ ещё не закрыт. Backend-вертикальный
срез, AI-адаптеры, RBAC, demo-loader, trends и safety/validation блок существуют;
интеграционные проверки и clean-run пройдены. Исследовательские результаты
подготовлены как описательный synthetic-эксперимент; конкурсные материалы ещё
требуют подготовки и стабилизации по календарю ТЗ. F1–F10 исправлены с
проверками ниже; даты демо и настоящий голосовой E2E ещё не завершены.

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

Проверка представления research-v2 и подготовка графиков завершены (2026-11-10):

- Принятые P0.6–P0.8 и research-v2 учтены локальным коммитом `3091b16`.
- Зафиксирован проверенный код отчёта `859b69581327a0f22d7f8ae75605fb83356c1b3e`.
- Исправлена граница входов: методы принимают `MethodInput` без labels;
  evaluator отдельно соединяет predictions с ground truth. Продуктовые API/UI
  не менялись. Генератор, split и пороги не подстраивались.
- Эксперимент повторён из сохранённой конфигурации. 100 профилей / 2800 дней
  сгенерированы; оценены 20 held-out профилей / 560 дней. Из них 156 положительных,
  404 отрицательных; 18 эпизодов изменения и 2 стабильных профиля.
- Добавлены TN, явные знаменатели и missed episodes. A: TP/FP/FN/TN =
  52/2/104/402; B и C без текста: 100/52/56/352; C: 128/52/28/352.
- False alert-days = FP/560 × 100, повторы учитываются ежедневно. Insufficient
  включён в матрицу как отсутствие срабатывания: 0 дней у A, 141/560 у B/C.
- Задержка в днях только по обнаруженным эпизодам: A 9/8=1.125 (10 пропущено),
  B 2/17≈0.118 (1 пропущен), C 0/18=0 (0 пропущено). Пропуски не заменяются нулём.
- Prefix/future-mutation тесты подтвердили отсутствие будущих наблюдений в
  baseline и ранних решениях; история строго предыдущая и только своего профиля.
- Артефакты: `experiments/artifacts/research-v2-seed42-2026-11-10/result.json`,
  `figures/{precision_recall_f1,false_alerts,timeline}.{png,svg}`, manifest и
  `SHA256SUMS`. Артефакт отслеживается Git отдельно от игнорируемого latest.json.
- В JSON сохранены конфигурация, seed/split, версии, commit/SHA-256 исходников,
  количества, test-записи, предсказания и извлечения. `--archive` не перезаписывает
  файл. Графики читают только архив; выбран первый по ID multimodal test-профиль.
- `.venv/bin/pytest -q`: 39 passed; compileall и frontend build прошли;
  `git diff --check` пройден. `experiments.verify_report` подтвердил полное
  совпадение сохранённого JSON с повторным расчётом; SHA256SUMS проверены.
- 20 test-профилей, один seed, описательная оценка; доверительные интервалы
  не рассчитаны, статистическая устойчивость улучшения не установлена.
- В test нет ambiguous/uncertain, activity_drop и missing_change сценариев;
  случайные пропуски есть. Все шаблоны test пересекаются с train. Сохраняются
  ограничения шаблонной разметки, условной latency и корреляции дней профиля.
- Допустимо использовать новые результаты только как конкретный synthetic
  engineering experiment с этими оговорками. Старые Method C метрики с прямым
  симптомным label не используются; клиническое превосходство не установлено.

Блок реальной интеграции GigaChat для демонстрации завершён (2026-11-10):

- Проверены фактический код и прежние подтверждения. Таблица 10 участков и
  полный сценарий подготовки/показа/восстановления — `docs/DEMO.md`.
- Первые live-пробы не прошли критерий положительного extraction; один ответ
  перевёл evidence и был отклонён. Уточнён prompt: точная цитата на исходном
  языке и snake_case категория; проверки evidence не ослаблялись.
- Реальный OAuth + GigaChat-2: возвращены 2 schema/evidence-валидных факта,
  оба неподтверждённые. Это adapter smoke, не UI и не сохранение в PostgreSQL.
- Реальная ошибка несуществующей модели: HTTP 404 обработана контролируемо.
- Намеренно вызванный live transport timeout обработан. Это искусственный
  локальный лимит времени, а не подтверждение аварии провайдера.
- Санитизированный отчёт: `docs/demo_checks/gigachat-2026-11-10.json`,
  содержит commit базового состояния + SHA-256 проверенного адаптера/скрипта;
  `working_tree_dirty=true` явно отражает проверку текущих изменений.
- Команда повторения: `PYTHONPATH=backend .venv/bin/python -m scripts.gigachat_smoke
  --env-file /home/linuxoid/Projects/secret.env --output /tmp/medsi-gigachat-check-new.json`.
  Число фактов/содержимое ответа внешнего API не считаются детерминированными.
- Ошибки OAuth/completion timeout, неверный JSON, пустой/выдуманный evidence
  проверены отдельно через MockTransport. Они не называются live-ответами.
- Новые тесты отказов API проверяют: 502/503 не сохраняют факты и события;
  ручной check-in, история, числовой анализ и caregiver работают без провайдера.
- Из исключений удалены непроверенные тела ошибок провайдера; ключ исключён
  из repr настроек. Credentials не печатались, не помещались в Git/frontend.
- Frontend явно показывает резервный режим при 502/503 и сообщение при потере
  связи. При новой записи очищаются факты предыдущей записи. Успешный extraction
  отключает резервную индикацию. Этот UI-элемент проверен сборкой, отдельный
  браузерный smoke новой индикации пока не проводился.
- Проверки: `.venv/bin/pytest -q` — 46 passed; compileall backend/experiments/scripts,
  frontend build, `git diff --check` — пройдены. research-v2 verify_report и
  SHA256SUMS совпадают; архив, правила, split и графики не менялись.
- Реальная запись микрофона, ASR по ней и полный real-GigaChat UI-путь ещё
  не проверены. Загрузка модели/готового текста не считается ASR-проверкой.
- Известное ограничение демо: loader имеет фиксированные октябрьские даты;
  новое измерение текущей датой может дать insufficient_data. Это не повод
  менять даты/пороги ради срабатывания; согласование времени голоса и чисел
  требует проверки в следующем блоке.

Независимый аудит и числовой блок F1/F5/F10 (2026-11-10):

- Аудит сохранён без изменений в
  `docs/reviews/audit-2026-11-10-independent-product-monitoring.md`.
  Исходный commit `61b8f79`; существующие незакоммиченные изменения GigaChat,
  резервного UI и демодокументации сохранены, откатов не выполнялось.
- До исправления 5 новых black-box регрессий упали на исходном продуктовом
  коде: сон скрывается нормальным пульсом; порядок влияет на результат;
  7 строк одного дня считаются историей; текущий день включён в baseline;
  viewport trends обрезает историческую базу. После исправления все проходят.
- **F1 исправлен:** `daily-multimetric-v2` анализирует все пять метрик на
  локальном дне профиля до as_of; отклонение одной сохраняет общий attention
  даже при недостатке истории другой. Per-metric missing_measurement,
  insufficient_data, no_change и attention разделены; частичность явная.
- **F5 исправлен:** предыдущие 14 локальных дат, минимум 7 валидных различных
  дней; текущий день и будущее исключены. Сон/активность: последнее суточное
  значение, median при timestamp tie; пульс/давление: дневная median. Повторы
  суточных значений не суммируются. Questionable исключён, unknown отмечается.
- **F10 исправлен:** days ограничивает только дневной viewport trends;
  baseline рассчитывается по всей доступной предшествующей истории.
  Analysis и trends используют общее продуктовое ядро.
- Контракт и критерии отбора/актуальности — `docs/MONITORING.md` и разделы
  7/9 ТЗ. Default as_of — now UTC, будущий cutoff даёт 422. Старые demo-даты
  остаются прежними: исторические проверки явно задают октябрьский as_of.
- Миграция `0005_daily_monitoring`: profiles.timezone и JSON snapshot
  monitoring_events.analysis_details с метриками, baseline, quality,
  периодом/часовым поясом и observation IDs. Старые события не переписываются.
  Это числовой snapshot, а не решение текстового provenance F2/F3/F9.
- Регрессии и дополнительные границы: 12 passed. HTTP/SQL-тесты: SQLite и
  optional PostgreSQL. Все backend: 61 passed, 3 skipped без PG URL;
  на выделенной `medsi_test_*` PostgreSQL-базе — **64 passed**.
- Live PostgreSQL: миграции с нуля до 0005, сохранение legacy-события при
  0004→0005, `alembic check` — без расхождений. Проверены JSON round-trip,
  timezone, normal pulse + sleep deviation, дневная история и viewport.
- Реальный HTTP/backend/PostgreSQL smoke: login → demo 63/21 → исторический
  анализ трёх attention-метрик → trends 7/28 с одинаковым baseline → сохранённый
  snapshot события → caregiver/notification/read → reset/reload. Отдельная
  временная база удалена, основная БД не менялась.
- Свидетельство с исходными хешами и результатами:
  `docs/reviews/f1-f5-f10-verification-2026-11-10.json`.
- compileall, frontend build (контракт дополнен), git diff --check проходят;
  research-v2 verify_report и SHA256SUMS совпадают. Исследовательские исходники,
  генератор, split, метрики и архив не изменялись.
- Открыты F2/F3/F9 (устаревшие факты, правки и пустое подтверждение), F4/F6/F7/F8
  (пустой ввод, запись caregiver через analysis, повторы notifications, ручной
  safety UI). Их поведение не исправлялось в этом блоке. Микрофон/ASR/даты demo
  и голосовой E2E также отложены. Браузерный smoke в этом блоке не проводился.

Блок жизненного цикла фактов F2/F3/F9 и текстового provenance (2026-11-10):

- Прежние принятые изменения сохранены отдельно: `54ae037` (GigaChat и
  F1/F5/F10). Текущий блок выполняется в `codex/facts-lifecycle-f2-f3-f9`.
  Существующий аудит использован без перезаписи; посторонние файлы не добавлены.
- До реализации пять исходных регрессий проверены в памяти и SQLite:
  **10 failed** (старая жалоба, отрицание, правка, пустой результат, provenance).
  Это поведенческие проверки существующих API/repository, а не копия алгоритма.
- **F2 исправлен:** явное включительное UTC-окно `[as_of−24h, as_of]`,
  created_at записи и confirmed_at не позже cutoff; только текущая проверенная
  редакция. Последняя запись категории по `(recorded_at, confirmed_at)` заменяет
  старую. Absent/uncertain подавляют прежнее present, но uncertain и отсутствие
  упоминания не являются отрицанием. При точном противоречивом tie сигнал
  категории подавляется с сохранением конфликта. Это технический выбор MVP.
- **F3 исправлен:** text_revision; фактическая правка снимает подтверждение и
  активные факты. Тот же текст сохраняет состояние. PATCH/confirm требуют revision;
  устаревшие запросы получают 409. В SQL row lock + revision в UPDATE. Extraction
  проверяет revision после ответа; UI отбрасывает старые ответы и блокирует
  extraction/confirm несохранённого текста. События прошлого не переписываются.
- **F9 исправлен:** confirmed_revision/confirmed_at отдельно от количества фактов.
  Подтверждение `facts: []` сохраняется в GET/list/SQL после перезапуска. UI
  удаляет отдельный/последний факт, подтверждает пустой набор и восстанавливает
  серверное состояние после перезагрузки. Числовое отклонение остаётся рабочим.
- **Provenance:** independent JSON snapshot в monitoring_events: check-in ID,
  fact ID, revision, category/polarity, цитата, temporal_context, recorded_at,
  confirmed_at, rule_version, resolution. Новая комбинированная версия обычных
  событий: `daily-multimetric-v2+facts-window-v1`. Safety хранит только факты,
  вызвавшие `safety-v1`, с `direct_confirmation`; его жизненный цикл не смешан
  с обычным 24-часовым окном. Правка/отрицание не удаляют safety event/notification.
- Миграция `0006_fact_lifecycle` проверена с нуля и поверх 0005 с legacy-данными
  на SQLite и PostgreSQL 18.6; `alembic check` без расхождений. Старые события
  читаются с пустым provenance, без выдумывания доказательств. Старые check-in
  требуют нового явного подтверждения, точная редакция не восстанавливается
  эвристикой. Legacy факты миграцией не удалены.
- Критерии готовности выполнены: все пять исходных регрессий, границы 24h
  (включая микросекунду), отрицание/uncertain/пустота/tie, позднее подтверждение,
  будущая запись/подтверждение, race extraction и validation→write, 409/422,
  immutable normal/safety provenance и SQL restart покрыты тестами.
- Финальные проверки: `.venv/bin/pytest -q` — **103 passed, 23 skipped** без
  PostgreSQL URL; с `MEDSI_TEST_POSTGRES_URL` на выделенной базе — **126 passed**.
  Новые lifecycle/migration кейсы — 62, включая 20 реальных PostgreSQL-кейсов.
  Также проходят `.venv/bin/python -m compileall -q backend experiments`,
  `npm --prefix frontend run build`, `git diff --check`.
- Live HTTP + PostgreSQL smoke: login → loader 63/21 → исторический attention →
  trends → safety confirmation → edit → stale 409 → empty confirmation/GET →
  неизменный event → caregiver notification/read → reset/reload, старый check-in
  после reset возвращает 404. Две временные PostgreSQL-базы удалены, основная
  база не менялась. Команды тестирования и миграций: `docs/FACTS.md`.
- Браузер IAB + реальный локальный API (memory): создание записи, загрузка двух
  synthetic-фактов, заранее подтверждённых через API, удаление одного и сохранение
  оставшегося, удаление последнего, пустое подтверждение, reload, изменение текста,
  блокировка до PATCH, подтверждение revision 2 и reload — пройдено. LLM/ASR не
  вызывались; это не дополнительная live-проверка GigaChat или голоса.
- Свидетельство: `docs/reviews/f2-f3-f9-verification-2026-11-10.json`.
  Правила и контракт: `docs/FACTS.md`, MONITORING.md, SAFETY.md, ТЗ и README.
- Research-v2: `verify_report` и все SHA256SUMS проходят; исходники, архив,
  генератор, split, пороги и исследовательские метрики не менялись.
- Ограничения: полного replay прошлых редакций нет (сохранённые события остаются
  snapshot); relative temporal_context не преобразуется в дату; legacy записи
  требуют повторного подтверждения; Vite предупреждает о bundle >500 kB.
  F4/F6/F7/F8, согласование дат demo и реальный голосовой E2E **открыты**.
  В этом блоке они не исправлялись; следующая задача — F4/F6/F7/F8.

Блок пользовательского пути F4/F6/F7/F8 (2026-11-10):

- Работа продолжена на `codex/facts-lifecycle-f2-f3-f9`, HEAD перед блоком
  `3f029a3`; предыдущие F1/F5/F10 и F2/F3/F9/provenance сохранены. Переключения
  на main, объединения веток, секретов и посторонних файлов нет.
- До реализации: 8 backend-регрессий упали на memory/SQLite (caregiver меняет
  хранилище, последовательные/конкурентные дубли, повтор safety confirmation).
  Frontend-обработчик воспроизвёл 4 ошибки пустого/пробельного сна/активности;
  явные 0/8 проходили. Четыре проверки ручного пути выявили отсутствие обработчика.
- **F4 исправлен:** trim проверяется до Number; затем проверка конечного числа.
  Пустое поле/пробелы дают понятную ошибку без API-запроса. Явный 0 допускается
  для сна/активности. Серверная валидация диапазонов/units/source/quality сохранена.
- **F6 исправлен:** POST analysis требует write=True до расчёта/сохранения.
  Проверены последствия запретов всех затронутых write-маршрутов (analysis,
  loader/reset, observation/check-in, PATCH/extract/confirm/ASR). GET summary,
  profile/history/trends/events/своих notifications не пишут в БД. Собственный
  notification/read разрешён; чужой возвращает 404 без изменений.
- **F7 исправлен:** `event-identity-v1` SHA-256 по profile, виду события,
  правилам, периоду и значимым числовым/текстовым входам. Период обычного анализа —
  локальный календарный день профиля. Request time/event random ID не образуют
  новый ключ. Повтор возвращает прежний event_id и исходный snapshot/cutoff.
- Факты: новый facts_revision увеличивается только при содержательном новом
  подтверждении. Unordered одинаковый набор сохраняет fact IDs/confirmed_at.
  A→B→A, новая text_revision, новое измерение/день, истечение актуальности факта
  и другая версия правил корректно обрабатываются как новые состояния/периоды.
  Safety использует identity подтверждения с check-in/text/facts revision.
- SQL: UNIQUE identity_key, вставка события и notifications одной транзакцией;
  конкурентный проигравший читает существующий результат. Повтор не меняет
  status/read_at. Проверены шесть одновременных analysis/confirmation, шесть
  независимых SQL repositories, прямое нарушение unique-индекса и rollback
  события вместе с notification при намеренной ошибке записи. Memory — RLock,
  PostgreSQL confirmation — FOR UPDATE + CAS, SQLite — BEGIN IMMEDIATE + CAS.
- **F8 исправлен:** ручной UI-черновик без успешного extraction: ограниченный
  выбор категорий, polarity и точная цитата, затем явное подтверждение прежним
  API. Evidence, text_revision, 409/422, права и provenance сохранены. При ошибке
  LLM автоматическое создание/подтверждение фактов отсутствует.
- Миграция `0007_event_identity`: facts_revision и nullable unique identity_key.
  С нуля и upgrade 0006→0007 пройдены на PostgreSQL 18.6 и SQLite;
  alembic check не нашёл расхождений. Legacy проверки/события/read_at сохранены;
  old events имеют NULL key и не дедуплицируются ретроспективно.
- Финальные проверки: с `MEDSI_TEST_POSTGRES_URL` — **167 passed, 2 skipped**
  (оба skip — SQL-only варианты для memory; все PostgreSQL-кейсы выполнены).
  Без PostgreSQL URL — **130 passed, 39 skipped**. Frontend: **12 passed** через
  `npm --prefix frontend test`, без новых зависимостей. Команды:
  `.venv/bin/pytest -q`, `.venv/bin/python -m compileall -q backend experiments scripts`,
  `npm --prefix frontend run build`, `git diff --check` — проходят.
- Live API/PostgreSQL smoke: demo 63/21, исторический attention/trends, повтор
  analysis с тем же event_id, повтор safety confirmation с тем же event,
  PATCH/stale409/empty confirmation/provenance, caregiver GET/read и POST403,
  reset/reload с очисткой старых events/notifications/check-in — пройдено.
- **Браузер IAB + настоящий FastAPI/PostgreSQL:** сон и активность — пустая
  строка/пробелы отклонены; явно введённые 0/8 hours и 0/30 minutes сохранены.
  До допустимого ввода БД оставалась пустой; после пробельной активности в ней
  оставались только две строки сна. F8: реальный 503 из-за отсутствующей
  конфигурации GigaChat → явный fallback → ручной chest_pain/present/цитата →
  черновик без фактов/событий в БД → explicit confirmation → safety/provenance →
  повтор без дубля → caregiver UI с одним событием и одним своим уведомлением.
  PostgreSQL подтвердил 4 observations, 1 факт, 1 event, 2 notifications
  (по одному каждому получателю), facts_revision=1. LLM/ASR не вызывались.
- Новые тесты: `test_product_access_idempotency.py`,
  `test_event_identity_migration.py`, `frontend/tests/*.test.mjs`.
  Старый тест будущего confirmation теперь проверяет действительно первое
  подтверждение после cutoff; одинаковый повтор больше не сдвигает confirmed_at.
- Правила/контракт: `docs/IDEMPOTENCY.md`, MONITORING/FACTS/SAFETY, ТЗ и README.
  Свидетельство: `docs/reviews/f4-f6-f7-f8-verification-2026-11-10.json`.
  Все временные PostgreSQL-базы удалены, основная БД не менялась.
- Research-v2 verify_report и 9 SHA256SUMS совпали; генератор/split/архив/метрики
  не менялись. Предыдущие исправления покрыты полным backend-набором.
- Ограничения: legacy-дубли не удаляются; первый post-upgrade анализ может
  создать новый snapshot рядом с legacy событием. Совпавшие значимые входы
  внутри дня возвращают первый snapshot/cutoff, даже для другого as_of того же
  дня. Медицинская модель эпизодов/автозакрытие safety отсутствуют. Vite сообщает
  существующее предупреждение bundle >500 kB. Production auth и остальные
  прежние ограничения сохраняются. Даты demo и реальный голосовой E2E не начаты.
- Критерии F4/F6/F7/F8 выполнены; следующий блок по плану — согласование времени
  demo и затем настоящий голосовой E2E. Полный мультимодальный MVP пока не объявлен.

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
- 169 backend/исследовательских кейсов (37 optional PostgreSQL-кейсов;
  2 SQL-only варианта намеренно skipped для memory).

## 4. Что проверено тестами

- `.venv/bin/pytest -q` — 130 passed, 39 skipped без PostgreSQL URL;
  с `MEDSI_TEST_POSTGRES_URL` — 167 passed, 2 skipped (SQL-only memory), включая API,
  диапазонную валидацию, safety, confirmation и caregiver notification;
- `.venv/bin/python -m compileall -q backend experiments`;
- `DATABASE_URL=sqlite:///... .venv/bin/alembic upgrade head` и `alembic check` —
  миграции до `0007_event_identity` проходят;
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

Deterministic extractor: TP=84, FP=0, FN=0 по парам category/polarity,
P/R/F1=1.000. Ошибки отрицания 0/21. Неопределённых фактов в test — 0; их
качество не оценено. Все 3 шаблона test присутствуют в train (4 шаблона).
Это не оценка обобщения на новые тексты или качества реальной модели.

## 5. Что не реализовано

- таблица и API `audit_events`;
- production-аутентификация и приглашения доверенных лиц.

## 6. Подтверждённые P0-проблемы

Независимый аудит выявил продуктовые блокеры, несмотря на прежние clean-run
и PostgreSQL smoke. F1/F5/F10 и затем F2/F3/F9/text provenance исправлены;
F4/F6/F7/F8 также исправлены с проверками выше. Полный мультимодальный
MVP не подтверждён: остались даты демо и настоящий голосовой E2E.

## 7. Оставшиеся проблемы

- согласование времени демосценария и реальный голосовой E2E не завершены;
- отсутствуют baselines/audit tables из полной модели ТЗ;
- нет rate limit и prompt-injection тестов;
- нет ограничения длительности аудио;
- нет локального автоматического extractor; ручной структурированный fallback есть;
- нет Python lock-файла.

## 8. Следующая задача

Следующая задача — согласовать даты/момент анализа demo, затем выполнить
настоящий голосовой E2E по утверждённому плану. В текущем блоке это не начиналось.
F1–F10 исправлены с представленными проверками и указанными legacy-ограничениями.
Исследовательские результаты research-v2 остаются frozen и описательными.

## 9. Известные ограничения и технический долг

- demo identities используют synthetic credentials и не являются production auth;
- Docker Compose поднимает только PostgreSQL;
- результаты Method C допустимо показывать только как synthetic engineering
  experiment; они не являются клиническим доказательством;
- Python-зависимости пока задаются диапазонами без lock-файла;
- реальные медицинские данные, FHIR, wearable API, TTS и Ollama исключены.

## 10. Приблизительная инженерная оценка готовности

Прежняя оценка 70% не используется как критерий готовности. Инфраструктурные
и исследовательские проверки пройдены, но после независимого аудита остаются
продуктовые findings и неподтверждённый реальный голосовой E2E.
