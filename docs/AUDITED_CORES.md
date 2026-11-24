# Воспроизведение пяти ядер

Десять ядер сохраняют вес 10% каждое. Чтение календарной строки, ручное
наблюдение и авторская арифметика записываются без прогноза. Перед фиксацией
отчёта требуется ручная приёмка. Пустой `claims_by_core` фиксирует воздержание.

## Входы и статусы

| Ядро | Данные для запуска | Статус и причина |
| --- | --- | --- |
| Да Лю Жэнь | Профиль утверждённой школы, точный момент вопроса с часовым поясом, место, координаты при расчёте солнечного времени | `UNAVAILABLE / APPROVED_DALIUREN_PROFILE_UNAVAILABLE`. Переданный блок `adapters.daliuren` отклоняется до регистрации. |
| Египет | `adapters.egypt` с профилем `egyptian-cairo-declared-correlation-v1`, моментом на оси события, IANA-зоной, гражданской границей суток и явной корреляцией с датой и источником | Читаемая строка даёт `ABSTAIN / DECLARED_CORRELATION_LOOKUP_WITHOUT_VERIFIED_INTERPRETATION`. Без корреляции, файла или строки — `UNAVAILABLE` с отдельной причиной. |
| Шакуна | `manual_observation`, объект, действие, направление, сторона, время со смещением, место, контекст, ссылка или архивный идентификатор свидетельства | `ABSTAIN / NO_SOURCE_VERIFIED_RULE_CORPUS` после записи наблюдения. Без блока — `UNAVAILABLE / MISSING_MANUAL_OBSERVATION`. |
| Славянская процедура | `manual_observation`, региональный вариант и его источник, участники и предметы, порядок песен, политика возврата, хронология раунда, источник песни и ссылка на наблюдение | `ABSTAIN / REGIONAL_PROTOCOL_AND_SONG_CORPUS_UNVERIFIED` после записи. Без блока — `UNAVAILABLE / MISSING_REGIONAL_DRAW_OBSERVATION`. |
| Пять сеток имени | `manual_strokes`, точные иероглифы, по одному целому числу черт на знак, заявленный стандарт, источник, `author-five-grid-arithmetic-v1` | `ABSTAIN / AUTHOR_ARITHMETIC_ONLY_TRADITIONAL_PROFILE_AND_INTERPRETATION_UNVERIFIED`. Без блока или при `automatic` — `UNAVAILABLE` с отдельной причиной. |

Неполный или некорректный переданный блок отклоняется до регистрации. В
египетском ядре пустой блок или пустая `correlation` явно обозначают
отсутствие корреляции. Три `null` в строке корпуса дают `ABSTAIN /
UNREADABLE_SOURCE_ROW`. Пять добавочных дней дают `ABSTAIN /
EPAGOMENAL_PROGNOSES_UNAVAILABLE`. Повреждённая схема корпуса отклоняется.
Профиль и формат корпуса описаны в [календарном контексте](RUNE_CALENDAR_CONTEXT.md)
и [схеме локального файла](../data/calendar/README.md).

Для Шакуны и славянского жребия свидетельства должны описывать наблюдения до
`cutoff_at` и регистрации. Для нового славянского раунда указывайте
`evidence_ref` вместе с `song_source_ref`. Прежний формат раунда принимается.
Результат перечисляет песни, для которых отсутствует ссылка на наблюдение.

## Синтетический цикл

[Минимальные блоки для четырёх ядер](../examples/audited_cores/manifest.synthetic.json)
собраны в одном манифесте. Тестовый [корпус](../examples/audited_cores/cairo_corpus.synthetic.json)
содержит три вымышленные строки. Выполняйте из корня checkout. Временная
копия изолирует корпус и SQLite от рабочих файлов.

