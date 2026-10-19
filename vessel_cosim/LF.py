"""Six-degree-of-freedom low-frequency vessel dynamics, with RK4 integration. 1234

This is the calculation part of the hull, not a standalone FMU or simulation.
A future hull FMU will read shared config during initialization, create
LF with the vessel matrices, and call step() during each do_step().

State: [north, east, down, roll, pitch, yaw, u, v, w, p, q, r].
Pose uses metres/radians; body velocities use m/s and rad/s.
Body axes: forward, starboard, down. NED: north, east, down.
Loads: [X, Y, Z, K, M, N] in N and N m, about the matrix reference origin.

Equation:
  (M_RB + A) nu_dot =
      tau - C_RB(nu) nu - C_A(nu_r) nu_r - D nu_r - G eta + A nu_c_dot
  eta_dot = J(eta) nu,   nu_r = nu - nu_c
  tau = tau_wind + tau_thruster + tau_wave_drift + tau_external

Current is a velocity input, not an extra tau. Assume uniform, constant NED
current over each step; changing-current acceleration is not modelled.
Linear damping/restoring assume small roll/pitch near hydrostatic equilibrium.
WF motion and first-order wave forces already represented by WF are excluded.

Matrices must be supplied, not invented here. They can be loaded from vessel
data such as the existing Gunnerus JSON, but must be appropriate LF coefficients.
The demo's lowest tabulated frequency is not a validated zero-frequency limit.
Based on the existing Vessel6DOF LF/kinematics implementation; see ../NOTICE.md
and ../LICENSE for NTNU/mcsimpy attribution and GPL-3.0-or-later licensing.
Theory: https://www.fossen.biz/html/marineCraftModel.html
"""
import numpy as np


def checked(value, shape, name):
    """Return an independent numeric array with the required shape and finite values."""
    result = np.asarray(value, dtype=float)
    if result.shape != shape or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must have shape {shape} and finite values")
    return result.copy()


def rotation(angles):
    """Rotate body vectors into NED using roll, pitch, yaw in radians; transpose reverses it."""
    phi, theta, psi = angles
    cp, ct, cs = np.cos([phi, theta, psi])
    sp, st, ss = np.sin([phi, theta, psi])
    return np.array([
        [cs*ct, cs*st*sp-ss*cp, cs*st*cp+ss*sp],
        [ss*ct, ss*st*sp+cs*cp, ss*st*cp-cs*sp],
        [-st, ct*sp, ct*cp],
    ])


def kinematics(eta):
    """Map body velocity to NED position rates and Euler-angle rates: eta_dot = J nu."""
    phi, theta, _ = eta[3:]
    if abs(np.cos(theta)) < 1e-6:
        raise ValueError("Euler angles are singular near pitch +/-90 degrees")
    s, c, t = np.sin(phi), np.cos(phi), np.tan(theta)
    J = np.zeros((6, 6))
    J[:3, :3] = rotation(eta[3:])
    J[3:, 3:] = [[1., s*t, c*t], [0., c, -s],
                 [0., s/np.cos(theta), c/np.cos(theta)]]
    return J


def skew(v):
    """Build the cross-product matrix: skew(v) @ w equals v cross w."""
    x, y, z = v
    return np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])


def coriolis(mass, velocity):
    """Build rotating-body-frame inertial terms from a mass matrix and body velocity."""
    momentum = mass @ velocity
    p, h = skew(momentum[:3]), skew(momentum[3:])
    return np.block([[np.zeros((3, 3)), -p], [-p, -h]])


