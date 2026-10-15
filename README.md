# Gunnerus_OSP_sim – DP co-simulation where each FMU reads the config file itself

A complete DP (dynamic positioning) simulator in OSP, with one closed loop of seven FMUs:

- **Environment** gives the wind (mean, slowly varying and gust speed, slowly varying direction), the sea state (H_s, T_p, wave direction) and the current, all in the earth-fixed NED frame. See [docs/environment_fmu.md](docs/environment_fmu.md).
- **Waves** turns the sea state into 100 regular wave components (amplitude, frequency, phase, direction). Regular or irregular (long- or short-crested) sea. See [docs/waves_fmu.md](docs/waves_fmu.md).
- **VesselBlock** is the 6-DOF hull: low-frequency (LF) and wave-frequency (WF) motion, with wind loads (Blendermann), wave loads and current calculated inside. See [docs/vessel_fmu.md](docs/vessel_fmu.md).
- **ExtendedKalmanFilter** estimates the vessel's position, velocity and slowly varying disturbances (bias) from the measured position and heading. See [docs/kalman_filter.md](docs/kalman_filter.md).
- **DPController** is a simple PID that holds the vessel at the set-point in `config.toml`. See [docs/dp_controller.md](docs/dp_controller.md).
- **ThrustAllocation** and **ThrusterDynamics** turn the commanded force τ = (X, Y, N) into thrust and azimuth commands per thruster, and then into the force the thrusters actually give the vessel. See [docs/thruster_fmus.md](docs/thruster_fmus.md).

Plus **Test**, a minimal example FMU (output = input × test) that is not connected to anything.

Every constant is in one file, `config.toml`. Each FMU reads that file itself when the simulation starts, so you can change constants and run again **without rebuilding the FMUs**.

This is option **B3** in [Configfile_ways.md](../Configfile_ways.md).

> **Note:** the vessel data in `[vessel_fmu]` (`vessel_cosim/example_test_config.json`) and the 3-DOF matrices in `[vessel]` are **synthetic placeholder values** for an 88 m OSV, not RV Gunnerus.

## Documentation

| Doc | FMU |
|---|---|
| [docs/environment_fmu.md](docs/environment_fmu.md) | Environment: wind, sea state and current models, `config.toml` keys |
| [docs/waves_fmu.md](docs/waves_fmu.md) | Waves: inputs and outputs, `config.toml` keys, the wave elevation the hull must use |
| [docs/vessel_fmu.md](docs/vessel_fmu.md) | VesselBlock: the hull model and its data file |
| [docs/kalman_filter.md](docs/kalman_filter.md) | ExtendedKalmanFilter: states, process and measurement model, tuning |
| [docs/dp_controller.md](docs/dp_controller.md) | DPController: the control law, gains, `config.toml` keys |
| [docs/thruster_fmus.md](docs/thruster_fmus.md) | ThrustAllocation and ThrusterDynamics: allocation, dynamics, power, `config.toml` keys |

## Getting started

Run from this folder in the VS Code terminal:

```powershell
conda activate master
pip install -r requirements.txt   # once: the libraries the simulation needs
python build_fmus.py              # creates one .fmu in fmus/ for each .py in models/
python run_simulation.py          # runs the simulation and saves the results to results/
```

Expected output (10 s, default `config.toml`):

```
Vessel:  offshore_supply_vessel, simulated for 10.0 s
Wind:    14.6 m/s from 97.3 deg (NED, at the end)
Current: 0.5 m/s towards 0 deg (NED)

Vessel at the end of the simulation:
  north          =        0.316 m
  east           =       -0.398 m
  yaw            =       -0.011 rad
  wind_X         =       3936.3 N
  wind_Y         =     -82860.4 N
  wind_N         =    -820747.0 Nm

Kalman filter estimates at the end of the simulation:
  north_hat =       0.2918 m
  ...

Thrusters at the end of the simulation (utilisation 0.140, saturated False):
  X              =      10413.1 N
  Y              =      65189.0 N
  N              =    -742876.0 Nm
  total_power_kw =        116.5 kW
```

The wind comes from the east, so it pushes the vessel west (east < 0) and gives a force to port (wind_Y < 0). The current pushes it north. The thrusters push back.

**Try it** (no rebuild needed, only `python run_simulation.py` again):
- Set `duration = 300.0` in `[simulation]` and look at `results/vessel_*.csv`: the vessel drifts about 4 m in the first minute, and the controller then brings it back to within 1 m of the set-point.
- Switch the gusts off with `n_components = 0` in `[wind.gust]`, or the current off with `speed = 0.0` in `[current]`.
- Change `north_ref` in `[controller]` and watch the vessel move to the new set-point.

