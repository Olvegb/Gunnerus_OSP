"""Builds every model in models/ into an FMU in fmus/.

Run again only when a .py file in models/ changes.
Changes to config.toml do NOT need a rebuild.

Does the same as running this for each model:
    pythonfmu build -f models/windloads.py thruster_cosim -d fmus
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

for script in sorted((ROOT / "models").glob("*.py")):
    print(f"Building {script.name} ...")
    # sys.executable is the Python of the active conda environment, so its pythonfmu is used.
    # thruster_cosim/ goes into the FMU's resources/, which is on sys.path when the FMU runs.
    subprocess.run([sys.executable, "-m", "pythonfmu", "build", "-f", script, ROOT / "thruster_cosim",
                    "-d", ROOT / "fmus"], check=True)
