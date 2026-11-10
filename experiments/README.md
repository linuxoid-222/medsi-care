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
