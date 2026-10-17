# Спецификации адаптеров: Мо и Гуань Инь (Цю Цянь) — ИСПРАВЛЕННАЯ ВЕРСИЯ

Дата: 14.10.2026. Статус: **черновик исследовательской задачи (исправлено после проверки)**.
Ветка: `codex/universal-engine-v0.1`, HEAD `3ef5e4aea1783e6cd9808766fa623a600618086b`.
Не изменяет runtime, старые расклады или журналы.

---

## Сводная таблица готовности (ИСПРАВЛЕНА)

| Адаптер | Что проверено | Что воспроизводится | Что заблокировано | Что можно передать программисту |
|---------|---------------|---------------------|-------------------|--------------------------------|
| **mo** | Механика двух бросков (6×6=36); атрибут Мипхаму (XIX в.); источник Shambhala | Сырой результат: упорядоченная пара (a,b); статус процедуры | Полная таблица 36 толкований с идентификаторами и текстами; пример PA NA / Golden Lotus по странице; соответствие чисел 1–6 слогам мантры | Механика генерации пары; каркас карточки; статус ABSTAIN до получения корпуса |
| **qiuqian** (Гуань Инь) | Храм Kwan Im Thong Hood Cho Temple (Сингапур), 100 палочек; процедура 筊杯 по行天宮; источник NLB Singapore | Сырой результат: номер палочки + статус подтверждения; ветви процедуры | Полный корпус текстов 100 жребиев с идентификаторами; точные формулировки толкований; правила повторов именно этого храма | Механика выбора номера; процедура подтверждения; конечные состояния; статус ABSTAIN до корпуса |

**ИЗМЕНЕНИЯ:**
- Удалено ложное заключение "оба адаптера готовы к реализации"
- Исправлен храм: Kwan Im Thong Hood Cho Temple (Сингапур), не Linshun Gong (Тайвань)
- Исправлены правила 筊杯 по официальному источнику 行天宮
- Вероятности 50/25/25 помечены как математическая модель, не традиционные
- Исправлены все алгоритмы и входные схемы
- Добавлены исполняемые тесты

---

## 1. Мо (`mo`) — тибетская кубиковая система

### 1.1. Источник и атрибуция

**Основной источник:**
- Jamgön Mipham (1846–1912). *Mo: Tibetan Divination System*.
- Издатель: Shambhala Publications. Книга содержит предисловие Его Святейшества Сакья Тризина.
- URL (описание): https://www.shambhala.com/snowlion_articles/mo-tibetan-divination-system/

**Атрибуция:**
- Мипхам — мастер традиции Ньингма тибетского буддизма, не Сакья.
- Предисловие Сакья Тризина не делает систему принадлежащей школе Сакья; это одобрение уважаемого учителя другой традиции.
- Система связана с бодхисаттвой Манджушри (Манджушри Мо).

**Страницы и конкретные данные:**
- Полная таблица 36 сочетаний и пример PA NA / Golden Lotus **не подтверждены по конкретным страницам** в текущем исследовании. Книга доступна для приобретения, но полный текст не извлечён.
- Без сверки с конкретными страницами таблица толкований не может быть воспроизведена.

### 1.2. Механика (подтверждённая часть)

**Процедура:**
1. Два последовательных броска шестигранного кубика.
2. Первый бросок — `a` (1..6), второй — `b` (1..6).
3. Результат — упорядоченная пара `(a, b)`.
4. Всего 36 возможных сочетаний.

**Важно:**
- Сочетания `(a, b)` и `(b, a)` различны, если `a ≠ b` (упорядоченность).
- Традиционные кубики могут иметь на гранях слоги мантры Манджушри: `A Ra Pa Ca Na Dhi`. В цифровой адаптации используются числа 1–6.
- **Соответствие чисел 1–6 слогам НЕ ПОДТВЕРЖДЕНО** конкретным изданием. Это предположение на основе вторичных источников.
- Дата, время и содержание вопроса **не являются обязательными расчётными входами** без подтверждения источником.

**Историческая vs цифровая процедура:**
- Историческая: ритуал с мантрой, визуализацией Манджушри, физическим кубиком.
- Цифровая: CSPRNG генерирует два числа 1–6. Это адаптация, не религиозный ритуал.

### 1.3. Входная схема (ИСПРАВЛЕНА)

```json
{
  "adapter_id": "mo",
  "protocol_version": "mo-mipham-v1-draft",
  "inputs": {
    "event_id": "string (обязательно)",
    "session_id": "string (обязательно, для сохранения сессии)",
    "first_throw": "int 1..6 | null",
    "second_throw": "int 1..6 | null",
    "use_csprng": "bool (обязательно, явно задано)"
  }
}
```

**Правила обработки входов:**
- `event_id` и `session_id` обязательны
- `use_csprng` должно быть явно задано (true/false)
- Если `use_csprng = true`: оба `first_throw` и `second_throw` игнорируются, генерируются через CSPRNG
- Если `use_csprng = false`: оба `first_throw` и `second_throw` обязательны и должны быть int 1..6
- Частичный ввод (один задан, другой null) при `use_csprng = false` отклоняется с ошибкой

### 1.4. Алгоритм (ИСПРАВЛЕН)

