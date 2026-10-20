"""Reads the simulation results and config.toml for the results app.

Plain Python and pandas, no Streamlit, so it can be used and checked on its own.

run_simulation.py puts every run in its own folder, results/<YYYYMMDD_HHMMSS>[_name]/,
with a copy of the config it was run with (config.toml). libcosim writes one
CSV per FMU there, named <simulator>_<YYYYMMDD>_<HHMMSS>_<microseconds>.csv,
where <simulator> is the name in OspSystemStructure.xml (environment, vessel, ...).
"""
import re
import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]       # the repo folder
RESULTS = ROOT / "results"
CONFIG = ROOT / "config.toml"

CSV_NAME = re.compile(r"^(?P<simulator>.+)_\d{8}_\d{6}_\d+\.csv$")
WAVE_COLUMN = re.compile(r"^wave\d+_")


def result_files(folder):
    """{simulator: newest CSV file} in a results folder."""
    files = {}
    for path in sorted(Path(folder).glob("*.csv")):  # sorted by name = by time stamp
        match = CSV_NAME.match(path.name)
        if match:
            files[match["simulator"]] = path
    return files


def load_results(folder):
    """{simulator: DataFrame indexed by time [s]}. The config_path column is dropped."""
    results = {}
    for simulator, path in result_files(folder).items():
        df = pd.read_csv(path, index_col="Time")
        results[simulator] = df.drop(columns=["StepCount", "config_path"], errors="ignore")
    return results


def folder_stamp(folder):
    """Changes whenever a CSV file in the folder changes. Used as a cache key."""
    return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(Path(folder).glob("*.csv")))


def list_runs(results=RESULTS):
    """[(label, folder)] of every run folder with CSV files, newest first.

    Older flat results directly in results/ (from before run folders, or from
    cosim CLI) are listed last.
    """
    results = Path(results)
    if not results.is_dir():
        return []
    runs = [(d.name, d) for d in sorted(results.iterdir(), reverse=True) if d.is_dir() and any(d.glob("*.csv"))]
    if any(results.glob("*.csv")):
        runs.append(("results/ (loose files)", results))
    return runs


def run_config_path(folder):
    """The config a run was made with, or None for runs without a copy."""
    path = Path(folder) / "config.toml"
    return path if path.is_file() else None


def load_config(path=CONFIG):
    return tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))


def thruster_slots(config):
    """[(slot number, name)] for the thrusters in config.toml, in slot order."""
    return [(k, thruster["name"]) for k, thruster in enumerate(config.get("thrusters", []), start=1)]


def total_wind_speed(environment):
    return (environment["mean_wind_speed"] + environment["slowly_varying_wind_speed"]
            + environment["gust_wind_speed"])


# Arrow length per quantity in the footprint plot: an arrow is full length at this value.
ENVIRONMENT_REFERENCE = {"Wind": 20.0, "Waves": 5.0, "Current": 1.0}


def summary(results, config):
    """Key numbers of a run, as {label: (value, unit)}. Missing data is skipped."""
    out = {}
    first = next(iter(results.values()), None)
    if first is not None and len(first):
        out["Simulated time"] = (first.index[-1], "s")
    dp = results.get("dp_controller")
    if dp is not None and len(dp):
        distance = (dp["error_north"] ** 2 + dp["error_east"] ** 2) ** 0.5
        out["Position error, end"] = (distance.iloc[-1], "m")
        out["Position error, max"] = (distance.max(), "m")
        out["Heading error, max"] = (dp["error_heading_deg"].abs().max(), "deg")
    dynamics = results.get("dynamics")
    if dynamics is not None and len(dynamics):
        out["Power, mean"] = (dynamics["total_power_kw"].mean(), "kW")
        out["Power, max"] = (dynamics["total_power_kw"].max(), "kW")
    allocation = results.get("allocation")
    if allocation is not None and len(allocation):
        out["Utilisation, max"] = (allocation["utilisation"].max(), "")
        out["Time saturated"] = (100.0 * allocation["saturated"].astype(bool).mean(), "%")
    environment = results.get("environment")
    if environment is not None and len(environment):
        out["Wind speed, mean"] = (total_wind_speed(environment).mean(), "m/s")
    return out
