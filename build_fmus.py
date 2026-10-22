"""Builds every model in models/ into an FMU in fmus/.

Run again only when a .py file in models/ changes.
Changes to config.toml do NOT need a rebuild.

Does the same as running this for each model:
    pythonfmu build -f models/vessel.py thruster_cosim wave_cosim vessel_cosim -d fmus
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# pythonfmu imports each model while building, to find its variables. That
# import only sees models/, so put ROOT on PYTHONPATH for the *_cosim packages.
env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}

for script in sorted((ROOT / "models").glob("*.py")):
    print(f"Building {script.name} ...")
    # sys.executable is the Python of the active conda environment, so its pythonfmu is used.
    # thruster_cosim/, wave_cosim/ and vessel_cosim/ go into the FMU's resources/, which is on sys.path when the FMU runs.
    subprocess.run([sys.executable, "-m", "pythonfmu", "build", "-f", script, ROOT / "thruster_cosim",
                    ROOT / "wave_cosim", ROOT / "vessel_cosim", "-d", ROOT / "fmus"], check=True, env=env)
