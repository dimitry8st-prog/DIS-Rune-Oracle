# Процедуры рун и Ицзин — v0.2

Дата: 12.10.2026. Продолжение универсального ядра v0.1. Это вычисление процедурных результатов, не доказательство предсказательной способности.

## Руны

Применяется современная карта проекта из MASTER_PROMPT_v2.1.md, с сохранённым SHA-256 источника в `rune_map.json`. В исходном наборе 24 руны и blank. CSPRNG перемешивает набор, задаёт ориентации и 128-битный nonce. Канонический манифест соответствует METHOD: UTF-8, LF, без завершающего LF.

```bash
python -m dis_oracle rune-prepare --db private-runs/rune-sessions.sqlite --session-id demo-rune --event-id synthetic-only
python -m dis_oracle rune-select --db private-runs/rune-sessions.sqlite --session-id demo-rune --slot 1 --rotation 0
python -m dis_oracle rune-select --db private-runs/rune-sessions.sqlite --session-id demo-rune --slot 2 --rotation 180
python -m dis_oracle rune-select --db private-runs/rune-sessions.sqlite --session-id demo-rune --slot 3 --rotation 0
python -m dis_oracle rune-reveal --db private-runs/rune-sessions.sqlite --session-id demo-rune
```

Первые два выбора возвращают только номера/повороты и commitment; третья руна завершает выбор всех трёх и фиксирует чтение I–II–III. Только после этого отдельный reveal раскрывает весь манифест. Девять неинвертируемых рун сохраняют одно значение; blank имеет ориентацию null. Повтор номера, недопустимый поворот, подмена манифеста и новый выбор завершённой сессии блокируются.

`rune-status` восстанавливает состояние после перезапуска. Повтор `rune-prepare` не создаёт новый набор. Приватная БД сессий хранит скрытый манифест; её нельзя давать ИИ или публиковать. При создании POSIX-файл получает режим 0600; на Windows требуются настройки ACL. Локальный владелец БД способен прочесть скрытый набор; этот прототип не обеспечивает слепой выбор против администратора. БД сессий и экспортируемый журнал — разные файлы.

Рунная карточка имеет OK, поскольку процедура и современное описательное чтение выполнены. `claims=[]`: исходу не назначается автоматический голос. Пользователь или будущий смысловой модуль отдельно предлагает соответствия реестру, человек принимает метки. Карта не является единым древним каноном.

## Ицзин

Закреплена механика трёх монет, шестикратный бросок снизу вверх: 6 — изменяющаяся инь, 7 — ян, 8 — инь, 9 — изменяющийся ян. Цифровой режим использует CSPRNG; для физических бросков вводится массив из шести троек 2/3. Монетная процедура не смешивается со стеблями: вероятности различаются.

```bash
python -m dis_oracle yijing --db private-runs/procedure-journal.sqlite --run-id demo-yi --event-id synthetic-only
python -m dis_oracle yijing --db private-runs/procedure-journal.sqlite --run-id reported-yi --event-id synthetic-only --throws examples/yijing-throws.json
```

Сохраняются броски, суммы, инь/ян, изменяющиеся позиции и вторичная структура. Повтор того же run_id возвращает прежний результат, а не новый бросок. Введение новых физических значений под прежним ID запрещено.

Источники: выбранная современная монетная процедура автора [biroco.com](https://www.biroco.com/yijing/basics.htm); классический корпус — [Legge, Great Appendix](https://sacred-texts.com/ich/icap3-1.htm), который не используется как источник этой цифровой монетной реализации.

Номер по порядку Вэнь-вана, полный корпус текстов и правила чтения изменяющихся линий пока не закреплены. Поэтому карточка ABSTAIN / TEXT_CORPUS_AND_READING_RULES_NOT_FIXED, хотя сырой шестилинейный результат сохранён. Она не голосует и не увеличивает процедурное покрытие OK. Это явная граница реализованной механики, а не полная историческая интерпретация.

## Соединение с универсальным ядром

```bash
python -m dis_oracle assemble --event examples/event.json --rune-db private-runs/rune-sessions.sqlite --rune-session demo-rune --yijing-db private-runs/procedure-journal.sqlite --yijing-run demo-yi > private-runs/adapter-input.json
python -m dis_oracle freeze private-runs/adapter-input.json --run-id demo-adapters --db private-runs/engine-journal.sqlite
```

Пример synthetic-only имеет режим analysis. Реальный forecast требует предварительного паспорта, критериев и будущего срока. Карточка другого event_id отклоняется; временные метаданные созданной процедуры не могут быть позже freeze. Без принятых FORECAST-claims результат NO_COMPARABLE_DATA, а не выдуманный прогноз. Остальные восемь ядер остаются NOT_SUPPLIED/UNAVAILABLE.

Секреты, личные вопросы, БД и полные журналы не помещаются в Git. Время остаётся локальным; независимая аттестация отсутствует. Требования к поиску процедур остальных ядер: [дополнительный промпт](../prompts/ADAPTER_RESEARCH_FOLLOWUP.md).
