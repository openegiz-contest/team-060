"""
Static model of the Aktogay-type open pit sector: geometry, road graph,
equipment and every numeric parameter in one place.

Coordinates are metres in a local mine grid: x to the east, y to the north,
z is elevation relative to the pit rim (0 m). The pit is an elliptical cone
with 15 m benches; ramps are spirals on the pit wall, so their grade follows
from the geometry instead of being typed in by hand.

Sources of the numbers are listed in SUBMISSION.md, section "Data and
assumptions". Everything marked ASSUMPTION is an engineering estimate.
"""

import math

NS = "kz.aktogay.pit"          # Ditto namespace of every twin of this mine
ROOT = f"{NS}:mine"            # parent twin of the hierarchy

# --- pit geometry -----------------------------------------------------------
RIM_A, RIM_B = 900.0, 620.0    # pit rim semi-axes, m (ASSUMPTION, scaled to one sector)
PIT_DEPTH = 120.0              # 8 benches x 15 m in the current pushback (ASSUMPTION)
BENCH_H = 15.0
FLOOR_F = 0.25                 # pit floor ellipse as a fraction of the rim ellipse


def wall_factor(z):
    """Size of the pit-wall ellipse at elevation z (0 at rim, -PIT_DEPTH at floor)."""
    return FLOOR_F + (1.0 - FLOOR_F) * (z + PIT_DEPTH) / PIT_DEPTH


def wall_point(theta_deg, z):
    f = wall_factor(z)
    t = math.radians(theta_deg)
    return (RIM_A * f * math.cos(t), RIM_B * f * math.sin(t), z)


def spiral(theta0, theta1, z0, z1, n=40):
    """Ramp on the pit wall from (theta0, z0) to (theta1, z1)."""
    return [wall_point(theta0 + (theta1 - theta0) * i / n, z0 + (z1 - z0) * i / n) for i in range(n + 1)]


def line(p0, p1, n=8):
    return [tuple(p0[k] + (p1[k] - p0[k]) * i / n for k in range(3)) for i in range(n + 1)]


def arc_on_level(theta0, theta1, z, n=12):
    return [wall_point(theta0 + (theta1 - theta0) * i / n, z) for i in range(n + 1)]


Z_FLOOR = -PIT_DEPTH
Z_MID = -60.0

# --- nodes of the road graph -------------------------------------------------
NODES = {
    "J1": wall_point(180, Z_FLOOR),          # pit floor, west
    "J2": wall_point(0, Z_FLOOR),            # pit floor, east
    "SH01": wall_point(235, Z_FLOOR),        # ore face, south-west floor
    "SH02": wall_point(320, Z_FLOOR),        # ore face, south-east floor
    "M_A": wall_point(290, Z_MID),           # ramp A at -60 m
    "M_B": wall_point(110, Z_MID),            # ramp B at -60 m
    "SH03": wall_point(140, Z_MID),          # waste face on the -60 m bench, north wall
    "EXIT_A": wall_point(340, 0.0),          # ramp A top, south-east rim
    "EXIT_B": wall_point(160, 0.0),          # ramp B top, north-west rim
    "N1": (60.0, 820.0, 0.0),                # north rim haul road
    "E1": (1230.0, 150.0, 0.0),              # east junction
    "CRUSHER": (1480.0, -330.0, 8.0),        # primary gyratory crusher, tipping platform
    "ROM": (1300.0, -720.0, 0.0),            # run-of-mine ore stockpile (emergency)
    "DUMP": (-1650.0, 760.0, 30.0),          # waste dump, top lift +30 m
    "FUEL": (1250.0, 560.0, 0.0),            # fuel station
}

