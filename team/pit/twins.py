"""Twin definitions (Ditto things) and the feature snapshot of the running pit."""

import model as M
from sim import ORE_SHOVELS

POLICY = "default:basic_policy"


def f(value, unit=None):
    p = {"value": value}
    if unit:
        p["unit"] = unit
    return p


def r1(x):
    return round(x, 1)


def definitions():
    """Static part of every twin: attributes, including the geometry the UI draws."""
    root = M.ROOT
    things = {
        M.thing("mine"): {"attributes": {
            "name": "Карьер (сектор питания линии 1 ОФ), тип Актогай", "kind": "mine", "_isType": False,
            "rim": {"a": M.RIM_A, "b": M.RIM_B, "depth": M.PIT_DEPTH, "bench": M.BENCH_H, "floor_f": M.FLOOR_F},
            "nodes": {k: [r1(v[0]), r1(v[1]), r1(v[2])] for k, v in M.NODES.items()},
        }},
        M.thing("dispatch"): {"attributes": {"name": "Модуль диспетчеризации и поддержки решений", "kind": "dispatch"}},
        M.thing("control"): {"attributes": {"name": "Пульт сценариев «что если»", "kind": "control"}},
        M.thing("crusher"): {"attributes": {"name": M.CRUSHER["name"], "kind": "crusher", "node": "CRUSHER",
                                             "rated_tph": M.CRUSHER["rated_tph"], "pocket_t": M.CRUSHER["pocket_t"],
                                             "feeds": M.thing("cos")}},
        M.thing("cos"): {"attributes": {"name": "Склад крупнодроблёной руды → мельница", "kind": "stockpile",
                                         "node": "CRUSHER", "capacity_t": M.COS["capacity_t"],
                                         "mill_feed_tph": M.COS["mill_feed_tph"]}},
        M.thing("rom"): {"attributes": {"name": "Рудный склад (аварийный)", "kind": "stockpile", "node": "ROM"}},
        M.thing("dump"): {"attributes": {"name": "Отвал вскрыши", "kind": "dump", "node": "DUMP"}},
        M.thing("fuel"): {"attributes": {"name": "АЗС и стоянка", "kind": "fuel", "node": "FUEL"}},
    }
    for sid, sp in M.SHOVELS.items():
        things[M.thing(sid)] = {"attributes": {
            "name": sp["name"], "kind": "shovel", "node": sid, "material": sp["material"], "model": sp["model"],
            "pass_t": sp["pass_t"], "pass_s": sp["pass_s"],
            "road": [rid for rid, r in M.ROADS.items() if sid in (r[0], r[1])][0]}}
    for tid in M.FLEET:
        things[M.thing(tid)] = {"attributes": {
            "name": f"Самосвал {tid}", "kind": "truck", "model": M.TRUCK["model"],
            "payload_t": M.TRUCK["payload_t"], "tank_l": M.TRUCK["tank_l"],
            "plan_shovel": M.thing(M.FIXED_PLAN[tid])}}
    for rid, (a, b, pts, limit, kind) in M.ROADS.items():
        things[M.thing(rid)] = {"attributes": {
            "name": M.ROAD_NAMES[rid], "kind": "road", "road_kind": kind, "from": a, "to": b,
            "length_m": round(M.polyline_length(pts)), "grade_pct": round(M.road_grade_pct(rid), 1),
            "speed_limit_kmh": limit, "polyline": [[r1(p[0]), r1(p[1]), r1(p[2])] for p in pts]}}
    out = {}
    for tid, body in things.items():
        body["policyId"] = POLICY
        body["attributes"].setdefault("_isType", False)
        if tid != root:
            body["attributes"]["_parents"] = root
        body["features"] = {}
        out[tid] = body
    # control twin starts with the default scenarios
    out[M.thing("control")]["features"] = {"scenarios": {"properties": dict(M.DEFAULT_SCENARIOS)}}
    return out


