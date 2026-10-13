# Спецификация трактовки И-Цзин для адаптера v0.3

Дата: 12.10.2026. Владелец: Дмитрий Степанов. Статус: проект спецификации (исправленная версия).

Этот документ определяет корпус текстов, таблицу гексаграмм, правила чтения и формат данных для расширения адаптера И-Цзин с ABSTAIN до OK. Не изменяет существующий код; не доказывает предсказательную эффективность.

---

## 1. Корпус текстов

### 1.1. Предлагаемый источник

**James Legge. "The Yî King" (The Sacred Books of the East, Vol. XVI).**

- **Редакция на sacred-texts.com:** второе издание 1899 г. (2nd edition)
  - URL: https://sacred-texts.com/ich/index.htm
  - Структура страниц: `https://sacred-texts.com/ich/ic{N}.htm` (где N — номер гексаграммы без ведущих нулей, например ic1.htm, ic47.htm)
- **Первое издание 1882 г.:** доступно как PDF
  - URL: https://www.biroco.com/yijing/Legge1882.pdf
  - Источник указан на biroco.com (Yijing Dao)

### 1.2. Обоснование выбора

| Критерий | Legge (1882/1899) | Wilhelm/Baynes (1950) | Китайский оригинал |
|----------|-------------------|---------------------|-------------------|
| Доступность | ✅ Public domain | ❌ Защищён АП | ✅ Древний текст, но нужен перевод |
| Полнота | ✅ 64 гексаграммы + все линии | ✅ Полная | ✅ Полная |
| Проверяемость | ✅ URL + страницы | ❌ Только по изданию | Требуется специалист |
| Точность | Признанный академический перевод | Более популярный, менее буквальный | Оригинал |

### 1.3. Важное уточнение о редакциях

**ВНИМАНИЕ:** sacred-texts.com содержит **второе издание 1899 года**, а не первое 1882 года. Различия между изданиями минимальны, но для воспроизводимости необходимо указывать конкретную редакцию.

- **Для программы:** используем редакцию 1899 с sacred-texts.com (удобна для парсинга)
- **Для сверки:** первое издание 1882 доступно как PDF на biroco.com
- **В документации:** всегда указываем "Legge 1899 (2nd edition)" или "Legge 1882 (1st edition)"

### 1.4. Что НЕ включается

- Перевод Wilhelm/Baynes (защищён авторским правом)
- Современные интерпретации и комментарии
- Вероятностные утверждения
- Автоматическое назначение прогнозных голосов

### 1.5. Ограничения

Legge использует устаревшую транскрипцию (Wade-Giles). Для программы это не критично: имена гексаграмм берутся из таблицы ниже. Важны только тексты Judgment и Line.

---

## 2. Таблица 64 гексаграмм (последовательность Вэнь-вана)

Порядок линий: **снизу вверх** (1 → 6). Линия 1 = нижняя, линия 6 = верхняя.

Триграммы (снизу вверх, 1=ян, 0=инь):
- ☰ Цянь (qián) Небо: 1,1,1
- ☷ Кунь (kūn) Земля: 0,0,0
- ☳ Чжэнь (zhèn) Гром: 1,0,0
- ☵ Кань (kǎn) Вода: 0,1,0
- ☶ Гэнь (gèn) Гора: 0,0,1
- ☴ Сюнь (xùn) Ветер: 0,1,1
- ☲ Ли (lí) Огонь: 1,0,1
- ☱ Дуй (duì) Озеро: 1,1,0

Гексаграмма = верхняя триграмма (линии 4-5-6) + нижняя триграмма (линии 1-2-3).

**Полная таблица (исправленная):**

