# Исследовательский режим ablation признаков — feature-research-v1.1

Отдельный журнал и CLI. **Не изменяет** стандартную выдачу `workflow`,
`combination_lab` или `lottery-rune-hash-v2`. Гипотеза о связи символических
входов / времени события с исходом **не предполагается истинной**; режим только
фиксирует прогнозы до события и сравнивает заранее объявленные варианты.

```bash
python -m dis_oracle.feature_research --db private-runs/feature-research.sqlite3 register examples/feature_research/protocol.synthetic.json
python -m dis_oracle.feature_research --db private-runs/feature-research.sqlite3 forecast examples/feature_research/forecast.synthetic.json
python -m dis_oracle.feature_research --db private-runs/feature-research.sqlite3 outcome hunt DRAW examples/feature_research/outcome.synthetic.json
python -m dis_oracle.feature_research --db private-runs/feature-research.sqlite3 evaluate --study-id STUDY
python -m dis_oracle.feature_research synthetic-demo --directory /tmp/feature-research-demo
```

На Windows укажите локальный пустой каталог вместо `/tmp`.

## Совместимость журнала

| Версия | Статус |
| --- | --- |
| `feature-research-v1` | Старые записи **не переписываются**. Читаются в `evaluate`; помечаются `LEGACY_SCHEMA_V1` / непригодностью для подтверждения при сомнительных сроках |
| `feature-research-v1.1` | Текущий протокол и новые прогнозы: закреплённые параметры, граница confirmatory, формат признаков |

Смена правил исследования → новый `study_id` (или новая версия протокола), не правка старых хешей.

## Что сохраняется до события

- игра и номер тиража;
- заявленное время события, IANA-часовой пояс, UTC;
- время формирования прогноза; отдельно — `data_received_at`;
- происхождение символического входа;
- `core_results` других ядер (хранение, не голос);
- явные признаки метода;
- **закреплённые** параметры: `frequency_window`, `min_train`, `shrinkage_alpha`,
  `feature_schema`, `method_versions`, `primary_contrast`, размер серии, остановка;
- хеш обучающей выборки;
- прогнозы A–F.

Неизвестные даты **не** восстанавливаются по номеру тиража.

## Формат признаков истории (`feature-tokens-v1.1`)

- `time_model_tokens` — бины модели (weekday, hour_bucket, календарные метки); без `local_date`;
- `time_tokens` — аудит (может включать `local_date`); если задан один, модель берёт subset без `local_date`;
- `rune_tokens` — упорядоченные позиции для E/F;
- `feature_tokens` — необязательный legacy-мешок; не должен противоречить явным полям.

Конфликт `time_model_tokens` и model-subset из `time_tokens` → отклонение, не молчаливая потеря.

## Варианты A–F

| ID | Содержание |
| --- | --- |
| A_random | Равномерный контроль 4-из-20 × 2 поля |
| B_frequency | Частоты; окно **закреплено протоколом** (30 или 100) |
| C_lottery_rune_hash_v2 | Точная базовая формула |
| D_time_features_only | Регуляризованная модель по бинам времени/календаря |
| E_rune_features_only | Только явные рунические токены |
| F_rune_plus_time | Руны + время |

## Защита оценки

- приём исхода только **после** заявленного времени события (даже без `occurred_at`);
- `recorded_at` не подменяет время получения в журнале;
- сводки **по игре** и по исследованию/отпечатку параметров; общего пула нет;
- `games_separated=True` соответствует фактическому расчёту;
- граница confirmatory задаётся в протоколе **до** периода; CLI-переопределение без
  протокола — только `EXPLORATORY` / `RETROSPECTIVE_EXPLORATORY_SPLIT`;
- перестановка: H0 обменности целых двухполевых исходов внутри игры (и блоков);
  статистика пересчитывается по сохранённым прогнозам и исходам; не причинность;
- основной показатель: сумма совпадений внутри полей (0…8).

## Синтетический пример

`synthetic-demo` — только синтетика. Успех на синтетике проверяет механизм, не
реальную связь тиражей.