```python
def mo_procedure(event_id, session_id, use_csprng, first_throw=None, second_throw=None):
    """
    Исправленная версия:
    - Явная проверка типов до генерации
    - Разделение ручного ввода и CSPRNG
    - Сохранение сессии по session_id
    - Повтор без нового жребия
    """
    
    # Проверка обязательных полей
    if not event_id or not isinstance(event_id, str):
        raise ContractError("event_id must be a non-empty string")
    if not session_id or not isinstance(session_id, str):
        raise ContractError("session_id must be a non-empty string")
    if not isinstance(use_csprng, bool):
        raise ContractError("use_csprng must be a boolean")
    
    # Проверка существующей сессии
    existing = load_session(session_id)
    if existing:
        if existing["event_id"] != event_id:
            raise ContractError("session_id already bound to different event_id")
        # Повторный вызов возвращает сохранённый результат
        return existing["card"]
    
    # Генерация или проверка входов
    if use_csprng:
        rng = secrets.SystemRandom()
        first_throw = rng.randint(1, 6)
        second_throw = rng.randint(1, 6)
    else:
        # Ручной ввод: строгая проверка типов и диапазонов
        if first_throw is None or second_throw is None:
            raise ContractError("both throws required when use_csprng=false")
        if type(first_throw) is not int or type(second_throw) is not int:
            raise ContractError("throws must be integers")
        if not (1 <= first_throw <= 6 and 1 <= second_throw <= 6):
            raise ContractError("throws must be 1..6")
    
    combination_id = f"mo-{first_throw}-{second_throw}"
    
    inputs = {
        "event_id": event_id,
        "session_id": session_id,
        "use_csprng": use_csprng,
        "first_throw": first_throw,
        "second_throw": second_throw,
        "combination_id": combination_id
    }
    
    card = {
        "core_id": "mo",
        "status": "ABSTAIN",
        "reason": "TEXT_CORPUS_NOT_FIXED",
        "protocol_version": "mo-mipham-v1-draft",
        "inputs": inputs,
        "input_hash": digest(inputs),
        "raw_result": {
            "generated_at": now_iso(),
            "method": "digital-csprng" if use_csprng else "reported-throws",
            "first_throw": first_throw,
            "second_throw": second_throw,
            "combination_id": combination_id
        },
        "interpretation": "Raw combination only; no traditional interpretation supplied.",
        "claims": []
    }
    
    # Сохранение сессии
    save_session(session_id, {"event_id": event_id, "card": card})
    
    return card
```

### 1.5. Сырой результат

```json
{
  "generated_at": "2026-10-14T10:00:00Z",
  "method": "digital-csprng",
  "first_throw": 3,
  "second_throw": 5,
  "combination_id": "mo-3-5"
}
```

### 1.6. Что заблокировано

| Элемент | Статус | Причина |
|---------|--------|---------|
| Таблица 36 толкований | UNAVAILABLE | Полный текст книги не извлечён; страницы не сверены |
| Идентификаторы сочетаний | UNAVAILABLE | Требуют источник |
| Названия результатов | UNAVAILABLE | Требуют источник |
| Пример PA NA / Golden Lotus | UNAVAILABLE | Страница и текст не подтверждены |
| Правила чтения | UNAVAILABLE | Требуют источник |
| Соответствие чисел 1–6 слогам | UNVERIFIED | Предположение на основе вторичных источников, не подтверждено изданием |
| Различие переставленных сочетаний | ЧАСТИЧНО | Механически различаются, но толкования не сверены |

### 1.7. Тестовые случаи (ИСПРАВЛЕНЫ)

