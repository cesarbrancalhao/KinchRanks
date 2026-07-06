#!/usr/bin/env python3

import json
import os
import sqlite3
import gzip
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

KINCH_EVENTS = [
    "333", "222", "444", "555", "666", "777",
    "333bf", "333fm", "333oh",
    "minx", "pyram", "skewb", "sq1",
    "444bf", "555bf", "333mbf",
]
KINCH_EVENTS_ALL = KINCH_EVENTS + ["clock"]

RETIRED_EVENTS = ["333ft", "magic", "mmagic"]
ALL_DB_EVENTS = KINCH_EVENTS_ALL + RETIRED_EVENTS

AVERAGE_EVENTS = {"333", "222", "444", "555", "666", "777", "333oh", "clock", "minx", "pyram", "skewb", "sq1", "333ft"}
BETTER_OF_EVENTS = {"333bf", "444bf", "555bf", "333fm"}
SINGLE_ONLY_EVENTS = {"magic", "mmagic"}
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

assert set(KINCH_EVENTS) == (AVERAGE_EVENTS | BETTER_OF_EVENTS | {MBF_EVENT}) - {"clock", "333ft"}
assert set(ALL_DB_EVENTS) == (AVERAGE_EVENTS | BETTER_OF_EVENTS | SINGLE_ONLY_EVENTS | {MBF_EVENT})


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


def _compute_rank(sorted_items):
    result = {}
    rank = 0
    prev_val = None
    prev_rank = 0
    for val, pid in sorted_items:
        rank += 1
        if val is not None and val == prev_val:
            actual_rank = prev_rank
        else:
            actual_rank = rank
            prev_rank = rank
        prev_val = val
        result[pid] = actual_rank
    return result