# road id -> (from, to, polyline, speed limit km/h, kind)
ROADS = {
    "r-sh01": ("SH01", "J1", arc_on_level(235, 180, Z_FLOOR), 25, "spur"),
    "r-sh02": ("SH02", "J2", arc_on_level(320, 360, Z_FLOOR), 25, "spur"),
    "r-floor": ("J1", "J2", arc_on_level(180, 90, Z_FLOOR) + arc_on_level(90, 0, Z_FLOOR)[1:], 30, "floor"),
    "r-ramp-a-low": ("J1", "M_A", spiral(180, 290, Z_FLOOR, Z_MID), 40, "ramp"),
    "r-ramp-a-up": ("M_A", "EXIT_A", spiral(290, 340, Z_MID, 0.0), 40, "ramp"),
    "r-ramp-b-low": ("J2", "M_B", spiral(0, 110, Z_FLOOR, Z_MID), 40, "ramp"),
    "r-ramp-b-up": ("M_B", "EXIT_B", spiral(110, 160, Z_MID, 0.0), 40, "ramp"),
    "r-sh03": ("SH03", "M_B", arc_on_level(140, 110, Z_MID), 25, "spur"),
    "r-crusher": ("EXIT_A", "CRUSHER", line(wall_point(340, 0.0), NODES["CRUSHER"]), 50, "surface"),
    "r-rom": ("EXIT_A", "ROM", line(wall_point(340, 0.0), NODES["ROM"]), 50, "surface"),
    "r-east": ("EXIT_A", "E1", line(wall_point(340, 0.0), NODES["E1"]), 50, "surface"),
    "r-e1-crusher": ("E1", "CRUSHER", line(NODES["E1"], NODES["CRUSHER"]), 50, "surface"),
    "r-north-w": ("EXIT_B", "N1", line(wall_point(160, 0.0), NODES["N1"]), 50, "surface"),
    "r-north-e": ("N1", "E1", line(NODES["N1"], NODES["E1"], 12), 50, "surface"),
    "r-dump": ("EXIT_B", "DUMP", line(wall_point(160, 0.0), NODES["DUMP"]), 50, "surface"),
    "r-fuel": ("E1", "FUEL", line(NODES["E1"], NODES["FUEL"]), 30, "surface"),
}

ROAD_NAMES = {
    "r-sh01": "Заезд к ЭКГ-1", "r-sh02": "Заезд к ЭКГ-2", "r-floor": "Дно карьера",
    "r-ramp-a-low": "Съезд A, нижний", "r-ramp-a-up": "Съезд A, верхний",
    "r-ramp-b-low": "Съезд B, нижний", "r-ramp-b-up": "Съезд B, верхний",
    "r-sh03": "Заезд к ЭКГ-3 (вскрыша)", "r-crusher": "Дорога на ККД",
    "r-rom": "Дорога на рудный склад", "r-east": "Восточная дорога",
    "r-e1-crusher": "Подъезд к ККД с севера", "r-north-w": "Северная объездная, запад",
    "r-north-e": "Северная объездная, восток", "r-dump": "Дорога на отвал",
    "r-fuel": "Дорога на АЗС",
}


def polyline_length(points):
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def road_grade_pct(rid):
    a, b, pts, _, _ = ROADS[rid]
    horiz = sum(math.dist(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1))
    return 100.0 * (pts[-1][2] - pts[0][2]) / horiz if horiz else 0.0


# --- equipment ---------------------------------------------------------------
# Haul truck: Komatsu 830E class, 231 t rated payload (Komatsu 830E data sheet).
TRUCK = {
    "model": "Komatsu 830E-5 (класс 230 т)",
    "payload_t": 231.0,
    "empty_t": 155.0,
    "tank_l": 4540.0,             # 1200 US gal tank (ASSUMPTION: typical 830E option)
    "spot_s": 45.0,               # manoeuvre under the shovel
    "dump_s": 60.0,               # tipping + leaving the platform
    "refuel_s": 900.0,            # 15 min at the fuel station
    "refuel_below_pct": 15.0,
}