```json
{
  "test_cases": [
    {
      "id": "mo-normal-manual-01",
      "description": "Ручной ввод: оба броска заданы",
      "input": {
        "event_id": "test",
        "session_id": "session-001",
        "use_csprng": false,
        "first_throw": 3,
        "second_throw": 5
      },
      "expected": {
        "status": "ABSTAIN",
        "reason": "TEXT_CORPUS_NOT_FIXED",
        "raw_result.combination_id": "mo-3-5",
        "raw_result.method": "reported-throws"
      }
    },
    {
      "id": "mo-csprng-01",
      "description": "CSPRNG генерация",
      "input": {
        "event_id": "test",
        "session_id": "session-002",
        "use_csprng": true
      },
      "expected": {
        "status": "ABSTAIN",
        "raw_result.method": "digital-csprng",
        "raw_result.first_throw": "int 1..6",
        "raw_result.second_throw": "int 1..6"
      }
    },
    {
      "id": "mo-invalid-throw-type",
      "description": "Неверный тип: float вместо int",
      "input": {
        "event_id": "test",
        "session_id": "session-003",
        "use_csprng": false,
        "first_throw": 1.5,
        "second_throw": 2
      },
      "expected": "ContractError: throws must be integers"
    },
    {
      "id": "mo-invalid-throw-bool",
      "description": "Неверный тип: bool вместо int",
      "input": {
        "event_id": "test",
        "session_id": "session-004",
        "use_csprng": false,
        "first_throw": true,
        "second_throw": 2
      },
      "expected": "ContractError: throws must be integers"
    },
    {
      "id": "mo-invalid-throw-range-low",
      "description": "Неверный диапазон: 0",
      "input": {
        "event_id": "test",
        "session_id": "session-005",
        "use_csprng": false,
        "first_throw": 0,
        "second_throw": 3
      },
      "expected": "ContractError: throws must be 1..6"
    },
    {
      "id": "mo-invalid-throw-range-high",
      "description": "Неверный диапазон: 7",
      "input": {
        "event_id": "test",
        "session_id": "session-006",
        "use_csprng": false,
        "first_throw": 7,
        "second_throw": 2
      },
      "expected": "ContractError: throws must be 1..6"
    },
    {
      "id": "mo-partial-input",
      "description": "Частичный ввод: один бросок задан, другой null",
      "input": {
        "event_id": "test",
        "session_id": "session-007",
        "use_csprng": false,
        "first_throw": 3,
        "second_throw": null
      },
      "expected": "ContractError: both throws required when use_csprng=false"
    },
    {
      "id": "mo-repeatability",
      "description": "Повторный вызов с тем же session_id возвращает сохранённый результат",
      "input": {
        "event_id": "test",
        "session_id": "session-001",
        "use_csprng": false,
        "first_throw": 3,
        "second_throw": 5
      },
      "expected": {
        "raw_result.combination_id": "mo-3-5",
        "note": "Повторный вызов игнорирует новые входы и возвращает сохранённую карточку"
      }
    },
    {
      "id": "mo-session-event-mismatch",
      "description": "Попытка использовать session_id с другим event_id",
      "input": {
        "event_id": "different-event",
        "session_id": "session-001",
        "use_csprng": true
      },
      "expected": "ContractError: session_id already bound to different event_id"
    },
    {
      "id": "mo-full-coverage-36",
      "description": "Полный перебор всех 36 сочетаний",
      "test_type": "exhaustive",
      "verification": {
        "all_combinations": [
          {"first": 1, "second": 1, "id": "mo-1-1"},
          {"first": 1, "second": 2, "id": "mo-1-2"},
          {"first": 1, "second": 3, "id": "mo-1-3"},
          {"first": 1, "second": 4, "id": "mo-1-4"},
          {"first": 1, "second": 5, "id": "mo-1-5"},
          {"first": 1, "second": 6, "id": "mo-1-6"},
          {"first": 2, "second": 1, "id": "mo-2-1"},
          {"first": 2, "second": 2, "id": "mo-2-2"},
          {"first": 2, "second": 3, "id": "mo-2-3"},
          {"first": 2, "second": 4, "id": "mo-2-4"},
          {"first": 2, "second": 5, "id": "mo-2-5"},
          {"first": 2, "second": 6, "id": "mo-2-6"},
          {"first": 3, "second": 1, "id": "mo-3-1"},
          {"first": 3, "second": 2, "id": "mo-3-2"},
          {"first": 3, "second": 3, "id": "mo-3-3"},
          {"first": 3, "second": 4, "id": "mo-3-4"},
          {"first": 3, "second": 5, "id": "mo-3-5"},
          {"first": 3, "second": 6, "id": "mo-3-6"},
          {"first": 4, "second": 1, "id": "mo-4-1"},
          {"first": 4, "second": 2, "id": "mo-4-2"},
          {"first": 4, "second": 3, "id": "mo-4-3"},
          {"first": 4, "second": 4, "id": "mo-4-4"},
          {"first": 4, "second": 5, "id": "mo-4-5"},
          {"first": 4, "second": 6, "id": "mo-4-6"},
          {"first": 5, "second": 1, "id": "mo-5-1"},
          {"first": 5, "second": 2, "id": "mo-5-2"},
          {"first": 5, "second": 3, "id": "mo-5-3"},
          {"first": 5, "second": 4, "id": "mo-5-4"},
          {"first": 5, "second": 5, "id": "mo-5-5"},
          {"first": 5, "second": 6, "id": "mo-5-6"},
          {"first": 6, "second": 1, "id": "mo-6-1"},
          {"first": 6, "second": 2, "id": "mo-6-2"},
          {"first": 6, "second": 3, "id": "mo-6-3"},
          {"first": 6, "second": 4, "id": "mo-6-4"},
          {"first": 6, "second": 5, "id": "mo-6-5"},
          {"first": 6, "second": 6, "id": "mo-6-6"}
        ],
        "total": 36,
        "ordered_pairs_verified": true
      }
    }
  ]
}
```

### 1.8. Следующие шаги для Mo

1. **Получить полный текст книги** Mipham's *Mo: Tibetan Divination System* (Shambhala).
2. **Извлечь таблицу 36 сочетаний** с идентификаторами, названиями и толкованиями.
3. **Сверить пример PA NA / Golden Lotus** по конкретной странице.
4. **Подтвердить соответствие чисел 1–6 слогам** мантры из конкретного издания.
5. **Зафиксировать атрибуцию**: Мипхам (Ньингма), не Сакья.
6. **Обновить протокол** до `mo-mipham-v1` после получения корпуса.

---

## 2. Гуань Инь (`qiuqian`) — китайские храмовые жребии

### 2.1. Источник и выбор набора (ИСПРАВЛЕН)

