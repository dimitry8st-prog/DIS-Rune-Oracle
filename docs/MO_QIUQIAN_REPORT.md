# Реализация механики Мо / Гуань Инь — отчёт

17.10.2026. База: `codex/mo-qiuqian-v4-review`,
`15a75510b67ad7aff2d1ba2d0a4a41a3e348ecbd` — фактический remote HEAD
совпал с ожидаемым. Новая ветка: `codex/mo-qiuqian-persistent-mechanics`.

## Реализовано

- `dis_oracle/adapters/mo.py`: 36 упорядоченных числовых пар; ручной режим
  и CSPRNG раздельны, без выдуманного соответствия слогам или толкований.
- `qiuqian.py`: авторский набор 1–100, состояния pending/confirmed/
  no_confirmation, фиксированная палочка, явные наблюдения и завершение,
  общий лимит попыток и математическая модель двух независимых fair sides.
- `mechanics_store.py`: отдельная SQLite-БД, атомарные команды, привязка
  к событию, неизменяемые снимки всех попыток, идемпотентность, проверка
  цепочки хешей, блокировка записи до любого случайного выбора.
- `mechanics_cli.py`: отдельный CLI, не меняющий прежний CLI движка.
- Исторический режим заблокирован. Полные inputs хешируются и карточки
  проверяются существующим валидатором; изменение контракта не понадобилось.

Определения и решения, отличающиеся от непроверенного Markdown v4,
зафиксированы в [MO_QIUQIAN_MECHANICS.md](MO_QIUQIAN_MECHANICS.md).
В частности, отрицательный ручной результат сохраняется как наблюдение,
не вызывает ошибку/новый жребий; max_attempts=3 означает три попытки;
цифровое подтверждение выполняется по одной явной команде.

## Запуск и выполненные проверки

Python 3.12.14, стандартная библиотека. Из корня checkout:

```bash
python -m unittest tests.test_mo_qiuqian -v
python -m unittest discover -v
python -m dis_oracle compare examples/mixed.json
```

Проверены 27 новых тестов и 58 существующих; итог полного запуска:

```text
Ran 85 tests
OK
```

Выполнены: все 36 пар Мо, все 100 номеров цифрового набора с проверкой
итоговых карточек, все четыре сочетания сторон/три исхода, ручной отказ,
ожидание, явное завершение, лимиты 0/1/2/3 и границы допустимого параметра,
исчерпание без четвёртой попытки, успех на последней попытке,
восстановление pending и завершённых сессий после открытия БД, отсутствие
повторного RNG при replay, сохранность всех наблюдений/сторон/палочки,
изменение ввода и конфликт события, неверные типы/диапазоны/частичный ввод,
запрет смешанного режима, блокировка исторического режима, контракты и
маршрутизация/freeze в **новый временный** журнал, запрет UPDATE/DELETE,
обнаружение повреждения, конкурирующие повторные запросы и реальные CLI-процессы.
Исходный CLI по mixed.json сохранил `MIXED`. Сообщение существующего теста
`ERROR: journal does not exist` — ожидаемая отрицательная проверка.

Выполнены также отдельные CLI-процессы с новым временным файлом:

```bash
demo_dir=$(mktemp -d /tmp/dis-mechanics.XXXXXX)
python -m dis_oracle.adapters.mechanics_cli mo-run --db "$demo_dir/mechanics.sqlite" --session-id mo --event-id synthetic-only --mode manual --first-throw 3 --second-throw 5
python -m dis_oracle.adapters.mechanics_cli qiuqian-start --db "$demo_dir/mechanics.sqlite" --session-id qq --event-id synthetic-only --mode manual --stick-number 42 --max-attempts 2
python -m dis_oracle.adapters.mechanics_cli qiuqian-confirm --db "$demo_dir/mechanics.sqlite" --session-id qq --event-id synthetic-only --request-id obs-1 --confirmation-result yin_bei
python -m dis_oracle.adapters.mechanics_cli qiuqian-confirm --db "$demo_dir/mechanics.sqlite" --session-id qq --event-id synthetic-only --request-id obs-2 --confirmation-result xiao_bei
python -m dis_oracle.adapters.mechanics_cli qiuqian-status --db "$demo_dir/mechanics.sqlite" --session-id qq --event-id synthetic-only
```

Фактически получено `mo-3-5`, затем `pending → pending → no_confirmation`;
история содержит `(42,yin_bei)`, `(42,xiao_bei)`. Повторы запуска Мо и
последнего наблюдения Гуань Инь вернули идентичные карточки после запуска
отдельных процессов. Для цифрового режима `qiuqian-start --mode digital`
создаёт ожидание; `qiuqian-advance --request-id throw-1` добавляет одну
попытку. `qiuqian-finish --request-id finish-1` закрывает ожидание явно.

## Не изменено

Оригиналы Qwen v4, старые примеры/журналы, рунный адаптер, И-Цзин,
контракты/журнал/роутер, веса 0.10 и научная ветка не менялись. Сравнение
защищённых путей с исходным SHA (`git diff --exit-code`) прошло.
Дополнительно исходные SHA-256 Qwen совпали с REVIEW.md:

| Файл | SHA-256 |
| --- | --- |
| MO_QIUQIAN_SPECIFICATION.md | b09dfa1eafd205b957e621be42262f22a05fdda46808000eff65918ee1092a83 |
| mo_qiuqian_tables.json | d106f92b86b2cbb3240684e581dd7ef3dc93e680db18415214bfbfc816b46469 |
| mo_qiuqian_tests.json | ccd7a74601005ad89d6758d661769ea9293e98f515cd318837c42c2560b5022b |

Старые журналы не использовались для примеров. Попытка открыть существующий
журнал движка новым API отклоняется; отдельный тест подтвердил сохранность
его байтов. Восстановление проверено после успешных commit; испытание
аварии питания/повреждения диска не проводилось.

## Источники и данные, которых по-прежнему нет

- **Мо:** полный источник Mipham с проверенными страницами для всех 36
  толкований, соответствие чисел граням/слогам, имена результатов и
  свидетельство для PA NA / Golden Lotus. Корпус — UNAVAILABLE.
- **Гуань Инь:** источник состава/нумерации и полный корпус выбранного
  Kwan Im Thong Hood Cho Temple; его собственные правила подтверждения,
  ожидания и повторов — BLOCKED_SOURCE. Цифровая нумерация 1–100 их не заменяет.
- Из v4/REVIEW известны ссылки [Shambhala](https://www.shambhala.com/snowlion_articles/mo-tibetan-divination-system/),
  [NLB Singapore](https://www.nlb.gov.sg/main/article-detail?cmsuuid=d9189e20-2326-46b4-828c-db52113b78e5),
  [Xingtian Temple](https://www.ht.org.tw/religion207.htm).
  Новый независимый сетевой/постраничный аудит этих источников в данной
  задаче **не выполнялся**. Правила Xingtian не присваиваются сингапурскому храму.

Интерпретации остаются ABSTAIN, корпуса UNAVAILABLE, claims пусты.
Проверена **механика программной адаптации**; два исторических ядра
полностью готовыми не объявляются. Предсказательная эффективность и
физический обратный поток времени этими тестами не проверялись.
