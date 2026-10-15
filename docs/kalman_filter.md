# Extended Kalman filter FMU

One FMU (FMI 2.0 co-simulation, built with pythonfmu 0.7.0, run in OSP) that estimates the vessel's
position, velocity and slowly varying disturbances from position and heading measurements. It is a
**simple 3-DOF DP observer** (surge, sway, yaw), after Fossen. Owner: Olve.

```
VesselBlock ──north, east, yaw──────────► ExtendedKalmanFilter ──north_hat ... r_hat──► DPController
VesselBlock ──wind_X, wind_Y, wind_N────►          │
ThrusterDynamics ──X, Y, N──────────────►          └──b_x_hat, b_y_hat, b_n_hat──► logging
                                [vessel] and [kalman_filter] in config.toml
```

## 1. Inputs, outputs, parameter

**Parameter**

| Name | Description |
|---|---|
| `config_path` | Path to `config.toml`, set in `OspSystemStructure.xml` |

**Inputs**

| Name | Unit | From | Description |
|---|---|---|---|
| `north_meas`, `east_meas` | m | VesselBlock (`north`, `east`) | Measured position, NED (GNSS) |
| `psi_meas` | rad | VesselBlock (`yaw`) | Measured heading (gyro) |
| `tau_thr_x`, `tau_thr_y` | N | ThrusterDynamics (`X`, `Y`) | Delivered thruster force, body frame |
| `tau_thr_n` | Nm | ThrusterDynamics (`N`) | Delivered thruster yaw moment |
| `tau_wind_x`, `tau_wind_y` | N | VesselBlock (`wind_X`, `wind_Y`) | Wind force (feed-forward), body frame |
| `tau_wind_n` | Nm | VesselBlock (`wind_N`) | Wind yaw moment (feed-forward) |

**Outputs**

| Name | Unit | To | Description |
|---|---|---|---|
| `north_hat`, `east_hat` | m | DPController | Estimated position, NED |
| `psi_hat` | rad | DPController | Estimated heading, −π to π |
| `u_hat`, `v_hat` | m/s | DPController | Estimated velocity, body frame |
| `r_hat` | rad/s | DPController | Estimated yaw rate |
| `b_x_hat`, `b_y_hat` | N | logging | Estimated bias force, **NED** |
| `b_n_hat` | Nm | logging | Estimated bias yaw moment |

## 2. Model

Nine states:

```
x = [η, ν, b]
η = [north, east, ψ]      position and heading, NED          [m, m, rad]
ν = [u, v, r]             velocity, body frame               [m/s, m/s, rad/s]
b = [b_x, b_y, b_n]       bias, NED                          [N, N, Nm]
```

The bias b collects every force the model does not know about: current, wave drift, model errors.

**Process model** (Fossen's low-frequency model):

```
η̇ = R(ψ) ν
ν̇ = M⁻¹ (τ_thr + τ_wind + R(ψ)ᵀ b − D ν)
ḃ = −T_b⁻¹ b                                    (+ process noise)
```

M and D are the 3-DOF `mass_matrix` and `damping_matrix` from `[vessel]`, shared with the DP controller.

**Measurement model:** GNSS position and gyro heading.

```
y = [north, east, ψ] = H x,    H = [I₃ 0 0]
```

**Each time step:**

1. **Predict.** Move the state one step ahead with the process model (forward Euler), and the
   covariance with the Jacobian F = ∂f/∂x: Φ = I + F dt, P ← Φ P Φᵀ + Q dt.
2. **Correct.** Kalman gain K = P Hᵀ (H P Hᵀ + R)⁻¹, then x ← x + K (y − H x). The covariance is updated
   in Joseph form, which keeps P symmetric and positive definite.

**Heading wrap.** ψ and the heading innovation are wrapped to [−π, π), so 359° against 1° is a 2° error,
not 358°.

## 3. `config.toml`

| Key in `[kalman_filter]` | Description |
|---|---|
| `bias_time_constants` | T_b for [b_x, b_y, b_n] [s]. Large = the bias changes slowly |
| `process_noise` | Diagonal of Q, per second, in state order. Larger = trust the model less |
| `measurement_noise` | Diagonal of R = std². Default: GNSS 0.5 m, gyro 0.5° |
| `initial_covariance` | Diagonal of P₀. Default: the bias starts unknown (std 1e5 N, 1e6 Nm) |

Plus `mass_matrix` and `damping_matrix` in `[vessel]`. **Changing `config.toml` needs no rebuild.**

**Tuning in short.** The bias process noise (the last three entries of `process_noise`) sets how fast
the bias follows a new disturbance. Larger = faster, but noisier estimates. The ratio between Q and R
sets how much the filter trusts the measurements over the model.

## 4. Files

| File | What it does |
|---|---|
| `models/kalman_filter.py` | The FMU, everything in one file |

There is no test script yet. A quick check: hold the vessel still (measurements at 0) with a constant
wind force. The filter must then explain the force with a bias of the opposite sign. With the default
tuning, `b_y_hat` and `b_n_hat` settle at about 97 % of −Y and −N after about 30 s. T_b pulls the
estimate slightly towards 0, which is why it is not 100 %.

## 5. Known limitations

- **No wave-frequency states.** The measurements are the vessel's total motion (LF + WF), so the
  wave-frequency motion goes straight into the estimates and on to the controller. Fossen's full DP
  observer adds 6 wave states to filter it out.
- Forward Euler in the prediction. Fine at dt = 0.1 s with the current matrices, but check it if the
  step size or the matrices change.
- The vessel model is linear and 3-DOF, with the **placeholder** matrices in `[vessel]`. It is not the
  6-DOF model inside VesselBlock. Update the matrices when the Gunnerus data is in.
- The measurements are perfect (no noise added). R only tells the filter how much to trust them.
- The bias is in NED, so with a constant heading it maps directly to a constant current or drift force.