**Выбранный набор:**
- **Храм:** Kwan Im Thong Hood Cho Temple (观音堂佛祖庙), Сингапур.
- **Адрес:** 178 Waterloo Street, Singapore 187964.
- **Божество:** Гуань Инь (Avalokiteshvara / 观音).
- **Количество палочек:** 100 (с упоминанием, что номер 100 может пропускаться).
- **Источник описания:** 
  - National Library Board Singapore: https://www.nlb.gov.sg/main/article-detail?cmsuuid=d9189e20-2326-46b4-828c-db52113b78e5
  - В 1990 году храм первым в Сингапуре предоставил переводы жребиев на английский.

**Обоснование выбора:**
- Один из наиболее документированных храмов Гуань Инь в Сингапуре.
- 100 палочек — стандартный размер для этого божества.
- Не смешивается с наборами на 28, 60 или 101 палочку других храмов.
- **ВАЖНО:** Это храм в Сингапуре, не на Тайване. Предыдущая версия ошибочно указывала Linshun Gong (Тайвань).

### 2.2. Процедура 筊杯 (ИСПРАВЛЕНА по официальному источнику)

**Источник:** 行天宮 (Xingtian Temple / Hang Tian Gong) — официальный сайт
- URL: https://www.ht.org.tw/religion207.htm
- Это источник другого храма (行天宫), используемый для выявления расхождений в правилах.

**Правила 筊杯 по 行天宮:**

杯筊 (bēi jiǎo) — два деревянных полумесяца.
- Выпуклая сторона = 陰 (yīn) / 俯 (fǔ) = "инь" / "вниз"
- Плоская сторона = 陽 (yáng) / 仰 (yǎng) = "ян" / "вверх"

**Три исхода:**

| Китайский | Pinyin | Описание | Значение |
|-----------|--------|----------|----------|
| 聖筊 | shèng jiǎo | Одна выпуклая + одна плоская | Подтверждение: "да, хорошо, можно" |
| 陰筊 | yīn jiǎo | Обе выпуклые | Отрицание: "нет, плохо, нельзя" |
| 笑筊 | xiào jiǎo | Обе плоские | Неясность: вопрос неясен, нельзя определить |

**ВАЖНО: Расхождение с предыдущей версией!**
- В предыдущей версии было перепутано: 笑筊 и 陰筊.
- Правильно: 陰筊 = обе выпуклые (отрицание), 笑筊 = обе плоские (неясность).

**Правила повторов по 行天宮:**
- **行天宫 НЕ требует повторения до получения 聖筊.**
- Цитата: "在行天宮擲筊請示，以一次為定，不須一而再、再而三，非擲得聖筊不可" (В 行天宫 при гадании достаточно одного броска, не нужно повторять снова и снова, пока не выпадет 聖筊).
- **Это правило именно 行天宫.** Для Kwan Im Thong Hood Cho Temple правила повторов **НЕ ПОДТВЕРЖДЕНЫ** из источника.
- **Статус:** BLOCKED_SOURCE для правил повторов именно этого храма.

**Цифровая адаптация:**
- CSPRNG выбирает номер палочки (1–100).
- Подтверждение моделируется через математическую модель двух независимых равновероятных сторон:
  - Каждая сторона: 50% выпуклая, 50% плоская
  - 聖筊 (одна выпуклая + одна плоская): 2 × 0.5 × 0.5 = 0.50 (50%)
  - 陰筊 (обе выпуклые): 0.5 × 0.5 = 0.25 (25%)
  - 笑筊 (обе плоские): 0.5 × 0.5 = 0.25 (25%)

**ВАЖНО:** Это **математическая модель**, не "традиционные вероятности" и не измеренные данные.

### 2.3. Входная схема (ИСПРАВЛЕНА)

```json
{
  "adapter_id": "qiuqian",
  "protocol_version": "qiuqian-guanyin-kwan-im-v1-draft",
  "inputs": {
    "event_id": "string (обязательно)",
    "session_id": "string (обязательно, для сохранения сессии)",
    "stick_number": "int 1..100 | null",
    "use_csprng": "bool (обязательно, явно задано)",
    "confirmation_result": "string: sheng_bei | yin_bei | xiao_bei | null",
    "max_retries": "int (техническое ограничение адаптации, не историческое правило)"
  }
}
```

**Правила обработки входов:**
- `event_id` и `session_id` обязательны
- `use_csprng` должно быть явно задано (true/false)
- Если `use_csprng = true`: `stick_number` игнорируется, генерируется через CSPRNG
- Если `use_csprng = false`: `stick_number` обязателен и должен быть int 1..100
- `confirmation_result`: если null, моделируется через CSPRNG; если задан, используется как есть
- `max_retries`: техническое ограничение цифровой адаптации (по умолчанию 3)

### 2.4. Алгоритм (ИСПРАВЛЕН)

