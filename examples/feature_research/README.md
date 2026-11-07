# Synthetic feature-research example

These fixtures are **SYNTHETIC**. They are not a personal archive and must not be
treated as evidence of predictive skill.

Preferred smoke path (builds a complete synthetic series automatically):

```bash
python -m dis_oracle.feature_research synthetic-demo --directory private-runs/feature-research-demo
```

Manual ledger commands need a protocol registered before its `starts_at`, a
history large enough for D/E/F (`min_train`), and a forecast clock before
`event_at`. The JSON files here show the schema; for a one-row history D/E/F
will correctly return `недостаточно данных`.
