# Краткий отчёт: fix/feature-research-defects

База: `research/feature-ablation-engine` @ `3847369b6f65e80c8ded8bd40e49b75b77129bf6`.
Ветка исправлений: `fix/feature-research-defects`. В `main` не сливалось.

## Дефект → исправление → тест

| Дефект | Исправление | Тест |
| --- | --- | --- |
| `permutation_null` давал p=1 (инвариант суммы) | Перестановка целых двухполевых исходов внутри игры; пересчёт hits метода и контроля; явная H0; отказ при вырождении | `test_permutation_null_statistic_changes_on_nondegenerate_set` |
| Исход до события без `occurred_at` принимался как PROSPECTIVE | Запрет приёма до `event_at_declared`; `recorded_at` не заменяет receipt; откат без частичных записей; legacy пометка | `test_outcome_before_event_rejected_even_without_occurred_at` |
| `evaluate` смешивал игры при `games_separated=True` | Сводки только в `by_game` / `by_study`; `pooled_summary=None` | `test_evaluate_separates_games_in_one_db` |
| В одном study можно было сменить окно 30→100 | Протокол v1.1 закрепляет окно, min_train, alpha, schema, versions, contrast, stopping, confirmatory | `test_protocol_rejects_frequency_window_change` |
| `confirmatory_after` выбирался после результатов | Граница в протоколе; конфликт CLI отклоняется; без протокола — только exploratory split | `test_confirmatory_boundary_locked_in_protocol` |
| `_history_rows` отбрасывал `time_model_tokens` | `normalize_history_features` / `feature-tokens-v1.1`; конфликты отклоняются | `test_time_model_tokens_alone_feed_method_d`, `test_conflicting_time_feature_representations_rejected` |

## Совместимость

Старые записи v1 не изменяются. Новые протоколы/прогнозы пишутся как
`feature-research-v1.1`. При чтении legacy помечается для confirmatory.

## Ограничения

- Нет независимой аттестации времени/исходов.
- Перестановка — диагностика обменности, не причинность.
- Синтетический сигнал ≠ реальная связь тиражей.
- Другие ядра по-прежнему не автоматические руки A–F.
- Cycle/`fcntl` на Windows в полном discover может падать как раньше (вне research).

## Можно ли запускать будущую серию

Да, **исследовательскую** серию на v1.1, если заранее зарегистрирован протокол с
зафиксированными параметрами и (для подтверждения) границей `confirmatory_after`,
исходы принимаются только после заявленного события, игры не смешиваются в сводках,
и анализ до границы помечен exploratory при любом post-hoc split. Подтверждающий
вывод требует будущих наблюдений после locked boundary, без подбора правил по ним.