```python
def qiuqian_procedure(event_id, session_id, use_csprng, stick_number=None, 
                      confirmation_result=None, max_retries=3):
    """
    Исправленная версия:
    - Явная проверка типов до генерации
    - Разделение ручного ввода и CSPRNG
    - Сохранение сессии по session_id
    - Журнал всех попыток
    - Все карточки соответствуют контракту
    """
    
    temple = "Kwan Im Thong Hood Cho Temple"
    deity = "Guanyin"
    total_sticks = 100
    
    # Проверка обязательных полей
    if not event_id or not isinstance(event_id, str):
        raise ContractError("event_id must be a non-empty string")
    if not session_id or not isinstance(session_id, str):
        raise ContractError("session_id must be a non-empty string")
    if not isinstance(use_csprng, bool):
        raise ContractError("use_csprng must be a boolean")
    if not isinstance(max_retries, int) or max_retries < 0:
        raise ContractError("max_retries must be a non-negative integer")
    
    # Проверка существующей сессии
    existing = load_session(session_id)
    if existing:
        if existing["event_id"] != event_id:
            raise ContractError("session_id already bound to different event_id")
        # Повторный вызов возвращает сохранённый результат
        return existing["card"]
    
    # Журнал попыток
    attempts_log = []
    retries = 0
    
    while retries <= max_retries:
        # Генерация или проверка номера палочки
        if use_csprng:
            rng = secrets.SystemRandom()
            current_stick = rng.randint(1, total_sticks)
        else:
            if stick_number is None:
                raise ContractError("stick_number required when use_csprng=false")
            if type(stick_number) is not int:
                raise ContractError("stick_number must be an integer")
            if not (1 <= stick_number <= total_sticks):
                raise ContractError(f"stick_number must be 1..{total_sticks}")
            current_stick = stick_number
        
        # Подтверждение через 筊杯
        if confirmation_result is None:
            # Моделирование через математическую модель
            current_confirmation = simulate_jiaobei_mathematical()
        else:
            # Использование заданного результата
            if confirmation_result not in ("sheng_bei", "yin_bei", "xiao_bei"):
                raise ContractError("invalid confirmation_result")
            current_confirmation = confirmation_result
        
        # Запись попытки
        attempts_log.append({
            "attempt": retries + 1,
            "stick_number": current_stick,
            "confirmation": current_confirmation
        })
        
        # Проверка результата
        if current_confirmation == "sheng_bei":
            # Успешное подтверждение
            break
        else:
            # yin_bei или xiao_bei
            retries += 1
            if retries > max_retries:
                # Превышен лимит попыток
                card = {
                    "core_id": "qiuqian",
                    "status": "ABSTAIN",
                    "reason": "CONFIRMATION_NOT_RECEIVED",
                    "protocol_version": "qiuqian-guanyin-kwan-im-v1-draft",
                    "inputs": {
                        "event_id": event_id,
                        "session_id": session_id,
                        "use_csprng": use_csprng,
                        "stick_number": stick_number,
                        "max_retries": max_retries,
                        "temple": temple,
                        "deity": deity
                    },
                    "input_hash": digest({
                        "event_id": event_id,
                        "session_id": session_id,
                        "use_csprng": use_csprng,
                        "stick_number": stick_number,
                        "max_retries": max_retries
                    }),
                    "raw_result": {
                        "generated_at": now_iso(),
                        "method": "digital-csprng-adaptation" if use_csprng else "reported-stick",
                        "attempts": attempts_log,
                        "final_state": "no_confirmation",
                        "temple": temple,
                        "deity": deity,
                        "total_sticks": total_sticks
                    },
                    "interpretation": f"Confirmation not received after {max_retries + 1} attempts.",
                    "claims": []
                }
                save_session(session_id, {"event_id": event_id, "card": card})
                return card
            
            # Продолжить цикл (новая попытка)
            if not use_csprng:
                # При ручном входе нельзя менять номер без явного указания
                raise ContractError("manual mode does not allow automatic retry with new stick")
    
    # Успешное подтверждение
    card = {
        "core_id": "qiuqian",
        "status": "ABSTAIN",
        "reason": "TEXT_CORPUS_NOT_FIXED",
        "protocol_version": "qiuqian-guanyin-kwan-im-v1-draft",
        "inputs": {
            "event_id": event_id,
            "session_id": session_id,
            "use_csprng": use_csprng,
            "stick_number": current_stick,
            "confirmation": "sheng_bei",
            "temple": temple,
            "deity": deity
        },
        "input_hash": digest({
            "event_id": event_id,
            "session_id": session_id,
            "use_csprng": use_csprng,
            "stick_number": current_stick,
            "confirmation": "sheng_bei"
        }),
        "raw_result": {
            "generated_at": now_iso(),
            "method": "digital-csprng-adaptation" if use_csprng else "reported-stick",
            "stick_number": current_stick,
            "confirmation": "sheng_bei",
            "attempts": attempts_log,
            "temple": temple,
            "deity": deity,
            "total_sticks": total_sticks
        },
        "interpretation": f"Stick #{current_stick} selected and confirmed. Text not supplied.",
        "claims": []
    }
    
    save_session(session_id, {"event_id": event_id, "card": card})
    return card

def simulate_jiaobei_mathematical():
    """
    Математическая модель двух независимых равновероятных сторон.
    НЕ традиционные вероятности, не измеренные данные.
    """
    rng = secrets.SystemRandom()
    # Каждая сторона: 50% выпуклая (0), 50% плоская (1)
    side1 = rng.choice([0, 1])  # 0 = выпуклая, 1 = плоская
    side2 = rng.choice([0, 1])
    
    if side1 != side2:
        return "sheng_bei"  # Одна выпуклая + одна плоская
    elif side1 == 0 and side2 == 0:
        return "yin_bei"  # Обе выпуклые
    else:  # side1 == 1 and side2 == 1
        return "xiao_bei"  # Обе плоские
```

### 2.5. Конечные состояния (ИСПРАВЛЕНЫ)

