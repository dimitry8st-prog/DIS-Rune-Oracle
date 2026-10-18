# Maya Adapter Specification

## Overview
Maya calendar system with Tzolkin (260-day sacred calendar) calculations. Divination procedures (pajooneem) are not implemented due to incomplete ethnographic sources.

## Calendar System

### Tzolkin Structure
- 20 day signs (nahuales) in fixed sequence
- Numbers 1-13 cycle independently
- Combination creates 260 unique days (LCM of 13 and 20)

### 20 Day Signs Sequence
1. Imix (Crocodile/Water)
2. Ik' (Wind/Spirit)
3. Ak'b'al (Night)
4. K'an (Lizard/Net)
5. Chikchan (Serpent)
6. Kimi (Death)
7. Manik' (Deer)
8. Lamat (Rabbit/Moon)
9. Muluk (Water/Jade)
10. Ok (Dog)
11. Chuwen (Monkey)
12. Eb' (Human/Grass)
13. B'en (Corn)
14. Ix (Jaguar)
15. Men (Eagle)
16. Kib' (Owl/Wisdom)
17. Kab'an (Earth/Thought)
18. Etz'nab' (Flint/Knife)
19. Kawak (Storm)
20. Ajaw (Lord/Sun)

### GMT Correlation
- Anchor date: August 11, 3114 BCE (proleptic Gregorian)
- Corresponds to Long Count 0.0.0.0.0
- Corresponds to 1 Imix 0 Pop in Tzolkin+Haab
- Julian Day Number: 584283

### Conversion Formula
```
JD = 584283 + Long Count days
```

For Gregorian date to Julian Day:
```python
def gregorian_to_jd(year, month, day):
    if month <= 2:
        year -= 1
        month += 12
    A = year // 100
    B = 2 - A + A // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524.5
```

### Tzolkin Calculation
```python
def calculate_tzolkin(jd):
    days_from_base = int(jd - 584283)
    number = (days_from_base % 13) + 1
    sign_index = days_from_base % 20
    return number, sign_index
```

## Divination (Pajooneem)
**Status: BLOCKED_SOURCE**

Available sources provide general descriptions but lack:
- Exact counting procedure for 260 tz'ite seeds
- Grouping rules
- Sequence of actions
- Completion criteria

**Recommendation:** Do not implement until complete ethnographic description from specific community is obtained.

## Input Schema
```json
{
  "event_id": "string",
  "year": "int (Gregorian year)",
  "month": "int (1-12)",
  "day": "int (1-31)"
}
```

## Output Schema
```json
{
  "core_id": "maya",
  "status": "ABSTAIN",
  "reason": "PAJOONEEM_PROCEDURE_NOT_FIXED",
  "protocol_version": "maya-calendar-v1",
  "inputs": {...},
  "input_hash": "sha256",
  "raw_result": {
    "calendar_system": "tzolkin",
    "correlation": "GMT",
    "tzolkin": {
      "number": "int (1-13)",
      "sign_index": "int (0-19)",
      "sign_name": "string"
    }
  },
  "interpretation": "Calendar date calculated; no divination applied.",
  "claims": []
}
```

## Control Dates
| Gregorian | Tzolkin | Verification |
|-----------|---------|--------------|
| 2000-01-01 | 3 Kib' | Cross-checked |
| 2012-12-21 | 4 Ajaw | End of 13th baktun |
| 2026-10-17 | 8 Ben | Current date |

## Limitations
- Calendar calculation only
- No divination procedure implemented
- No interpretation corpus
- Status always ABSTAIN for divination aspects
