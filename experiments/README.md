# Синтетические эксперименты

Генератор использует фиксированный seed и независимые скрытые labels. Labels
`ground_truth_event`/`ground_truth_facts` используются только evaluator и не
передаются в extractor или Method C. Разделение выполняется по профилям, поэтому
история одного профиля не попадает одновременно в train и held-out оценку.

Запуск из корня репозитория:

```bash
source .venv/bin/activate
PYTHONPATH=. python -m experiments.run_experiment --output experiments/results/latest.json
```

Результат содержит конфигурацию и split, Precision, Recall, F1, ложные
уведомления на 100 человеко-дней, detection latency, долю `insufficient_data`,
а также отдельные метрики deterministic extractor для Baseline A, Baseline B,
абляции Method C без текста и Method C.

Проверенный неизменяемый артефакт и графики:
`experiments/artifacts/research-v2-seed42-2026-11-10/`.

```bash
.venv/bin/python -m experiments.verify_report experiments/artifacts/research-v2-seed42-2026-11-10/result.json
.venv/bin/pip install -r experiments/requirements-plot.txt
.venv/bin/python -m experiments.plot_results --result experiments/artifacts/research-v2-seed42-2026-11-10/result.json --output-dir /tmp/medsi-research-figures-new
```

`--config-from <result.json>` повторяет параметры генерации и split.
`--archive` требует чистый Git, добавляет provenance и запрещает перезапись.
Метрики вычисляются по человеко-дням; delay — по обнаруженным эпизодам в днях,
пропущенные эпизоды показаны отдельно. Все дни insufficient_data включены.
Результаты описательные: один seed, 20 test-профилей, шаблоны пересекаются с
train; неопределённые факты отсутствуют в test. См. `docs/RESEARCH.md`.