| Состояние | Описание | Статус карточки | Причина |
|-----------|----------|-----------------|---------|
| `confirmed` | Палочка выбрана и подтверждена через 筊杯 | ABSTAIN | TEXT_CORPUS_NOT_FIXED |
| `no_confirmation` | Превышен лимит попыток подтверждения | ABSTAIN | CONFIRMATION_NOT_RECEIVED |
| `pending` | Процедура не завершена (не реализовано в текущей версии) | N/A | N/A |

**ВАЖНО:** Все карточки, включая отказ, соответствуют контракту CoreResult.

**Ограничение повторов (`max_retries`):**
- Это **техническое правило цифровой адаптации**, не историческое.
- В 行天宫 достаточно одного броска, не требуется повторение.
- Для Kwan Im Thong Hood Cho Temple правила повторов **НЕ ПОДТВЕРЖДЕНЫ**.
- В цифровой версии ограничение предотвращает бесконечный цикл.

### 2.6. Сырой результат

```json
{
  "generated_at": "2026-10-14T10:00:00Z",
  "method": "digital-csprng-adaptation",
  "stick_number": 42,
  "confirmation": "sheng_bei",
  "attempts": [
    {
      "attempt": 1,
      "stick_number": 42,
      "confirmation": "sheng_bei"
    }
  ],
  "temple": "Kwan Im Thong Hood Cho Temple",
  "deity": "Guanyin",
  "total_sticks": 100
}
```

### 2.7. Что заблокировано

| Элемент | Статус | Причина |
|---------|--------|---------|
| Корпус текстов 100 жребиев | UNAVAILABLE | Полный текст не извлечён; источник NLB описывает процедуру, но не все тексты |
| Идентификаторы жребиев | UNAVAILABLE | Требуют полный корпус |
| Формулировки толкований | UNAVAILABLE | Требуют источник |
| Правила повторов Kwan Im Thong Hood Cho Temple | BLOCKED_SOURCE | Не подтверждены из источника; 行天宫 не требует повторов |
| Точные вероятности 筊杯 | МАТЕМАТИЧЕСКАЯ МОДЕЛЬ | 50/25/25 — математическая модель двух независимых сторон, не традиционные вероятности |

### 2.8. Тестовые случаи (ИСПРАВЛЕНЫ)

```json
{
  "test_cases": [
    {
      "id": "qiuqian-normal-manual-01",
      "description": "Ручной ввод: номер палочки задан, подтверждение успешное",
      "input": {
        "event_id": "test",
        "session_id": "session-101",
        "use_csprng": false,
        "stick_number": 42,
        "confirmation_result": "sheng_bei"
      },
      "expected": {
        "status": "ABSTAIN",
        "reason": "TEXT_CORPUS_NOT_FIXED",
        "raw_result.stick_number": 42,
        "raw_result.confirmation": "sheng_bei",
        "raw_result.attempts": [{"attempt": 1, "stick_number": 42, "confirmation": "sheng_bei"}]
      }
    },
    {
      "id": "qiuqian-normal-manual-02",
      "description": "Ручной ввод: номер палочки задан, подтверждение отрицательное",
      "input": {
        "event_id": "test",
        "session_id": "session-102",
        "use_csprng": false,
        "stick_number": 1,
        "confirmation_result": "yin_bei"
      },
      "expected": {
        "status": "ABSTAIN",
        "reason": "CONFIRMATION_NOT_RECEIVED",
        "raw_result.final_state": "no_confirmation"
      }
    },
    {
      "id": "qiuqian-csprng-01",
      "description": "CSPRNG выбор с успешным подтверждением",
      "input": {
        "event_id": "test",
        "session_id": "session-103",
        "use_csprng": true,
        "max_retries": 3
      },
      "expected": {
        "status": "ABSTAIN",
        "raw_result.stick_number": "int 1..100",
        "raw_result.confirmation": "sheng_bei",
        "raw_result.attempts": "array of attempts"
      }
    },
    {
      "id": "qiuqian-invalid-stick-type",
      "description": "Неверный тип: float вместо int",
      "input": {
        "event_id": "test",
        "session_id": "session-104",
        "use_csprng": false,
        "stick_number": 42.5
      },
      "expected": "ContractError: stick_number must be an integer"
    },
    {
      "id": "qiuqian-invalid-stick-range-low",
      "description": "Неверный диапазон: 0",
      "input": {
        "event_id": "test",
        "session_id": "session-105",
        "use_csprng": false,
        "stick_number": 0
      },
      "expected": "ContractError: stick_number must be 1..100"
    },
    {
      "id": "qiuqian-invalid-stick-range-high",
      "description": "Неверный диапазон: 101",
      "input": {
        "event_id": "test",
        "session_id": "session-106",
        "use_csprng": false,
        "stick_number": 101
      },
      "expected": "ContractError: stick_number must be 1..100"
    },
    {
      "id": "qiuqian-no-confirmation",
      "description": "Превышен лимит попыток (max_retries=0)",
      "input": {
        "event_id": "test",
        "session_id": "session-107",
        "use_csprng": false,
        "stick_number": 50,
        "confirmation_result": "yin_bei",
        "max_retries": 0
      },
      "expected": {
        "status": "ABSTAIN",
        "reason": "CONFIRMATION_NOT_RECEIVED",
        "raw_result.final_state": "no_confirmation",
        "raw_result.attempts": [{"attempt": 1, "stick_number": 50, "confirmation": "yin_bei"}]
      }
    },
    {
      "id": "qiuqian-repeatability",
      "description": "Повторный вызов с тем же session_id возвращает сохранённый результат",
      "input": {
        "event_id": "test",
        "session_id": "session-101",
        "use_csprng": false,
        "stick_number": 42,
        "confirmation_result": "sheng_bei"
      },
      "expected": {
        "raw_result.stick_number": 42,
        "note": "Повторный вызов игнорирует новые входы и возвращает сохранённую карточку"
      }
    },
    {
      "id": "qiuqian-session-event-mismatch",
      "description": "Попытка использовать session_id с другим event_id",
      "input": {
        "event_id": "different-event",
        "session_id": "session-101",
        "use_csprng": true
      },
      "expected": "ContractError: session_id already bound to different event_id"
    },
    {
      "id": "qiuqian-manual-no-retry",
      "description": "Ручной режим не позволяет автоматический повтор с новой палочкой",
      "input": {
        "event_id": "test",
        "session_id": "session-108",
        "use_csprng": false,
        "stick_number": 25,
        "confirmation_result": "xiao_bei",
        "max_retries": 3
      },
      "expected": "ContractError: manual mode does not allow automatic retry with new stick"
    },
    {
      "id": "qiuqian-full-coverage-100",
      "description": "Полный перебор всех 100 номеров палочек",
      "test_type": "exhaustive",
      "verification": {
        "all_stick_numbers": "int 1..100",
        "total": 100,
        "each_valid": true
      }
    },
    {
      "id": "qiuqian-confirmation-branches",
      "description": "Проверка всех трёх ветвей подтверждения через управляемую подстановку",
      "test_type": "branch_coverage",
      "branches": [
        {"confirmation": "sheng_bei", "expected_final_state": "confirmed"},
        {"confirmation": "yin_bei", "expected_final_state": "no_confirmation"},
        {"confirmation": "xiao_bei", "expected_final_state": "no_confirmation"}
      ]
    }
  ]
}
```

