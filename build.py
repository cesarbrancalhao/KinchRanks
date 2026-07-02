#!/usr/bin/env python3

import json
import os
from collections import defaultdict
from datetime import datetime, timezone


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

DUMP_PATH = os.environ["DUMP_PATH"]
OUTPUT_PATH = os.environ["OUTPUT_PATH"]

KINCH_EVENTS = [
    "333", "222", "444", "555", "666", "777",
    "333bf", "333fm", "333oh",
    "minx", "pyram", "skewb", "sq1",
    "444bf", "555bf", "333mbf",
]
KINCH_EVENTS_ALL = KINCH_EVENTS + ["clock"]

AVERAGE_EVENTS = {"333", "222", "444", "555", "666", "777", "333oh", "clock", "minx", "pyram", "skewb", "sq1"}
BETTER_OF_EVENTS = {"333bf", "444bf", "555bf", "333fm"}
MBF_EVENT = "333mbf"

MIN_EVENTS = 1
TOP_OVERALL = 1000
TOP_PER_EVENT = 200

CONTINENT_NAMES = {
    "_Africa": "Africa",
    "_Asia": "Asia",
    "_Europe": "Europe",
    "_North America": "North America",
    "_South America": "South America",
    "_Oceania": "Oceania",
}

assert set(KINCH_EVENTS) == (AVERAGE_EVENTS | BETTER_OF_EVENTS | {MBF_EVENT}) - {"clock"}


def decode_mbf(wca_value):
    if wca_value <= 0:
        return None
    old = wca_value // 1_000_000_000 != 0
    if old:
        time_seconds = wca_value % 100_000
        wca_value //= 100_000
        attempted = wca_value % 100
        wca_value //= 100
        solved = 99 - (wca_value % 100)
    else:
        missed = wca_value % 100
        wca_value //= 100
        time_seconds = wca_value % 100_000
        wca_value //= 100_000
        difference = 99 - (wca_value % 100)
        solved = difference + missed
        attempted = solved + missed
    return (solved, attempted, time_seconds)


def compute_kinch_mbf(wca_value):
    decoded = decode_mbf(wca_value)
    if decoded is None:
        return None
    solved, attempted, time_seconds = decoded
    points = 2 * solved - attempted
    time_capped = min(time_seconds, 3600)
    return points + (3600 - time_capped) / 3600


def parse_sql_row(line):
    line = line.strip()
    if line.endswith(","):
        line = line[:-1]
    if line.endswith(";"):
        line = line[:-1]
    line = line.strip()
    if not line.startswith("(") or not line.endswith(")"):
        return None
    inner = line[1:-1]
    fields = []
    current = ""
    in_string = False
    just_closed_string = False
    i = 0
    while i < len(inner):
        c = inner[i]
        if in_string:
            if c == "\\":
                if i + 1 < len(inner):
                    i += 1
                    current += inner[i]
            elif c == "'":
                if i + 1 < len(inner) and inner[i + 1] == "'":
                    current += "'"
                    i += 1
                else:
                    in_string = False
                    fields.append(current)
                    current = ""
                    just_closed_string = True
            else:
                current += c
        else:
            if c == "'":
                in_string = True
                just_closed_string = False
            elif c == ",":
                if just_closed_string:
                    just_closed_string = False
                else:
                    val = current.strip()
                    if val == "NULL" or val == "":
                        fields.append(None)
                    else:
                        try:
                            fields.append(int(val))
                        except ValueError:
                            try:
                                fields.append(float(val))
                            except ValueError:
                                fields.append(val)
                    current = ""
            else:
                current += c
                just_closed_string = False
        i += 1
    if not just_closed_string:
        val = current.strip()
        if val == "NULL":
            fields.append(None)
        else:
            try:
                fields.append(int(val))
            except ValueError:
                try:
                    fields.append(float(val))
                except ValueError:
                    fields.append(val)
    return fields