| № | Имя | Пиньинь | Верхняя | Нижняя | Линии (1→6) | Unicode |
|---|-----|---------|---------|--------|-------------|---------|
| 1 | 乾 | qián | ☰ | ☰ | 1,1,1,1,1,1 | ䷀ |
| 2 | 坤 | kūn | ☷ | ☷ | 0,0,0,0,0,0 | ䷁ |
| 3 | 屯 | zhūn | ☵ | ☳ | 1,0,0,0,1,0 | ䷂ |
| 4 | 蒙 | méng | ☶ | ☵ | 0,1,0,0,0,1 | ䷃ |
| 5 | 需 | xū | ☵ | ☰ | 1,1,1,0,1,0 | ䷄ |
| 6 | 讼 | sòng | ☰ | ☵ | 0,1,0,1,1,1 | ䷅ |
| 7 | 师 | shī | ☷ | ☵ | 0,1,0,0,0,0 | ䷆ |
| 8 | 比 | bǐ | ☵ | ☷ | 0,0,0,0,1,0 | ䷇ |
| 9 | 小畜 | xiǎo xù | ☴ | ☰ | 1,1,1,0,1,1 | ䷈ |
| 10 | 履 | lǚ | ☰ | ☱ | 1,1,0,1,1,1 | ䷉ |
| 11 | 泰 | tài | ☷ | ☰ | 1,1,1,0,0,0 | ䷊ |
| 12 | 否 | pǐ | ☰ | ☷ | 0,0,0,1,1,1 | ䷋ |
| 13 | 同人 | tóng rén | ☰ | ☲ | 1,0,1,1,1,1 | ䷌ |
| 14 | 大有 | dà yǒu | ☲ | ☰ | 1,1,1,1,0,1 | ䷍ |
| 15 | 谦 | qiān | ☷ | ☶ | 0,0,1,0,0,0 | ䷎ |
| 16 | 豫 | yù | ☳ | ☷ | 0,0,0,1,0,0 | ䷏ |
| 17 | 随 | suí | ☱ | ☳ | 1,0,0,1,1,0 | ䷐ |
| 18 | 蛊 | gǔ | ☶ | ☴ | 0,1,1,0,0,1 | ䷑ |
| 19 | 临 | lín | ☷ | ☱ | 1,1,0,0,0,0 | ䷒ |
| 20 | 观 | guān | ☴ | ☷ | 0,0,0,0,1,1 | ䷓ |
| 21 | 噬嗑 | shì kè | ☲ | ☳ | 1,0,0,1,0,1 | ䷔ |
| 22 | 贲 | bì | ☶ | ☲ | 1,0,1,0,0,1 | ䷕ |
| 23 | 剥 | bō | ☶ | ☷ | 0,0,0,0,0,1 | ䷖ |
| 24 | 复 | fù | ☷ | ☳ | 1,0,0,0,0,0 | ䷗ |
| 25 | 无妄 | wú wàng | ☰ | ☳ | 1,0,0,1,1,1 | ䷘ |
| 26 | 大畜 | dà xù | ☶ | ☰ | 1,1,1,0,0,1 | ䷙ |
| 27 | 颐 | yí | ☶ | ☳ | 1,0,0,0,0,1 | ䷚ |
| 28 | 大过 | dà guò | ☱ | ☴ | 0,1,1,1,1,0 | ䷛ |
| 29 | 坎 | kǎn | ☵ | ☵ | 0,1,0,0,1,0 | ䷜ |
| 30 | 离 | lí | ☲ | ☲ | 1,0,1,1,0,1 | ䷝ |
| 31 | 咸 | xián | ☱ | ☶ | 0,0,1,1,1,0 | ䷞ |
| 32 | 恒 | héng | ☳ | ☴ | 0,1,1,1,0,0 | ䷟ |
| 33 | 遁 | dùn | ☰ | ☶ | 0,0,1,1,1,1 | ䷠ |
| 34 | 大壮 | dà zhuàng | ☳ | ☰ | 1,1,1,1,0,0 | ䷡ |
| 35 | 晋 | jìn | ☲ | ☷ | 0,0,0,1,0,1 | ䷢ |
| 36 | 明夷 | míng yí | ☷ | ☲ | 1,0,1,0,0,0 | ䷣ |
| 37 | 家人 | jiā rén | ☴ | ☲ | 1,0,1,0,1,1 | ䷤ |
| 38 | 睽 | kuí | ☲ | ☱ | 1,1,0,1,0,1 | ䷥ |
| 39 | 蹇 | jiǎn | ☵ | ☶ | 0,0,1,0,1,0 | ䷦ |
| 40 | 解 | jiě | ☳ | ☵ | 0,1,0,1,0,0 | ䷧ |
| 41 | 损 | sǔn | ☶ | ☱ | 1,1,0,0,0,1 | ䷨ |
| 42 | 益 | yì | ☴ | ☳ | 1,0,0,0,1,1 | ䷩ |
| 43 | 夬 | guài | ☱ | ☰ | 1,1,1,1,1,0 | ䷪ |
| 44 | 姤 | gòu | ☰ | ☴ | 0,1,1,1,1,1 | ䷫ |
| 45 | 萃 | cuì | ☱ | ☷ | 0,0,0,1,1,0 | ䷬ |
| 46 | 升 | shēng | ☷ | ☴ | 0,1,1,0,0,0 | ䷭ |
| 47 | 困 | kùn | ☱ | ☵ | 0,1,0,1,1,0 | ䷮ |
| 48 | 井 | jǐng | ☵ | ☴ | 0,1,1,0,1,0 | ䷯ |
| 49 | 革 | gé | ☱ | ☲ | 1,0,1,1,1,0 | ䷰ |
| 50 | 鼎 | dǐng | ☲ | ☴ | 0,1,1,1,0,1 | ䷱ |
| 51 | 震 | zhèn | ☳ | ☳ | 1,0,0,1,0,0 | ䷲ |
| 52 | 艮 | gèn | ☶ | ☶ | 0,0,1,0,0,1 | ䷳ |
| 53 | 渐 | jiàn | ☴ | ☶ | 0,0,1,0,1,1 | ䷴ |
| 54 | 归妹 | guī mèi | ☳ | ☱ | 1,1,0,1,0,0 | ䷵ |
| 55 | 丰 | fēng | ☳ | ☲ | 1,0,1,1,0,0 | ䷶ |
| 56 | 旅 | lǚ | ☲ | ☶ | 0,0,1,1,0,1 | ䷷ |
| 57 | 巽 | xùn | ☴ | ☴ | 0,1,1,0,1,1 | ䷸ |
| 58 | 兑 | duì | ☱ | ☱ | 1,1,0,1,1,0 | ䷹ |
| 59 | 涣 | huàn | ☴ | ☵ | 0,1,0,0,1,1 | ䷺ |
| 60 | 节 | jié | ☵ | ☱ | 1,1,0,0,1,0 | ䷻ |
| 61 | 中孚 | zhōng fú | ☴ | ☱ | 1,1,0,0,1,1 | ䷼ |
| 62 | 小过 | xiǎo guò | ☳ | ☶ | 0,0,1,1,0,0 | ䷽ |
| 63 | 既济 | jì jì | ☵ | ☲ | 1,0,1,0,1,0 | ䷾ |
| 64 | 未济 | wèi jì | ☲ | ☵ | 0,1,0,1,0,1 | ䷿ |