## Commands

All commands are run from this folder, with the `master` environment active (`conda activate master`).

| What | Command |
|---|---|
| Install the libraries (once) | `pip install -r requirements.txt` |
| Install scipy with OpenBLAS (if missing) | `conda install -n master scipy=1.14.1 "libblas=*=*openblas"` |
| Build every FMU | `python build_fmus.py` |
| Build one FMU | `python -m pythonfmu build -f models/environment.py thruster_cosim wave_cosim vessel_cosim -d fmus` |
| Run the simulation (Python) | `python run_simulation.py` |
| Run the simulation (cosim CLI) | `cosim run OspSystemStructure.xml -d 10 --output-dir results` |
| Waves checks | `python tests/waves/check_waves_fmu.py` (and the other scripts in `tests/waves/`) |
| Controller checks | `python tests/controller/check_dp_controller.py`, `python tests/controller/check_closed_loop.py` |
| Vessel check (needs fmpy) | `python tests/vessel/check_vessel_fmu.py` |

**Rebuild only when a `.py` file changes** (in `models/` or a `*_cosim/` package). Changes to `config.toml` and `OspSystemStructure.xml` need no rebuild.

When building one FMU by hand, include the `*_cosim/` packages the model imports (`thruster_cosim`, `wave_cosim`, `vessel_cosim`). `build_fmus.py` does this for every model, and also puts this folder on `PYTHONPATH` so pythonfmu can import the packages while building.

## The files

| File | What it does | When do you change it? |
|---|---|---|
| `config.toml` | **Every constant**: environment, vessel, controller, filter, thrusters, simulation length | When you want to change a value. No rebuild. |
| `OspSystemStructure.xml` | Which FMUs are included, how they are connected, step size, and **where the config file is** | When you add FMUs or connections |
| `models/environment.py` | Environment FMU. Wind, sea state and current from `config.toml`, NED | When the logic changes. Needs a rebuild. |
| `models/waves.py` | Waves FMU. Thin wrapper around `wave_cosim/` | When the logic changes. Needs a rebuild. |
| `models/vessel.py` | VesselBlock FMU. Thin wrapper around `vessel_cosim/` | When the logic changes. Needs a rebuild. |
| `models/kalman_filter.py` | ExtendedKalmanFilter FMU, everything in one file | When the logic changes. Needs a rebuild. |
| `models/dp_controller.py` | DPController FMU, everything in one file | When the logic changes. Needs a rebuild. |
| `models/thrust_allocation.py`, `models/thruster_dynamics.py` | ThrustAllocation and ThrusterDynamics FMUs. Thin wrappers around `thruster_cosim/` | When the logic changes. Needs a rebuild. |
| `models/test.py` | Test FMU, a minimal example of the set-up | Never |
| `wave_cosim/`, `vessel_cosim/`, `thruster_cosim/` | The wave, vessel and thruster logic. Built into every FMU's `resources/` | When the logic changes. Needs a rebuild. |
| `tests/` | Check scripts for waves, controller and vessel | When that logic changes |
| `docs/` | One document per FMU | When an FMU changes |
| `build_fmus.py` | Turns each `.py` in `models/` into an `.fmu` in `fmus/`, with the `*_cosim/` packages included | Rarely |
| `run_simulation.py` | Runs the simulation from Python and prints the result | When you want other output |
| `requirements.txt` | The Python libraries the simulation needs | When a library is added |
| `fmus/` | The built FMUs | Created by `build_fmus.py` |
| `results/` | One CSV file per FMU with every input and output for each time step | Created by `run_simulation.py` |

## How it fits together

```
 environment ──► wind (mean, slowly varying, gust, direction), current ──────────────┐
      │                                                                               │
      └──► H_s, T_p, wave_direction ──► waves ──► wave<k>_* (k = 1..100) ─────────────┤
                                                                                      ▼
 dynamics ──► X, Y, N (delivered thrust, body) ─────────────────────────────────► vessel
    ▲  │                                                                              │
    │  └──► tau_thr_x/y/n ──────────────┐                north, east, yaw ────────────┤
    │                                   ▼                                             │
    │                             kalman_filter ◄── tau_wind_x/y/n (wind_X/Y/N) ──────┘
    │                                   │
    │                                   ▼  north_hat ... r_hat
    │                             dp_controller
    │                                   │
    │                                   ▼  tau_X, tau_Y, tau_N
    └── thrust + azimuth command ◄── allocation      (8 thruster slots)
```

