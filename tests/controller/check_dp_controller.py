"""Check the DPController FMU code WITHOUT building an FMU and without OSP.
Run from the repo folder:  python tests/controller/check_dp_controller.py

Creates the DPController class from models/dp_controller.py and checks the
signs: the commanded force must push the vessel back towards the set-point,
also when the vessel has another heading.
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]       # the repo folder
sys.path.insert(0, str(ROOT))                    # so models/ can be imported

import numpy as np

from app.data import default_config  # noqa: E402
from models.dp_controller import OUTPUTS, DPController, total_tau

CONFIG = default_config()                        # the config the simulation uses (OspSystemStructure.xml)
DT = 0.1                                         # time step [s], as in OspSystemStructure.xml


def controller():
    """A started controller with the config the simulation uses. The checks assume set-point north 0, east 0, heading 0."""
    fmu = DPController(instance_name="dp_controller")
    fmu.config_path = str(CONFIG)
    fmu.exit_initialization_mode()
    return fmu


def tau(**estimates):
    """tau after one step for the given estimates (the rest are 0). psi_hat in degrees here."""
    fmu = controller()
    for name, value in estimates.items():
        setattr(fmu, name, np.radians(value) if name == "psi_hat" else value)
    fmu.do_step(0.0, DT)
    return total_tau(fmu) + 0.0                  # + 0.0 turns -0 into 0


def show(text, t, expected):
    print(f"  {text:45s} tau_X = {t[0]:10.0f} N,  tau_Y = {t[1]:10.0f} N,  tau_N = {t[2]:12.0f} Nm   ({expected})")


config = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))
fmu = controller()
print("GAINS FROM [vessel] AND [controller]:")
for name, gain in (("Kp", fmu.kp), ("Ki", fmu.ki), ("Kd", fmu.kd)):
    print(f"  {name} = {gain}  [surge, sway, yaw]")
print(f"  {len(OUTPUTS)} outputs: {', '.join(OUTPUTS)}")

print("CHECK AT THE SET-POINT:")
show("At the set-point, not moving", tau(), "should be 0")

print("CHECK THE P TERM (heading north):")
show("10 m north of the set-point", tau(north_hat=10.0), "tau_X < 0: push back south")
show("10 m east of the set-point", tau(east_hat=10.0), "tau_Y < 0: push back west")
show("Heading 10 deg (set-point 0 deg)", tau(psi_hat=10.0), "tau_N < 0: turn back")
show("Heading 359 deg (set-point 0 deg)", tau(psi_hat=359.0), "tau_N > 0: turn 1 deg, not 359")

print("CHECK THE ROTATION (heading east, 90 deg):")
t = tau(north_hat=10.0, psi_hat=90.0)
show("10 m north, bow pointing east", t, "tau_Y > 0: starboard = south")

print("CHECK THE D TERM (at the set-point, moving):")
show("Moving forward at 1 m/s", tau(u_hat=1.0), "tau_X < 0: brake")
show("Turning at 0.01 rad/s", tau(r_hat=0.01), "tau_N < 0: brake")

print("CHECK THE I TERM AND ANTI-WINDUP (10 m north, held there):")
fmu = controller()
fmu.north_hat = 10.0
t = 0.0
for minutes in (1, 10, 100):
    while t < minutes * 60.0 - 1e-9:
        fmu.do_step(t, DT)
        t += DT
    integral_force = -fmu.ki[0] * fmu.z[0]
    print(f"  after {minutes:3d} min: integral term = {integral_force:9.0f} N   "
          f"(limit {config['controller']['integral_force_limit'][0]:.0f} N)")