def _write_sqlite(persons, wr, cwr, conwr, by_country, result, country_continent, used_comp_ids, comp_names):
    db_path = os.path.join(os.path.dirname(__file__), "data.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE persons (
            wca_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            continent TEXT NOT NULL,
            gender TEXT NOT NULL,
            debut_year INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE event_scores (
            wca_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            best_single INTEGER,
            best_average INTEGER,
            mbf_raw_score REAL,
            single_comp TEXT,
            average_comp TEXT,
            nr_single INTEGER,
            nr_average INTEGER,
            cr_single INTEGER,
            cr_average INTEGER,
            wr_single INTEGER,
            wr_average INTEGER,
            PRIMARY KEY (wca_id, event_id)
        )
    """)
    cur.execute("""
        CREATE TABLE records (
            scope TEXT NOT NULL,
            gender TEXT NOT NULL DEFAULT 'all',
            event_id TEXT NOT NULL,
            record_single INTEGER,
            record_average INTEGER,
            mbf_score REAL,
            PRIMARY KEY (scope, gender, event_id)
        )
    """)
    cur.execute("""
        CREATE TABLE competitions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    generated_at = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    cur.execute("INSERT INTO meta VALUES ('generated_at', ?)", (generated_at,))

    selected_ids = set()
    for cdata in result.values():
        for entry in cdata["entries"]:
            selected_ids.add(entry["id"])

    person_rows = []
    event_rows = []
    person_count = 0

    for cid, entries in by_country.items():
        conid = country_continent.get(cid, "")

        for entry in entries:
            wca_id = entry["id"]
            if wca_id not in selected_ids:
                continue

            person = persons.get(wca_id)
            if not person:
                continue

            debut_year = int(wca_id[:4]) if wca_id and len(wca_id) >= 4 and wca_id[:4].isdigit() else 0

            person_rows.append((
                wca_id, person["name"], cid, conid,
                person["gender"], debut_year,
            ))
            person_count += 1

            pbs_full = entry.get("pbs", {})
            pbs_ext = entry.get("_pbs_ext", {})

            for eid in ALL_DB_EVENTS:
                pb = pbs_full.get(eid, {})
                ext = pbs_ext.get(eid, {})
                if not pb:
                    continue

                mbf_raw = None
                if eid == MBF_EVENT:
                    sv = pb.get("s")
                    if sv is not None:
                        raw = compute_kinch_mbf(sv)
                        if raw is not None:
                            mbf_raw = raw

                event_rows.append((
                    wca_id, eid,
                    pb.get("s"), pb.get("a"),
                    mbf_raw,
                    ext.get("sc"), ext.get("ac"),
                    ext.get("sr"), ext.get("ar"),
                    ext.get("scr"), ext.get("acr"),
                    ext.get("swr"), ext.get("awr"),
                ))

    cur.executemany(
        "INSERT OR IGNORE INTO persons VALUES (?,?,?,?,?,?)",
        person_rows,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO event_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        event_rows,
    )

    wr_rows = []
    for gk in ("all", "m", "f"):
        w = wr.get(gk, {})
        for eid in ALL_DB_EVENTS:
            rs = w["single"].get(eid) if "single" in w else None
            ra = w["average"].get(eid) if "average" in w else None
            mbf = w.get("mbf_score") if eid == MBF_EVENT else None
            wr_rows.append(("world", gk, eid, rs, ra, mbf))
    for cid in result:
        cw = cwr.get(cid, {})
        for gk in ("all", "m", "f"):
            w = cw.get(gk, {})
            for eid in ALL_DB_EVENTS:
                rs = w["single"].get(eid) if "single" in w else None
                ra = w["average"].get(eid) if "average" in w else None
                mbf = w.get("mbf_score") if eid == MBF_EVENT else None
                if rs or ra or (mbf is not None and eid == MBF_EVENT):
                    wr_rows.append((cid, gk, eid, rs, ra, mbf))
    for confid in conwr:
        if confid in CONTINENT_NAMES:
            cw = conwr[confid]
            for gk in ("all", "m", "f"):
                w = cw.get(gk, {})
                for eid in ALL_DB_EVENTS:
                    rs = w["single"].get(eid) if "single" in w else None
                    ra = w["average"].get(eid) if "average" in w else None
                    mbf = w.get("mbf_score") if eid == MBF_EVENT else None
                    if rs or ra or (mbf is not None and eid == MBF_EVENT):
                        wr_rows.append((confid, gk, eid, rs, ra, mbf))

    cur.executemany(
        "INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)",
        wr_rows,
    )

    comp_rows = [(cid, comp_names[cid]) for cid in used_comp_ids if cid in comp_names]
    cur.executemany(
        "INSERT OR IGNORE INTO competitions VALUES (?,?)",
        comp_rows,
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_es_wca ON event_scores(wca_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_es_event ON event_scores(event_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_p_country ON persons(country)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_p_continent ON persons(continent)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_p_gender ON persons(gender)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_p_debut ON persons(debut_year)")

    print("  Computing precomputed rankings...", flush=True)
    cur.execute("""
        CREATE TABLE precomputed (
            gender TEXT NOT NULL,
            event_group TEXT NOT NULL,
            include_clock INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            wca_id TEXT NOT NULL,
            overall REAL NOT NULL,
            PRIMARY KEY (gender, event_group, include_clock, rank)
        )
    """)
    cur.execute("""
        CREATE TABLE precomputed_totals (
            gender TEXT NOT NULL,
            event_group TEXT NOT NULL,
            include_clock INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            PRIMARY KEY (gender, event_group, include_clock)
        )
    """)

    GROUP_EVENTS_PY = {
        "__all__": KINCH_EVENTS,
        "nxn": ["333","222","444","555","666","777","333oh"],
        "big": ["444","555","666","777"],
        "bld": ["333bf","444bf","555bf","333mbf"],
        "nonbld": ["333","222","444","555","666","777","333fm","333oh","minx","pyram","skewb","sq1"],
        "other": ["minx","pyram","skewb","sq1","333fm"],
    }

    event_kinch = {}
    for cid, entries in by_country.items():
        for entry in entries:
            wca_id = entry["id"]
            if wca_id not in selected_ids:
                continue
            pbs = entry.get("pbs", {})
            scores = {}
            for eid in ALL_DB_EVENTS:
                pb = pbs.get(eid, {})
                s = 0.0
                if eid == MBF_EVENT:
                    sv = pb.get("s")
                    if sv is not None and wr["all"]["mbf_score"] and wr["all"]["mbf_score"] > 0:
                        raw = compute_kinch_mbf(sv)
                        if raw is not None:
                            s = round(min(raw / wr["all"]["mbf_score"] * 100, 100.0), 2)
                elif eid in AVERAGE_EVENTS:
                    av = pb.get("a")
                    wv = wr["all"]["average"].get(eid)
                    if av is not None and av > 0 and wv and wv > 0:
                        s = round(min(wv / av * 100, 100.0), 2)
                elif eid in BETTER_OF_EVENTS:
                    sv = pb.get("s")
                    av = pb.get("a")
                    ks = 0.0
                    ka = 0.0
                    wvs = wr["all"]["single"].get(eid)
                    wva = wr["all"]["average"].get(eid)
                    if sv is not None and sv > 0 and wvs and wvs > 0:
                        ks = wvs / sv * 100
                    if av is not None and av > 0 and wva and wva > 0:
                        ka = wva / av * 100
                    s = round(min(max(ks, ka), 100.0), 2)
                elif eid in SINGLE_ONLY_EVENTS:
                    sv = pb.get("s")
                    wvs = wr["all"]["single"].get(eid)
                    if sv is not None and sv > 0 and wvs and wvs > 0:
                        s = round(min(wvs / sv * 100, 100.0), 2)
                scores[eid] = s
            event_kinch[wca_id] = scores

    precomp_rows = []
    precomp_total_rows = []
    for g in ("all", "m", "f"):
        for gk, g_events in GROUP_EVENTS_PY.items():
            for inc_clock in (0, 1):
                events = list(g_events)
                if inc_clock and "clock" not in events:
                    events.append("clock")
                n = len(events)
                ranked = []
                for wca_id, scores in event_kinch.items():
                    p_entry = persons.get(wca_id)
                    if not p_entry:
                        continue
                    if g != "all" and p_entry["gender"] != g:
                        continue
                    overall = sum(scores.get(eid, 0) for eid in events) / n
                    if overall > 0:
                        ranked.append((overall, wca_id))
                ranked.sort(key=lambda x: x[0], reverse=True)
                precomp_total_rows.append((g, gk, inc_clock, len(ranked)))
                for rank, (overall, wca_id) in enumerate(ranked[:500], 1):
                    precomp_rows.append((g, gk, inc_clock, rank, wca_id, round(overall, 2)))

    cur.executemany(
        "INSERT OR IGNORE INTO precomputed VALUES (?,?,?,?,?,?)",
        precomp_rows,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO precomputed_totals VALUES (?,?,?,?)",
        precomp_total_rows,
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_lookup ON precomputed(gender, event_group, include_clock)")
    print(f"    {len(precomp_rows)} precomputed rows across all combinations", flush=True)

    conn.commit()
    conn.close()

    db_size = os.path.getsize(db_path)
    print(f"Wrote {db_path} ({db_size / 1024 / 1024:.1f} MB)", flush=True)
    print(f"  {person_count} persons, {len(event_rows)} event scores, {len(wr_rows)} records, {len(comp_rows)} comps", flush=True)


def main():
    persons = {}
    pbs = defaultdict(lambda: defaultdict(dict))
    country_continent = {}
    comp_names = {}

    in_table = None
    line_no = 0
    result_count = 0

    with open(DUMP_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_no += 1
            stripped = line.strip()

            if stripped.startswith("INSERT INTO `competitions` VALUES") or stripped.startswith("INSERT INTO `Competitions` VALUES"):
                in_table = "competitions"
                continue
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

                if in_table == "competitions":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 2:
                        continue
                    cid = row[0]
                    cname = row[1]
                    if cid and cname:
                        comp_names[cid] = cname

                elif in_table == "persons":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 5:
                        continue
                    sub_id = row[1]
                    wca_id = row[0]
                    if sub_id == 1 and wca_id:
                        persons[wca_id] = {
                            "name": row[2] or "",
                            "country_id": row[3] or "",
                            "gender": row[4] or "",
                        }
                elif in_table == "countries":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 2:
                        continue
                    c_name = row[0]
                    cont_id = row[2]
                    if c_name and cont_id:
                        country_continent[c_name] = cont_id
                elif in_table == "results":
                    row = parse_sql_row(line)
                    if row is None or len(row) < 9:
                        continue
                    try:
                        competition_id = row[1]
                        event_id = row[2]
                        person_id = row[8]
                        average = row[6]
                        best = row[5]
                    except (IndexError, TypeError):
                        continue

                    if event_id not in ALL_DB_EVENTS:
                        continue
                    if not person_id:
                        continue

                    result_count += 1
                    if result_count % 500000 == 0:
                        print(f"  line {line_no}: {result_count} results, {len(persons)} persons, {len(pbs)} with PBs, {len(comp_names)} comps", flush=True)

                    entry = pbs[person_id][event_id]

                    if isinstance(best, int) and best > 0:
                        if event_id == MBF_EVENT:
                            cur = entry.get("single")
                            if cur is None or best < cur:
                                entry["single"] = best
                                entry["single_comp"] = competition_id
                        else:
                            cur = entry.get("single")
                            if cur is None or best < cur:
                                entry["single"] = best
                                entry["single_comp"] = competition_id

                    if isinstance(average, int) and average > 0:
                        cur = entry.get("average")
                        if cur is None or average < cur:
                            entry["average"] = average
                            entry["average_comp"] = competition_id

    print(f"Parsed: {len(persons)} persons, {result_count} results, {len(pbs)} with PBs, {len(comp_names)} comps", flush=True)
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

    print("Computing event ranks (NR/CR/WR)...", flush=True)

    for eid in ALL_DB_EVENTS:
        s_world = []
        a_world = []
        s_by_country = defaultdict(list)
        a_by_country = defaultdict(list)
        s_by_continent = defaultdict(list)
        a_by_continent = defaultdict(list)

        for pid, events in pbs.items():
            person = persons.get(pid)
            if not person:
                continue
            cid = person["country_id"]
            conid = person.get("continent_id", "")
            vals = events.get(eid)
            if not vals:
                continue

            sv = vals.get("single")
            if sv is not None and sv > 0:
                s_world.append((sv, pid))
                s_by_country[cid].append((sv, pid))
                if conid:
                    s_by_continent[conid].append((sv, pid))

            av = vals.get("average")
            if av is not None and av > 0:
                a_world.append((av, pid))
                a_by_country[cid].append((av, pid))
                if conid:
                    a_by_continent[conid].append((av, pid))

        s_world.sort(key=lambda x: x[0])
        a_world.sort(key=lambda x: x[0])

        wr_s = _compute_rank(s_world)
        wr_a = _compute_rank(a_world)

        nr_s = {cid: _compute_rank(sorted(items, key=lambda x: x[0])) for cid, items in s_by_country.items()}
        nr_a = {cid: _compute_rank(sorted(items, key=lambda x: x[0])) for cid, items in a_by_country.items()}

        cr_s = {conid: _compute_rank(sorted(items, key=lambda x: x[0])) for conid, items in s_by_continent.items()}
        cr_a = {conid: _compute_rank(sorted(items, key=lambda x: x[0])) for conid, items in a_by_continent.items()}

        for pid, events in pbs.items():
            person = persons.get(pid)
            if not person:
                continue
            cid = person["country_id"]
            conid = person.get("continent_id", "")
            vals = events.get(eid)
            if not vals:
                continue

            if vals.get("single") is not None and vals["single"] > 0:
                vals["sr"] = (nr_s.get(cid) or {}).get(pid)
                vals["swr"] = wr_s.get(pid)
                if conid:
                    vals["scr"] = (cr_s.get(conid) or {}).get(pid)

            if vals.get("average") is not None and vals["average"] > 0:
                vals["ar"] = (nr_a.get(cid) or {}).get(pid)
                vals["awr"] = wr_a.get(pid)
                if conid:
                    vals["acr"] = (cr_a.get(conid) or {}).get(pid)

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
        for event_id in ALL_DB_EVENTS:
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
            elif event_id in SINGLE_ONLY_EVENTS:
                s = vals.get("single")
                wr_s = cw["single"].get(event_id)
                if s is not None and s > 0 and wr_s and wr_s > 0:
                    kinch = wr_s / s * 100

            kinch = min(kinch, 100.0)
            scores[event_id] = round(kinch, 2)

        default_nonzero = [v for eid, v in scores.items() if eid in KINCH_EVENTS and v > 0]
        default_sum = sum(v for eid, v in scores.items() if eid in KINCH_EVENTS)
        overall = round(default_sum / len(KINCH_EVENTS), 2)
        n_events = len(default_nonzero)

        entry_pbs = {}
        entry_pbs_ext = {}
        for event_id in ALL_DB_EVENTS:
            vals = events.get(event_id, {})
            if not vals:
                continue
            pb = {}
            pb_ext = {}
            s = vals.get("single")
            if s is not None and s > 0:
                pb["s"] = s
                if vals.get("single_comp"):
                    pb_ext["sc"] = vals["single_comp"]
                if vals.get("sr") is not None:
                    pb_ext["sr"] = vals["sr"]
                if vals.get("swr") is not None:
                    pb_ext["swr"] = vals["swr"]
                if vals.get("scr") is not None:
                    pb_ext["scr"] = vals["scr"]
            a = vals.get("average")
            if a is not None and a > 0:
                pb["a"] = a
                if vals.get("average_comp"):
                    pb_ext["ac"] = vals["average_comp"]
                if vals.get("ar") is not None:
                    pb_ext["ar"] = vals["ar"]
                if vals.get("awr") is not None:
                    pb_ext["awr"] = vals["awr"]
                if vals.get("acr") is not None:
                    pb_ext["acr"] = vals["acr"]
            if pb:
                entry_pbs[event_id] = pb
            if pb_ext:
                entry_pbs_ext[event_id] = pb_ext

        by_country[cid].append({
            "id": person_id,
            "name": person["name"],
            "country": cid,
            "continent": person.get("continent_id", ""),
            "gender": gender,
            "overall": overall,
            "pbs": entry_pbs,
            "_pbs_ext": entry_pbs_ext,
            "_scores": scores,
            "_n_events": n_events,
        })

    print(f"  Computed scores for {sum(len(v) for v in by_country.values())} persons", flush=True)

    result = {}
    profiles_data = {}
    clock_pbs = {}
    clock_pbs_ext = {}
    used_comp_ids = set()

    for cid, entries in sorted(by_country.items()):
        entries.sort(key=lambda x: x["overall"], reverse=True)

        selected = set()
        for i, e in enumerate(entries):
            if i < TOP_OVERALL and e["_n_events"] >= MIN_EVENTS:
                selected.add(i)

        for event_id in ALL_DB_EVENTS:
            indexed = list(enumerate(entries))
            indexed.sort(key=lambda x: x[1]["_scores"].get(event_id, 0.0), reverse=True)
            for i, _ in indexed[:TOP_PER_EVENT]:
                if entries[i]["_scores"].get(event_id, 0.0) > 0:
                    selected.add(i)

        top_entries = [entries[i] for i in sorted(selected)]
        top_entries.sort(key=lambda x: x["overall"], reverse=True)

        clean_entries = []
        for entry in top_entries:
            wca_id = entry["id"]
            ext = entry.get("_pbs_ext", {})
            ext_no_clock = {}
            for eid, pb_ext in ext.items():
                if eid == "clock":
                    clock_pbs_ext[wca_id] = pb_ext
                    if pb_ext.get("sc"):
                        used_comp_ids.add(pb_ext["sc"])
                    if pb_ext.get("ac"):
                        used_comp_ids.add(pb_ext["ac"])
                else:
                    ext_no_clock[eid] = pb_ext
                    if pb_ext.get("sc"):
                        used_comp_ids.add(pb_ext["sc"])
                    if pb_ext.get("ac"):
                        used_comp_ids.add(pb_ext["ac"])
            if ext_no_clock:
                profiles_data[wca_id] = {"pbs_ext": ext_no_clock}

            pbs = entry["pbs"]
            if "clock" in pbs:
                clock_pbs[wca_id] = pbs["clock"]
                pbs = {k: v for k, v in pbs.items() if k != "clock"}

            clean_entries.append({
                "id": entry["id"],
                "name": entry["name"],
                "country": entry["country"],
                "continent": entry["continent"],
                "gender": entry["gender"],
                "overall": entry["overall"],
                "pbs": pbs,
            })

        result[cid] = {
            "name": cid,
            "count": len(clean_entries),
            "entries": clean_entries,
        }

    def _filter_wr(w):
        return {
            "single": {k: v for k, v in w["single"].items() if k in ALL_DB_EVENTS},
            "average": {k: v for k, v in w["average"].items() if k in ALL_DB_EVENTS},
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

    print("Building global pre-computed rankings (World / All events / All genders)...", flush=True)
    global_entries = []
    w = wr["all"]
    ws = w["single"]
    wa = w["average"]
    wm = w["mbf_score"]
    for cid, cdata in result.items():
        for entry in cdata["entries"]:
            scores = {}
            for eid in KINCH_EVENTS:
                pb = entry["pbs"].get(eid, {})
                kinch = 0.0
                if eid == MBF_EVENT:
                    sv = pb.get("s")
                    if sv is not None and wm and wm > 0:
                        raw = compute_kinch_mbf(sv)
                        if raw is not None:
                            kinch = raw / wm * 100
                elif eid in AVERAGE_EVENTS:
                    av = pb.get("a")
                    wv = wa.get(eid)
                    if av is not None and av > 0 and wv and wv > 0:
                        kinch = wv / av * 100
                elif eid in BETTER_OF_EVENTS:
                    sv = pb.get("s")
                    av = pb.get("a")
                    ks = 0.0
                    ka = 0.0
                    wvs = ws.get(eid)
                    wva = wa.get(eid)
                    if sv is not None and sv > 0 and wvs and wvs > 0:
                        ks = wvs / sv * 100
                    if av is not None and av > 0 and wva and wva > 0:
                        ka = wva / av * 100
                    kinch = max(ks, ka)
                scores[eid] = round(min(kinch, 100.0), 2)
            overall = round(sum(scores.values()) / len(KINCH_EVENTS), 2)
            global_entries.append({
                "id": entry["id"],
                "name": entry["name"],
                "country": entry["country"],
                "continent": entry["continent"],
                "gender": entry["gender"],
                "overall": overall,
                "events": scores,
            })
    global_entries.sort(key=lambda x: x["overall"], reverse=True)
    precomputed = global_entries[:1000]
    print(f"  Pre-computed {len(precomputed)} entries for default view", flush=True)

    comps_output = {cid: comp_names[cid] for cid in used_comp_ids if cid in comp_names}

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y/%m/%d"),
        "wr": wr_data,
        "cwr": cwr_data,
        "conwr": conwr_data,
        "country_continent": country_continent,
        "continents": CONTINENT_NAMES,
        "countries": result,
        "competitions": comps_output,
        "precomputed": precomputed,
    }

    total_entries = sum(v["count"] for v in result.values())
    count_200 = sum(1 for v in result.values() if v["count"] >= 200)
    print(f"  {len(result)} countries, {total_entries} total entries, {count_200} with 200+ entries", flush=True)
    print(f"  {len(comps_output)} competitions referenced in output", flush=True)

    quick_data = {
        "entries": precomputed,
        "wr": wr_data["all"],
        "generated_at": output["generated_at"],
    }
    quick_js = os.path.join(os.path.dirname(__file__), "1000.js")
    with open(quick_js, "w") as f:
        f.write("window.KINCH_QUICK=")
        json.dump(quick_data, f, ensure_ascii=False)
        f.write(";")
    print(f"Wrote {quick_js}", flush=True)

    print("Writing SQLite database...", flush=True)
    _write_sqlite(persons, wr, cwr, conwr, by_country, result, country_continent, used_comp_ids, comp_names)

    db_path = os.path.join(os.path.dirname(__file__), "data.db")
    gz_path = db_path + ".gz"
    with open(db_path, "rb") as f_in:
        with gzip.open(gz_path, "wb", compresslevel=9) as f_out:
            while True:
                chunk = f_in.read(1 << 20)
                if not chunk:
                    break
                f_out.write(chunk)
    gz_size = os.path.getsize(gz_path)
    print(f"Compressed data.db.gz ({gz_size / 1024 / 1024:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
