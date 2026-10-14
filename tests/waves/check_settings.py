"""Quick check of wave_cosim/settings.py. Run from the repo folder:  python tests/waves/check_settings.py

Reads [waves] from config.toml and builds the sea ONLY from that, the same way the Waves FMU does it.
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]       # the repo folder
sys.path.insert(0, str(ROOT))                    # so wave_cosim/ and models/ can be imported

import numpy as np

from models.waves import N_WAVES
from wave_cosim.sea_state import sea_from_settings
from wave_cosim.settings import load_settings, settings_from_config

CONFIG = ROOT / "config.toml"
waves = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))["waves"]
settings = load_settings(CONFIG)

print("SETTINGS FROM config.toml:")
for name, value in settings.items():
    print(f"  {name:20s} = {value}")

print(f"SEA STATE FROM [waves]: H_s = {waves['hs']} m, T_p = {waves['tp']} s, from {waves['direction_deg']} deg")
sea, kept = sea_from_settings(waves["hs"], waves["tp"], settings, N_WAVES)
n_grid = settings["n_frequencies"] * (settings["n_directions"] if settings["spreading_type"] != "none" else 1)
hs_kept = 4 * np.sqrt(np.sum(0.5 * sea.amplitudes**2))
print(f"  Sea type: {settings['sea_type']}")
if settings["sea_type"] == "irregular":
    print(f"  Grid: {n_grid} components. Sent out: the {N_WAVES} strongest")
print(f"  Kept energy: {kept:.1%}  ->  H_s of the components sent out = {hs_kept:.2f} m (full sea: {waves['hs']} m)")
nonzero = sea.frequencies[sea.amplitudes > 0]
print(f"  Frequencies sent out: {nonzero.min():.2f} to {nonzero.max():.2f} rad/s "
      f"(peak frequency {2 * np.pi / waves['tp']:.2f} rad/s)")

print("CHECK THAT A WRONG NAME IN THE CONFIG IS CAUGHT:")
wrong = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))
wrong["waves"]["spreading"]["type"] = "cos-2s"
try:
    settings_from_config(wrong)
except ValueError as error:
    print(f"  {error}")