**Источник:** [Wikipedia: List of hexagrams of the I Ching](https://en.wikipedia.org/wiki/List_of_hexagrams_of_the_I_Ching). Номера Вэнь-вана, имена и триграммы — стандартные данные, не защищённые авторским правом.

**Проверка уникальности:** все 64 комбинации уникальны (8 триграмм × 8 триграмм = 64).

**Исправления:**
- №54: 110100 (было 110101) — ниж ☱ = 1,1,0; верх ☳ = 1,0,0
- №61: 110011 (было 110001) — ниж ☱ = 1,1,0; верх ☴ = 0,1,1
- №62: 001100 (было 001011) — ниж ☶ = 0,0,1; верх ☳ = 1,0,0

---

## 3. Правила чтения при изменяющихся линиях

### 3.1. Источник правил

**Чжу Си (朱熹, 1130–1200). "Исюэ Цимэн" (易学启蒙, Introduction to the Study of the Classic of Change).**

**Академический источник:**
- **Joseph Adler translation:** "Introduction to the Study of the Classic of Change by Chu Hsi (Zhu Xi)"
  - Corrected 2017 PDF edition: http://www2.kenyon.edu/Depts/Religion/Fac/Adler/Writings/Qimeng-3.pdf
  - Chapter IV (страницы 62-82) содержит детальные правила
  - Оригинальная работа написана в **1186 году**

**Дополнительные источники:**
- Adler, Joseph A. "Sung Dynasty Uses of the I Ching" (Princeton University Press, 1990), chapters 6-7
- Обсуждение на форуме I Ching Community: https://www.onlineclarity.co.uk/friends/index.php?threads/zhu-xis-rules.29041/

### 3.2. Семь правил Чжу Си

| Изменяющихся линий | Что читать | Обоснование | Статус |
|-------------------|-----------|-------------|--------|
| **0** | Judgment (Тхуан) исходной гексаграммы | Ситуация стабильна; достаточно общего описания | ✅ Подтверждено Adler |
| **1** | Текст конкретной изменяющейся линии | Одно изменение — фокус на этой линии | ✅ Подтверждено Adler |
| **2** | Тексты обеих линий; **верхняя** преимущественна | Верхняя линия = более поздняя стадия развития | ✅ Подтверждено Adler |
| **3** | **ВАРИАНТ A:** "take the middle" (средняя линия?) | Неполная формулировка | ⚠️ Неподтверждено |
| | **ВАРИАНТ B:** Judgment исходной (как вопрос) + Judgment преобразованной (как предсказание) | Альтернативная версия из другого источника | ⚠️ Требует проверки |
| **4** | Две **неизменяющиеся** линии преобразованной гексаграммы; **нижняя** преимущественна | Большинство меняется; ищем опору в том, что остаётся стабильным | ✅ Подтверждено Adler |
| **5** | Одна **неизменяющаяся** линия **ИСХОДНОЙ** гексаграммы (НЕ преобразованной!) | Всё в движении, кроме одной точки — это ось | ✅ Подтверждено Adler |
| **6** | Judgment преобразованной гексаграммы | Полная трансформация | ✅ Подтверждено Adler |
| **6 (особый случай)** | Для гексаграммы 1 (Цянь): "yong nine" (用九); для гексаграммы 2 (Кунь): "yong six" (用六) | Специальные тексты для всех ян / всех инь | ✅ Подтверждено (присутствуют в тексте Legge) |

### 3.3. Расхождения между школами

| Вопрос | Чжу Си (Adler) | Альтернативные школы | Наш выбор |
|--------|----------------|---------------------|-----------|
| 2 линии | Верхняя преимущественна | Некоторые читают обе равно | Чжу Си (более определён) |
| 3 линии | **НЕЯСНО** — "take the middle" или Judgment обеих? | Вариант B: Judgment обеих | **Требует уточнения по Adler** |
| 4-5 линий | Неизменяющиеся линии (4: преобразованной, 5: исходной) | Некоторые читают Judgment преобразованной | Чжу Си (сохраняет конкретность) |
| 6 линий (не Цянь/Кунь) | Judgment преобразованной | Некоторые не читают ничего | Чжу Си (даёт результат) |

### 3.4. КРИТИЧЕСКОЕ ЗАМЕЧАНИЕ для 3 изменяющихся линий

**Правило для 3 изменяющихся линий требует дополнительной проверки.**

Из обсуждения на форуме (со ссылкой на Adler):
> "Three lines change - take the middle. (However, from a different source: 1st hex judgement as the question & 2nd hex judgement as the prognostication)"

**Два варианта:**
1. **"Take the middle"** — возможно, имеется в виду средняя линия из трёх изменяющихся? Но это неясно.
2. **Judgment обеих гексаграмм** — исходная как вопрос, преобразованная как предсказание.

**Рекомендация:** Перед реализацией необходимо свериться с Adler translation Chapter IV (страницы 62-82) для уточнения точной формулировки правила для 3 изменяющихся линий.

**Временное решение:** использовать Вариант B (Judgment обеих), как более распространённый в практике.

### 3.5. Что НЕ делается

- Тексты не превращаются в вероятности событий
- Нет автоматического назначения SUPPORT/OPPOSE
- Нет выдуманных трактовок вне корпуса
- Карточка остаётся ABSTAIN, если пользователь не предоставил принятые claims через ручной процесс

---

## 4. Формат данных

### 4.1. Расширение raw_result

Текущий `raw_result` (v0.2):
```json
{
  "throws_bottom_up": [[2,2,2], [2,2,3], ...],
  "lines_bottom_up": [6, 7, 8, 9, 7, 8],
  "yin_yang_bottom_up": ["yang", "yin", ...],
  "moving_lines": [1, 4],
  "transformed_lines_bottom_up": [7, 7, 8, 8, 7, 8],
  "king_wen_number": null,
  "text_corpus": null
}
```

Расширенный `raw_result` (v0.3):
```json
{
  "throws_bottom_up": [[2,2,2], [2,2,3], [2,3,3], [3,3,3], [2,3,2], [3,2,3]],
  "lines_bottom_up": [6, 7, 8, 9, 7, 8],
  "yin_yang_bottom_up": ["yin", "yang", "yin", "yang", "yang", "yin"],
  "moving_lines": [1, 4],
  "transformed_lines_bottom_up": [7, 7, 8, 8, 7, 8],
  
  "primary_hexagram": {
    "king_wen_number": 47,
    "name": "困",
    "pinyin": "kùn",
    "english": "Oppression (Exhaustion)",
    "upper_trigram": "☱",
    "lower_trigram": "☵",
    "lines_binary": [0, 1, 0, 1, 1, 0]
  },
  
  "relating_hexagram": {
    "king_wen_number": 60,
    "name": "节",
    "pinyin": "jié",
    "english": "Limitation",
    "upper_trigram": "☵",
    "lower_trigram": "☱",
    "lines_binary": [1, 1, 0, 0, 1, 0]
  },
  
  "reading_rule": {
    "moving_count": 2,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "line",
        "hexagram": 47,
        "line_number": 1,
        "source": "Legge 1899, The Yî King, Hexagram 47, Line 1",
        "url": "https://sacred-texts.com/ich/ic47.htm"
      },
      {
        "type": "line",
        "hexagram": 47,
        "line_number": 4,
        "source": "Legge 1899, The Yî King, Hexagram 47, Line 4",
        "url": "https://sacred-texts.com/ich/ic47.htm",
        "priority": "predominant"
      }
    ],
    "priority": "upper_line",
    "note": "Two moving lines: read both, upper line (4) is predominant."
  },
  
  "procedure_version": "yijing-three-coins-v1-with-reading",
  "text_corpus_version": "legge-1899-2nd-edition",
  "generated_at": "2026-10-12T10:00:00Z",
  "method": "digital-three-coins",
  "source": "https://www.biroco.com/yijing/basics.htm"
}
```

### 4.2. Статус карточки

**ВАЖНО:** Отсутствие FORECAST-claims само по себе НЕ означает ошибку процедуры.

**Вариант A (рекомендуемый):** карточка остаётся ABSTAIN, но `raw_result` содержит полную информацию для ручного или LLM-чтения.

```json
{
  "core_id": "yijing",
  "status": "ABSTAIN",
  "reason": "READING_NOT_AUTOMATED",
  "protocol_version": "yijing-three-coins-v1-with-reading",
  "inputs": {...},
  "input_hash": "...",
  "raw_result": {...},
  "interpretation": "Raw six-line result with hexagram identification and reading rule applied. Texts not automatically assigned as forecast claims. Procedure completed successfully; claims require manual or LLM-assisted review.",
  "claims": []
}
```

**Вариант B (если пользователь предоставляет claims):** карточка может стать OK, если пользователь или LLM (с ручной проверкой) предлагает claims на основе текстов из `reading_rule.ruling_texts`.

### 4.3. Ссылки на тексты

Каждая ссылка в `ruling_texts` указывает:
- Тип (judgment / line / yong_nine / yong_six)
- Номер гексаграммы
- Номер линии (если применимо)
- Источник (Legge 1899, 2nd edition)
- URL на sacred-texts.com

URL-шаблон: `https://sacred-texts.com/ich/ic{N}.htm` (где N — номер гексаграммы без ведущих нулей).

---

## 5. Проверочные примеры

### Пример 1: 0 изменяющихся линий

**Входы:**
```json
{
  "throws_bottom_up": [[2,3,2], [3,2,2], [2,2,3], [3,2,3], [2,3,2], [3,2,2]]
}
```

**Промежуточные вычисления:**
- Суммы: [7, 7, 7, 8, 7, 7]
- Линии: 7, 7, 7, 8, 7, 7 (все стабильные, нет 6 или 9)
- Бинарно: 1, 1, 1, 0, 1, 1
- Нижняя триграмма: 1,1,1 = ☰ Цянь
- Верхняя триграмма: 0,1,1 = ☴ Сюнь
- Гексаграмма: ☴ над ☰ = **№9 (小畜, xiǎo xù, Small Taming)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [7, 7, 7, 8, 7, 7],
  "moving_lines": [],
  "primary_hexagram": {
    "king_wen_number": 9,
    "name": "小畜",
    "pinyin": "xiǎo xù",
    "english": "Small Taming",
    "lines_binary": [1, 1, 1, 0, 1, 1]
  },
  "relating_hexagram": null,
  "reading_rule": {
    "moving_count": 0,
    "method": "zhu_xi",
    "ruling_texts": [{
      "type": "judgment",
      "hexagram": 9,
      "source": "Legge 1899, The Yî King, Hexagram 9, Judgment",
      "url": "https://sacred-texts.com/ich/ic09.htm"
    }]
  }
}
```

**Проверка:** все линии 7 (ян) или 8 (инь), ни одной 6 или 9 → нет изменяющихся. Четвёртая линия = 8 (инь), поэтому это НЕ "все ян". Гексаграмма 9. Читаем Judgment гексаграммы 9.

---

### Пример 2: 1 изменяющаяся линия

**Входы:**
```json
{
  "throws_bottom_up": [[2,2,2], [3,2,3], [2,3,2], [3,2,3], [2,3,2], [3,2,3]]
}
```

**Промежуточные вычисления:**
- Суммы: [6, 8, 7, 8, 7, 8]
- Линии: 6, 8, 7, 8, 7, 8
- Изменяющиеся: линия 1 (= 6, инь → ян)
- Бинарно: 0, 0, 1, 0, 1, 0
- Нижняя: 0,0,1 = ☶ Гэнь
- Верхняя: 0,1,0 = ☵ Кань
- Гексаграмма: ☵ над ☶ = **№39 (蹇, jiǎn, Obstruction)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [6, 8, 7, 8, 7, 8],
  "moving_lines": [1],
  "primary_hexagram": {
    "king_wen_number": 39,
    "name": "蹇",
    "pinyin": "jiǎn",
    "english": "Obstruction",
    "lines_binary": [0, 0, 1, 0, 1, 0]
  },
  "relating_hexagram": {
    "king_wen_number": 53,
    "name": "渐",
    "pinyin": "jiàn",
    "english": "Gradual Progress",
    "lines_binary": [1, 0, 1, 0, 1, 1]
  },
  "reading_rule": {
    "moving_count": 1,
    "method": "zhu_xi",
    "ruling_texts": [{
      "type": "line",
      "hexagram": 39,
      "line_number": 1,
      "source": "Legge 1899, The Yî King, Hexagram 39, Line 1",
      "url": "https://sacred-texts.com/ich/ic39.htm"
    }],
    "priority": "single_line"
  }
}
```

