# Kinch Ranks — Documentation (Generated)

## Overview

Kinch Ranks is a data pipeline + static frontend for visualizing WCA Kinch scores. It streams the WCA developer SQL dump (~5GB, ~50M lines) in a single pass, computes personal bests, world/country records, country-specific Kinch scores, and outputs a static JS file consumed by the frontend.

---

## build.py — Data Pipeline

### Phases

**Phase 1 — Parse**
Streams the WCA developer SQL dump in a single pass. Extracts the `persons` table (wca_id → name, country) and the `results` table (event_id, person_id, best, average). Keeps only `sub_id=1` persons (the "current" name record) and only events listed in `KINCH_EVENTS_ALL`.

**Phase 2 — Personal bests**
Computes the all-time personal record (minimum valid solve) per person per event, for both single and average. Multi-Blind raw WCA integer values are stored directly (decoded later).

**Phase 3 — World records & country records**
Iterates all PBs to find the best (lowest) single/average per event, both globally (`wr_*`) and per country (`cwr[*]`). MBF records use the Kinch raw score (points + time ratio) rather than the WCA integer.

**Phase 4 — Country-specific Kinch & selection**
For each person, computes Kinch event scores against their country's WR baseline. Persons with fewer than `MIN_EVENTS` non-zero scores are discarded. The overall is the average of the 16 default events (clock excluded).

Per-country selection (ensuring specialists aren't lost):
- Top 200 by overall score
- Top 50 per individual event
- Union of both sets → stored in the JSON.

Raw PBs (single/average per event) are written into the JS output so the frontend can recompute scores against any baseline (global or country-specific) and toggle Clock inclusion dynamically.

**Phase 5 — JSON output**
Output structure:
```json
{
  "wr": { "single": {"333": best, ...}, "average": {"333": best, ...}, "mbf_score": float },
  "cwr": { "USA": { ... }, ... },
  "conwr": { "_Europe": { ... }, ... },
  "countries": {
    "USA": {
      "name": "USA",
      "count": 200,
      "entries": [
        { "id": "2005XXXX01", "name": "Max Park", "country": "USA",
          "pbs": { "333": {"s": 422, "a": 501}, ... } }
      ]
    }
  }
}
```

The frontend loads this data and computes scores on the fly. When viewing "World" it uses `wr`; when viewing a specific country it uses `cwr[country]`. The Clock checkbox changes the event list length used for the overall average.

### Event classification

Events are grouped by how their Kinch score is derived:

| Category | Events | Derivation |
|---|---|---|
| `AVERAGE_EVENTS` | 333, 222, 444, 555, 666, 777, 333oh, clock, minx, pyram, skewb, sq1 | `WR_avg / PB_avg × 100` |
| `BETTER_OF_EVENTS` | 333bf, 444bf, 555bf, 333fm | `max(score_from_single, score_from_average)` |
| `MBF_EVENT` | 333mbf | decode WCA multi-blind integer → `(points + time_ratio) / WR_mbf_score × 100` |

`KINCH_EVENTS` is the default 16-event set (clock exclued). `KINCH_EVENTS_ALL` includes clock for data collection; the frontend toggles it.

### Selection tuning

- `MIN_EVENTS = 1` — persons must have at least this many non-zero Kinch scores to be included.
- `TOP_OVERALL = 1000` — guarantee top N by overall score per country.
- `TOP_PER_EVENT = 200` — guarantee top N per individual event per country.
- Final set is the UNION of both guarantees so event specialists (e.g. a 5BLD ace with low overall) are never omitted.

### Key functions

**`decode_mbf(wca_value)`** — decode a WCA multi-blind integer into `(solved, attempted, time_seconds)`. Returns `None` for DNF (-1), DNS (-2), or skipped (0). Logic extracted from the WCA Ruby source (`SolveTime.rb`). Handles both the "old" format (≥ 1e9) and the current format (≤ 9 digits).

**`compute_kinch_mbf(wca_value)`** — compute the raw Kinch MBF score: `(solved − unsolved) + (3600 − min(time_seconds, 3600)) / 3600`. Higher is better.

**`parse_sql_row(line)`** — parse a single SQL VALUES row like `(123,456,'text with spaces',...)`. Handles quoted strings (single quotes, escaped `''`), NULL literals, integers, floats, and bare strings. Deliberately simple to stay fast over 50M+ lines.

**`main()`** — run the full pipeline: parse → PBs → WRs → Kinch → JSON.

### Scaling notes

- The file is read line-by-line; memory usage is dominated by the persons dict (~300K entries × ~100 bytes ≈ 30MB) and the PBs defaultdict (~300K persons × ~10 events × 60 bytes ≈ 180MB).
- Current single-pass approach processes ~50M lines in ~8 minutes on a consumer SSD.
- For a much larger dataset, consider: using a faster parser (e.g. C-extension CSV reader), splitting the dump and processing chunks in parallel then merging PBs with a min-reduce, or importing into PostgreSQL and running SQL aggregations.

### Per-country selection flow

For each country:
1. Build the set of person indices to include.
2. Top 1000 overall: only persons with ≥ `MIN_EVENTS` qualify.
3. Top 200 per event: anyone with a score in that event qualifies.
4. Union both sets.
5. Sort by overall score, assign ranks.

WR/country-WR data assembled at the top level contains per-gender baselines (`"all"`, `"m"`, `"f"`). The frontend picks the right one based on the gender filter.

---

## index.html — Frontend

### Data flow

`data.js` (generated by `build.py`) is loaded via a `<script>` tag. It sets `window.KINCH_DATA` containing raw personal bests (`pbs`) per person, plus world-record baselines: global (`wr`) and per-country (`cwr`).

Event scores are NOT pre-computed in the JS file. Instead, `computeKinch(pbs, wr, activeEvents)` calculates them on the fly. This allows switching baselines instantly (World vs. country) and toggling the Clock event without re-fetching data.

### Key functions

| Function | Description |
|---|---|
| `decodeMbf(wca)` | Decode WCA multi-blind integer → raw Kinch score. Returns null for DNF (-1), DNS (-2), or skipped (0). Logic mirrors `decode_mbf` + `compute_kinch_mbf` in `build.py`. |
| `computeKinch(pbs, wr, activeEvents)` | Compute `{ scores, overall }` from raw PBs + WR baseline. Each event score is capped at 100. Overall = average across `activeEvents` (missing events contribute 0). |
| `getWR()` | Returns the right WR baseline. Hierarchy: country > continent > world. |
| `getEntries()` | Collects entries for the current view, filtered by country, continent, gender, and debut year. |
| `renderTable()` | Builds/refreshes the HTML table. Applies column-sort on top of the default overall sort. Paginates with global ranks. |

### Event classification (must match build.py)

- `AVERAGE_EVENTS` — use best average (333, 444, mega, pyram, ...)
- `BETTER_OF_EVENTS` — use max(single_score, average_score)
- `333mbf` — use decodeMbf() for points+time ratio

### Visual hints (dark mode)

- Scores ≥ 90: bold
- Scores = 100: green + bold (world record tier)

### Visual hints (light mode)

- Scores ≥ 90: bold
- Scores = 100: blue + bold (world record tier)
- Overall scores: always bold + dark orange

### Column sort behavior

The default sort is by overall score (descending). Column sort is applied on top. The top-200 per-event slice happens AFTER the column sort so that event specialists (e.g. #1 in 5BLD but low overall) surface correctly.