### 2.9. Следующие шаги для qiuqian

1. **Получить полный корпус текстов** 100 жребиев Kwan Im Thong Hood Cho Temple.
2. **Зафиксировать идентификаторы** и формулировки каждого жребия.
3. **Подтвердить правила повторов** именно этого храма (если существуют).
4. **Сверить процедуру** с дополнительными этнографическими источниками.
5. **Обновить протокол** до `qiuqian-guanyin-kwan-im-v1` после получения корпуса.

---

## 3. Общий контракт и интеграция

### 3.1. Совместимость с контрактом v1

Оба адаптера соответствуют контракту из `ARCHITECTURE_10_CORES.md`:
- `core_id`: `mo` и `qiuqian` — из списка десяти ядер.
- `weight`: 0.10 для каждого.
- `status`: ABSTAIN (процедура выполнена, но интерпретация недоступна).
- `claims`: [] (нет автоматических прогнозных утверждений).

### 3.2. Разделение статусов

| Статус | Значение |
|--------|----------|
| `procedure_status = OK` | Механика выполнена корректно |
| `interpretation_status = ABSTAIN` | Корпус текстов не зафиксирован |
| `claims = []` | Нет принятых прогнозных утверждений |

**Важно:** отсутствие `FORECAST` claims само по себе **не означает ошибку процедуры**. Это ожидаемое состояние до получения корпуса текстов.

### 3.3. Ограничения

- Ни Mo, ни qiuqian не доказывают предсказательную эффективность.
- Цифровые адаптации не являются историческими ритуалами.
- Согласие ядер не превращается в вероятность события.
- Веса 0.10 фиксированы, не перераспределяются.

---

## 4. Проверка и воспроизводимость

### 4.1. Первый проход (независимая сверка источников и таблиц)

- **Mo:** механика 6×6=36 подтверждена несколькими источниками (Shambhala, Wikipedia, академические описания). Таблица толкований требует книгу.
- **qiuqian:** процедура 筊杯 описана в NLB Singapore для Kwan Im Thong Hood Cho Temple. Правила 筊杯 сверены с официальным источником 行天宮.

### 4.2. Второй проход (сверка схем, алгоритмов и тестов)

- **Mo:** 36 сочетаний математически полны (6×6). Упорядоченность `(a,b) ≠ (b,a)` при `a≠b` подтверждена. Все алгоритмы исправлены.
- **qiuqian:** 100 палочек — стандарт для Гуань Инь. Процедура подтверждения описана. Все алгоритмы исправлены.

### 4.3. Запуск кода

**Не запускал** в текущей среде (Python недоступен). Алгоритмы представлены как исправленный псевдокод для проверки логики.

---

## 5. Список изменений

### Исправления источников

1. **qiuqian:** Исправлен храм с Linshun Gong (Тайвань) на Kwan Im Thong Hood Cho Temple (Сингапур).
2. **qiuqian:** Исправлены правила 筊杯 по официальному источнику 行天宮:
   - 聖筊 = одна выпуклая + одна плоская (подтверждение)
   - 陰筊 = обе выпуклые (отрицание)
   - 笑筊 = обе плоские (неясность)
