# Синтетические эксперименты

Генератор использует фиксированный seed и независимую спецификацию сценариев.
Разделение выполняется по профилям, поэтому история одного профиля не попадает
одновременно в настройку и отложенную оценку.

Запуск из корня репозитория:

```bash
source .venv/bin/activate
python -m experiments.run_experiment --output experiments/results/latest.json
```

Результат содержит Precision, Recall, F1, ложные уведомления на 100 человеко-дней
и долю статусов `insufficient_data` для Baseline A, Baseline B и Method C.
