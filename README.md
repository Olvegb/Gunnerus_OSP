# Config_path_sim – co-simulation where the FMU reads the config file itself

A small, complete simulation program with three FMUs:

- **Environment** turns the wind in the earth frame (from `config.toml`) and the vessel heading into the wind seen from the vessel. It also outputs the sea state (H_s, T_p, wave direction).
- **WindLoads** (from `FMU_try`) calculates the wind forces and moments on the vessel with the Blendermann method.
- **ExtendedKalmanFilter** estimates the vessel's position, velocity and slowly varying disturbances (bias) from position and heading measurements. See [The Kalman filter](#the-kalman-filter).

Every constant is in one file, `config.toml`. Each FMU reads that file itself when the simulation starts, so you can change constants and run again **without rebuilding the FMUs**.

This is option **B3** in [Configfile_ways.md](../Configfile_ways.md).

## Getting started

Run from this folder in the VS Code terminal:

```powershell
conda activate master
python build_fmus.py       # creates fmus/Environment.fmu and fmus/WindLoads_Blendermann.fmu
python run_simulation.py   # runs the simulation and saves the results to results/
```

Expected output:

```
Vessel:  offshore_supply_vessel, simulated for 10.0 s
Wind:    13.8 m/s from 45.0 deg (earth frame)
Heading: 0 deg
Relative wind at WindLoads: 13.8 m/s from 45 deg off the bow

Wind loads at the end of the simulation:
  X =     -16046.4 N
  Y =      65644.3 N
  N =    1604390.0 Nm
  K =     236320.0 Nm
```

**Try it:**
- Change `type = "offshore_supply_vessel"` to `type = "ferry"` in `config.toml`, and run `python run_simulation.py` again without rebuilding. The loads change.
- Change `heading_deg` from `0.0` to `30.0` in `OspSystemStructure.xml`. The relative wind becomes 15 deg (45 − 30).

## The files

| File | What it does | When do you change it? |
|---|---|---|
| `config.toml` | **Every constant**: wind, vessel data, air density, Blendermann coefficients, simulation length | When you want to change a value. No rebuild. |
| `models/environment.py` | Environment FMU. Reads the wind from `config.toml`, takes the heading as input, outputs wind speed and relative wind direction. | When the logic changes. Needs a rebuild. |
| `models/windloads.py` | WindLoads FMU. Reads `config.toml` and calculates the wind loads. | When the logic changes. Needs a rebuild. |
| `models/kalman_filter.py` | ExtendedKalmanFilter FMU. Reads the vessel matrices and filter settings from `config.toml`, estimates position, velocity and bias. | When the logic changes. Needs a rebuild. |
| `build_fmus.py` | Turns each `.py` in `models/` into an `.fmu` in `fmus/` | Rarely |
| `OspSystemStructure.xml` | Which FMUs are included, how they are connected, step size, and **where the config file is** | When you add FMUs or connections |
| `run_simulation.py` | Runs the simulation from Python and prints the result | Rarely |
| `fmus/` | The built FMUs | Created by `build_fmus.py` |
| `results/` | One CSV file per FMU with every input and output for each time step | Created by `run_simulation.py` |

## How it fits together

```
                          config.toml (constants, read by both FMUs at start-up)
                         ┌─────────┴──────────┐
                         ▼                    ▼
 heading_deg ──► Environment FMU ──────► WindLoads FMU ──► X, Y, N, K
 (from XML)        [wind]          wind_speed,       [environment], [vessel],
                                   relative_wind_    [blendermann]
                                   direction_deg
```

Step by step, when you run `python run_simulation.py`:

1. **The system is loaded.** libcosim reads `OspSystemStructure.xml`, loads both FMUs and sets the start values from `<InitialValues>`: `config_path = "config.toml"` on both, and `heading_deg` on Environment.
2. **The FMUs read the config file.** Right before the simulation starts, each FMU runs `exit_initialization_mode()` and takes what it needs from `config.toml`. Environment takes `[wind]`. WindLoads takes `[environment]`, `[vessel]` and the row in `[blendermann]` that matches the vessel type.
3. **The simulation runs.** Every time step (0.1 s):
   - Environment calculates the relative wind direction, `(wind direction − heading) mod 360`, and the wind speed.
   - libcosim passes them to WindLoads through the `<VariableConnection>`s.
   - WindLoads calculates X, Y, N and K.
4. **The results are saved** to `results/` (one CSV per FMU), and `run_simulation.py` prints the last values.

### Angle conventions

All angles are in degrees and measured clockwise:

| Angle | 0° means | 90° means |
|---|---|---|
| Wind direction (`[wind] direction_deg`) | wind comes **from** north | wind comes from east |
| Heading (`heading_deg`) | bow points north | bow points east |
| Relative wind direction | wind comes from straight ahead | wind comes from starboard |

Example: wind from 45°, heading 30° → the wind comes 15° to starboard of the bow.

## The Kalman filter

