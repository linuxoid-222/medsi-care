# Исследовательский протокол MEDSI Care

## Статус

Текущий протокол `research-v2` предназначен для воспроизводимой проверки
инженерного предложения на синтетических данных. Он не доказывает клиническую
эффективность и не должен описываться как клиническая валидация.

## Независимые labels

Генератор сохраняет в каждом `DayRecord` только для evaluator:

- `ground_truth_event`;
- `ground_truth_facts` с полярностью `present`, `absent` или `uncertain`;
- `scenario_type`;
- `change_start_day`.

Эти поля не передаются extractor, monitoring engine, Method C, prompt LLM или
frontend. Method C получает только наблюдаемые числовые поля, `check_in_text`,
результат extractor, `quality`, `completeness` и историю предыдущих дней.

## Extractor

`experiments/extractor.py` определяет общий контракт `FactExtractor` и
валидируемые Pydantic-схемы `ExtractedFact`/`ExtractorResult`.

Основной эксперимент использует `DeterministicRuExtractor` версии
`deterministic-ru-v1`. Это прозрачная русскоязычная эвристика для synthetic
текстов, а не клинически обученная модель. Она различает наличие, отрицание,
неопределённость и отсутствие факта. `LlmExtractorAdapter` существует как
необязательный адаптер совместимого провайдера и не требуется для запуска
эксперимента.

## Split и методы

Split выполняется по `profile_id` с фиксированным seed `seed + 17071`.
Профили train/test не пересекаются. Train в текущем протоколе не используется
для подстройки результата (`train_used_for_tuning=false`), а нужен для явного
сохранения границы оценки.

Сравниваются:

- Baseline A — фиксированные технические пороги числовых показателей;
- Baseline B — персональная статистика числовых показателей;
- Method C без текста — абляция Baseline B;
- Method C — Baseline B плюс признаки текущего текста, извлечённые
  независимым extractor.

Отрицательные и неопределённые факты не превращаются в положительный текстовый
сигнал. В сценариях присутствуют пропуски, отрицание, неопределённость,
несогласованность текста и числовых наблюдений.

## Метрики и ограничения

На одном held-out наборе считаются precision, recall, F1, ложные уведомления на
100 человеко-дней, detection latency и доля `insufficient_data`. Для extractor
отдельно считаются precision/recall/F1 по парам `category/polarity`, ошибки
отрицания и ошибки неопределённости.

Интервалы неопределённости пока не рассчитываются: это небольшой синтетический
инженерный протокол, а не статистическое исследование мощности. Полученные
числа можно использовать только как иллюстрацию воспроизводимости и сравнения
реализаций; старые Method C метрики до `research-v2` публиковать нельзя.

## Запуск

```bash
PYTHONPATH=. .venv/bin/python -m experiments.run_experiment \
  --profiles 100 --days 28 --seed 42 --test-fraction 0.2 \
  --output experiments/results/latest.json
```

Файл результата содержит protocol version, seed, конфигурацию, split с profile
IDs, версии numeric rules/extractor, метрики методов и extractor metrics.
