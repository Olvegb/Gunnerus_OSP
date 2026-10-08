"""Builds every model in models/ into an FMU in fmus/.

Run again only when a .py file in models/ changes.
Changes to config.toml do NOT need a rebuild.

Does the same as running this for each model:
    pythonfmu build -f models/windloads.py -d fmus
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

for script in sorted((ROOT / "models").glob("*.py")):
    print(f"Building {script.name} ...")
    # sys.executable is the Python of the active conda environment, so its pythonfmu is used.
    subprocess.run([sys.executable, "-m", "pythonfmu", "build", "-f", script, "-d", ROOT / "fmus"], check=True)
