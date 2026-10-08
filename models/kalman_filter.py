"""Extended Kalman filter (EKF) FMU: estimates the vessel's position, velocity and slowly varying disturbances.

A simple 3-DOF DP observer (surge, sway, yaw) with 9 states:

    x = [eta, nu, b]
    eta = [north, east, psi]   position and heading in NED [m, m, rad]
    nu  = [u, v, r]            velocity in the body frame [m/s, m/s, rad/s]
    b   = [b_x, b_y, b_n]      bias in NED [N, N, Nm]: every force the
                               model does not know about (current, wave
                               drift, model errors)

Process model (Fossen, low-frequency model):

    eta_dot = R(psi) nu
    nu_dot  = M^-1 (tau_thr + tau_wind + R(psi)^T b - D nu)
    b_dot   = -T_b^-1 b                          (+ noise)

Measurement model: GNSS position and gyro heading.

    y = [north, east, psi] = H x,   H = [I 0 0]

Every time step the filter
  1. predicts the state one step ahead with the process model (predict), and
  2. corrects the prediction with the new measurement (correct).

Units: SI, angles in radians. The bias is in NED, the forces tau in the body frame.

Not included yet: wave-frequency motion (the first-order wave model in
Fossen's DP observer). It can be added as 6 extra states later.
"""
import tomllib
from pathlib import Path

import numpy as np
from pythonfmu import Fmi2Causality, Fmi2Slave, Fmi2Variability, Real, String


def rotation(psi):
    """R(psi): rotates a body-frame vector [x, y, n] into NED."""
    c, s = np.cos(psi), np.sin(psi)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def rotation_derivative(psi):
    """dR/dpsi, used in the Jacobian of the process model."""
    c, s = np.cos(psi), np.sin(psi)
    return np.array([[-s, -c, 0.0], [c, -s, 0.0], [0.0, 0.0, 0.0]])


def wrap_angle(angle):
    """Wraps an angle to [-pi, pi)."""
    return (angle + np.pi) % (2.0 * np.pi) - np.pi


INPUTS = (
    "north_meas", "east_meas", "psi_meas",   # measurements: GNSS [m] and gyro [rad]
    "tau_thr_x", "tau_thr_y", "tau_thr_n",   # thruster forces, body frame [N, N, Nm]
    "tau_wind_x", "tau_wind_y", "tau_wind_n",  # wind forces (feed-forward), body frame [N, N, Nm]
)
OUTPUTS = (
    "north_hat", "east_hat", "psi_hat",      # estimated position and heading [m, m, rad]
    "u_hat", "v_hat", "r_hat",               # estimated velocity [m/s, m/s, rad/s]
    "b_x_hat", "b_y_hat", "b_n_hat",         # estimated bias in NED [N, N, Nm]
)


class ExtendedKalmanFilter(Fmi2Slave):

    author = "Olve Grønås Birkeland"
    description = "Extended Kalman filter: 3-DOF DP observer with position, velocity and bias estimates"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # PARAMETER: path to the config file.
        self.config_path = ""
        self.register_variable(String("config_path", causality=Fmi2Causality.parameter,
                                      variability=Fmi2Variability.fixed))

        # INPUTS: measurements and known forces.
        for name in INPUTS:
            setattr(self, name, 0.0)
            self.register_variable(Real(name, causality=Fmi2Causality.input))

        # OUTPUTS: the estimates.
        for name in OUTPUTS:
            setattr(self, name, 0.0)
            self.register_variable(Real(name, causality=Fmi2Causality.output))

        # CONSTANTS and filter state: set in exit_initialization_mode.
        self.M_inv = self.D = self.T_b = None   # vessel model
        self.Q = self.R = None                  # noise covariances
        self.x = self.P = None                  # state estimate and its covariance

    def exit_initialization_mode(self):
        if not self.config_path:
            raise ValueError("config_path is not set. Set it in OspSystemStructure.xml.")
        config = tomllib.loads(Path(self.config_path).read_text(encoding="utf-8-sig"))

        # Vessel model, from [vessel]. Shared with other FMUs that need the same matrices.
        vessel = config["vessel"]
        self.M_inv = np.linalg.inv(np.array(vessel["mass_matrix"], dtype=float))
        self.D = np.array(vessel["damping_matrix"], dtype=float)

        # Filter settings, from [kalman_filter].
        kf = config["kalman_filter"]
        self.T_b = np.array(kf["bias_time_constants"], dtype=float)
        self.Q = np.diag(np.array(kf["process_noise"], dtype=float))
        self.R = np.diag(np.array(kf["measurement_noise"], dtype=float))
        self.P = np.diag(np.array(kf["initial_covariance"], dtype=float))
        self.x = np.zeros(9)

        self.write_outputs()

    def predict(self, tau, dt):
        """Moves the estimate one time step ahead with the process model (forward Euler)."""
        eta, nu, b = self.x[0:3], self.x[3:6], self.x[6:9]
        R, dR = rotation(eta[2]), rotation_derivative(eta[2])

        eta_dot = R @ nu
        nu_dot = self.M_inv @ (tau + R.T @ b - self.D @ nu)
        b_dot = -b / self.T_b

        # Jacobian F = df/dx of the process model.
        F = np.zeros((9, 9))
        F[0:3, 2] = dR @ nu
        F[0:3, 3:6] = R
        F[3:6, 2] = self.M_inv @ (dR.T @ b)
        F[3:6, 3:6] = -self.M_inv @ self.D
        F[3:6, 6:9] = self.M_inv @ R.T
        F[6:9, 6:9] = -np.diag(1.0 / self.T_b)

        self.x = self.x + dt * np.concatenate([eta_dot, nu_dot, b_dot])
        self.x[2] = wrap_angle(self.x[2])
        Phi = np.eye(9) + dt * F                       # discrete-time transition matrix
        self.P = Phi @ self.P @ Phi.T + self.Q * dt

    def correct(self, y):
        """Corrects the estimate with a measurement y = [north, east, psi]."""
        H = np.hstack([np.eye(3), np.zeros((3, 6))])
        innovation = y - H @ self.x
        innovation[2] = wrap_angle(innovation[2])      # 359 deg vs 1 deg is 2 deg, not 358

        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)            # Kalman gain
        self.x = self.x + K @ innovation
        self.x[2] = wrap_angle(self.x[2])
        I_KH = np.eye(9) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ self.R @ K.T  # Joseph form, keeps P symmetric

    def write_outputs(self):
        for name, value in zip(OUTPUTS, self.x):
            setattr(self, name, float(value))

    def do_step(self, current_time, step_size):
        tau = np.array([self.tau_thr_x + self.tau_wind_x,
                        self.tau_thr_y + self.tau_wind_y,
                        self.tau_thr_n + self.tau_wind_n])
        y = np.array([self.north_meas, self.east_meas, self.psi_meas])

        self.predict(tau, step_size)
        self.correct(y)
        self.write_outputs()
        return True
