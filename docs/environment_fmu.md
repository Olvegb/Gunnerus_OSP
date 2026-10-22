# Environment FMU

One FMU (FMI 2.0 co-simulation, built with pythonfmu 0.7.0, run in OSP) that gives the weather the
vessel sees: wind, sea state and current. Everything is in the earth-fixed **NED frame**, and the FMU
knows nothing about the vessel (no heading input). The vessel FMU turns the wind into relative wind
and loads itself. Owner: Olve.

```
                    ┌──mean, slowly varying, gust wind speed, wind_direction_deg──► VesselBlock
[wind], [waves],    │
[current] in  ──► Environment ──current_north, current_east──────────────────────► VesselBlock
config.toml         │
                    └──H_s, T_p, wave_direction_deg──► Waves ──wave<k>_*──► VesselBlock
```

## 1. Inputs, outputs, parameter

**Parameter**

| Name | Description |
|---|---|
| `config_path` | Path to `config.toml`, set in `OspSystemStructure.xml` |

**Inputs:** none.

**Outputs**

| Name | Unit | To | Description |
|---|---|---|---|
| `mean_wind_speed` | m/s | VesselBlock | V_mean, constant |
| `slowly_varying_wind_speed` | m/s | VesselBlock | V_sv, slowly varying part (zero mean) |
| `gust_wind_speed` | m/s | VesselBlock | V_gust, gust part (zero mean) |
| `wind_direction_deg` | deg | VesselBlock | Where the wind comes **from**, clockwise from north, 0–360 |
| `H_s`, `T_p` | m, s | Waves | Significant wave height and peak period, from `[waves]` |
| `wave_direction_deg` | deg | Waves | Where the waves come **from**, clockwise from north |
| `current_speed` | m/s | logging | Current speed |
| `current_direction_deg` | deg | logging | Where the current flows **to**, clockwise from north |
| `current_north`, `current_east` | m/s | VesselBlock | Current velocity components, NED |

The total wind speed V = V_mean + V_sv + V_gust is **not** an output. It is added up where it is used
(in the vessel FMU), so each part can be logged and plotted on its own.

## 2. Model

### Wind speed

```
V(t) = V_mean + V_sv(t) + V_gust(t)
```

**Slowly varying wind, V_sv.** A first-order Gauss-Markov process (Fossen, *Handbook of Marine Craft
Hydrodynamics and Motion Control*, wind models). It is discretised exactly, so the statistics do not
depend on the step size:

```
x[k+1] = a x[k] + σ √(1 − a²) w[k],    a = exp(−dt / T),    w[k] ~ N(0, 1)
```

T is the time constant and σ the stationary standard deviation. The process starts in its stationary
distribution, so there is no start-up transient.

**Gusts, V_gust.** A sum of harmonics from the NORSOK N-003 / ISO 19901-1 (Frøya) wind spectrum, with
random phases:

```
V_gust(t) = Σᵢ √(2 S(fᵢ) Δfᵢ) cos(2π fᵢ t + φᵢ)

S(f) = 320 (U₀/10)² (z/10)^0.45 / (1 + f̃ⁿ)^(5/(3n)),    f̃ = 172 f (z/10)^(2/3) (U₀/10)^(−3/4),    n = 0.468
```

U₀ is `mean_speed` (1-hour mean at 10 m) and z is `reference_height`. The frequencies are spread
logarithmically between `f_min` and `f_max`, and each one is drawn at random inside its band so the
signal does not repeat itself.

**Avoid double counting.** The NORSOK spectrum also covers low frequencies. Keep `f_min` above the
slowly varying band (about 1/(2πT) Hz), or use only one of the two parts.

### Wind direction

```
β(t) = β_mean + rate · t + β_sv(t)
```

- `rate`: a constant turning rate, for a steady veer.
- β_sv: a slow random variation, the same Gauss-Markov process as V_sv.

### Waves and current

Both are constant and passed straight on from the config file. The Waves FMU turns the sea state into
wave components (see [waves_fmu.md](waves_fmu.md)). The current is given as speed and direction in
`config.toml` and sent out both that way and as NED components:

```
current_north = V_c cos(β_c),    current_east = V_c sin(β_c)
```

### Switching parts off

Set the part to 0 in `config.toml`. No rebuild is needed:

| Part | Set |
|---|---|
| Slowly varying wind speed | `[wind.slowly_varying] std = 0` |
| Gusts | `[wind.gust] n_components = 0` |
| Direction variation | `[wind.direction_variation] rate_deg_per_s = 0` and `std_deg = 0` |
| Current | `[current] speed = 0` |

### Randomness

`[wind] seed` seeds all wind randomness (V_sv, gust frequencies and phases, β_sv). Same seed = the same
wind every run. The waves have their own `seed` in `[waves]`.

## 3. `config.toml`

| Key | Description |
|---|---|
| `[wind] mean_speed` | V_mean, 1-hour mean [m/s] |
| `[wind] direction_deg` | β_mean, where the wind comes from [deg] |
| `[wind] reference_height` | Height the wind speed is given for, used in the spectrum [m] |
| `[wind] seed` | Random seed |
| `[wind.slowly_varying] time_constant`, `std` | T [s] and σ [m/s] of V_sv |
| `[wind.gust] f_min`, `f_max` | Frequency range of the gusts [Hz] |
| `[wind.gust] n_components` | Number of harmonics |
| `[wind.direction_variation] rate_deg_per_s` | Constant turning rate, clockwise positive [deg/s] |
| `[wind.direction_variation] time_constant`, `std_deg` | T [s] and σ [deg] of β_sv |
| `[waves] hs`, `tp`, `direction_deg` | Sea state, sent on to the Waves FMU |
| `[current] speed`, `direction_deg` | Current speed [m/s] and where it flows to [deg] |

**Changing `config.toml` needs no rebuild.**

## 4. Files

| File | What it does |
|---|---|
| `models/environment.py` | The FMU, everything in one file |
| `tests/environment/check_environment.py` | Checks without OSP: everything switched off gives constant outputs; V_sv has zero mean, the right std and time constant, also with another step size; the gust std matches the NORSOK spectrum; the direction follows mean + rate · t and stays in [0, 360); the current components; the seed |

Run from the repo folder:

```
python tests/environment/check_environment.py
```

Result with the default config:

| Check | Expected | Result |
|---|---|---|
| V_sv std (T = 300 s, dt = 0.1 s / 1.0 s) | 1.0 m/s | 0.995 / 0.974 m/s |
| V_sv correlation after T | e⁻¹ = 0.368 | 0.366 / 0.356 |
| Gust std (one hour) | 1.395 m/s (spectrum) | 1.373 m/s |

## 5. Known limitations

- The current is constant: no tidal variation and no depth profile (`current_down` on the vessel is 0).
- The wind is the same everywhere: no spatial coherence over the vessel length.
- The wind direction variation does not change the gust spectrum or the mean speed.
- The default parameters (T, σ, f_min, …) are reasonable starting values, not taken from a source.
  Justify them before using the results.