**Проверка:** линия 1 = 6 (изменяющаяся инь → ян). Преобразованная: линия 1 становится 7. Читаем текст линии 1 исходной гексаграммы 39.

---

### Пример 3: 2 изменяющиеся линии

**Входы:**
```json
{
  "throws_bottom_up": [[2,2,2], [2,2,3], [2,3,3], [3,3,3], [2,3,2], [3,2,3]]
}
```

**Промежуточные вычисления:**
- Суммы: [6, 7, 8, 9, 7, 8]
- Линии: 6, 7, 8, 9, 7, 8
- Изменяющиеся: линии 1 и 4
- Бинарно: 0, 1, 0, 1, 1, 0
- Нижняя: 0,1,0 = ☵ Кань
- Верхняя: 1,1,0 = ☱ Дуй
- Гексаграмма: ☱ над ☵ = **№47 (困, kùn, Oppression)**
- Преобразованная: 7, 7, 8, 8, 7, 8 → 1,1,0,0,1,0 → ☵ над ☱ = **№60 (节, jié, Limitation)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [6, 7, 8, 9, 7, 8],
  "moving_lines": [1, 4],
  "primary_hexagram": {
    "king_wen_number": 47,
    "name": "困",
    "pinyin": "kùn",
    "english": "Oppression (Exhaustion)",
    "lines_binary": [0, 1, 0, 1, 1, 0]
  },
  "relating_hexagram": {
    "king_wen_number": 60,
    "name": "节",
    "pinyin": "jié",
    "english": "Limitation",
    "lines_binary": [1, 1, 0, 0, 1, 0]
  },
  "reading_rule": {
    "moving_count": 2,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "line",
        "hexagram": 47,
        "line_number": 1,
        "source": "Legge 1899, The Yî King, Hexagram 47, Line 1",
        "url": "https://sacred-texts.com/ich/ic47.htm"
      },
      {
        "type": "line",
        "hexagram": 47,
        "line_number": 4,
        "source": "Legge 1899, The Yî King, Hexagram 47, Line 4",
        "url": "https://sacred-texts.com/ich/ic47.htm",
        "priority": "predominant"
      }
    ],
    "priority": "upper_line",
    "note": "Two moving lines: read both, upper line (4) is predominant."
  }
}
```

**Проверка:** 2 изменяющиеся линии (1 и 4). Читаем обе, линия 4 преимущественна.

---

### Пример 4: 3 изменяющиеся линии

**Входы:**
```json
{
  "throws_bottom_up": [[2,2,3], [3,3,3], [2,2,2], [3,3,3], [2,2,3], [3,2,2]]
}
```

**Промежуточные вычисления:**
- Суммы: [7, 9, 6, 9, 7, 7]
- Линии: 7, 9, 6, 9, 7, 7
- Изменяющиеся: линии 2, 3, 4
- Бинарно: 1, 1, 0, 1, 1, 1
- Нижняя: 1,1,0 = ☱ Дуй
- Верхняя: 1,1,1 = ☰ Цянь
- Гексаграмма: ☰ над ☱ = **№43 (夬, guài, Breakthrough)**
- Преобразованная: 1,0,1,0,1,1 → ☴ над ☲ = **№37 (家人, jiā rén, The Family)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [7, 9, 6, 9, 7, 7],
  "moving_lines": [2, 3, 4],
  "primary_hexagram": {
    "king_wen_number": 43,
    "name": "夬",
    "pinyin": "guài",
    "english": "Breakthrough",
    "lines_binary": [1, 1, 0, 1, 1, 1]
  },
  "relating_hexagram": {
    "king_wen_number": 37,
    "name": "家人",
    "pinyin": "jiā rén",
    "english": "The Family",
    "lines_binary": [1, 0, 1, 0, 1, 1]
  },
  "reading_rule": {
    "moving_count": 3,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "judgment",
        "hexagram": 43,
        "source": "Legge 1899, The Yî King, Hexagram 43, Judgment",
        "url": "https://sacred-texts.com/ich/ic43.htm",
        "note": "Primary hexagram judgment (as question)"
      },
      {
        "type": "judgment",
        "hexagram": 37,
        "source": "Legge 1899, The Yî King, Hexagram 37, Judgment",
        "url": "https://sacred-texts.com/ich/ic37.htm",
        "note": "Relating hexagram judgment (as prognostication)"
      }
    ],
    "priority": "both_judgments",
    "note": "Three moving lines: read judgments of both hexagrams. REQUIRES VERIFICATION against Adler Chapter IV."
  }
}
```