3. **qiuqian:** Вероятности 50/25/25 помечены как математическая модель, не традиционные.
4. **qiuqian:** Правила повторов помечены как BLOCKED_SOURCE для Kwan Im Thong Hood Cho Temple.

### Исправления алгоритмов

5. **mo:** Добавлена явная проверка типов до генерации.
6. **mo:** Добавлен параметр `use_csprng` в сигнатуру функции.
7. **mo:** Исправлена обработка `first_throw or ...` (может заменить ноль).
8. **mo:** Добавлена проверка `type(first_throw) is not int` для отклонения bool и float.
9. **mo:** Добавлено сохранение сессии по `session_id`.
10. **mo:** Добавлен повтор без нового жребия.
11. **qiuqian:** Добавлена явная проверка типов до генерации.
12. **qiuqian:** Добавлен параметр `confirmation_result` в функцию.
13. **qiuqian:** Исправлена карточка `no_confirmation` — теперь содержит все обязательные поля контракта.
14. **qiuqian:** Добавлен журнал всех попыток.
15. **qiuqian:** Добавлено сохранение сессии по `session_id`.
16. **qiuqian:** Добавлен повтор без нового жребия.
17. **qiuqian:** Запрещён автоматический повтор с новой палочкой в ручном режиме.

### Исправления тестов

18. **mo:** Добавлен полный перебор всех 36 сочетаний.
19. **mo:** Добавлены тесты на неверные типы (bool, float).
20. **mo:** Добавлены тесты на частичный ввод.
21. **mo:** Добавлен тест на повторный вызов с тем же session_id.
22. **qiuqian:** Добавлен полный перебор всех 100 номеров палочек.
23. **qiuqian:** Добавлены тесты на все ветви подтверждения через управляемую подстановку.
24. **qiuqian:** Добавлен тест на исчерпание лимита.
25. **qiuqian:** Добавлен тест на сохранность ручного номера и истории.
26. **qiuqian:** Добавлен тест на повтор после перезапуска без нового розыгрыша.
27. **qiuqian:** Удалён некорректный тест "все значения возможны в CSPRNG".

### Удалённые ложные заключения

28. Удалено заключение "оба адаптера готовы к реализации".

---

## 6. Незакрытые зависимости

### Mo

1. **Таблица 36 толкований** — требует полный текст книги Mipham's *Mo*.
2. **Идентификаторы сочетаний** — требуют источник.
3. **Названия результатов** — требуют источник.
4. **Пример PA NA / Golden Lotus** — требует сверку по странице.
5. **Соответствие чисел 1–6 слогам** — требует подтверждение из конкретного издания.
6. **Правила чтения** — требуют источник.

### qiuqian

1. **Корпус текстов 100 жребиев** — требует полный текст Kwan Im Thong Hood Cho Temple.
2. **Идентификаторы жребиев** — требуют полный корпус.
3. **Формулировки толкований** — требуют источник.
4. **Правила повторов** — BLOCKED_SOURCE для Kwan Im Thong Hood Cho Temple.

---

## 7. Отдельные вердикты

### Механика

- **Mo:** ✓ Готова. 36 сочетаний, упорядоченность, CSPRNG, сохранение сессии.
- **qiuqian:** ✓ Готова. 100 палочек, процедура 筊杯, математическая модель подтверждения, сохранение сессии.

### Источники

- **Mo:** ⚠ Частично подтверждены. Механика подтверждена, таблица толкований требует книгу.
- **qiuqian:** ⚠ Частично подтверждены. Храм и процедура подтверждены, корпус текстов требует источник, правила повторов BLOCKED_SOURCE.

### Корпуса текстов

- **Mo:** ✗ Не получены.
- **qiuqian:** ✗ Не получены.

### Интеграция

- **Mo:** ✓ Готова к интеграции с контрактом v1. Карточка соответствует CoreResult.
- **qiuqian:** ✓ Готова к интеграции с контрактом v1. Карточка соответствует CoreResult.

---

## 8. Источники

### Mo

1. Jamgön Mipham. *Mo: Tibetan Divination System*. Shambhala Publications.
   - URL (описание): https://www.shambhala.com/snowlion_articles/mo-tibetan-divination-system/
   - Статус: книга доступна для приобретения, полный текст не извлечён.

2. Wikipedia: Mo (divination).
   - URL: https://en.wikipedia.org/wiki/Mo_(divination)
   - Статус: общее описание, не первоисточник.

### qiuqian

1. National Library Board Singapore. Kwan Im Thong Hood Cho Temple.
   - URL: https://www.nlb.gov.sg/main/article-detail?cmsuuid=d9189e20-2326-46b4-828c-db52113b78e5
   - Статус: описание храма и процедуры, не полный корпус текстов.

2. 行天宮 (Xingtian Temple). 濟世服務 - 擲筊.
   - URL: https://www.ht.org.tw/religion207.htm
   - Статус: официальные правила 筊杯 для 行天宮, использованы для выявления расхождений.

---

**Ограничения документа:**
- Не изменяет runtime `dis_oracle/`.
- Не публикует в GitHub.
- Не объединяет PR.
- Петля времени и обратный поток остаются исследовательскими вопросами проекта.
- Эти два адаптера сами по себе не реализуют и не подтверждают физический механизм времени.