`models/kalman_filter.py` is a 3-DOF extended Kalman filter (a simple DP observer, Fossen). It has 9 states:

| States | Meaning | Unit |
|---|---|---|
| `north`, `east`, `psi` | position and heading in NED | m, m, rad |
| `u`, `v`, `r` | velocity in the body frame | m/s, m/s, rad/s |
| `b_x`, `b_y`, `b_n` | bias in NED: every force the model doesn't know (current, wave drift, model errors) | N, N, Nm |

| Kind | Variables | Source |
|---|---|---|
| **Inputs** | `north_meas`, `east_meas`, `psi_meas` | GNSS and gyro. Not connected yet, so 0. Later from the hull FMU. |
| | `tau_thr_x`, `tau_thr_y`, `tau_thr_n` | Thruster forces, body frame. Not connected yet, so 0. |
| | `tau_wind_x`, `tau_wind_y`, `tau_wind_n` | Wind forces from WindLoads (feed-forward), body frame. |
| **Outputs** | `north_hat`, `east_hat`, `psi_hat`, `u_hat`, `v_hat`, `r_hat`, `b_x_hat`, `b_y_hat`, `b_n_hat` | The estimates |
| **Constants** | `mass_matrix`, `damping_matrix` (in `[vessel]`) | Shared with a future hull FMU. **Placeholder values.** |
| | `bias_time_constants`, `process_noise`, `measurement_noise`, `initial_covariance` (in `[kalman_filter]`) | Filter tuning |

Each time step it **predicts** the state with the process model and then **corrects** it with the measurement.

**Check that it works:** with the measurements at 0 (the vessel held still at the origin) and the wind pushing, the filter must explain the wind with a bias of the opposite sign. After about 30 s, `b_y_hat` and `b_n_hat` settle at about 97 % of −Y and −N from WindLoads. The bias time constant `T_b` pulls the estimate slightly towards 0, which is why it is not 100 %.

Not included yet: wave-frequency motion (6 extra states in Fossen's DP observer).

## Key concepts in the FMU

In `models/windloads.py` the variables fall into four kinds:

| Kind | Example | Where does the value come from? |
|---|---|---|
| **Parameter** | `config_path` | Set once before the start, here from the XML |
| **Input** | `wind_speed`, `heading_deg` | Can change every time step. Comes from another FMU through a connection, or a fixed value from the XML (like `heading_deg` until there is a hull FMU). |
| **Constant** | `loa`, `cd_t`, `air_density` | Read from `config.toml`. Plain Python variables inside the FMU, not FMI variables. |
| **Output** | `X`, `Y`, `N`, `K` | Calculated in `do_step()` and can be connected to other FMUs |

**Why isn't the config file read in `__init__`?** `__init__` also runs when the FMU is *built* (PythonFMU creates an instance to find the variables), and `config_path` is not set at that point. So the file is read in `exit_initialization_mode()`, which only runs when the simulation actually starts.

## Adding more

**A new constant in an existing FMU:**
1. Add it to `config.toml`, for example under `[vessel]`.
2. Add the name to `CONSTANTS` in `models/windloads.py`.
3. Use it in `do_step()` as `self.name`.
4. Run `python build_fmus.py` (because the `.py` file changed).

**Slowly varying wind, gusts etc. in Environment:**
1. Add the parameters to `[wind]` in `config.toml`, for example `gust_amplitude = 3.0`.
2. Read them in `exit_initialization_mode()` in `models/environment.py`.
3. Add the variation in `wind_speed_at(time)`, which only returns the mean wind for now.
4. Run `python build_fmus.py`.

**A new FMU that uses the same config:**
1. Write `models/new_model.py` the same way: a `config_path` parameter, and read the file in `exit_initialization_mode()`.
2. Run `python build_fmus.py`.
3. Add it to `OspSystemStructure.xml` with its own `<InitialValue variable="config_path">`, and connect inputs and outputs with `<VariableConnection>`.

Once several FMUs read the config file, it is worth moving the reading code into a shared file (for example `models/load_config.py`) and including it when building. That is not done here yet, to keep things simple.

## Good to know

- **Relative path.** `config_path = "config.toml"` is read from the folder the simulation is started from. `run_simulation.py` changes to this folder itself. With cosim CLI you must stand in this folder. With OSP-GUI it is safest to write a full path, such as `C:\Users\...\Config_path_sim\config.toml`, in the XML.
- **Save the config file as UTF-8.** VS Code does this automatically.
- **Python must be available when the FMU runs.** FMUs made with PythonFMU use the Python on the machine. So run with the `master` environment activated, also from the CLI.
- **numpy must use OpenBLAS, not MKL.** On the NTNU virtual PC, `numpy.linalg` with MKL crashes Python without an error message. Fix: `conda install -n master "libblas=*=*openblas"`.
- **The CSV files have 6 significant digits**, for example `1.60439e+06`. That is how libcosim writes them.
- **cosim CLI kommando;cosim run OspSystemStructure.xml -d 10 --output-dir results