# Speed of a 230 t diesel-electric truck as a function of grade, km/h.
# ASSUMPTION: read off typical rimpull / retarder curves of the class.
def truck_speed_kmh(grade_pct, loaded, limit_kmh, winter):
    up = grade_pct if loaded else -grade_pct  # grade in the direction of the load
    if loaded:
        if grade_pct > 6:
            v = 12.5
        elif grade_pct > 2:
            v = 22.0
        elif grade_pct < -6:
            v = 22.0             # retarding downhill, loaded
        else:
            v = 38.0
    else:
        if grade_pct > 6:
            v = 24.0             # empty up a ramp
        elif grade_pct < -6:
            v = 28.0             # empty down a ramp: retarder limit
        else:
            v = 50.0
    del up
    v = min(v, limit_kmh)
    if winter:
        v *= 0.7                 # ASSUMPTION: ice and snow on haul roads, -30 %
    return v


# Diesel burn, l/h, by duty. ASSUMPTION: 1835 kW engine x load factor x 0.21 l/kWh.
FUEL_LPH = {"haul_up": 330.0, "haul_flat": 210.0, "empty": 130.0, "idle": 45.0}

SHOVELS = {
    "SH01": {"name": "ЭКГ-1 (руда)", "material": "ore", "grade0": 0.38,
             "model": "гидравлический экскаватор класса 42 м³", "pass_t": 60.0, "pass_s": 32.0},
    "SH02": {"name": "ЭКГ-2 (руда)", "material": "ore", "grade0": 0.31,
             "model": "гидравлический экскаватор класса 42 м³", "pass_t": 60.0, "pass_s": 32.0},
    "SH03": {"name": "ЭКГ-3 (вскрыша)", "material": "waste", "grade0": 0.0,
             "model": "гидравлический экскаватор класса 42 м³", "pass_t": 60.0, "pass_s": 30.0},
}
SHOVEL_KW = {"loading": 1900.0, "idle": 350.0, "down": 0.0}   # ASSUMPTION

# Primary crusher and the coarse ore stockpile (COS) that feeds the mill line.
CRUSHER = {
    "name": "ККД-1 (гирационная дробилка)",
    "rated_tph": 4500.0,          # ASSUMPTION: 60x113 gyratory class
    "pocket_t": 700.0,            # dump pocket ~3 truckloads
    "kw_crushing": 750.0, "kw_idle": 150.0,
}
COS = {
    "capacity_t": 60000.0,        # ASSUMPTION: live capacity of the coarse ore stockpile
    "start_t": 30000.0,
    "mill_feed_tph": 2850.0,      # one 25 Mt/a line: 25e6 / 8760 h
}
ROM_START_T = 15000.0

FLEET = [f"HT{n:02d}" for n in range(1, 11)]   # 10 trucks in the sector

# Fuel levels at the start of the shift, % (spread so refuelling happens in a demo).
FUEL_START = [62, 18, 85, 40, 16, 71, 55, 29, 90, 47]

# Fixed allocation used when dispatching is "fixed": the classic plan of the shift.
FIXED_PLAN = {"HT01": "SH01", "HT02": "SH01", "HT03": "SH01", "HT04": "SH02", "HT05": "SH02",
              "HT06": "SH02", "HT07": "SH03", "HT08": "SH03", "HT09": "SH03", "HT10": "SH01"}

STATIC_TWINS = ["mine", "dispatch", "control", "crusher", "cos", "rom", "dump", "fuel"]


def thing(name):
    return f"{NS}:{name.lower()}"


def all_thing_ids():
    ids = [thing(n) for n in STATIC_TWINS]
    ids += [thing(s) for s in SHOVELS]
    ids += [thing(t) for t in FLEET]
    ids += [thing(r) for r in ROADS]
    return ids


DEFAULT_SCENARIOS = {
    "ramp_a_closed": False,       # close ramp A (upper segment) — e.g. wall instability
    "sh02_down": False,           # shovel SH02 breakdown
    "crusher_down": False,        # primary crusher stop
    "winter": False,              # snow and ice on the roads
    "parked_trucks": 0,           # trucks without drivers this shift (0..4)
    "dispatch_mode": "dynamic",   # "dynamic" or "fixed"
}
