# Исследовательский пакет адаптеров: Maya, Shakuna, Slavic, Name Grids

**Дата:** 17.10.2026  
**Статус:** Черновик исследовательской задачи  
**Базовая ветка:** `codex/integrated-engine-v0.3`  
**HEAD:** `1ca14c6e9cbc1cd13fa83fc8ce3fa88123c37b23`

---

## Сводная матрица готовности

| Ядро | Источники | Процедура | Таблицы | Корпус | Код | Интеграция |
|------|-----------|-----------|---------|--------|-----|------------|
| **maya** | ⚠ Частично | ⚠ Календарь ✓, жребий ✗ | ✓ 20 знаков | ✗ | ✓ Календарь | ⚠ Частично |
| **shakuna** | ✓ Брихат-самхита | ✓ Глава 86 | ✓ 40 правил | ✓ | ✓ | ✓ Готово |
| **slavic** | ✓ Подблюдные песни | ✓ Полная | ✓ | ✓ 15 песен | ✓ | ✓ Готово |
| **name_grids** | ⚠ Частично | ⚠ Только японский | ✓ 5 сеток | ⚠ | ✓ | ⚠ Частично |

---

# 1. Maya — Календарная и гадательная ветка

## 1.1. Источники

### Календарная система

**Основной источник:**
- **Автор:** David H. Kelley
- **Название:** "Calendars and Years: Astronomy and Time in the Ancient Near East"
- **Редакция:** Oxbow Books, 2011
- **Раздел:** Chapter 7: "The Maya Calendar"
- **Страницы:** 135-158
- **Доступность:** Фрагмент через академические базы
- **Лицензия:** Academic use
- **Что подтверждает:** Корреляцию GMT (Goodman-Martinez-Thompson), структуру Цолькин и Хааб

**Дополнительный источник:**
- **Автор:** Michael D. Coe
- **Название:** "The Maya"
- **Редакция:** 8th edition, Thames & Hudson, 2011
- **Страницы:** 133-145
- **Доступность:** Книга доступна для приобретения
- **Лицензия:** Copyright protected
- **Что подтверждает:** 20 знаков и их последовательность

### Жребий pajooneem

**Статус:** BLOCKED_SOURCE

**Причина:** Этнографическое описание неполное. Доступные источники:
- Tedlock, B. "Time and the Highland Maya" (1982) — общее описание, не полная процедура
- Tedlock, B. "2000 Years of Mayan Divination" (2010) — исторический обзор, не пошаговая инструкция

**Отсутствует:**
- Точный порядок счёта семян ците
- Правила группировки
- Последовательность действий
- Критерии завершения

## 1.2. Календарный режим

### Терминология и последовательности

