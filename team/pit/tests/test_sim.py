"""Headless check of the pit model: run each What-if Scenario for a few simulated hours
and print the shift KPIs. Usage: python3 team/pit/tests/test_sim.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import model as M  # noqa: E402
from sim import Pit  # noqa: E402

CASES = [
    ("база (динамическая)", {}),
    ("фиксированное закрепление", {"dispatch_mode": "fixed"}),
    ("съезд A закрыт", {"ramp_a_closed": True}),
    ("съезд A закрыт, фикс.", {"ramp_a_closed": True, "dispatch_mode": "fixed"}),
    ("ЭКГ-2 поломка", {"sh02_down": True}),
    ("ЭКГ-2 поломка, фикс.", {"sh02_down": True, "dispatch_mode": "fixed"}),
    ("ККД стоп", {"crusher_down": True}),
    ("гололёд", {"winter": True}),
    ("3 самосвала без водителей", {"parked_trucks": 3}),
]


def run(scen, hours=4.0, warmup=1.0):
    pit = Pit(seed=7)
    for _ in range(int(warmup * 3600)):
        pit.step(1.0)
    o0, w0, r0 = pit.ore_to_crusher, pit.waste_t, pit.ore_to_rom
    wait0 = sum(t.wait_s for t in pit.trucks)
    pit.apply_scenarios(scen)
    for _ in range(int(hours * 3600)):
        pit.step(1.0)
    ore = (pit.ore_to_crusher - o0) / hours
    rom = (pit.ore_to_rom - r0) / hours
    waste = (pit.waste_t - w0) / hours
    wait = (sum(t.wait_s for t in pit.trucks) - wait0) / 60 / hours
    return pit, ore, rom, waste, wait


if __name__ == "__main__":
    print(f"{'сценарий':30} {'руда ККД т/ч':>12} {'руда склад':>10} {'вскрыша т/ч':>11} {'ожид. мин/ч':>11} {'COS т':>8}")
    for name, scen in CASES:
        pit, ore, rom, waste, wait = run(scen)
        a = pit.analysis()
        print(f"{name:30} {ore:12.0f} {rom:10.0f} {waste:11.0f} {wait:11.0f} {pit.cos:8.0f}  "
              f"нужно на руде {a['need_ore_trucks']}, цикл {a['ore_cycle_min']} мин")
        for r in a["recommendations"]:
            print("      -", r)
    for rid in M.ROADS:
        print(rid, round(M.road_grade_pct(rid), 1), "%")
