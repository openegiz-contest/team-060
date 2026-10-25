"""
Discrete-time model of the open-pit haul cycle with a dispatch module.

Pure Python, no I/O: simulator.py drives it and publishes its state to the
platform; tests/test_sim.py runs it headless to check the numbers.
"""

import heapq
import math
import random
from collections import deque

import model as M

ORE_SHOVELS = [s for s, v in M.SHOVELS.items() if v["material"] == "ore"]


class Road:
    def __init__(self, rid, a, b, pts, limit, kind):
        self.id, self.a, self.b, self.pts, self.limit, self.kind = rid, a, b, pts, limit, kind
        self.cum = [0.0]
        for i in range(len(pts) - 1):
            self.cum.append(self.cum[-1] + math.dist(pts[i], pts[i + 1]))
        self.length = self.cum[-1]
        self.closed = False

    def seg_index(self, s):
        # index i such that cum[i] <= s < cum[i+1]
        lo, hi = 0, len(self.cum) - 2
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def point(self, s):
        s = max(0.0, min(self.length, s))
        i = self.seg_index(s)
        seg = self.cum[i + 1] - self.cum[i] or 1.0
        f = (s - self.cum[i]) / seg
        p, q = self.pts[i], self.pts[i + 1]
        return tuple(p[k] + (q[k] - p[k]) * f for k in range(3)), (q[0] - p[0], q[1] - p[1])

    def grade_at(self, s):
        i = self.seg_index(max(0.0, min(self.length - 1e-6, s)))
        p, q = self.pts[i], self.pts[i + 1]
        horiz = math.dist(p[:2], q[:2]) or 1.0
        return 100.0 * (q[2] - p[2]) / horiz

    def travel_s(self, forward, loaded, winter):
        """Time to drive the whole road in one direction."""
        t = 0.0
        for i in range(len(self.pts) - 1):
            p, q = self.pts[i], self.pts[i + 1]
            horiz = math.dist(p[:2], q[:2]) or 1.0
            g = 100.0 * (q[2] - p[2]) / horiz
            if not forward:
                g = -g
            v = M.truck_speed_kmh(g, loaded, self.limit, winter) / 3.6
            t += math.dist(p, q) / v
        return t


class Truck:
    def __init__(self, tid, fuel_pct):
        self.id = tid
        self.state = "idle"
        self.node = "FUEL"
        self.route = []          # list of (road, forward)
        self.s = 0.0             # distance along the current road
        self.dest = None         # node we drive to
        self.purpose = None      # "shovel", "dump", "fuel", "park"
        self.shovel = None       # assigned shovel
        self.payload = 0.0
        self.grade = 0.0
        self.material = None
        self.fuel_l = M.TRUCK["tank_l"] * fuel_pct / 100.0
        self.timer = 0.0
        self.speed = 0.0
        self.xyz = M.NODES["FUEL"]
        self.heading = 0.0
        self.trips = 0
        self.tonnes = 0.0
        self.wait_s = 0.0
        self.cycle_start = None
        self.parked = False

    @property
    def fuel_pct(self):
        return 100.0 * self.fuel_l / M.TRUCK["tank_l"]


class Shovel:
    def __init__(self, sid, spec, rng):
        self.id, self.spec = sid, spec
        self.state = "idle"
        self.queue = deque()
        self.current = None
        self.grade = spec["grade0"]
        self.free_at = 0.0       # dispatch estimate of when the shovel is free
        self.down = False
        self.passes = 0
        self.tonnes = 0.0
        self.busy_s = 0.0
        self.rng = rng