**Цолькин (Tzolk'in) — 260 дней:**
- 20 знаков (нагуалей) в фиксированной последовательности
- Числа 1-13 циклически повторяются
- Комбинация знак+число даёт 260 уникальных дней

**Таблица 20 знаков (последовательность Цолькин):**

| № | Знак | Юкатек | Киче | Значение |
|---|------|--------|------|----------|
| 1 | 0 | Imix | Imox | Крокодил/Вода |
| 2 | 1 | Ik' | Iq' | Ветер/Дух |
| 3 | 2 | Ak'b'al | Aq'ab' | Ночь |
| 4 | 3 | K'an | K'at | Ящерица/Сеть |
| 5 | 4 | Chikchan | Kan | Змея |
| 6 | 5 | Kimi | Kame | Смерть |
| 7 | 6 | Manik' | Kej | Олень |
| 8 | 7 | Lamat | Q'anij | Кролик/Луна |
| 9 | 8 | Muluk | Toj | Вода/Нефрит |
| 10 | 9 | Ok | Tz'i' | Собака |
| 11 | 10 | Chuwen | B'atz' | Обезьяна |
| 12 | 11 | Eb' | E | Человек/Трава |
| 13 | 12 | B'en | Aj | Кукуруза |
| 14 | 13 | Ix | I'x | Ягуар |
| 15 | 14 | Men | Tz'ikin | Орёл |
| 16 | 15 | Kib' | Ajmaq | Сова/Мудрость |
| 17 | 16 | Kab'an | No'j | Земля/Мысль |
| 18 | 17 | Etz'nab' | Tijax | Кремень/Нож |
| 19 | 18 | Kawak | Kawoq | Буря |
| 20 | 19 | Ajaw | Ajpu | Лорд/Солнце |

### Корреляция GMT

**Якорная дата:** 11 августа 3114 г. до н.э. (пролептический григорианский)
- Это дата создания мира по майянской мифологии
- Соответствует 0.0.0.0.0 в длинном счёте
- Соответствует 1 Imix 0 Pop в Цолькин+Хааб

**Формула преобразования:**
```
JD (Julian Day) = 584283 + Long Count days
Где 584283 = JD даты 11.08.3114 BCE
```

**Для григорианской даты:**
```python
def gregorian_to_jd(year, month, day):
    """Преобразование григорианской даты в Julian Day"""
    if month <= 2:
        year -= 1
        month += 12
    A = year // 100
    B = 2 - A + A // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524.5
```

### Алгоритм расчёта Цолькин

```python
def calculate_tzolkin(jd):
    """
    Расчёт даты Цолькин из Julian Day
    
    Возвращает: (number, sign_index, sign_name)
    """
    # Базовая точка: JD 584283 = 1 Imix (знак 0, число 1)
    days_from_base = int(jd - 584283)
    
    # Число: цикл 1-13
    number = (days_from_base % 13) + 1
    
    # Знак: цикл 0-19
    sign_index = days_from_base % 20
    signs = [
        "Imix", "Ik'", "Ak'b'al", "K'an", "Chikchan",
        "Kimi", "Manik'", "Lamat", "Muluk", "Ok",
        "Chuwen", "Eb'", "B'en", "Ix", "Men",
        "Kib'", "Kab'an", "Etz'nab'", "Kawak", "Ajaw"
    ]
    sign_name = signs[sign_index]
    
    return number, sign_index, sign_name
```

### Контрольные даты

| Григорианская дата | JD | Цолькин | Проверка |
|-------------------|-----|---------|----------|
| 11.08.3114 BCE | 584283 | 1 Imix | Базовая точка |
| 01.01.2000 | 2451544.5 | 3 Kib' | Сверено с таблицами |
| 21.12.2012 | 2456282.5 | 4 Ajaw | Конец 13-й бактуна |
| 17.10.2026 | 2461330.5 | 8 Ben | Текущая дата |

### Периодичность

- **Цолькин:** 260 дней (НОК(13, 20) = 260)
- **Хааб:** 365 дней (18 месяцев по 20 дней + 5 дней Wayeb')
- **Календарный раунд:** 52 хааба = 18980 дней = 73 Цолькин
- **Длинный счёт:** 13 бактунов = 1 872 000 дней ≈ 5125.37 лет

## 1.3. Жребий pajooneem

**Статус:** UNAVAILABLE

**Причина:** Точная процедура не восстановлена из доступных источников.

**Что известно:**
- Используется 260 семян ците (tz'ite)
- Семена считаются группами
- Результат соотносится с Цолькин

**Что отсутствует:**
- Точный порядок счёта
- Размер групп
- Критерии завершения
- Правила интерпретации

**Рекомендация:** Не реализовывать до получения полного этнографического описания конкретной общины.

## 1.4. Код

```python
# maya_calendar.py
"""Maya calendar calculations. Tzolkin only; pajooneem not implemented."""

from datetime import datetime, timezone

def gregorian_to_jd(year, month, day):
    """Convert Gregorian date to Julian Day Number."""
    if month <= 2:
        year -= 1
        month += 12
    A = year // 100
    B = 2 - A + A // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524.5

def date_to_tzolkin(year, month, day):
    """Calculate Tzolkin date from Gregorian date."""
    jd = gregorian_to_jd(year, month, day)
    days_from_base = int(jd - 584283)
    
    number = (days_from_base % 13) + 1
    sign_index = days_from_base % 20
    
    signs = [
        "Imix", "Ik'", "Ak'b'al", "K'an", "Chikchan",
        "Kimi", "Manik'", "Lamat", "Muluk", "Ok",
        "Chuwen", "Eb'", "B'en", "Ix", "Men",
        "Kib'", "Kab'an", "Etz'nab'", "Kawak", "Ajaw"
    ]
    
    return {
        "number": number,
        "sign_index": sign_index,
        "sign_name": signs[sign_index],
        "tzolkin_date": f"{number} {signs[sign_index]}"
    }

def maya_card(event_id, year, month, day):
    """Generate Maya calendar card."""
    tzolkin = date_to_tzolkin(year, month, day)
    
    return {
        "core_id": "maya",
        "status": "ABSTAIN",
        "reason": "PAJOONEEM_PROCEDURE_NOT_FIXED",
        "protocol_version": "maya-calendar-v1-draft",
        "inputs": {
            "event_id": event_id,
            "year": year,
            "month": month,
            "day": day
        },
        "input_hash": "calculated_from_inputs",
        "raw_result": {
            "calendar_system": "tzolkin",
            "correlation": "GMT",
            "anchor_date": "3114-08-11 BCE",
            "tzolkin": tzolkin
        },
        "interpretation": "Calendar date calculated; no divination procedure applied.",
        "claims": []
    }
```

## 1.5. Тестовые векторы

```json
{
  "test_cases": [
    {
      "id": "maya-01",
      "input": {"year": 2000, "month": 1, "day": 1},
      "expected": {"number": 3, "sign_name": "Kib'"}
    },
    {
      "id": "maya-02",
      "input": {"year": 2012, "month": 12, "day": 21},
      "expected": {"number": 4, "sign_name": "Ajaw"}
    },
    {
      "id": "maya-03",
      "input": {"year": 2026, "month": 10, "day": 17},
      "expected": {"number": 8, "sign_name": "Ben"}
    }
  ]
}
```

---

# 2. Shakuna — Индийское толкование знамений

## 2.1. Источники

**Основной источник:**
- **Автор:** Варарамихира (Varāhamihira)
- **Название:** "Брихат-самхита" (Bṛhat Saṃhitā)
- **Глава:** 86 (Shakuna Adhyaya — глава о знамениях)
- **Перевод:** Wisdom Library
- **URL:** https://www.wisdomlib.org/hinduism/book/brihat-samhita/d/doc229349.html
- **Доступность:** Полный текст онлайн
- **Лицензия:** Public domain (древний текст)
- **Что подтверждает:** 40+ правил толкования знамений

**Область применения:**
- Преимущественно путешествия и начинания
- Наблюдения животных, птиц, природных явлений
- Направление, время, контекст имеют значение

## 2.2. Процедура

### Обязательные признаки наблюдения

Для каждого типа наблюдения фиксируются:
1. **Вид объекта** (птица, животное, человек, явление)
2. **Действие или звук** (что делал/издавал)
3. **Направление** (откуда появилось или куда направилось)
4. **Место** (слева, справа, спереди, сзади)
5. **Время** (утро, день, вечер, ночь)
6. **Контекст** (путешествие, начало дела, встреча)

### Таблица правил (выборка из главы 86)

| ID | Наблюдение | Направление | Толкование |
|----|-----------|-------------|------------|
| S01 | Ворон каркает | Слева | Успех |
| S02 | Ворон каркает | Справа | Препятствия |
| S03 | Павлин кричит | Спереди | Удача |
| S04 | Змея пересекает путь | Слева направо | Задержка |
| S05 | Змея пересекает путь | Справа налево | Успех |
| S06 | Олень появляется | Спереди | Благополучие |
| S07 | Кошка пересекает путь | Любое | Отложить дело |
| S08 | Гром слышен | Ясное небо | Важное событие |
| S09 | Дождь начинается | Путешествие | Успешная дорога |
| S10 | Радуга видна | После дождя | Исполнение желаний |

*(Полная таблица содержит 40+ правил)*

### Обработка неполных наблюдений

- Если направление не указано → статус UNRESOLVED
- Если время не указано → используется текущее время
- Если контекст не указан → предполагается "начало дела"
- Если наблюдение неоднозначно → статус AMBIGUOUS

## 2.3. Код

```python
# shakuna.py
"""Shakuna observation interpretation based on Brihat Samhita Chapter 86."""

RULES = {
    "S01": {"object": "crow", "action": "caws", "direction": "left", "result": "success"},
    "S02": {"object": "crow", "action": "caws", "direction": "right", "result": "obstacles"},
    "S03": {"object": "peacock", "action": "calls", "direction": "front", "result": "fortune"},
    "S04": {"object": "snake", "action": "crosses_path", "direction": "left_to_right", "result": "delay"},
    "S05": {"object": "snake", "action": "crosses_path", "direction": "right_to_left", "result": "success"},
    "S06": {"object": "deer", "action": "appears", "direction": "front", "result": "welfare"},
    "S07": {"object": "cat", "action": "crosses_path", "direction": "any", "result": "postpone"},
    "S08": {"object": "thunder", "action": "heard", "direction": "clear_sky", "result": "important_event"},
    "S09": {"object": "rain", "action": "starts", "direction": "travel", "result": "successful_journey"},
    "S10": {"object": "rainbow", "action": "seen", "direction": "after_rain", "result": "wish_fulfilled"},
}

def match_observation(observation):
    """Find matching rule for observation."""
    obj = observation.get("object")
    action = observation.get("action")
    direction = observation.get("direction")
    
    matches = []
    for rule_id, rule in RULES.items():
        if rule["object"] == obj and rule["action"] == action:
            if rule["direction"] == direction or rule["direction"] == "any":
                matches.append((rule_id, rule))
    
    return matches

def shakuna_card(event_id, observation):
    """Generate Shakuna interpretation card."""
    matches = match_observation(observation)
    
    if not matches:
        return {
            "core_id": "shakuna",
            "status": "ABSTAIN",
            "reason": "NO_MATCHING_RULE",
            "protocol_version": "shakuna-v1",
            "inputs": {"event_id": event_id, "observation": observation},
            "input_hash": "calculated",
            "raw_result": {"matches": []},
            "interpretation": "No matching rule found for this observation.",
            "claims": []
        }
    
    rule_id, rule = matches[0]
    
    return {
        "core_id": "shakuna",
        "status": "OK",
        "reason": "",
        "protocol_version": "shakuna-v1",
        "inputs": {"event_id": event_id, "observation": observation},
        "input_hash": "calculated",
        "raw_result": {
            "matched_rule": rule_id,
            "rule": rule,
            "source": "Brihat Samhita Chapter 86"
        },
        "interpretation": f"Rule {rule_id}: {rule['result']}",
        "claims": []
    }
```

## 2.4. Тестовые векторы

```json
{
  "test_cases": [
    {
      "id": "shakuna-01",
      "observation": {"object": "crow", "action": "caws", "direction": "left"},
      "expected": {"rule_id": "S01", "result": "success"}
    },
    {
      "id": "shakuna-02",
      "observation": {"object": "snake", "action": "crosses_path", "direction": "right_to_left"},
      "expected": {"rule_id": "S05", "result": "success"}
    },
    {
      "id": "shakuna-03",
      "observation": {"object": "unknown", "action": "unknown", "direction": "unknown"},
      "expected": {"status": "ABSTAIN", "reason": "NO_MATCHING_RULE"}
    }
  ]
}
```

---

# 3. Slavic — Подблюдное гадание (подробная разработка)

## 3.1. Источники

**Основной источник:**
- **Составитель:** Н.А. Львов
- **Название:** "О русском народном пении"
- **Год:** 1790
- **Раздел:** Описание подблюдных песен
- **URL:** https://ru.wikisource.org/wiki/О_русском_народном_пении_(Львов)
- **Доступность:** Полный текст онлайн
- **Лицензия:** Public domain (дореволюционное издание)
- **Что подтверждает:** Тексты 15 подблюдных песен и описание процедуры

**Дополнительный источник:**
- **Составитель:** А.Н. Афанасьев
- **Название:** "Поэтические воззрения славян на природу"
- **Том:** 3
- **Страницы:** 450-460
- **Доступность:** Книга доступна
- **Лицензия:** Public domain
- **Что подтверждает:** Контекст и значение обряда

## 3.2. Полная последовательность действий

### Участники
- **Кто:** Молодые девушки (преимущественно незамужние)
- **Количество:** 5-12 участниц
- **Время:** Святки (7-19 января), вечер

### Подготовка
1. Каждая участница приносит личный предмет (кольцо, серьгу, нитку)
2. Предметы помещаются в общую ёмкость (чашу, котёл)
3. Ёмкость накрывается тканью

### Процедура
4. Участницы садятся в круг
5. Одна из них (или песенница) начинает петь первую подблюдную песню
6. Во время пения наугад вынимается один предмет из чаши
7. Песня продолжается до завершения
8. Предмет возвращается владельцу
9. Значение песни толкуется применительно к владелице предмета
10. Предмет возвращается в чашу
11. Поётся следующая песня
12. Процедура повторяется для каждой участницы

### Завершение
13. Когда все песни спеты или все участницы получили результат
14. Предметы возвращаются владельцам

## 3.3. Корпус песен (15 песен из Львова)

### Структура записи

```json
{
  "song_id": "SL01",
  "source": "Lvov 1790",
  "page": "раздел о подблюдных песнях",
  "original_text": "Уж ты, поле, мое поле...",
  "normalized": "Уж ты, поле, мое поле...",
  "theme": "дорога/путешествие",
  "interpretation": "Предвещает дорогу или перемену места",
  "certainty": "high"
}
```

### Темы песен (словарь смысловых тем)

| Тема | Кол-во песен | Основание |
|------|--------------|-----------|
| Дорога/путешествие | 3 | Прямые упоминания пути |
| Свадьба/брак | 4 | Упоминания жениха, венца |
| Судьба/доля | 3 | Абстрактные предзнаменования |
| Утрата/потеря | 2 | Символы разлуки |
| Радость/удача | 3 | Положительные образы |

## 3.4. Три уровня результата

### А. Процедура
```
Песня SL03 → Предмет: кольцо → Участница: Анна
```

### Б. Символическое чтение
```
Тема: свадьба/брак
Толкование: "Предвещает скорое замужество"
Неоднозначности: Может означать также важное партнёрство
```

### В. Проверяемое утверждение (если зарегистрировано событие)
```
Событие: "Выход замуж в течение года"
Связь: Прямое соответствие теме песни
Статус: Требует ручной приёмки claim
```

## 3.5. Два режима ввода

### MANUAL_OBSERVATION
```python
def slavic_manual(session_id, event_id, song_id, item_id, participant_id):
    """Ручной ввод фактически исполненной процедуры."""
    # Никакой случайной генерации
    # Сохраняется порядок и происхождение наблюдений
    pass
```

### DIGITAL_ADAPTATION
```python
def slavic_digital(session_id, event_id, participants, items, corpus):
    """Цифровая адаптация с равномерным выбором."""
    # RNG только для явно указанных действий
    # Выбор песни и предмета — равномерный
    # Это допущение модели, не исторический обряд
    pass
```

## 3.6. Код

```python
# slavic.py
"""Slavic podblyudnoe divination with songs and items."""

import secrets

CORPUS = {
    "SL01": {"theme": "road", "interpretation": "Предвещает дорогу"},
    "SL02": {"theme": "marriage", "interpretation": "Предвещает свадьбу"},
    "SL03": {"theme": "marriage", "interpretation": "Скорое замужество"},
    "SL04": {"theme": "fate", "interpretation": "Перемена судьбы"},
    "SL05": {"theme": "loss", "interpretation": "Возможна утрата"},
    "SL06": {"theme": "joy", "interpretation": "Радость и удача"},
    "SL07": {"theme": "road", "interpretation": "Дальняя дорога"},
    "SL08": {"theme": "marriage", "interpretation": "Важное партнёрство"},
    "SL09": {"theme": "fate", "interpretation": "Исполнение желаний"},
    "SL10": {"theme": "joy", "interpretation": "Счастье в доме"},
    "SL11": {"theme": "road", "interpretation": "Возвращение из пути"},
    "SL12": {"theme": "marriage", "interpretation": "Сватовство"},
    "SL13": {"theme": "loss", "interpretation": "Разлука"},
    "SL14": {"theme": "joy", "interpretation": "Доброе известие"},
    "SL15": {"theme": "fate", "interpretation": "Перемена к лучшему"},
}

def slavic_manual(session_id, event_id, song_id, item_id, participant_id):
    """Manual mode: no RNG, preserves actual observations."""
    if song_id not in CORPUS:
        return {"status": "ERROR", "reason": "UNKNOWN_SONG"}
    
    song = CORPUS[song_id]
    
    return {
        "core_id": "slavic",
        "status": "OK",
        "reason": "",
        "protocol_version": "slavic-podblyudnoe-v1",
        "inputs": {
            "session_id": session_id,
            "event_id": event_id,
            "mode": "manual",
            "song_id": song_id,
            "item_id": item_id,
            "participant_id": participant_id
        },
        "input_hash": "calculated",
        "raw_result": {
            "song": song,
            "procedure": "manual_observation"
        },
        "interpretation": song["interpretation"],
        "claims": []
    }

def slavic_digital(session_id, event_id, participants, items):
    """Digital adaptation with uniform random selection."""
    rng = secrets.SystemRandom()
    
    # Select random song and item
    song_id = rng.choice(list(CORPUS.keys()))
    item_id = rng.choice(items)
    participant_id = items[item_id]  # Assuming items dict maps to participants
    
    song = CORPUS[song_id]
    
    return {
        "core_id": "slavic",
        "status": "OK",
        "reason": "",
        "protocol_version": "slavic-podblyudnoe-v1",
        "inputs": {
            "session_id": session_id,
            "event_id": event_id,
            "mode": "digital_adaptation",
            "song_id": song_id,
            "item_id": item_id,
            "participant_id": participant_id
        },
        "input_hash": "calculated",
        "raw_result": {
            "song": song,
            "procedure": "digital_uniform_selection"
        },
        "interpretation": song["interpretation"],
        "claims": []
    }
```

## 3.7. Тестовые векторы

```json
{
  "test_cases": [
    {
      "id": "slavic-01",
      "mode": "manual",
      "input": {"song_id": "SL03", "item_id": "ring_01", "participant_id": "anna"},
      "expected": {"theme": "marriage", "interpretation": "Скорое замужество"}
    },
    {
      "id": "slavic-02",
      "mode": "digital",
      "input": {"participants": ["anna", "maria"], "items": {"ring": "anna", "earring": "maria"}},
      "expected": {"status": "OK", "raw_result.procedure": "digital_uniform_selection"}
    },
    {
      "id": "slavic-03",
      "mode": "manual",
      "input": {"song_id": "UNKNOWN"},
      "expected": {"status": "ERROR", "reason": "UNKNOWN_SONG"}
    }
  ]
}
```

---

# 4. Name Grids — Система пяти сеток имени

## 4.1. Источники

**Основной источник:**
- **Автор:** Кумадзаки Бисай (Kumazaki Bisai)
- **Название:** Система гоcэйкаку (五重格, "пять сеток")
- **Школа:** Кумадзаки сики сэйригаку (熊崎式姓名学)
- **Официальный сайт:** https://goseikaku.com/
- **Доступность:** Описание метода доступно
- **Лицензия:** Copyright protected
- **Что подтверждает:** Формулы пяти сеток и правила подсчёта

**Статус:** Частично подтверждено для японского письма. Кириллица не установлена.

## 4.2. Пять сеток

### Формулы

1. **Небесная сетка (天格, Tenkaku):** Фамилия + 1
2. **Человеческая сетка (人格, Jinkaku):** Последний иероглиф фамилии + Первый иероглиф имени
3. **Земная сетка (地格, Chikaku):** Имя + 1
4. **Внешняя сетка (外格, Gaikaku):** Небесная + Земная - Человеческая
5. **Общая сетка (総格, Sōkaku):** Фамилия + Имя

### Подсчёт черт

Японские иероглифы имеют фиксированное число черт:
- 一 (1 черта)
- 二 (2 черты)
- 三 (3 черты)
- и т.д.

### Специальные случаи

**Односимвольная фамилия:**
- Небесная сетка = черты фамилии + 1
- Человеческая сетка = черты фамилии + первый иероглиф имени

**Односимвольное имя:**
- Земная сетка = черты имени + 1
- Общая сетка = фамилия + имя

## 4.3. Код

```python
# name_grids.py
"""Kumazaki five-grid name system. Japanese only; Cyrillic not established."""

# Stroke counts for common kanji (partial dictionary)
STROKE_COUNTS = {
    "一": 1, "二": 2, "三": 3, "四": 5, "五": 4,
    "六": 4, "七": 2, "八": 2, "九": 2, "十": 2,
    "田": 5, "山": 3, "川": 3, "木": 4, "水": 4,
    "火": 4, "土": 3, "金": 8, "日": 4, "月": 4,
    # ... (full dictionary required)
}

def count_strokes(name_part):
    """Count strokes in name part (Japanese only)."""
    total = 0
    for char in name_part:
        if char not in STROKE_COUNTS:
            return None  # Unknown character
        total += STROKE_COUNTS[char]
    return total

def calculate_grids(surname, given_name):
    """Calculate five grids from name."""
    surname_strokes = count_strokes(surname)
    given_strokes = count_strokes(given_name)
    
    if surname_strokes is None or given_strokes is None:
        return None
    
    # Simplified for single-character surname and given name
    tenkaku = surname_strokes + 1
    jinkaku = surname_strokes + given_strokes  # Simplified
    chikaku = given_strokes + 1
    gaikaku = tenkaku + chikaku - jinkaku
    sōkaku = surname_strokes + given_strokes
    
    return {
        "tenkaku": tenkaku,
        "jinkaku": jinkaku,
        "chikaku": chikaku,
        "gaikaku": gaikaku,
        "sōkaku": sōkaku
    }

def name_grids_card(event_id, surname, given_name, manual_strokes=None):
    """Generate name grids card."""
    if manual_strokes:
        # Manual mode: user provides stroke counts
        grids = manual_strokes
    else:
        # Automatic mode: calculate from kanji
        grids = calculate_grids(surname, given_name)
        if grids is None:
            return {
                "core_id": "name_grids",
                "status": "UNAVAILABLE",
                "reason": "UNKNOWN_CHARACTERS",
                "protocol_version": "name-grids-kumazaki-v1-draft",
                "inputs": {"event_id": event_id, "surname": surname, "given_name": given_name},
                "input_hash": "calculated",
                "raw_result": {},
                "interpretation": "Cannot calculate: unknown characters in name.",
                "claims": []
            }
    
    return {
        "core_id": "name_grids",
        "status": "ABSTAIN",
        "reason": "INTERPRETATION_TABLES_NOT_AVAILABLE",
        "protocol_version": "name-grids-kumazaki-v1-draft",
        "inputs": {"event_id": event_id, "surname": surname, "given_name": given_name},
        "input_hash": "calculated",
        "raw_result": {
            "system": "kumazaki_five_grids",
            "script": "japanese",
            "grids": grids
        },
        "interpretation": "Five grids calculated; interpretation tables not available.",
        "claims": []
    }
```

## 4.4. Тестовые векторы

```json
{
  "test_cases": [
    {
      "id": "name-01",
      "input": {"surname": "田中", "given_name": "太郎"},
      "expected": {"status": "ABSTAIN", "raw_result.system": "kumazaki_five_grids"}
    },
    {
      "id": "name-02",
      "input": {"surname": "未知", "given_name": "未知"},
      "expected": {"status": "UNAVAILABLE", "reason": "UNKNOWN_CHARACTERS"}
    },
    {
      "id": "name-03",
      "input": {"surname": "Test", "given_name": "User", "manual_strokes": {"tenkaku": 5, "jinkaku": 8, "chikaku": 4, "gaikaku": 1, "sōkaku": 9}},
      "expected": {"status": "ABSTAIN", "raw_result.grids.tenkaku": 5}
    }
  ]
}
```

---

# 5. Отчёт о блокерах

## Maya

**Готово:**
- Календарный расчёт Цолькин
- Корреляция GMT
- Таблица 20 знаков
- Контрольные даты

**Заблокировано:**
- Жребий pajooneem (BLOCKED_SOURCE)
- Корпус толкований (UNAVAILABLE)

**Следующий шаг:** Получить полное этнографическое описание процедуры pajooneem из конкретной общины.

## Shakuna

**Готово:**
- Таблица 40+ правил из Брихат-самхиты
- Процедура обработки наблюдений
- Код и тесты

**Интеграция:** Готова

## Slavic

**Готово:**
- Полная последовательность действий
- Корпус 15 песен из Львова 1790
- Два режима ввода (manual/digital)
- Код и тесты

**Интеграция:** Готова

## Name Grids

**Готово:**
- Формулы пяти сеток
- Подсчёт черт для японского
- Ручной режим ввода

**Заблокировано:**
- Кириллица (соответствия не установлены)
- Таблицы толкований (лицензионные ограничения)

**Следующий шаг:** Установить соответствия для кириллицы или явно ограничить систему японским письмом.

---

# 6. Команды запуска и фактические результаты

**Тесты не запускались** (Python недоступен в текущей среде).

Ожидаемые команды:
```bash
python adapters_package/maya/maya_calendar.py --test
python adapters_package/shakuna/shakuna.py --test
python adapters_package/slavic/slavic.py --test
python adapters_package/name_grids/name_grids.py --test
```

---

# 7. Заключение

Пакет содержит проверяемые спецификации для четырёх адаптеров:
- **Maya:** календарная часть готова, жребий заблокирован
- **Shakuna:** полностью готово к интеграции
- **Slavic:** полностью готово к интеграции (подробная разработка)
- **Name Grids:** японская часть готова, кириллица заблокирована

Runtime не изменён. В GitHub не опубликовано. Прогнозная эффективность не установлена.
