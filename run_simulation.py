"""Runs the simulation described in OspSystemStructure.xml and saves the results in a run folder.

Run with (with the conda environment master activated):

    python run_simulation.py                              # default config, results/<time stamp>/
    python run_simulation.py --name high_wind             # results/<time stamp>_high_wind/
    python run_simulation.py --config configs/other.toml  # another config file

The default config is the file in configs/ that OspSystemStructure.xml points
config_path to.
    python run_simulation.py --output results/my_run      # a chosen folder

Every run gets its own folder with one CSV per FMU and a copy of the config it
was run with (config.toml). Nothing from earlier runs is overwritten.
"""
import argparse
import os
import re
import tomllib
from datetime import datetime
from pathlib import Path

import pandas as pd
from libcosimpy.CosimExecution import CosimExecution
from libcosimpy.CosimLogging import CosimLogLevel, log_output_level
from libcosimpy.CosimObserver import CosimObserver

from app.config_tools import make_paths_absolute
from app.data import default_config

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def run_folder(name):
    """results/<YYYYMMDD_HHMMSS>[_name], with the name made safe for a folder."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return RESULTS / (f"{stamp}_{name}" if name else stamp)


def set_config_path(execution, config_path):
    """Points config_path on every FMU to the run's own copy of the config."""
    for slave in execution.slave_infos():
        for variable in execution.slave_variables(slave.index):
            if variable.name == b"config_path":
                execution.string_initial_value(slave.index, variable.reference, str(config_path))


def print_summary(run_dir, config):
    def last(simulator):
        return pd.read_csv(next(run_dir.glob(f"{simulator}_*.csv")), index_col="Time").iloc[-1]

    environment, vessel = last("environment"), last("vessel")
    wind_speed = (environment["mean_wind_speed"] + environment["slowly_varying_wind_speed"]
                  + environment["gust_wind_speed"])
    print(f"Vessel:  {config['vessel']['type']}, simulated for {config['simulation']['duration']} s")
    print(f"Wind:    {wind_speed:.1f} m/s from {environment['wind_direction_deg']:.1f} deg (NED, at the end)")
    print(f"Current: {environment['current_speed']} m/s towards {environment['current_direction_deg']} deg (NED)")

    print("\nVessel at the end of the simulation:")
    for name, unit in [("north", "m"), ("east", "m"), ("yaw", "rad")]:
        print(f"  {name:14} = {vessel[name]:12.3f} {unit}")
    for name, unit in [("wind_X", "N"), ("wind_Y", "N"), ("wind_N", "Nm")]:
        print(f"  {name:14} = {vessel[name]:12.1f} {unit}")

    kalman = last("kalman_filter")
    print("\nKalman filter estimates at the end of the simulation:")
    for name, unit in [("north_hat", "m"), ("east_hat", "m"), ("psi_hat", "rad"),
                       ("u_hat", "m/s"), ("v_hat", "m/s"), ("r_hat", "rad/s"),
                       ("b_x_hat", "N"), ("b_y_hat", "N"), ("b_n_hat", "Nm")]:
        print(f"  {name:9} = {kalman[name]:12.4g} {unit}")

    allocation, dynamics = last("allocation"), last("dynamics")
    print(f"\nThrusters at the end of the simulation (utilisation {allocation['utilisation']:.3f}, "
          f"saturated {bool(allocation['saturated'])}):")
    for name, unit in [("X", "N"), ("Y", "N"), ("N", "Nm"), ("total_power_kw", "kW")]:
        print(f"  {name:14} = {dynamics[name]:12.1f} {unit}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help="config file (default: the one OspSystemStructure.xml points to)")
    parser.add_argument("--name", default="", help="short name added to the run folder")
    parser.add_argument("--output", default=None, help="run folder (default: results/<time stamp>[_name])")
    args = parser.parse_args(argv)

    # 1. Change to this folder, so the relative paths in OspSystemStructure.xml
    #    (fmus/...) work wherever the script is started from.
    # The default config is the one in OspSystemStructure.xml; a given path is relative to where you stand.
    source = Path(args.config).resolve() if args.config else default_config()
    if not source.is_file():
        raise SystemExit(f"Config file not found: {source}")
    os.chdir(ROOT)

    # 2. Make the run folder and save the config there. Relative file paths in
    #    the config are made absolute, because the FMUs read them relative to
    #    the config file, which now lies in the run folder.
    run_dir = Path(args.output).resolve() if args.output else run_folder(args.name)
    run_dir.mkdir(parents=True, exist_ok=True)
    for old in [*run_dir.glob("*.csv"), *run_dir.glob("*.yaml")]:
        old.unlink()                             # only if an existing folder is reused with --output
    text = make_paths_absolute(source.read_text(encoding="utf-8-sig"), source.parent)
    run_config = run_dir / "config.toml"
    run_config.write_text(text, encoding="utf-8")
    config = tomllib.loads(text)

    # 3. Load the system, and point every FMU to the run's config.
    log_output_level(CosimLogLevel.WARNING)  # hide routine messages, show only warnings and errors
    execution = CosimExecution.from_osp_config_file(osp_path="OspSystemStructure.xml")
    set_config_path(execution, run_config)

    # 4. Save every variable to one CSV file per FMU in the run folder.
    observer = CosimObserver.create_to_dir(log_dir=str(run_dir))
    execution.add_observer(observer=observer)

    # 5. Run. The FMUs read the config here (in exit_initialization_mode).
    #    libcosim measures time in nanoseconds.
    if not execution.simulate_until(target_time=int(config["simulation"]["duration"] * 1e9)):
        raise RuntimeError("The simulation failed, see the error message above.")

    # Close the simulation, so libcosim finishes writing the CSV files. Otherwise
    # the last line may be half-written when it is read below.
    del execution, observer

    # 6. Show the result.
    print_summary(run_dir, config)
    print(f"\nResults: {run_dir}")
    return run_dir


if __name__ == "__main__":
    main()
