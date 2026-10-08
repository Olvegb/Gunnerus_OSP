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
result = pd.read_csv(next(RESULTS.glob("windloads_*.csv")), index_col="Time")
print(f"Vessel:  {config['vessel']['type']}, simulated for {duration} s")
print(f"Wind:    {config['wind']['mean_speed']} m/s from {config['wind']['direction_deg']} deg (earth frame)")
print(f"Heading: {environment['heading_deg'].iloc[-1]} deg")
print(f"Relative wind at WindLoads: {result['wind_speed'].iloc[-1]} m/s "
      f"from {result['relative_wind_direction_deg'].iloc[-1]} deg off the bow")
print("\nWind loads at the end of the simulation:")
for name, unit in [("X", "N"), ("Y", "N"), ("N", "Nm"), ("K", "Nm")]:
    print(f"  {name} = {result[name].iloc[-1]:12.1f} {unit}")