```bash
run_root=$(mktemp -d)
mkdir -p "$run_root/data/calendar"
cp -R dis_oracle research_stats examples "$run_root/"
cp examples/audited_cores/cairo_corpus.synthetic.json "$run_root/data/calendar/cairo_calendar_prognoses.json"
cd "$run_root"

python -m dis_oracle cycle-start examples/audited_cores/manifest.synthetic.json --directory journal --run-id audited --at 2026-01-01T00:00:00Z > start.json
python -m dis_oracle cycle-review examples/v0_3/review.json --directory journal --run-id audited > review.json
python -m dis_oracle cycle-freeze --directory journal --run-id audited --at 2098-12-31T00:00:00Z > original.json
python -m dis_oracle cycle-freeze --directory journal --run-id audited > replay.json
cmp original.json replay.json
sha256sum original.json replay.json
python -m dis_oracle verify --db journal/cycle-v03.sqlite3
```

В отдельном прогоне с опубликованной строкой месяца 1, дня 6 получено
`SSG`. Для привязки к современному событию использована синтетическая дата.
[Jetsu и Porceddu, PLOS ONE, Identification of SW dates](https://doi.org/10.1371/journal.pone.0144140)

В Dryad v1 файл `data4.txt` под CC0 содержит 282 однородные тройки.
Чтобы получить частичный корпус, возьмите из каждой строки день, месяц и метку
`GGG` или `SSS`, отбросьте столбец времени и разложите метку на три сегмента.
MD5 исходного файла `e69d9054dc0bd2aeb147ff9163033940`. Все 282 позиции
совпали с таблицей 1. В CLI проверены 1/1 и 12/30, обе строки `GGG`.
Остальные 78 позиций этот файл не покрывает.
[Dryad v1](https://doi.org/10.5061/dryad.tj4qg) · [Таблица 1](https://www.mv.helsinki.fi/home/jetsu/papers/algol1.pdf)

## Проверка ветки

```bash
python -m unittest tests.test_audited_core_cycle tests.test_core_availability_router tests.test_egypt_core tests.test_observation_inputs tests.test_name_grids tests.test_calendar_context tests.test_calendar_pipeline tests.test_audited_inputs -q
python -m unittest discover -q
python3.13 -m unittest discover -q
python scripts/audit_four_qwen.py --check
python scripts/yijing_audit.py --check
python -m dis_oracle compare examples/mixed.json
git diff --check
```

Целевой прогон прошёл 67 тестов. Полный набор прошёл 297 тестов на Python
3.12 и 297 на 3.13. Оба аудита вернули `MATCH`. В трёх сквозных CLI-прогонах
повторное чтение дало побайтно совпадающий отчёт и тот же хеш цепочки. Два
прогона с четырьмя карточками дали по 11 записей, прогон без карточек — 8.

## Методические решения

- **Да Лю Жэнь.** Закрепить школу и первичный источник. Согласовать календарь,
  границу дня шестидесятеричного цикла и границы двухчасовых страж, гражданское
  или солнечное время, солнечные термины и момент смены месячного генерала.
  Зафиксировать вычисление стволов и ветвей, наложение плат, порядок четырёх
  уроков, приоритет и исключения для трёх передач. Нужны опубликованные карты
  с промежуточными шагами и независимая сверка. [Архитектура](ARCHITECTURE_10_CORES.md#источники-процедур)
- **Египет.** Для рабочего корпуса закрепить источник, редакцию, права и
  способ сборки с проверяемым хешем. Автоматическая историческая корреляция
  современной даты, рассвет и часовые границы частей дня требуют отдельного
  решения.
- **Шакуна.** Утвердить редакцию первоисточника, точные места, область
  применения правил и проверенную таблицу соответствий.
- **Славянская процедура.** Закрепить цельный региональный протокол и корпус
  песен с местами в издании и обоснованием трактовок.
- **Пять сеток.** Для исторического или автоматического режима утвердить школу,
  формулы, стандарт подсчёта, версию словаря, права и таблицу толкований.
  [Аудит Шакуны, славянской процедуры и сеток](../research/audit/four_cores/REPORT.md)

Любое новое преобразование символов в числа требует отдельного согласования.