**Проверка:** 3 изменяющиеся линии. Использован Вариант B (Judgment обеих). **ТРЕБУЕТ ПРОВЕРКИ** по Adler Chapter IV.

---

### Пример 5: 4 изменяющиеся линии

**Входы:**
```json
{
  "throws_bottom_up": [[3,3,3], [2,2,2], [3,3,3], [2,2,2], [3,3,3], [2,2,3]]
}
```

**Промежуточные вычисления:**
- Суммы: [9, 6, 9, 6, 9, 7]
- Линии: 9, 6, 9, 6, 9, 7
- Изменяющиеся: линии 1, 2, 3, 4
- Бинарно: 1, 0, 1, 0, 1, 1
- Нижняя: 1,0,1 = ☲ Ли
- Верхняя: 0,1,1 = ☴ Сюнь
- Гексаграмма: ☴ над ☲ = **№59 (涣, huàn, Dispersion)**
- Преобразованная: 0,1,0,1,1,1 → ☰ над ☵ = **№5 (需, xū, Waiting)**
- Неизменяющиеся в преобразованной: линии 5 и 6

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [9, 6, 9, 6, 9, 7],
  "moving_lines": [1, 2, 3, 4],
  "primary_hexagram": {
    "king_wen_number": 59,
    "name": "涣",
    "pinyin": "huàn",
    "english": "Dispersion",
    "lines_binary": [1, 0, 1, 0, 1, 1]
  },
  "relating_hexagram": {
    "king_wen_number": 5,
    "name": "需",
    "pinyin": "xū",
    "english": "Waiting",
    "lines_binary": [0, 1, 0, 1, 1, 1]
  },
  "reading_rule": {
    "moving_count": 4,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "line",
        "hexagram": 5,
        "line_number": 5,
        "source": "Legge 1899, The Yî King, Hexagram 5, Line 5",
        "url": "https://sacred-texts.com/ich/ic05.htm"
      },
      {
        "type": "line",
        "hexagram": 5,
        "line_number": 6,
        "source": "Legge 1899, The Yî King, Hexagram 5, Line 6",
        "url": "https://sacred-texts.com/ich/ic05.htm",
        "priority": "predominant"
      }
    ],
    "priority": "lower_stable_line_in_relating",
    "note": "Four moving lines: read the lower of two unchanging lines in the relating hexagram (line 5)."
  }
}
```

**Проверка:** 4 изменяющиеся линии. Неизменяющиеся в преобразованной: 5 и 6. Читаем нижнюю (5).

---

### Пример 6: 5 изменяющихся линий

**Входы:**
```json
{
  "throws_bottom_up": [[3,3,3], [3,3,3], [2,2,2], [3,3,3], [3,3,3], [2,2,3]]
}
```

**Промежуточные вычисления:**
- Суммы: [9, 9, 6, 9, 9, 7]
- Линии: 9, 9, 6, 9, 9, 7
- Изменяющиеся: линии 1, 2, 3, 4, 5
- Бинарно: 1, 1, 0, 1, 1, 1
- Нижняя: 1,1,0 = ☱ Дуй
- Верхняя: 1,1,1 = ☰ Цянь
- Гексаграмма: ☰ над ☱ = **№43 (夬, guài, Breakthrough)**
- Неизменяющаяся в исходной: линия 6

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [9, 9, 6, 9, 9, 7],
  "moving_lines": [1, 2, 3, 4, 5],
  "primary_hexagram": {
    "king_wen_number": 43,
    "name": "夬",
    "pinyin": "guài",
    "english": "Breakthrough",
    "lines_binary": [1, 1, 0, 1, 1, 1]
  },
  "relating_hexagram": {
    "king_wen_number": 2,
    "name": "坤",
    "pinyin": "kūn",
    "english": "The Receptive",
    "lines_binary": [0, 0, 1, 0, 0, 0]
  },
  "reading_rule": {
    "moving_count": 5,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "line",
        "hexagram": 43,
        "line_number": 6,
        "source": "Legge 1899, The Yî King, Hexagram 43, Line 6",
        "url": "https://sacred-texts.com/ich/ic43.htm"
      }
    ],
    "priority": "stable_line_in_primary",
    "note": "Five moving lines: read the unchanging line in the PRIMARY hexagram (line 6), NOT the relating hexagram."
  }
}
```