def main():
    persons = {}
    pbs = defaultdict(lambda: defaultdict(dict))
    country_continent = {}

    in_table = None
    line_no = 0
    result_count = 0

    with open(DUMP_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_no += 1
            stripped = line.strip()

            if stripped.startswith("INSERT INTO `countries` VALUES"):
                in_table = "countries"
                continue
            if stripped.startswith("INSERT INTO `persons` VALUES"):
                in_table = "persons"
                continue
            if stripped.startswith("INSERT INTO `results` VALUES"):
                in_table = "results"
                continue

            if in_table:
                if stripped.startswith("/*!") or stripped.startswith("--") or stripped == "":
                    continue
                if stripped.startswith("UNLOCK") or stripped.startswith("COMMIT") or stripped.startswith("SET"):
                    in_table = None
                    continue

                if in_table == "persons":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 9:
                        continue
                    sub_id = row[7]
                    wca_id = row[8]
                    if sub_id == 1 and wca_id:
                        persons[wca_id] = {
                            "name": row[6] or "",
                            "country_id": row[2] or "",
                            "gender": row[4] or "",
                        }
                elif in_table == "countries":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 2:
                        continue
                    c_name = row[0]
                    cont_id = row[1]
                    if c_name and cont_id:
                        country_continent[c_name] = cont_id
                elif in_table == "results":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 8:
                        continue
                    try:
                        event_id = row[5]
                        person_id = row[7]
                        average = row[1]
                        best = row[2]
                    except (IndexError, TypeError):
                        continue

                    if event_id not in KINCH_EVENTS_ALL:
                        continue
                    if not person_id:
                        continue

                    result_count += 1
                    if result_count % 500000 == 0:
                        print(f"  line {line_no}: {result_count} results, {len(persons)} persons, {len(pbs)} with PBs", flush=True)

                    entry = pbs[person_id][event_id]

                    if isinstance(best, int) and best > 0:
                        if event_id == MBF_EVENT:
                            cur = entry.get("single")
                            if cur is None or best < cur:
                                entry["single"] = best
                        else:
                            cur = entry.get("single")
                            if cur is None or best < cur:
                                entry["single"] = best

                    if isinstance(average, int) and average > 0:
                        cur = entry.get("average")
                        if cur is None or average < cur:
                            entry["average"] = average

    print(f"Parsed: {len(persons)} persons, {result_count} results, {len(pbs)} with PBs", flush=True)
    print(f"  Country→continent mappings: {len(country_continent)}", flush=True)

    for p in persons.values():
        p["continent_id"] = country_continent.get(p["country_id"], "")

    print("Computing world and country records...", flush=True)

    def _new_wr():
        return {"single": {}, "average": {}, "mbf_score": None}

    wr = {"all": _new_wr(), "m": _new_wr(), "f": _new_wr()}
    cwr = defaultdict(lambda: {"all": _new_wr(), "m": _new_wr(), "f": _new_wr()})
    conwr = defaultdict(lambda: {"all": _new_wr(), "m": _new_wr(), "f": _new_wr()})

    for person_id, events in pbs.items():
        person = persons.get(person_id)
        if not person:
            continue
        cid = person["country_id"]
        conid = person.get("continent_id", "")
        g = person["gender"]
        genders = ["all"] + ([g] if g in ("m", "f") else [])

        for event_id, vals in events.items():
            if event_id == MBF_EVENT:
                wca = vals.get("single")
                if wca is not None:
                    score = compute_kinch_mbf(wca)
                    if score is not None:
                        for gk in genders:
                            w = wr[gk]
                            cw = cwr[cid][gk]
                            cow = conwr[conid][gk]
                            if w["mbf_score"] is None or score > w["mbf_score"]:
                                w["mbf_score"] = score
                            if cw["mbf_score"] is None or score > cw["mbf_score"]:
                                cw["mbf_score"] = score
                            if conid and (cow["mbf_score"] is None or score > cow["mbf_score"]):
                                cow["mbf_score"] = score
            else:
                s = vals.get("single")
                a = vals.get("average")
                for gk in genders:
                    w = wr[gk]
                    cw = cwr[cid][gk]
                    cow = conwr[conid][gk] if conid else None
                    if s is not None and s > 0:
                        se = w["single"]
                        sce = cw["single"]
                        if event_id not in se or s < se[event_id]:
                            se[event_id] = s
                        if event_id not in sce or s < sce.get(event_id, float("inf")):
                            sce[event_id] = s
                        if cow:
                            scoe = cow["single"]
                            if event_id not in scoe or s < scoe.get(event_id, float("inf")):
                                scoe[event_id] = s
                    if a is not None and a > 0:
                        ae = w["average"]
                        ace = cw["average"]
                        if event_id not in ae or a < ae[event_id]:
                            ae[event_id] = a
                        if event_id not in ace or a < ace.get(event_id, float("inf")):
                            ace[event_id] = a
                        if cow:
                            acoe = cow["average"]
                            if event_id not in acoe or a < acoe.get(event_id, float("inf")):
                                acoe[event_id] = a

    active_countries = {person["country_id"] for pid, person in persons.items() if pbs.get(pid)}

    print(f"  WR single (all): {wr['all']['single']}", flush=True)
    print(f"  WR average (all): {wr['all']['average']}", flush=True)
    print(f"  WR MBF score (all): {wr['all']['mbf_score']}", flush=True)

    print("Computing Kinch scores and grouping by country...", flush=True)

    by_country = defaultdict(list)

    for person_id, events in pbs.items():
        person = persons.get(person_id)
        if not person:
            continue
        cid = person["country_id"]
        if cid not in active_countries:
            continue
        cw = cwr[cid]["all"]
        gender = person["gender"]

        scores = {}
        for event_id in KINCH_EVENTS_ALL:
            vals = events.get(event_id, {})
            kinch = 0.0

            if event_id == MBF_EVENT:
                wca = vals.get("single")
                if wca is not None and cw["mbf_score"] and cw["mbf_score"] > 0:
                    raw = compute_kinch_mbf(wca)
                    if raw is not None:
                        kinch = raw / cw["mbf_score"] * 100
            elif event_id in AVERAGE_EVENTS:
                avg = vals.get("average")
                wr_val = cw["average"].get(event_id)
                if avg is not None and avg > 0 and wr_val and wr_val > 0:
                    kinch = wr_val / avg * 100
            elif event_id in BETTER_OF_EVENTS:
                s = vals.get("single")
                a_val = vals.get("average")
                wr_s = cw["single"].get(event_id)
                wr_a = cw["average"].get(event_id)
                k_single = 0.0
                k_avg = 0.0
                if s is not None and s > 0 and wr_s and wr_s > 0:
                    k_single = wr_s / s * 100
                if a_val is not None and a_val > 0 and wr_a and wr_a > 0:
                    k_avg = wr_a / a_val * 100
                kinch = max(k_single, k_avg)

            kinch = min(kinch, 100.0)
            scores[event_id] = round(kinch, 2)

        default_nonzero = [v for eid, v in scores.items() if eid in KINCH_EVENTS and v > 0]
        default_sum = sum(v for eid, v in scores.items() if eid in KINCH_EVENTS)
        overall = round(default_sum / len(KINCH_EVENTS), 2)
        n_events = len(default_nonzero)

        entry_pbs = {}
        for event_id in KINCH_EVENTS_ALL:
            vals = events.get(event_id, {})
            if not vals:
                continue
            pb = {}
            s = vals.get("single")
            if s is not None and s > 0:
                pb["s"] = s
            a = vals.get("average")
            if a is not None and a > 0:
                pb["a"] = a
            if pb:
                entry_pbs[event_id] = pb

        by_country[cid].append({
            "id": person_id,
            "name": person["name"],
            "country": cid,
            "continent": person.get("continent_id", ""),
            "gender": gender,
            "overall": overall,
            "pbs": entry_pbs,
            "_scores": scores,
            "_n_events": n_events,
        })

    print(f"  Computed scores for {sum(len(v) for v in by_country.values())} persons", flush=True)

    result = {}
    for cid, entries in sorted(by_country.items()):
        entries.sort(key=lambda x: x["overall"], reverse=True)

        selected = set()
        for i, e in enumerate(entries):
            if i < TOP_OVERALL and e["_n_events"] >= MIN_EVENTS:
                selected.add(i)

        for event_id in KINCH_EVENTS_ALL:
            indexed = list(enumerate(entries))
            indexed.sort(key=lambda x: x[1]["_scores"].get(event_id, 0.0), reverse=True)
            for i, _ in indexed[:TOP_PER_EVENT]:
                selected.add(i)

        top_entries = [entries[i] for i in sorted(selected)]
        top_entries.sort(key=lambda x: x["overall"], reverse=True)

        for rank, entry in enumerate(top_entries, 1):
            entry["rank"] = rank
            del entry["overall"]
            del entry["_scores"]
            del entry["_n_events"]
        result[cid] = {
            "name": cid,
            "count": len(top_entries),
            "entries": top_entries,
        }

    def _filter_wr(w):
        return {
            "single": {k: v for k, v in w["single"].items() if k in KINCH_EVENTS_ALL},
            "average": {k: v for k, v in w["average"].items() if k in KINCH_EVENTS_ALL},
            "mbf_score": w["mbf_score"],
        }

    wr_data = {gk: _filter_wr(wr[gk]) for gk in ("all", "m", "f")}
    cwr_data = {}
    for cid in result:
        cwr_data[cid] = {gk: _filter_wr(cwr[cid][gk]) for gk in ("all", "m", "f")}
    conwr_data = {}
    for confid in conwr:
        if confid in CONTINENT_NAMES:
            conwr_data[confid] = {gk: _filter_wr(conwr[confid][gk]) for gk in ("all", "m", "f")}

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y/%m/%d"),
        "wr": wr_data,
        "cwr": cwr_data,
        "conwr": conwr_data,
        "country_continent": country_continent,
        "continents": CONTINENT_NAMES,
        "countries": result,
    }

    total_entries = sum(v["count"] for v in result.values())
    count_200 = sum(1 for v in result.values() if v["count"] >= 200)
    print(f"  {len(result)} countries, {total_entries} total entries, {count_200} with 200+ entries", flush=True)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"Wrote {OUTPUT_PATH}", flush=True)

    data_js = os.path.join(os.path.dirname(__file__), "data.js")
    with open(data_js, "w") as f:
        f.write("window.KINCH_DATA=")
        json.dump(output, f, ensure_ascii=False)
        f.write(";")
    print(f"Wrote {data_js}", flush=True)


if __name__ == "__main__":
    main()
