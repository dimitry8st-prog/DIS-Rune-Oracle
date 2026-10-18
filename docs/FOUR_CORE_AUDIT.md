# Проверка четырёх ядер и исправления v0.3.1

[Подробный аудит Qwen, источники, расхождения и границы](../research/audit/four_cores/REPORT.md).
База `1ca14c6e9cbc1cd13fa83fc8ce3fa88123c37b23`, ветка `codex/four-core-audit-v0.3`.
Исторические источники недоступны через прокси (403), поэтому **новых исторически
подтверждённых адаптеров нет**. Подключены только явно условные вычисления и
ручные записи, без непроверенных толкований. `CoreResult` не изменён.

## Матрица десяти ядер

Все десять core_id и веса **0.10** сохранены; недоступные доли не перераспределяются.

| Ядро | Рабочая механика / вход | Корпус и интерпретация | Готовность |
| --- | --- | --- | --- |
| rune | прежние закрытые три выбора/commitment | прежняя современная карта v2.1 | прежний OK; FORECAST только вручную |
| yijing | прежние шесть троек монет | runtime-чтение не закреплено | ABSTAIN |
| mo | прежние 36 упорядоченных числовых сочетаний | слоги/корпус не закреплены | ABSTAIN |
| qiuqian | прежний авторский набор 1..100, подтверждения/лимит | храмовая процедура/корпус не подтверждены | ABSTAIN |
| daliuren | нет | нет | UNAVAILABLE |
| egypt | нет | нет | UNAVAILABLE |
| maya | условный GMT584283 календарь с явной гражданской границей суток | источник не проверен, pajooneem не реализован | ABSTAIN, математическая модель |
| shakuna | полный ручной протокол наблюдения | ни одного подтверждённого правила в runtime | ABSTAIN, только регистратор |
| slavic | ручной журнал песня/предмет/участник/возврат/завершение | исторический вариант и корпус песен не подтверждены | ABSTAIN, только регистратор; digital заблокирован |
| name_grids | ручные посимвольные черты, явный авторский арифметический профиль | словарь, лицензия, школа и толкования не подтверждены | ABSTAIN manual; UNAVAILABLE automatic |

Объект `adapters` теперь принимает восемь core_id; два остальных по-прежнему
недоступны. [Полный manifest восьми карточек](../examples/four_cores/manifest.json)
описывает все обязательные поля новых режимов и предпосылки. Нельзя молча заменить
авторскую условную модель на историческую: profile обязателен и фиксируется.
Shakuna и Slavic принимают только наблюдения, существовавшие до cutoff/регистрации.
Цифровые наблюдения запрещены. Внешних LLM/API-зависимостей нет.

## Полное воспроизведение

Python 3.11+; интегрированный цикл требует POSIX. В чистом checkout:

```bash
python -m unittest discover -v
python scripts/audit_four_qwen.py --check
python scripts/yijing_audit.py --check
python -m dis_oracle cycle-start examples/four_cores/manifest.json --directory /tmp/four-eight-cycle --run-id eight
python -m dis_oracle cycle-review examples/v0_3/review.json --directory /tmp/four-eight-cycle --run-id eight
python -m dis_oracle cycle-freeze --directory /tmp/four-eight-cycle --run-id eight
python -m dis_oracle cycle-science examples/v0_3/science-before.json --directory /tmp/four-eight-cycle --run-id eight
python -m dis_oracle cycle-evaluate examples/v0_3/outcome.json --directory /tmp/four-eight-cycle --run-id eight --at 2099-01-01T00:00:02Z
python -m dis_oracle cycle-science examples/four_cores/science-after.json --directory /tmp/four-eight-cycle --run-id eight --at 2099-01-01T00:01:00Z
python -m dis_oracle cycle-science examples/four_cores/science-correction.json --directory /tmp/four-eight-cycle --run-id eight --at 2099-01-01T00:02:00Z
python -m dis_oracle verify --db /tmp/four-eight-cycle/cycle-v03.sqlite3
python -m dis_oracle cycle-status --directory /tmp/four-eight-cycle --run-id eight
```

Каталог должен быть новым; он содержит только учебные записи. Все данные
**SYNTHETIC**; даты 2099 — моделируемое время, не проведённое исследование.
До/после оценки оригинал можно получить cycle-freeze: JSON неизменен.
Новый числовой результат записан в 00:00:03, после категориальной оценки 00:00:02;
научный cutoff 00:00:59, часы анализа 00:01:00. Отчёт принимается. Затем отдельная
научная версия меняет число с явной причиной и supersedes; первый результат остаётся.

`science` принимает `analysis_at` в JSON-запросе и опциональный CLI `--at` только
для SYNTHETIC. `created_at` всегда берётся с локальных часов создания, отдельно
от cutoff и синтетических часов. Ранний cutoff исключает запись через явный
отказ, а не скрытое отбрасывание. IMPORTED не допускает будущую границу анализа.
Повтор report_id возвращает сохранённый снимок; изменённый запрос отклоняется.

Безопасная повторная инспекция исходного вложения (путь задайте по месту):

```bash
python scripts/inspect_qwen_tar.py '/path/to/6 адаптеров.tar' --extract-to /tmp/qwen-four-new-extraction
python scripts/check_four_sources.py
```

Последняя команда только проверяет доступность/хеш ответа, не подтверждает
содержание источника автоматически и не меняет сохранённый журнал аудита.

Сборка и запуск установленного пакета **вне checkout**:

```bash
python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/four-wheel .
python -m venv /tmp/four-installed
/tmp/four-installed/bin/python -m pip install --no-index --no-deps /tmp/four-wheel/dis_rune_oracle-0.3.1-py3-none-any.whl
cd /tmp
/tmp/four-installed/bin/dis-oracle cycle-demo --directory /tmp/four-installed-demo
/tmp/four-installed/bin/dis-oracle verify --db /tmp/four-installed-demo/state/cycle-v03.sqlite3
```

Фактически проверено на Python 3.12.14: 163 теста OK; оба audit --check MATCH;
полный восьмикарточный CLI-цикл, отдельная поправка и verify (15 записей) успешны;
повтор исходного отчёта побайтно совпал. Wheel 0.3.1, установленный console script,
новые карточки и прежний cycle-demo из `/tmp` прошли. Windows не проверялась;
проверен только независимый compare при имитированном отсутствии fcntl.

Для следующего этапа нужны доступные исторические источники и корпус: Maya —
корреляция/граница суток и отдельный полный протокол конкретного pajooneem;
Shakuna — точные стихи, область действия и таблица правил; Slavic — единый
региональный протокол, полные песни с местами в издании и основания толкований;
Name Grids — выбранная школа, подтверждённые формулы, стандарт черт, словарь и
лицензия. Подтверждение этих материалов потребует отдельного аудита и версий.

Технические тесты не доказывают прогнозную эффективность. Гипотеза обратного
потока времени остаётся непроверенной.
