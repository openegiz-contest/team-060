#!/usr/bin/env python3
"""
Pit simulator: runs the haul-cycle model (sim.py) and drives the twins.

  state  -> MQTT telemetry/<twin> as Ditto "modify /features" commands -> Ditto
  Ditto  -> MQTT opentwins/.../kz.aktogay.pit/control (twin events) -> scenarios

The What-if Scenarios are not read from a file or an argument: they are the
features of the twin kz.aktogay.pit:control in Ditto. The UI (or curl, or the
OpenEgiz app in Grafana) changes the twin, Ditto publishes the change, and the
simulator applies it on the next tick.
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt

import ditto
import model as M
from sim import Pit
from twins import snapshot

log = logging.getLogger("pit")
CONTROL = M.thing("control")


def modify(thing_id, features):
    ns, name = thing_id.split(":", 1)
    return {"topic": f"{ns}/{name}/things/twin/commands/modify", "path": "/features",
            "value": {k: {"properties": v} for k, v in features.items()}}


def read_scenarios():
    try:
        body = ditto.get(f"/things/{CONTROL}/features/scenarios/properties", timeout=5)
        return body if isinstance(body, dict) else None
    except Exception as exc:  # noqa: BLE001
        log.warning("cannot read scenarios from Ditto: %s", exc)
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    p.add_argument("--interval", type=float, default=float(os.environ.get("SIM_INTERVAL", "1")))
    p.add_argument("--speedup", type=float, default=float(os.environ.get("SIM_SPEEDUP", "6")))
    p.add_argument("--seed", type=int, default=int(os.environ.get("SIM_SEED", "7")))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--steps", type=int, default=0)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pit = Pit(args.seed)
    dirty = threading.Event()
    dirty.set()

    client = None
    if not args.dry_run:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"aktogay-pit-sim-{os.getpid()}")

        def on_connect(c, userdata, flags, rc, props=None):
            c.subscribe(f"opentwins/+/+/{M.NS}/control", qos=0)
            dirty.set()

        def on_message(c, userdata, msg):
            dirty.set()   # a change of the control twin: re-read its scenarios

        client.on_connect = on_connect
        client.on_message = on_message
        for _ in range(60):
            try:
                client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
                break
            except OSError as exc:
                log.warning("MQTT not reachable (%s), retrying", exc)
                time.sleep(2)
        else:
            return 1
        client.loop_start()

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    ticks = 0
    last_poll = 0.0
    while not stop:
        started = time.time()
        if not args.dry_run and (dirty.is_set() or started - last_poll > 5):
            dirty.clear()
            last_poll = started
            scen = read_scenarios()
            if scen is not None:
                pit.apply_scenarios(scen)
        sim_seconds = args.interval * args.speedup
        for _ in range(max(1, int(round(sim_seconds)))):
            pit.step(sim_seconds / max(1, int(round(sim_seconds))))
        snap = snapshot(pit)
        for tid, feats in snap.items():
            if ":r-" in tid and ticks % 3:
                continue   # roads change slowly
            msg = json.dumps(modify(tid, feats), ensure_ascii=False)
            if client:
                client.publish(f"telemetry/{tid.split(':', 1)[1]}", msg, qos=0)
            elif ticks == 0:
                print(msg[:300])
        ticks += 1
        if ticks % 60 == 0:
            m = snap[M.thing("mine")]
            log.info("%s | ore %s t/h | waste %s t/h | COS %s t | %s", m["sim_clock"]["value"], m["ore_tph_1h"]["value"],
                     m["waste_tph_1h"]["value"], snap[M.thing("cos")]["level"]["value"], pit.scen)
        if args.steps and ticks >= args.steps:
            break
        time.sleep(max(0.0, args.interval - (time.time() - started)))
    if client:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