Step by step, when you run `python run_simulation.py`:

1. **The system is loaded.** libcosim reads `OspSystemStructure.xml`, loads every FMU and sets `config_path = "config.toml"` on each.
2. **The FMUs read the config file.** Right before the simulation starts, each FMU runs `exit_initialization_mode()` and takes what it needs from `config.toml` (see the table at the top of that file).
3. **The simulation runs.** Every time step (0.1 s), each FMU runs `do_step()`, and libcosim passes the outputs to the inputs through the `<VariableConnection>`s.
4. **The results are saved** to `results/` (one CSV per FMU), and `run_simulation.py` prints the last values.

### Frames and angle conventions

- **NED** (north, east, down) for the environment and the vessel position. **Body frame** (x forward, y to starboard, z down) for forces, velocities and thruster positions.
- Angles in `config.toml` and on the environment are in **degrees, clockwise from north**. The vessel's `yaw` and the filter's `psi` are in **radians**.

| Angle | 0° means | 90° means |
|---|---|---|
| Wind direction (`[wind] direction_deg`) | wind comes **from** north | wind comes from east |
| Wave direction (`[waves] direction_deg`) | waves come **from** north | waves come from east |
| Current direction (`[current] direction_deg`) | current flows **towards** north | current flows towards east |
| Heading (vessel `yaw`) | bow points north | bow points east |

The relative wind (wind seen from the vessel) is calculated inside VesselBlock, from the wind direction, the heading and the vessel's own velocity.

## Key concepts in the FMU

In every FMU in `models/` the variables fall into four kinds. Examples from `models/environment.py`:

| Kind | Example | Where does the value come from? |
|---|---|---|
| **Parameter** | `config_path` | Set once before the start, here from the XML |
| **Input** | (VesselBlock: `mean_wind_speed`) | Can change every time step. Comes from another FMU through a connection, or a fixed value from the XML |
| **Constant** | `mean_wind_direction_deg`, the gust components | Read from `config.toml`. Plain Python variables inside the FMU, not FMI variables. |
| **Output** | `mean_wind_speed`, `wind_direction_deg` | Calculated in `do_step()` and can be connected to other FMUs |

**Why isn't the config file read in `__init__`?** `__init__` also runs when the FMU is *built* (PythonFMU creates an instance to find the variables), and `config_path` is not set at that point. So the file is read in `exit_initialization_mode()`, which only runs when the simulation actually starts.

## Adding more

**A new constant in an existing FMU:**
1. Add it to `config.toml`, in the section that FMU reads.
2. Read it in `exit_initialization_mode()` and store it as `self.name`.
3. Use it in `do_step()`.
4. Run `python build_fmus.py` (because the `.py` file changed).

**A new FMU that uses the same config:**
1. Write `models/new_model.py` the same way: a `config_path` parameter, and read the file in `exit_initialization_mode()`.
2. Run `python build_fmus.py`.
3. Add it to `OspSystemStructure.xml` with its own `<InitialValue variable="config_path">`, and connect inputs and outputs with `<VariableConnection>`.
4. Add a document in `docs/` and a line in the tables above.

## Good to know

- **Relative path.** `config_path = "config.toml"` is read from the folder the simulation is started from. `run_simulation.py` changes to this folder itself. With cosim CLI you must stand in this folder. With OSP-GUI it is safest to write a full path, such as `C:\Users\...\Gunnerus_OSP_sim\config.toml`, in the XML.
- **Save the config file as UTF-8.** VS Code does this automatically.
- **Python must be available when the FMU runs.** FMUs made with PythonFMU use the Python on the machine. So run with the `master` environment activated, also from the CLI. That Python needs the libraries in `requirements.txt`, including **scipy** for ThrustAllocation.
- **numpy must use OpenBLAS, not MKL.** On the NTNU virtual PC, `numpy.linalg` with MKL crashes Python without an error message. Fix: `conda install -n master "libblas=*=*openblas"`.
- **Filenames on Windows.** Git cannot check out a file whose name ends with a dot (such as `README.md.`). If `git pull` fails with `invalid path`, rename the file on GitHub.
- **The CSV files have 6 significant digits**, for example `1.60439e+06`. That is how libcosim writes them.



- **cosim CLI:** ` cosim run OspSystemStructure.xml -d 10 --output-dir results`
- **Build one FMU commando** `python -m pythonfmu build -f models/environment.py -d fmus`