TRUCK_STATE_RU = {
    "to_shovel": "порожний к экскаватору", "queue_shovel": "очередь у экскаватора", "spotting": "установка под погрузку",
    "loading": "погрузка", "hauling": "гружёный рейс", "queue_crusher": "очередь у ККД", "queue_dump": "очередь на разгрузку",
    "dumping": "разгрузка", "to_fuel": "на АЗС", "queue_fuel": "очередь на АЗС", "fueling": "заправка",
    "to_park": "на стоянку", "parked": "стоянка (нет водителя)", "no_route": "нет маршрута", "no_task": "нет задания",
    "idle": "ожидание",
}


def snapshot(pit):
    """Features of every dynamic twin, keyed by thing id."""
    a = pit.analysis()
    out = {}
    states = {}
    for tr in pit.trucks:
        states[tr.state] = states.get(tr.state, 0) + 1
        road = tr.route[0][0].id if tr.route else ""
        out[M.thing(tr.id)] = {
            "state": f(tr.state), "state_ru": f(TRUCK_STATE_RU.get(tr.state, tr.state)),
            "x": f(r1(tr.xyz[0]), "m"), "y": f(r1(tr.xyz[1]), "m"), "z": f(r1(tr.xyz[2]), "m"),
            "heading": f(round(tr.heading), "deg"), "speed": f(r1(tr.speed), "km/h"),
            "payload": f(r1(tr.payload), "t"), "material": f(tr.material or ""),
            "load_grade": f(round(tr.grade, 3), "% Cu"),
            "destination": f(tr.dest or ""), "assigned_shovel": f(M.thing(tr.shovel) if tr.shovel else ""),
            "road": f(M.thing(road) if road else ""),
            "fuel": f(r1(tr.fuel_pct), "%"), "fuel_l": f(round(tr.fuel_l), "l"),
            "trips_total": f(tr.trips, "trips"), "tonnes_total": f(round(tr.tonnes), "t"),
            "wait_total": f(r1(tr.wait_s / 60), "min"),
        }
    for sid, sh in pit.shovels.items():
        out[M.thing(sid)] = {
            "state": f(sh.state), "queue": f(len(sh.queue), "trucks"),
            "loading_truck": f(M.thing(sh.current.id) if sh.current else ""),
            "face_grade": f(round(sh.grade, 3) if sh.spec["material"] == "ore" else 0.0, "% Cu"),
            "passes_total": f(sh.passes, "passes"), "tonnes_total": f(round(sh.tonnes), "t"),
            "utilization": f(round(100 * sh.busy_s / max(pit.t, 1)), "%"),
            "power": f(M.SHOVEL_KW["down" if sh.down else ("loading" if sh.current else "idle")], "kW"),
        }
    out[M.thing("crusher")] = {
        "state": f("stopped" if not pit.crusher_running else ("crushing" if pit.crusher_tph > 0 else "idle")),
        "throughput": f(round(pit.crusher_tph), "t/h"), "pocket": f(round(pit.pocket), "t"),
        "queue": f(len(pit.crusher_queue), "trucks"),
        "dumping_truck": f(M.thing(pit.dumping_at_crusher.id) if pit.dumping_at_crusher else ""),
        "ore_in_tph_1h": f(a["crusher_in_tph_1h"], "t/h"), "tonnes_total": f(round(pit.ore_to_crusher), "t"),
        "feed_grade_1h": f(round(pit.grade_1h(), 3), "% Cu"),
    }
    out[M.thing("cos")] = {
        "level": f(round(pit.cos), "t"), "level_pct": f(r1(100 * pit.cos / M.COS["capacity_t"]), "%"),
        "mill_feed": f(M.COS["mill_feed_tph"] if pit.cos > 1 else 0, "t/h"),
        "hours_left": f(a["cos_hours_left"], "h"), "mill_starved": f(r1(pit.mill_starved_s / 60), "min"),
    }
    out[M.thing("rom")] = {"level": f(round(pit.rom), "t"), "received_total": f(round(pit.ore_to_rom), "t"),
                           "queue": f(len(pit.tips["ROM"]["queue"]), "trucks")}
    out[M.thing("dump")] = {"received_total": f(round(pit.waste_t), "t"), "waste_tph_1h": f(round(pit.rate_1h("waste")), "t/h"),
                            "queue": f(len(pit.tips["DUMP"]["queue"]), "trucks")}
    out[M.thing("fuel")] = {"queue": f(len(pit.fuel_queue), "trucks"),
                            "fueling_truck": f(M.thing(pit.fuel_busy.id) if pit.fuel_busy else ""),
                            "parked": f(sum(1 for t in pit.trucks if t.state == "parked"), "trucks")}
    on_road = {}
    for tr in pit.trucks:
        if tr.route:
            on_road[tr.route[0][0].id] = on_road.get(tr.route[0][0].id, 0) + 1
    for rid, road in pit.roads.items():
        speeds = [tr.speed for tr in pit.trucks if tr.route and tr.route[0][0].id == rid]
        out[M.thing(rid)] = {"state": f("closed" if road.closed else "open"),
                             "trucks_on": f(on_road.get(rid, 0), "trucks"),
                             "avg_speed": f(r1(sum(speeds) / len(speeds)) if speeds else 0.0, "km/h"),
                             "speed_limit": f(round(road.limit * (0.7 if pit.scen["winter"] else 1.0)), "km/h")}
    total_t = pit.ore_to_crusher + pit.ore_to_rom + pit.waste_t
    out[M.thing("mine")] = {
        "sim_clock": f(pit.clock()), "sim_hours": f(round(pit.t / 3600, 2), "h"),
        "ore_tph_1h": f(a["ore_tph_1h"], "t/h"), "waste_tph_1h": f(round(pit.rate_1h("waste")), "t/h"),
        "ore_total": f(round(pit.ore_to_crusher + pit.ore_to_rom), "t"), "waste_total": f(round(pit.waste_t), "t"),
        "feed_grade_1h": f(round(pit.grade_1h(), 3), "% Cu"),
        "fuel_total": f(round(pit.fuel_used), "l"), "fuel_per_t": f(round(pit.fuel_used / total_t, 3) if total_t else 0, "l/t"),
        "energy_total": f(round(pit.kwh), "kWh"), "energy_per_t": f(round(pit.kwh / total_t, 3) if total_t else 0, "kWh/t"),
        "trucks_moving": f(sum(1 for t in pit.trucks if t.route), "trucks"),
        "trucks_waiting": f(sum(states.get(s, 0) for s in ("queue_shovel", "queue_crusher", "queue_dump", "queue_fuel", "no_route", "no_task")), "trucks"),
        "trucks_parked": f(states.get("parked", 0), "trucks"),
        "queue_wait_total": f(round(sum(t.wait_s for t in pit.trucks) / 60), "min"),
    }
    out[M.thing("dispatch")] = {
        "mode": f(pit.scen["dispatch_mode"]),
        "need_ore_trucks": f(a["need_ore_trucks"], "trucks"), "on_ore_trucks": f(a["on_ore_trucks"], "trucks"),
        "target_ore_trucks": f(pit.desired_ore_trucks() if pit.scen["dispatch_mode"] == "dynamic" else
                                sum(1 for t in M.FLEET if M.FIXED_PLAN[t] in ORE_SHOVELS), "trucks"),
        "ore_cycle": f(a["ore_cycle_min"], "min"), "ore_route": f(a["ore_route_km"], "km"),
        "ore_dig_capacity": f(a["ore_dig_capacity_tph"], "t/h"),
        "recommendations": f("\n".join(a["recommendations"])),
        "events": f("\n".join(pit.log)),
    }
    return out
