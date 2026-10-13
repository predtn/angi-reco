# ANGI — Preference survey, Ver1.0

The survey a Traveler answers once, right after signing up (F-17, PREF-02 / PREF-03). It is the source of
truth for the questions the frontend hardcodes and for the rows of `recommendation.survey_option_vectors`
(migration `0002`). Changing an option code, its vector or its mask needs a new version of this file and a
new migration.

How answers become the user vector: `Recommendation_System_Design_Ver1.1.docx` §3.2. Ontology (dimension
order, meaning): §2.2 and `app/core/ontology.py`.

## Rules for the app

- Every question is single choice. The app sends the `option_code` of the chosen option; it sends nothing
  for "Không quan trọng" (no preference) and nothing for a question the user leaves out.
- `scale_value` is not used by this version: leave it out (it counts as 1). It stays in the API for a
  later slider question.
- PREF-02 needs at least one answer (1..50). A user who answers nothing uses "Bỏ qua" (PREF-03).
- Diet filters (vegetarian, no pork, no seafood…) are **not** part of this survey and are never sent to
  reco: the app keeps them and sends them as `excludeTagIds` (API Design, PREF-02 note).
- The survey is accepted once; after submitting or skipping, PREF-02 / PREF-03 answer 409
  `SURVEY_ALREADY_SUBMITTED`.

## Questions

| # | Câu hỏi (hiển thị) | Lựa chọn (hiển thị) | `option_code` |
|---|---|---|---|
| 1 | Bạn ăn cay đến mức nào? | Không ăn cay | `spicy_none` |
| | | Cay nhẹ | `spicy_mild` |
| | | Cay vừa | `spicy_medium` |
| | | Cay nhiều | `spicy_hot` |
| | | Rất cay | `spicy_very_hot` |
| 2 | Bạn thích món ngọt đến mức nào? | Ít ngọt | `sweet_low` |
| | | Ngọt vừa | `sweet_medium` |
| | | Ngọt đậm | `sweet_high` |
| 3 | Bạn thích vị chua đến mức nào? | Ít chua | `sour_low` |
| | | Chua vừa | `sour_medium` |
| | | Chua nhiều | `sour_high` |
| 4 | Bạn ăn mặn đến mức nào? | Ăn nhạt | `salty_low` |
| | | Mặn vừa | `salty_medium` |
| | | Ăn mặn | `salty_high` |
| 5 | Bạn thích nước dùng thế nào? | Thanh, trong | `broth_light` |
| | | Đậm đà, ngọt thịt | `broth_rich` |
| 6 | Bạn thích món béo đến mức nào? | Ít béo | `fatty_low` |
| | | Béo vừa | `fatty_medium` |
| | | Béo nhiều (mỡ, nước cốt dừa, bơ) | `fatty_high` |
| 7 | Bạn thích rau thơm, gia vị thơm không? | Không thích | `herbs_none` |
| | | Một chút | `herbs_some` |
| | | Càng nhiều càng tốt | `herbs_lots` |
| 8 | Bạn có ăn được vị đắng, chát (khổ qua, lá chát, trà)? | Tránh | `bitter_avoid` |
| | | Ăn được | `bitter_ok` |
| | | Thích | `bitter_like` |
| 9 | Bạn thích món thanh mát hay ấm nóng, đậm vị? | Thanh mát | `cool_light` |
| | | Ấm nóng, đậm vị | `warm_hearty` |

Every question also shows "Không quan trọng"; choosing it sends no answer for that question.

## Option vectors

`vec` gives the intensity on each dimension the option has an opinion on; `dim_mask` (the listed
dimensions) marks those dimensions. Every other dimension is 0 in both `vec` and `dim_mask`, so the option
does not pull the user vector there.

| `option_code` | `dim_mask` | `vec` (on the masked dimensions) |
|---|---|---|
| `spicy_none` | spicy | spicy 0 |
| `spicy_mild` | spicy | spicy 0.25 |
| `spicy_medium` | spicy | spicy 0.5 |
| `spicy_hot` | spicy | spicy 0.75 |
| `spicy_very_hot` | spicy | spicy 1 |
| `sweet_low` | sweet | sweet 0 |
| `sweet_medium` | sweet | sweet 0.5 |
| `sweet_high` | sweet | sweet 1 |
| `sour_low` | sour | sour 0 |
| `sour_medium` | sour | sour 0.5 |
| `sour_high` | sour | sour 1 |
| `salty_low` | salty | salty 0 |
| `salty_medium` | salty | salty 0.5 |
| `salty_high` | salty | salty 1 |
| `broth_light` | umami, rich, fresh | umami 0.5, rich 0.25, fresh 0.75 |
| `broth_rich` | umami, rich, fatty | umami 1, rich 1, fatty 0.5 |
| `fatty_low` | fatty | fatty 0 |
| `fatty_medium` | fatty | fatty 0.5 |
| `fatty_high` | fatty | fatty 1 |
| `herbs_none` | aromatic | aromatic 0 |
| `herbs_some` | aromatic, fresh | aromatic 0.5, fresh 0.5 |
| `herbs_lots` | aromatic, fresh | aromatic 1, fresh 0.75 |
| `bitter_avoid` | bitter, astringent | bitter 0, astringent 0 |
| `bitter_ok` | bitter, astringent | bitter 0.5, astringent 0.5 |
| `bitter_like` | bitter, astringent | bitter 1, astringent 1 |
| `cool_light` | cooling, fresh | cooling 1, fresh 1 |
| `warm_hearty` | cooling, rich | cooling 0, rich 0.75 |

All 12 dimensions are covered: sweet (2), sour (3), salty (4), bitter and astringent (8), umami (5),
spicy (1), cooling (9), fatty (5, 6), fresh (5, 7, 9), rich (5, 9), aromatic (7).

## Example

Answers `spicy_medium`, `broth_rich`, `herbs_lots`:

- spicy = 0.5; umami = 1; fatty = 0.5; aromatic = 1
- rich = 1 (only `broth_rich` touches it)
- fresh = 0.75 (only `herbs_lots` touches it)
- every other dimension = 0 (no answer touches it)

The user vector is not zero, so it is stored as `initial_vec` and `vec`; `survey_answer_count` = 3.
Answers that only pick the 0 options (for example `spicy_none`, `sweet_low`) give the zero vector, which
is stored as NULL (Explicit = 0), while `survey_answer_count` still counts them.