class Pit:
    def __init__(self, seed=7):
        self.rng = random.Random(seed)
        self.t = 0.0                                   # simulated seconds since 08:00
        self.roads = {rid: Road(rid, *spec) for rid, spec in M.ROADS.items()}
        self.adj = {n: [] for n in M.NODES}
        for r in self.roads.values():
            self.adj[r.a].append((r, True))
            self.adj[r.b].append((r, False))
        self.shovels = {sid: Shovel(sid, spec, self.rng) for sid, spec in M.SHOVELS.items()}
        self.trucks = [Truck(tid, f) for tid, f in zip(M.FLEET, M.FUEL_START)]
        self.scen = dict(M.DEFAULT_SCENARIOS)
        # crusher, stockpiles
        self.pocket = 200.0
        self.crusher_running = True
        self.crusher_tph = 0.0
        self.dumping_at_crusher = None
        self.crusher_queue = deque()
        self.cos = M.COS["start_t"]
        self.rom = M.ROM_START_T
        self.mill_starved_s = 0.0
        self.dump_t = 0.0
        self.tips = {"DUMP": {"queue": deque(), "busy": None}, "ROM": {"queue": deque(), "busy": None}}
        self.fuel_busy = None
        self.fuel_queue = deque()
        # totals
        self.ore_to_crusher = 0.0
        self.ore_grade_t = 0.0
        self.ore_to_rom = 0.0
        self.waste_t = 0.0
        self.fuel_used = 0.0
        self.kwh = 0.0
        self.log = deque(maxlen=14)
        self.deliveries = deque()                    # (t, kind, tonnes, grade)
        self.cycles = deque(maxlen=30)               # (t, material, cycle_s)
        self._route_cache = {}
        self.event("Начало смены: 10 самосвалов, 3 экскаватора, ККД в работе")
        for i, tr in enumerate(self.trucks):
            # spread trucks over the network at the start
            tr.node = ["J1", "J2", "M_B", "J1", "J2", "EXIT_A", "M_B", "EXIT_B", "J2", "E1"][i]
            tr.xyz = M.NODES[tr.node]
            self.assign_next(tr)

    # ---------------------------------------------------------------- helpers
    def clock(self):
        m = int(8 * 60 + self.t / 60)
        return f"{(m // 60) % 24:02d}:{m % 60:02d}"

    def event(self, text):
        self.log.appendleft(f"{self.clock() if hasattr(self, 't') else '08:00'}  {text}")

    def winter(self):
        return bool(self.scen["winter"])

    def route(self, src, dst, loaded):
        """Dijkstra by travel time over open roads. Returns (seconds, [(road, forward)])."""
        key = (src, dst, loaded, self.winter(), tuple(r.closed for r in self.roads.values()))
        if key in self._route_cache:
            return self._route_cache[key]
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, n = heapq.heappop(pq)
            if n == dst:
                break
            if d > dist.get(n, 1e18):
                continue
            for road, fwd in self.adj[n]:
                if road.closed:
                    continue
                m = road.b if fwd else road.a
                nd = d + road.travel_s(fwd, loaded, self.winter())
                if nd < dist.get(m, 1e18):
                    dist[m] = nd
                    prev[m] = (n, road, fwd)
                    heapq.heappush(pq, (nd, m))
        if dst not in dist:
            res = (None, None)
        else:
            path, n = [], dst
            while n != src:
                p, road, fwd = prev[n]
                path.append((road, fwd))
                n = p
            res = (dist[dst], list(reversed(path)))
        self._route_cache[key] = res
        return res

    def route_km(self, path):
        return sum(r.length for r, _ in path) / 1000.0 if path else 0.0

    def load_s(self, sid):
        sp = M.SHOVELS[sid]
        return M.TRUCK["spot_s"] + math.ceil(M.TRUCK["payload_t"] / sp["pass_t"]) * sp["pass_s"]

    def ore_needed(self):
        return self.cos < 0.85 * M.COS["capacity_t"]

    # -------------------------------------------------------------- dispatch
    def choose_shovel(self, tr):
        if self.scen["dispatch_mode"] == "fixed":
            return M.FIXED_PLAN[tr.id]
        # Needs-based allocation: as many trucks on ore as the mill needs (from the
        # model's own cycle estimate), the rest strip waste. Within a material the
        # truck goes where it will be under a shovel soonest.
        desired = self.desired_ore_trucks()
        on_ore = sum(1 for o in self.trucks if o is not tr and not o.parked and o.shovel in ORE_SHOVELS
                     and o.state not in ("to_fuel", "queue_fuel", "fueling", "to_park", "parked"))
        want_ore = on_ore < desired
        best, best_score = None, None
        for sid, sh in self.shovels.items():
            if sh.down:
                continue
            travel, path = self.route(tr.node, sid, False)
            if travel is None:
                continue
            arrival = self.t + travel
            ready = max(arrival, sh.free_at)
            score = ready - self.t                       # time until the truck is under the shovel
            ore = M.SHOVELS[sid]["material"] == "ore"
            if ore != want_ore:
                score += 3600
            if best_score is None or score < best_score:
                best, best_score = sid, score
        return best

    def desired_ore_trucks(self):
        if self.t - getattr(self, "_desired_t", -1e9) < 60:
            return self._desired
        best = None
        for s in ORE_SHOVELS:
            if self.shovels[s].down:
                continue
            c, _ = self.ore_cycle_estimate(s)
            if c is not None and (best is None or c < best):
                best = c
        if best is None:
            n = 0
        else:
            frac = self.cos / M.COS["capacity_t"]
            k = 1.3 if frac < 0.4 else (1.1 if frac < 0.75 else (0.85 if frac < 0.95 else 0.5))
            n = math.ceil(M.COS["mill_feed_tph"] * k / (M.TRUCK["payload_t"] * 3600 / best) - 0.15)
        self._desired, self._desired_t = n, self.t
        return n

    def assign_next(self, tr):
        """Truck is empty at tr.node: decide where it goes."""
        if tr.parked:
            return self.send(tr, "FUEL", "park", loaded=False)
        if tr.fuel_pct < M.TRUCK["refuel_below_pct"]:
            self.event(f"{tr.id}: топливо {tr.fuel_pct:.0f} % — на АЗС")
            return self.send(tr, "FUEL", "fuel", loaded=False)
        sid = self.choose_shovel(tr)
        if sid is None:
            tr.state = "no_task"
            tr.shovel = None
            return
        sh = self.shovels[sid]
        travel, _ = self.route(tr.node, sid, False)
        if travel is not None:
            sh.free_at = max(self.t + travel, sh.free_at) + self.load_s(sid)
        tr.shovel = sid
        tr.cycle_start = self.t
        self.send(tr, sid, "shovel", loaded=False)

    def send(self, tr, dst, purpose, loaded):
        tr.dest, tr.purpose = dst, purpose
        if tr.node == dst:
            tr.route = []
            return self.arrive(tr)
        travel, path = self.route(tr.node, dst, loaded)
        if path is None:
            if tr.state != "no_route":
                self.event(f"{tr.id}: нет открытого маршрута {tr.node} → {dst}")
            tr.state = "no_route"
            tr.route = []
            return
        tr.route = list(path)
        tr.s = 0.0
        tr.state = {"shovel": "to_shovel", "dump": "hauling", "fuel": "to_fuel", "park": "to_park"}[purpose]

    def redirect(self, tr, dst):
        """Change destination of a moving truck: finish the current road, then re-plan."""
        road, fwd = tr.route[0]
        end = road.b if fwd else road.a
        tr.dest = dst
        _, path = self.route(end, dst, tr.payload > 0)
        tr.route = [(road, fwd)] + (list(path) if path else [])

    def destination_for_ore(self):
        if self.scen["dispatch_mode"] == "fixed":
            return "CRUSHER"
        if self.scen["crusher_down"]:
            return "ROM"
        if len(self.crusher_queue) >= 3:
            return "ROM"
        return "CRUSHER"

    # ------------------------------------------------------------ scenarios
    def apply_scenarios(self, new):
        new = {**M.DEFAULT_SCENARIOS, **{k: v for k, v in new.items() if k in M.DEFAULT_SCENARIOS}}
        old = self.scen
        if new == old:
            return
        self.scen = new
        self._route_cache.clear()
        self._desired_t = -1e9
        a_closed = bool(new["ramp_a_closed"])
        if a_closed != bool(old["ramp_a_closed"]):
            self.roads["r-ramp-a-up"].closed = a_closed
            self.event("Сценарий: съезд A закрыт (неустойчивость борта)" if a_closed else "Сценарий снят: съезд A открыт")
        down = bool(new["sh02_down"])
        if down != bool(old["sh02_down"]):
            sh = self.shovels["SH02"]
            sh.down = down
            self.event("Сценарий: ЭКГ-2 остановлен (поломка)" if down else "Сценарий снят: ЭКГ-2 в работе")
            if down:
                sh.state = "down"
                if sh.current is not None:
                    tr = sh.current
                    sh.current = None
                    if tr.payload > 0:
                        self.depart_loaded(tr, sh)
                    else:
                        tr.node = "SH02"
                        self.assign_next(tr)
                if new["dispatch_mode"] == "dynamic":
                    while sh.queue:
                        tr = sh.queue.popleft()
                        self.assign_next(tr)
            else:
                sh.state = "idle"
                sh.free_at = self.t
        if bool(new["crusher_down"]) != bool(old["crusher_down"]):
            self.crusher_running = not new["crusher_down"]
            self.event("Сценарий: ККД остановлена" if new["crusher_down"] else "Сценарий снят: ККД в работе")
            if new["crusher_down"] and new["dispatch_mode"] == "dynamic":
                while self.crusher_queue:
                    tr = self.crusher_queue.popleft()
                    tr.node = "CRUSHER"
                    self.send(tr, "ROM", "dump", loaded=True)
                for tr in self.trucks:
                    if tr.state == "hauling" and tr.dest == "CRUSHER" and tr.route:
                        self.redirect(tr, "ROM")
        if bool(new["winter"]) != bool(old["winter"]):
            self.event("Сценарий: гололёд, скорость −30 %" if new["winter"] else "Сценарий снят: сухие дороги")
        n_park = max(0, min(4, int(new["parked_trucks"] or 0)))
        if n_park != int(old["parked_trucks"] or 0):
            self.event(f"Сценарий: без водителей {n_park} самосвала(ов)" if n_park else "Сценарий снят: все самосвалы на линии")
        for i, tr in enumerate(reversed(self.trucks)):
            want = i < n_park
            if want != tr.parked:
                tr.parked = want
                if not want and tr.state in ("parked", "to_park"):
                    tr.state = "idle"
                    tr.route = []
                    if tr.state != "to_park":
                        self.assign_next(tr)
                    else:
                        self.assign_next(tr)
        if new["dispatch_mode"] != old["dispatch_mode"]:
            self.event("Диспетчеризация: динамическая" if new["dispatch_mode"] == "dynamic"
                       else "Диспетчеризация: фиксированное закрепление по плану смены")
        # trucks waiting for a route or task get another chance
        for tr in self.trucks:
            if tr.state in ("no_route", "no_task"):
                if tr.purpose == "dump" and tr.payload > 0:
                    self.send(tr, tr.dest, "dump", loaded=True)
                else:
                    self.assign_next(tr)
            elif tr.state == "queue_shovel" and new["dispatch_mode"] == "dynamic" and self.shovels[tr.shovel].down:
                pass

    # ------------------------------------------------------------ movement
    def arrive(self, tr):
        if tr.node != tr.dest:
            # the road ran out before the destination (re-planned while moving)
            return self.send(tr, tr.dest, tr.purpose, loaded=tr.payload > 0)
        tr.route = []
        tr.speed = 0.0
        tr.node = tr.dest
        tr.xyz = M.NODES[tr.dest]
        if tr.purpose == "shovel":
            sh = self.shovels[tr.shovel]
            tr.state = "queue_shovel"
            sh.queue.append(tr)
        elif tr.purpose == "dump":
            if tr.dest == "CRUSHER":
                tr.state = "queue_crusher"
                self.crusher_queue.append(tr)
            else:
                tr.state = "queue_dump"
                self.tips[tr.dest]["queue"].append(tr)
        elif tr.purpose == "fuel":
            tr.state = "queue_fuel"
            self.fuel_queue.append(tr)
        elif tr.purpose == "park":
            tr.state = "parked"

    def drive(self, tr, dt):
        loaded = tr.payload > 0
        remaining = dt
        while remaining > 0 and tr.route:
            road, fwd = tr.route[0]
            s_road = tr.s if fwd else road.length - tr.s
            g = road.grade_at(s_road)
            if not fwd:
                g = -g
            v = M.truck_speed_kmh(g, loaded, road.limit, self.winter()) / 3.6
            v *= self.rng.uniform(0.95, 1.03)
            tr.speed = v * 3.6
            step = v * remaining
            left = road.length - tr.s
            burn = M.FUEL_LPH["haul_up" if (loaded and g > 3) else ("haul_flat" if loaded else "empty")]
            if step < left:
                tr.s += step
                self.burn(tr, burn, remaining)
                remaining = 0
            else:
                used = left / v
                self.burn(tr, burn, used)
                remaining -= used
                tr.route.pop(0)
                tr.node = road.b if fwd else road.a
                tr.s = 0.0
                # re-plan at every junction: roads may have been closed meanwhile
                if tr.route and any(r.closed for r, _ in tr.route):
                    travel, path = self.route(tr.node, tr.dest, loaded)
                    if path is None:
                        tr.state = "no_route"
                        tr.route = []
                        self.event(f"{tr.id}: маршрут перекрыт, ожидание у {tr.node}")
                        return
                    tr.route = list(path)
                    self.event(f"{tr.id}: объезд через {', '.join(M.ROAD_NAMES[r.id] for r, _ in path[:2])}")
        if tr.route:
            road, fwd = tr.route[0]
            s_road = tr.s if fwd else road.length - tr.s
            p, d = road.point(s_road)
            tr.xyz = p
            if not fwd:
                d = (-d[0], -d[1])
            tr.heading = math.degrees(math.atan2(d[1], d[0]))
        elif tr.state in ("to_shovel", "hauling", "to_fuel", "to_park"):
            self.arrive(tr)

    def burn(self, tr, lph, seconds):
        litres = lph * seconds / 3600.0
        tr.fuel_l = max(0.0, tr.fuel_l - litres)
        self.fuel_used += litres

    def depart_loaded(self, tr, sh):
        tr.node = sh.id
        tr.material = M.SHOVELS[sh.id]["material"]
        dst = self.destination_for_ore() if tr.material == "ore" else "DUMP"
        self.send(tr, dst, "dump", loaded=True)

    # ------------------------------------------------------------ main step
    def step(self, dt=1.0):
        self.t += dt
        winter = self.winter()
        del winter
        # shovels
        for sid, sh in self.shovels.items():
            sh.grade = max(0.12, min(0.7, sh.grade + self.rng.gauss(0, 0.0006) + 0.002 * (sh.spec["grade0"] - sh.grade)))
            if sh.down:
                sh.state = "down"
                self.kwh += M.SHOVEL_KW["down"] * dt / 3600
                for tr in sh.queue:
                    tr.wait_s += dt
                    self.burn(tr, M.FUEL_LPH["idle"], dt)
                continue
            if sh.current is None and sh.queue:
                sh.current = sh.queue.popleft()
                sh.current.state = "spotting"
                sh.current.timer = M.TRUCK["spot_s"]
            tr = sh.current
            if tr is not None:
                sh.busy_s += dt
                tr.timer -= dt
                if tr.state == "spotting" and tr.timer <= 0:
                    tr.state = "loading"
                    tr.timer = sh.spec["pass_s"]
                elif tr.state == "loading" and tr.timer <= 0:
                    bucket = min(sh.spec["pass_t"] * self.rng.uniform(0.9, 1.06), M.TRUCK["payload_t"] - tr.payload)
                    tr.grade = (tr.grade * tr.payload + sh.grade * bucket) / (tr.payload + bucket)
                    tr.payload += bucket
                    sh.passes += 1
                    sh.tonnes += bucket
                    tr.timer = sh.spec["pass_s"]
                    if tr.payload >= M.TRUCK["payload_t"] - 5:
                        sh.current = None
                        self.depart_loaded(tr, sh)
                sh.state = "loading"
                self.burn(tr, M.FUEL_LPH["idle"], dt) if tr.payload == 0 else None
                self.kwh += M.SHOVEL_KW["loading"] * dt / 3600
            else:
                sh.state = "waiting_trucks"
                self.kwh += M.SHOVEL_KW["idle"] * dt / 3600
            for q in sh.queue:
                q.wait_s += dt
                self.burn(q, M.FUEL_LPH["idle"], dt)
        # crusher
        if self.crusher_running:
            if self.dumping_at_crusher is None and self.crusher_queue:
                tr = self.crusher_queue[0]
                if self.pocket + tr.payload <= M.CRUSHER["pocket_t"]:
                    self.crusher_queue.popleft()
                    self.dumping_at_crusher = tr
                    tr.state = "dumping"
                    tr.timer = M.TRUCK["dump_s"]
            out = min(self.pocket, M.CRUSHER["rated_tph"] * dt / 3600, M.COS["capacity_t"] - self.cos)
            self.pocket -= out
            self.cos += out
            self.crusher_tph = out * 3600 / dt
            self.kwh += (M.CRUSHER["kw_crushing"] if out > 0 else M.CRUSHER["kw_idle"]) * dt / 3600
        else:
            self.crusher_tph = 0.0
        tr = self.dumping_at_crusher
        if tr is not None:
            tr.timer -= dt
            if tr.timer <= 0:
                self.pocket += tr.payload
                self.ore_to_crusher += tr.payload
                self.ore_grade_t += tr.payload * tr.grade
                self.deliveries.append((self.t, "crusher", tr.payload, tr.grade))
                self.dumping_at_crusher = None
                self.finish_trip(tr)
        for q in self.crusher_queue:
            q.wait_s += dt
            self.burn(q, M.FUEL_LPH["idle"], dt)
        # mill draws from the coarse ore stockpile
        draw = min(self.cos, M.COS["mill_feed_tph"] * dt / 3600)
        self.cos -= draw
        if draw < M.COS["mill_feed_tph"] * dt / 3600 - 1e-6:
            self.mill_starved_s += dt
        # waste dump and ROM: each has its own tipping point, no pocket limit
        for place, tip in self.tips.items():
            if tip["busy"] is None and tip["queue"]:
                tip["busy"] = tip["queue"].popleft()
                tip["busy"].state = "dumping"
                tip["busy"].timer = M.TRUCK["dump_s"]
            for q in tip["queue"]:
                q.wait_s += dt
                self.burn(q, M.FUEL_LPH["idle"], dt)
            tr = tip["busy"]
            if tr is not None:
                tr.timer -= dt
                if tr.timer <= 0:
                    if place == "ROM":
                        self.rom += tr.payload
                        self.ore_to_rom += tr.payload
                        self.deliveries.append((self.t, "rom", tr.payload, tr.grade))
                    else:
                        self.dump_t += tr.payload
                        self.waste_t += tr.payload
                        self.deliveries.append((self.t, "waste", tr.payload, 0.0))
                    tip["busy"] = None
                    self.finish_trip(tr)
        # fuel station: one bay
        if self.fuel_busy is None and self.fuel_queue:
            self.fuel_busy = self.fuel_queue.popleft()
            self.fuel_busy.state = "fueling"
            self.fuel_busy.timer = M.TRUCK["refuel_s"]
        tr = self.fuel_busy
        if tr is not None:
            tr.timer -= dt
            if tr.timer <= 0:
                tr.fuel_l = M.TRUCK["tank_l"]
                self.fuel_busy = None
                self.event(f"{tr.id}: заправлен")
                tr.state = "idle"
                self.assign_next(tr)
        # trucks on the road
        for tr in self.trucks:
            if tr.route:
                self.drive(tr, dt)
            elif tr.state == "parked":
                tr.speed = 0.0
            elif tr.state in ("to_shovel", "hauling", "to_fuel", "to_park"):
                self.arrive(tr)
        while self.deliveries and self.t - self.deliveries[0][0] > 3600:
            self.deliveries.popleft()

    def finish_trip(self, tr):
        tr.trips += 1
        tr.tonnes += tr.payload
        if tr.cycle_start is not None:
            self.cycles.append((self.t, tr.material, self.t - tr.cycle_start))
        tr.payload = 0.0
        tr.grade = 0.0
        tr.material = None
        tr.state = "idle"
        self.assign_next(tr)

    # -------------------------------------------------------- decision support
    def rate_1h(self, kind):
        window = min(self.t, 3600.0) or 1.0
        return sum(w for t, k, w, g in self.deliveries if k == kind) * 3600 / window

    def grade_1h(self):
        tons = sum(w for t, k, w, g in self.deliveries if k in ("crusher", "rom"))
        return sum(w * g for t, k, w, g in self.deliveries if k in ("crusher", "rom")) / tons if tons else 0.0

    def ore_cycle_estimate(self, sid):
        """Model estimate of one ore cycle (s) from shovel sid via the current roads."""
        dst = "ROM" if self.scen["crusher_down"] else "CRUSHER"
        haul, hp = self.route(sid, dst, True)
        back, bp = self.route(dst, sid, False)
        if haul is None or back is None:
            return None, None
        return self.load_s(sid) + haul + M.TRUCK["dump_s"] + back + 60, self.route_km(hp)

    def analysis(self):
        """What the dispatcher should do now, in plain words, from the model."""
        recs = []
        mill = M.COS["mill_feed_tph"]
        ore_shovels = [s for s in ORE_SHOVELS if not self.shovels[s].down]
        best = None
        for s in ore_shovels:
            c, km = self.ore_cycle_estimate(s)
            if c is not None and (best is None or c < best[0]):
                best = (c, km, s)
        tph_per_truck = M.TRUCK["payload_t"] * 3600 / best[0] if best else 0.0
        ore_cap = sum(M.TRUCK["payload_t"] * 3600 / self.load_s(s) for s in ore_shovels)
        need = math.ceil(mill / tph_per_truck) if tph_per_truck else None
        on_ore = sum(1 for tr in self.trucks if not tr.parked and tr.shovel in ORE_SHOVELS
                     and tr.state not in ("to_fuel", "queue_fuel", "fueling"))
        active = sum(1 for tr in self.trucks if not tr.parked)
        ore_rate = self.rate_1h("crusher") + self.rate_1h("rom")
        crusher_in = self.rate_1h("crusher")
        net = crusher_in - mill if self.crusher_running else -mill
        hours_left = self.cos / -net if net < -1 else -1.0
        base_cycle, base_km = None, None
        if self.roads["r-ramp-a-up"].closed:
            self.roads["r-ramp-a-up"].closed = False
            self._route_cache.clear()
            base_cycle, base_km = self.ore_cycle_estimate("SH01")
            self.roads["r-ramp-a-up"].closed = True
            self._route_cache.clear()

        if self.scen["crusher_down"]:
            recs.append(f"ККД стоит: руду — на рудный склад; запаса перед мельницей хватит на {self.cos / mill:.1f} ч. "
                        f"Не останавливать экскавацию руды, после пуска ККД — догрузка со склада.")
        if best and base_cycle and self.scen["ramp_a_closed"]:
            recs.append(f"Съезд A закрыт: рудный рейс через съезд B и северную объездную {best[1]:.1f} км "
                        f"вместо {base_km:.1f} км, цикл {best[0] / 60:.0f} мин вместо {base_cycle / 60:.0f} мин. "
                        f"Для питания мельницы нужно {need} самосвалов на руде.")
        if self.shovels["SH02"].down:
            recs.append(f"ЭКГ-2 в ремонте: рудная производительность экскаваторов {ore_cap:,.0f} т/ч "
                        f"при потребности мельницы {mill:,.0f} т/ч. Самосвалы с ЭКГ-2 — на ЭКГ-1 и вскрышу.".replace(",", " "))
        if need is not None and on_ore < need and not self.scen["crusher_down"]:
            gap = need - on_ore
            recs.append(f"На руде {on_ore} самосвалов, нужно {need}: перевести {gap} со вскрыши (ЭКГ-3) на руду.")
        if need is not None and need > active:
            recs.append(f"Даже весь парк ({active} самосвалов) не закрывает потребность ({need}): "
                        f"снизить питание мельницы или вывести резервный самосвал.")
        if self.scen["dispatch_mode"] == "fixed":
            waiting = [tr.id for tr in self.trucks if tr.state in ("queue_shovel", "queue_crusher", "no_route")
                       and tr.wait_s > 0]
            idle_sh = [s for s, sh in self.shovels.items() if sh.state == "waiting_trucks"]
            if waiting or idle_sh:
                recs.append("Фиксированное закрепление: " +
                            (f"в очередях {len(waiting)} самосвалов" if waiting else "") +
                            (", " if waiting and idle_sh else "") +
                            (f"простаивают {', '.join(M.SHOVELS[s]['name'] for s in idle_sh)}" if idle_sh else "") +
                            ". Включите динамическую диспетчеризацию.")
        if 0 <= hours_left < 8:
            recs.append(f"Склад крупнодроблёной руды опустеет через {hours_left:.1f} ч — мельница встанет.")
        if self.scen["winter"]:
            recs.append("Гололёд: скорость −30 %, цикл длиннее — проверьте потребность в самосвалах выше.")
        if not recs:
            recs.append("Норма: питание мельницы обеспечено, очереди в пределах нормы.")
        return {
            "need_ore_trucks": need or 0,
            "on_ore_trucks": on_ore,
            "ore_cycle_min": round(best[0] / 60, 1) if best else 0,
            "ore_route_km": round(best[1], 2) if best else 0,
            "ore_tph_1h": round(ore_rate),
            "crusher_in_tph_1h": round(crusher_in),
            "cos_hours_left": round(hours_left, 1),
            "ore_dig_capacity_tph": round(ore_cap),
            "recommendations": recs,
        }
