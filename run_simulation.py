"""Runs the simulation described in OspSystemStructure.xml and saves the results to results/.

Run with:  python run_simulation.py   (with the conda environment master activated)
"""
import os
import tomllib
from pathlib import Path

import pandas as pd
from libcosimpy.CosimExecution import CosimExecution
from libcosimpy.CosimLogging import CosimLogLevel, log_output_level
from libcosimpy.CosimObserver import CosimObserver

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"

# 1. Change to this folder, so the relative path "config.toml" in
#    OspSystemStructure.xml points to the right file wherever the script is started from.
os.chdir(ROOT)

# 2. Read the simulation length from the same config file the FMU uses.
config = tomllib.loads(Path("config.toml").read_text(encoding="utf-8-sig"))
duration = config["simulation"]["duration"]

# 3. Load the system. config_path and the wind inputs are set from the XML here.
log_output_level(CosimLogLevel.WARNING)  # hide routine messages, show only warnings and errors
execution = CosimExecution.from_osp_config_file(osp_path="OspSystemStructure.xml")

# 4. Save every variable to one CSV file per FMU in results/.
RESULTS.mkdir(exist_ok=True)
for old in [*RESULTS.glob("*.csv"), *RESULTS.glob("*.yaml")]:
    old.unlink()
observer = CosimObserver.create_to_dir(log_dir=str(RESULTS))
execution.add_observer(observer=observer)

# 5. Run. The FMU reads config.toml here (in exit_initialization_mode) and
#    then calculates the loads every time step. libcosim measures time in nanoseconds.
if not execution.simulate_until(target_time=int(duration * 1e9)):
    raise RuntimeError("The simulation failed, see the error message above.")

# Close the simulation, so libcosim finishes writing the CSV file. Otherwise
# the last line may be half-written when it is read below.
del execution, observer

# 6. Show the result.
environment = pd.read_csv(next(RESULTS.glob("environment_*.csv")), index_col="Time")
vessel = pd.read_csv(next(RESULTS.glob("vessel_*.csv")), index_col="Time")
wind_speed = (environment["mean_wind_speed"] + environment["slowly_varying_wind_speed"]
              + environment["gust_wind_speed"]).iloc[-1]
print(f"Vessel:  {config['vessel']['type']}, simulated for {duration} s")
print(f"Wind:    {wind_speed:.1f} m/s from {environment['wind_direction_deg'].iloc[-1]:.1f} deg (NED, at the end)")
print(f"Current: {environment['current_speed'].iloc[-1]} m/s towards "
      f"{environment['current_direction_deg'].iloc[-1]} deg (NED)")

print("\nVessel at the end of the simulation:")
for name, unit in [("north", "m"), ("east", "m"), ("yaw", "rad")]:
    print(f"  {name:14} = {vessel[name].iloc[-1]:12.3f} {unit}")
for name, unit in [("wind_X", "N"), ("wind_Y", "N"), ("wind_N", "Nm")]:
    print(f"  {name:14} = {vessel[name].iloc[-1]:12.1f} {unit}")

kalman = pd.read_csv(next(RESULTS.glob("kalman_filter_*.csv")), index_col="Time")
print("\nKalman filter estimates at the end of the simulation:")
for name, unit in [("north_hat", "m"), ("east_hat", "m"), ("psi_hat", "rad"),
                   ("u_hat", "m/s"), ("v_hat", "m/s"), ("r_hat", "rad/s"),
                   ("b_x_hat", "N"), ("b_y_hat", "N"), ("b_n_hat", "Nm")]:
    print(f"  {name:9} = {kalman[name].iloc[-1]:12.4g} {unit}")

allocation = pd.read_csv(next(RESULTS.glob("allocation_*.csv")), index_col="Time")
dynamics = pd.read_csv(next(RESULTS.glob("dynamics_*.csv")), index_col="Time")
print(f"\nThrusters at the end of the simulation (utilisation {allocation['utilisation'].iloc[-1]:.3f}, "
      f"saturated {bool(allocation['saturated'].iloc[-1])}):")
for name, unit in [("X", "N"), ("Y", "N"), ("N", "Nm"), ("total_power_kw", "kW")]:
    print(f"  {name:14} = {dynamics[name].iloc[-1]:12.1f} {unit}")