class LF:
    """Calculate LF motion using supplied vessel properties; the caller stores the state."""

    def __init__(self, rigid_mass, added_mass, damping, restoring):
        """Store four SI 6-by-6 matrices, ordered surge, sway, heave, roll, pitch, yaw.

        rigid_mass describes physical mass/inertia; added_mass describes water
        inertia; damping describes resistance; restoring describes hydrostatics.
        All must use the same body axes/origin. This constructor does not read
        config files: the future FMU wrapper supplies the loaded matrices here.
        Shape/invertibility checks do not establish physical validity.
        """
        self.M_RB = checked(rigid_mass, (6, 6), "rigid_mass")
        self.A = checked(added_mass, (6, 6), "added_mass")
        self.D = checked(damping, (6, 6), "damping")
        self.G = checked(restoring, (6, 6), "restoring")
        self.M = self.M_RB + self.A
        if np.linalg.matrix_rank(self.M) != 6:
            raise ValueError("Total mass matrix must be invertible")

    @classmethod
    def from_shipx(cls, path, *, frequency):
        """Load zero-speed ShipX matrices at an explicitly chosen frequency (rad/s).

        Uses MRB, A(w), B(w)+Bv and hydrostatic C(w) from the SAME table slice.
        Nearest stored frequency is selected and exposed as selected_frequency.
        This is an explicit data selection, not an extrapolation to zero frequency
        or proof that the chosen radiation coefficients are suitable for LF/DP.
        The model remains fixed-coefficient; frequency-dependent memory is omitted.
        Wind geometry and motion RAOs are loaded separately.
        """
        import json
        from pathlib import Path
        data = json.loads(Path(path).read_text())
        freqs = np.asarray(data['freqs'], dtype=float)
        if (freqs.ndim != 1 or len(freqs) == 0 or not np.isfinite(freqs).all()
                or np.any(np.diff(freqs) <= 0)):
            raise ValueError('ShipX frequencies must be finite and increasing')
        if not np.isfinite(frequency) or not freqs[0] <= frequency <= freqs[-1]:
            raise ValueError('Choose a frequency inside the table; zero-frequency LF coefficients cannot be inferred')
        if not np.isclose(np.asarray(data['velocities'])[0], 0):
            raise ValueError('Expected zero speed at table index 0')
        index = int(np.argmin(abs(freqs-frequency)))
        obj = cls(np.asarray(data['MRB']), np.asarray(data['A'])[:, :, index, 0],
                  np.asarray(data['B'])[:, :, index, 0]+np.asarray(data['Bv']),
                  np.asarray(data['C'])[:, :, index, 0])
        obj.selected_frequency = float(freqs[index])
        obj.data_source = str(Path(path).resolve())
        return obj

    def derivative(self, state, tau, current_ned=(0., 0., 0.)):
        """Return twelve state rates, without changing state or advancing time.

        tau is the already summed six-component LF body load (N, N m).
        current_ned is the three-component water velocity (m/s).
        The first six returned values are pose rates; the last six are body
        accelerations. The vessel's existing velocity matters even at zero load.
        """
        state = checked(state, (12,), "state")
        tau = checked(tau, (6,), "tau")
        current_ned = checked(current_ned, (3,), "current_ned")
        eta, nu = state[:6], state[6:]

        # Express current in body axes, then calculate velocity relative to water.
        current_body = rotation(eta[3:]).T @ current_ned
        nu_c = np.r_[current_body, np.zeros(3)]
        nu_r = nu - nu_c

        # Steady earth-fixed current changes body components as the vessel turns.
        nu_c_dot = np.r_[-np.cross(nu[3:], current_body), np.zeros(3)]

        # Subtract inertial coupling, resistance and restoring loads.
        net_load = (tau - coriolis(self.M_RB, nu) @ nu
                    - coriolis(self.A, nu_r) @ nu_r
                    - self.D @ nu_r - self.G @ eta + self.A @ nu_c_dot)
        eta_dot = kinematics(eta) @ nu
        nu_dot = np.linalg.solve(self.M, net_load)
        return np.r_[eta_dot, nu_dot]

    def step(self, state, dt, *, tau_wind=(0.,)*6, tau_thruster=(0.,)*6,
             tau_wave_drift=(0.,)*6, current_ned=(0., 0., 0.),
             tau_external=(0.,)*6):
        """Return the LF state dt seconds later using fourth-order Runge-Kutta.

        Supply separately calculated wind, delivered thruster and LF wave-drift
        loads, each [X,Y,Z,K,M,N]. Missing loads/current default to zero.
        tau_external adds other body-frame loads, e.g. a rope, and defaults to
        six zeros. Forces are in N and moments in N m about the same origin as
        the vessel matrices. The caller converts rope forces to body axes and
        includes the attachment-point moment (lever arm cross force).
        tau_wave_drift receives WaveLoads.calculate(...).tau_second_order,
        which includes mean plus slowly varying drift. Do not add tau_mean again.
        First-order wave loads are excluded when WF motion is supplied by RAOs.
        This method sums loads; it does not calculate them from wind speed,
        thruster commands or raw waves. Loads/current are held over dt, while
        orientation and all state-dependent terms are recomputed at RK4 stages.
        The caller saves the returned state and advances its simulation clock.
        """
        if not np.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and positive")
        state = checked(state, (12,), "state")
        tau = (checked(tau_wind, (6,), "tau_wind")
               + checked(tau_thruster, (6,), "tau_thruster")
               + checked(tau_wave_drift, (6,), "tau_wave_drift")
               + checked(tau_external, (6,), "tau_external"))
        current = checked(current_ned, (3,), "current_ned")

        # Evaluate rates at the start, two midpoint estimates, and the endpoint.
        k1 = self.derivative(state, tau, current)
        k2 = self.derivative(state + dt*k1/2, tau, current)
        k3 = self.derivative(state + dt*k2/2, tau, current)
        k4 = self.derivative(state + dt*k3, tau, current)
        result = state + dt*(k1 + 2*k2 + 2*k3 + k4)/6
        return checked(result, (12,), "updated LF state")

    def step_with_waves(self, state, dt, *, time, wave_loads,
                        tau_wind=(0.,)*6, tau_thruster=(0.,)*6,
                        current_ned=(0., 0., 0.), tau_external=(0.,)*6):
        """Calculate second-order wave loads and feed them into the existing RK4 step.

        wave_loads is a configured WaveLoads object with current components.
        Evaluate at the start time/LF pose and hold the load across this step,
        matching the other held inputs. This is RK4 for the held-load equation;
        reduce the communication step to resolve time/heading-varying wave drift.
        For WF output, evaluate WF.displacement at time+dt and the returned pose.
        No first-order loads or WF motion are inserted into the LF equation.
        tau_external is forwarded to step(), with the same body-frame convention
        and zero default; it is held constant across this step like other loads.
        """
        state = checked(state, (12,), "state")
        result = wave_loads.calculate(time, state[:6])
        return self.step(state, dt, tau_wind=tau_wind,
                         tau_thruster=tau_thruster,
                         tau_wave_drift=result.tau_second_order,
                         current_ned=current_ned, tau_external=tau_external)
