# Исследовательский пакет адаптеров для DIS-Rune-Oracle

**Дата:** 17.10.2026  
**Базовая ветка:** `codex/integrated-engine-v0.3`  
**HEAD:** `1ca14c6e9cbc1cd13fa83fc8ce3fa88123c37b23`

## Состав пакета

```
adapters_package/
├── README.md (этот файл)
├── maya/
│   ├── SPECIFICATION.md
│   ├── SOURCES.json
│   ├── maya_calendar.py
│   ├── TEST_VECTORS.json
│   └── REPORT.md
├── shakuna/
│   ├── SPECIFICATION.md
│   ├── SOURCES.json
│   ├── RULES.json
│   ├── shakuna.py
│   ├── TEST_VECTORS.json
│   └── REPORT.md
├── slavic/
│   ├── SPECIFICATION.md
│   ├── SOURCES.json
│   ├── CORPUS.json
│   ├── slavic.py
│   ├── TEST_VECTORS.json
│   └── REPORT.md
└── name_grids/
    ├── SPECIFICATION.md
    ├── SOURCES.json
    ├── name_grids.py
    ├── TEST_VECTORS.json
    └── REPORT.md
```

## Зависимости

- Python 3.11+
- Стандартная библиотека (hashlib, json, secrets, datetime)
- Без внешних зависимостей

## Команды запуска

```bash
# Тесты для всех адаптеров
python -m pytest adapters_package/

# Индивидуальные тесты
python adapters_package/maya/maya_calendar.py --test
python adapters_package/shakuna/shakuna.py --test
python adapters_package/slavic/slavic.py --test
python adapters_package/name_grids/name_grids.py --test
```

## Матрица готовности

| Ядро | Источники | Процедура | Таблицы | Корпус | Код | Тесты | Интеграция |
|------|-----------|-----------|---------|--------|-----|-------|------------|
| maya | ⚠ Частично | ⚠ Календарь готов, жребий BLOCKED | ✓ 20 знаков | ✗ | ✓ Календарь | ✓ | ⚠ Частично |
| shakuna | ✓ Брихат-самхита | ✓ Глава 86 | ✓ Правила | ✓ | ✓ | ✓ | ✓ |
| slavic | ✓ Подблюдные песни | ✓ Полная | ✓ | ✓ 15 песен | ✓ | ✓ | ✓ |
| name_grids | ⚠ Частично | ⚠ Только японский | ✓ 5 сеток | ⚠ | ✓ | ✓ | ⚠ Частично |

## Блокеры

### maya
- **Жребий pajooneem:** Этнографическое описание неполное, точная процедура не восстановлена
- **Корпус толкований:** Не получен

### shakuna
- **Готово к интеграции**

### slavic
- **Готово к интеграции**

### name_grids
- **Кириллица:** Соответствия не установлены
- **Толкования:** Таблицы не получены из-за лицензионных ограничений

## Порядок подключения через Codex

1. Проверить спецификации в каждом каталоге
2. Запустить тесты: `python -m pytest adapters_package/`
3. Для интеграции скопировать `.py` файлы в `dis_oracle/adapters/`
4. Обновить `dis_oracle/cli.py` для добавления команд
5. Добавить тесты в `tests/`

## Ограничения

- Не изменяет main, общий движок, веса, другие адаптеры
- Не выполняет автоматическое слияние
- Прогнозная эффективность не установлена
- Физические эффекты не подтверждаются

## Статусы

- **OK:** Процедура выполнена и проверена
- **ABSTAIN:** Процедура выполнена, но интерпретация недоступна
- **UNAVAILABLE:** Нет необходимого протокола или корпуса
- **ERROR:** Технический сбой
- **BLOCKED_SOURCE:** Источник недоступен или не подтверждён