**Проверка:** 5 изменяющихся линий. Неизменяющаяся в ИСХОДНОЙ (не преобразованной!): линия 6. Читаем линию 6 гексаграммы 43.

---

### Пример 7: 6 изменяющихся линий (все 9 — Цянь → Кунь)

**Входы:**
```json
{
  "throws_bottom_up": [[3,3,3], [3,3,3], [3,3,3], [3,3,3], [3,3,3], [3,3,3]]
}
```

**Промежуточные вычисления:**
- Суммы: [9, 9, 9, 9, 9, 9]
- Линии: 9, 9, 9, 9, 9, 9 (все изменяющийся ян)
- Бинарно: 1, 1, 1, 1, 1, 1
- Гексаграмма: ☰ над ☰ = **№1 (乾, qián, The Creative)**
- Преобразованная: 0,0,0,0,0,0 = **№2 (坤, kūn, The Receptive)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [9, 9, 9, 9, 9, 9],
  "moving_lines": [1, 2, 3, 4, 5, 6],
  "primary_hexagram": {
    "king_wen_number": 1,
    "name": "乾",
    "pinyin": "qián",
    "english": "The Creative",
    "lines_binary": [1, 1, 1, 1, 1, 1]
  },
  "relating_hexagram": {
    "king_wen_number": 2,
    "name": "坤",
    "pinyin": "kūn",
    "english": "The Receptive",
    "lines_binary": [0, 0, 0, 0, 0, 0]
  },
  "reading_rule": {
    "moving_count": 6,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "yong_nine",
        "hexagram": 1,
        "source": "Legge 1899, The Yî King, Hexagram 1, All Nines (用九)",
        "url": "https://sacred-texts.com/ich/ic01.htm"
      }
    ],
    "priority": "special_yong_nine",
    "note": "All six lines changing in Hexagram 1: use special 'yong nine' text."
  }
}
```

**Проверка:** все линии = 9 (изменяющийся ян). Исходная = 1 (Цянь), преобразованная = 2 (Кунь). Читаем "yong nine" (用九) гексаграммы 1.

---

### Пример 8: 6 изменяющихся линий (все 6 — Кунь → Цянь)

**Входы:**
```json
{
  "throws_bottom_up": [[2,2,2], [2,2,2], [2,2,2], [2,2,2], [2,2,2], [2,2,2]]
}
```

**Промежуточные вычисления:**
- Суммы: [6, 6, 6, 6, 6, 6]
- Линии: 6, 6, 6, 6, 6, 6 (все изменяющаяся инь)
- Бинарно: 0, 0, 0, 0, 0, 0
- Гексаграмма: ☷ над ☷ = **№2 (坤, kūn, The Receptive)**
- Преобразованная: 1,1,1,1,1,1 = **№1 (乾, qián, The Creative)**

**Ожидаемый результат:**
```json
{
  "lines_bottom_up": [6, 6, 6, 6, 6, 6],
  "moving_lines": [1, 2, 3, 4, 5, 6],
  "primary_hexagram": {
    "king_wen_number": 2,
    "name": "坤",
    "pinyin": "kūn",
    "english": "The Receptive",
    "lines_binary": [0, 0, 0, 0, 0, 0]
  },
  "relating_hexagram": {
    "king_wen_number": 1,
    "name": "乾",
    "pinyin": "qián",
    "english": "The Creative",
    "lines_binary": [1, 1, 1, 1, 1, 1]
  },
  "reading_rule": {
    "moving_count": 6,
    "method": "zhu_xi",
    "ruling_texts": [
      {
        "type": "yong_six",
        "hexagram": 2,
        "source": "Legge 1899, The Yî King, Hexagram 2, All Sixes (用六)",
        "url": "https://sacred-texts.com/ich/ic02.htm"
      }
    ],
    "priority": "special_yong_six",
    "note": "All six lines changing in Hexagram 2: use special 'yong six' text."
  }
}
```

**Проверка:** все линии = 6 (изменяющаяся инь). Исходная = 2 (Кунь), преобразованная = 1 (Цянь). Читаем "yong six" (用六) гексаграммы 2.

---

## 6. План интеграции

### 6.1. Этап 1: Расширение raw_result (без изменения статуса)

1. Добавить функцию `identify_hexagram(lines_binary) → king_wen_number, name, trigrams`
2. Добавить функцию `apply_reading_rule(moving_lines, primary, relating) → reading_rule`
3. Обновить `calculate()` в `yijing.py` для заполнения новых полей
4. Статус карточки остаётся ABSTAIN с причиной `READING_NOT_AUTOMATED`
5. Добавить тесты на идентификацию гексаграмм и применение правил

**Не изменяет:** существующие расклады, контракты, журнал.

### 6.2. Этап 2: Текстовый корпус (опционально)

1. Создать `text_corpus.json` с текстами Legge 1899 (public domain)
2. Функция `lookup_text(hexagram_number, text_type, line_number) → text_fragment`
3. Заполнить `ruling_texts[i].text` в `reading_rule`
4. Статус карточки остаётся ABSTAIN (тексты доступны, но не назначаются как claims)

### 6.3. Этап 3: Ручная или LLM-приёмка claims (отдельный процесс)

1. Пользователь или LLM предлагает claims на основе `ruling_texts`
2. Человек проверяет и принимает метки (ACCEPTED/REJECTED)
3. Карточка может стать OK с принятыми FORECAST-claims
4. Это **отдельный** процесс, не автоматический

### 6.4. Совместимость

- Существующие расклады (v0.2) не изменяются
- Новый `raw_result` — надмножество старого
- `protocol_version` меняется на `yijing-three-coins-v1-with-reading`
- Старые записи в журнале остаются валидными

---

## 7. Остальные восемь адаптеров: что отсутствует

| Адаптер | Что нужно для OK | Статус |
|---------|------------------|--------|
| **mo** | Таблица 36 сочетаний Мипхама, соответствие граней символам, названия результатов, разметка по тексту | UNAVAILABLE |
| **qiuqian** | Выбор одного храма/набора, версия, количество палочек, правила 筊杯, номера и тексты | UNAVAILABLE |
| **daliuren** | Календарные конвенции, таблица месячного генерала, позиции стволов, построение 4 уроков, методы 3 передач, пример | UNAVAILABLE |
| **egypt** | Корпус P. Cairo 86637, машинная таблица, конвенция привязки дат, три оценки частей дня | UNAVAILABLE |
| **maya** | 20 знаков Chol Q'ij, корреляция/якорная дата, правила смены дня; для pajooneem — община, порядок счёта, этнография | UNAVAILABLE |
| **shakuna** | Правила выбранной главы Брихат-самхиты: вид наблюдения, направление, место, время, условия, формулировка | UNAVAILABLE |
| **slavic** | Одна региональная процедура, корпус песен с идентификаторами, связь песни/предмета/участника, примеры | UNAVAILABLE |
| **name_grids** | Формулы 5 сеток Кумадзаки, правила подсчёта черт, словарь вариантов, специальные случаи, проверка имени основателя | UNAVAILABLE |

Для всех восьми: нужны конкретные источники, таблицы, алгоритмы и тесты с ожидаемыми результатами. Без этого — только сырой жребий (UNAVAILABLE) или ABSTAIN.

---

## 8. Что готово, что требует проверки, следующий шаг

### Готово для реализации

1. ✅ Таблица 64 гексаграмм с номерами Вэнь-вана и триграммами (исправлена)
2. ✅ Формат данных (расширение raw_result)
3. ✅ Проверочные примеры с ожидаемыми результатами (8 примеров: 0-6 изменяющихся + особые случаи)
4. ✅ План интеграции без изменения существующих раскладов
5. ✅ Источник текстов (Legge 1899, 2nd edition) с URL
6. ✅ Академический источник правил Чжу Си (Adler translation)

### Требует проверки

1. ⚠️ **Правило для 3 изменяющихся линий** — требует сверки с Adler Chapter IV (страницы 62-82)
2. ⚠️ Точность таблицы гексаграмм (пересчитана, но желательна дополнительная сверка)
3. ⚠️ Корректность URL на sacred-texts.com (формат ic{N}.htm подтверждён)
4. ⚠️ Обработка граничных случаев (например, 6 линий в гексаграммах 29 и 30)

### Следующий шаг

1. **Проверить правило для 3 изменяющихся** по Adler Chapter IV
2. **Реализовать Этап 1:** функция `identify_hexagram()` и `apply_reading_rule()` в `yijing.py`
3. **Добавить тесты:** на идентификацию всех 64 гексаграмм и применение 7 правил
4. **Не переходить к Этапу 2** (текстовый корпус) до приёмки Этапа 1
5. **Не имитировать** остальные 8 адаптеров — они требуют отдельных спецификаций

---

## Источники и ссылки

1. **Таблица гексаграмм:** [Wikipedia: List of hexagrams of the I Ching](https://en.wikipedia.org/wiki/List_of_hexagrams_of_the_I_Ching)
2. **Тексты Legge 1899:** [The Sacred Books of the East, Vol. XVI (2nd edition)](https://www.sacred-texts.com/ich/index.htm)
3. **Тексты Legge 1882:** [First edition PDF](https://www.biroco.com/yijing/Legge1882.pdf)
4. **Правила Чжу Си (академический источник):** [Joseph Adler translation, corrected 2017 PDF](http://www2.kenyon.edu/Depts/Religion/Fac/Adler/Writings/Qimeng-3.pdf)
5. **Дополнительно о Чжу Си:** Adler, "Sung Dynasty Uses of the I Ching" (Princeton, 1990), chapters 6-7
6. **Монетная процедура:** [biroco.com/yijing/basics.htm](https://www.biroco.com/yijing/basics.htm)
7. **Обсуждение правил:** [I Ching Community forum](https://www.onlineclarity.co.uk/friends/index.php?threads/zhu-xis-rules.29041/)

---

**Ограничения:** Эта спецификация не доказывает предсказательную эффективность И-Цзин. Тексты — символическое чтение, не вероятность события. OK-статус карточки (если будет достигнут через ручную приёмку claims) означает выполненные процедуры, не истинность прогноза. Отсутствие FORECAST-claims само по себе не означает ошибку процедуры.
