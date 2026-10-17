# MO(4).tar — review, 2026-10-17

Status: UNVERIFIED / NOT READY FOR RUNTIME. Original Qwen files are preserved byte-for-byte in this folder; their internal readiness statements are not accepted. Source archive: MO(4).tar.

## Verified improvements
Temple corrected to Kwan Im Thong Hood Cho Temple, Singapore; jiaobei flat/convex mapping corrected; 50/25/25 explicitly labelled a mathematical model; Mo input validation improved. Both JSON files parse.

## Executed checks
Python snippets were extracted from Markdown and executed. No standalone Python implementation or test suite exists in the archive. Missing load_session/save_session were replaced ONLY IN THE REVIEW HARNESS with an in-memory dictionary, not a persistence implementation.

- All 36 reported Mo ordered pairs: generated expected IDs and passed dis_oracle.contracts.validate_cards with that harness.
- Reusing Mo session_id with changed throws silently returns previous card: changed input is not rejected.
- qiuqian success and no_confirmation cards both fail validate_cards: core input_hash mismatch. Hash omits temple/deity present in inputs.
- Manual yin_bei / xiao_bei with max_retries=3 raises ContractError rather than preserving the observation as a completed or waiting record.
- With forced repeated refusal, max_retries=3 produces four attempts: distinguish retries from total attempts consistently in schema/tests.
- max_retries=True is accepted because isinstance(True,int).
- Persistent restart behaviour not verified: load_session/save_session absent.

## Remaining dependencies
36 source-verified Mo meanings, numeric-face-to-syllable mapping, PA NA / Golden Lotus evidence; 100 source-verified qiuqian texts; confirmation and retry rules of the selected Singapore temple. NLB describes sticks but does not establish the entire claimed confirmation protocol. Pending state is not implemented. Digital mode silently ignores supplied manual values and needs an explicit conflict rule.

## Source checks performed during review
- https://www.shambhala.com/snowlion_articles/mo-tibetan-divination-system/ — supports two die rolls / 36 outcomes, not a full numbered table.
- https://www.nlb.gov.sg/main/article-detail?cmsuuid=d9189e20-2326-46b4-828c-db52113b78e5 — Singapore temple, not the previously claimed Taiwan temple.
- https://www.ht.org.tw/religion207.htm — another temple's official jiaobei rules; must not automatically transfer repeat policy to selected temple.

## Verdict
Research draft only. Mo mechanics may be used as input to further implementation; qiuqian needs contract/state fixes. No predictive efficacy established. Runtime, old examples and journals are unchanged.

## Original file SHA-256
- mo_qiuqian_tests.json: ccd7a74601005ad89d6758d661769ea9293e98f515cd318837c42c2560b5022b
- mo_qiuqian_tables.json: d106f92b86b2cbb3240684e581dd7ef3dc93e680db18415214bfbfc816b46469
- MO_QIUQIAN_SPECIFICATION.md: b09dfa1eafd205b957e621be42262f22a05fdda46808000eff65918ee1092a83
