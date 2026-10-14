"""Vessel-side wave loads using Viljar Simonnes Tveit's implementation.

Source: https://github.com/viljarst/DP_cosim/tree/wave-loads/wave_forces
Revision: 668b1c4a419ff9cbdc6ca28d348c5c62301d3bab
VesselData, interpolate_frequency, WaveLoadModel and build_model below are
copied from vessel_data.py and model.py (only module imports are consolidated).
The WaveLoads adapter preserves our LF/WF interface and maps X,Y,N into six DOFs.
Shared WaveComponents/ResponseTable helpers remain for WF and synthetic tables.

Inputs: amplitudes [m], frequencies [rad/s], phases [rad], propagation directions
[rad, clockwise from north]. Outputs: body-frame N/Nm. Drift includes the mean;
feed it once to LF. First-order loads remain diagnostic when using motion-RAO WF.
The upstream file loader uses raw freqs for both force and drift tables and
converts force-RAO phases from degrees. This deliberately follows Viljar's code.

Upstream license:
MIT License

Copyright (c) 2026 Viljar Simonnes Tveit

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np


def finite_vector(value, name):
    """Copy a finite one-dimensional array; the array may be empty for calm water."""
    a = np.asarray(value, dtype=float)
    if a.ndim != 1 or not np.all(np.isfinite(a)):
        raise ValueError(f'{name} must be a finite one-dimensional array')
    return a.copy()


@dataclass(frozen=True)
class WaveComponents:
    """Four arrays from the wave FMU: amplitude (m), omega (rad/s), phase/direction (rad).

    Zero-amplitude slots may have zero frequency. Active waves require omega>0.
    Arrays are copied and read-only: replace this object when the wave inputs change.
    """
    amplitude: np.ndarray
    omega: np.ndarray
    phase: np.ndarray
    direction: np.ndarray

    def __post_init__(self):
        """Check all slots and prevent accidental mutation of cached wave inputs."""
        for name in ('amplitude', 'omega', 'phase', 'direction'):
            a = finite_vector(getattr(self, name), name)
            a.setflags(write=False)
            object.__setattr__(self, name, a)
        if len({len(self.amplitude), len(self.omega), len(self.phase), len(self.direction)}) != 1:
            raise ValueError('The four wave arrays must have equal lengths')
        if np.any(self.amplitude < 0) or np.any(self.omega < 0):
            raise ValueError('Wave amplitude and frequency must be nonnegative')
        if np.any((self.amplitude > 0) & (self.omega == 0)):
            raise ValueError('Nonzero wave amplitudes require positive frequency')


def amplitude_phase(amplitude, phase, *, phase_unit, amplitude_mode):
    """Convert RAO tables to complex phase-lag responses without guessing conventions.

    phase_unit is 'rad' or 'deg'. amplitude_mode is 'absolute' (report default
    for force RAOs) or 'signed'. Units/axes/reference origin must be checked
    separately. This conversion does not fix an unknown lead/lag convention.
    """
    a, p = np.asarray(amplitude, dtype=float), np.asarray(phase, dtype=float)
    if a.shape != p.shape or not np.all(np.isfinite(a)) or not np.all(np.isfinite(p)):
        raise ValueError('RAO amplitudes and phases must have equal, finite shapes')
    if phase_unit not in ('rad', 'deg') or amplitude_mode not in ('absolute', 'signed'):
        raise ValueError('Specify phase_unit rad/deg and amplitude_mode absolute/signed')
    if phase_unit == 'deg':
        p = np.deg2rad(p)
    return (np.abs(a) if amplitude_mode == 'absolute' else a) * np.exp(1j*p)


class ResponseTable:
    """Frequency/direction table shared by force, drift and motion calculations.

    Values have shape (DOF, frequency, heading). Headings are full-circle relative
    propagation directions, sorted from 0 through a value >pi and <2*pi, radians.
    Do not supply a duplicate 360-degree column. Complex values interpolate in
    real/imaginary form, never by interpolating wrapped phase angles directly.
    """

    def __init__(self, frequencies, headings, values, *, kind):
        """Check table dimensions; kind selects RAO or drift frequency boundaries."""
        self.frequencies = finite_vector(frequencies, 'frequencies')
        self.headings = finite_vector(headings, 'headings')
        self.values = np.asarray(values).copy()
        if kind not in ('rao', 'drift'):
            raise ValueError('Table kind must be rao or drift')
        self.kind = kind
        if (len(self.frequencies) < 2 or self.frequencies[0] <= 0
                or np.any(np.diff(self.frequencies) <= 0)):
            raise ValueError('Need at least two increasing positive table frequencies')
        if (len(self.headings) < 3 or self.headings[0] != 0
                or np.any(np.diff(self.headings) <= 0)
                or not np.pi < self.headings[-1] < 2*np.pi):
            raise ValueError('Need full-circle headings starting at 0, without duplicate 2*pi')
        if (self.values.ndim != 3 or self.values.shape[1:] !=
                (len(self.frequencies), len(self.headings))
                or not np.all(np.isfinite(self.values))):
            raise ValueError('Table must have finite shape (DOF, frequency, heading)')
        if kind == 'drift' and np.iscomplexobj(self.values):
            raise ValueError('Drift coefficients must be real')

    def at_frequencies(self, omega):
        """Interpolate once when wave frequencies change: return (DOF, component, heading).

        RAOs: hold the lowest value below the table, zero above it.
        Drift: interpolate from zero at omega=0, hold the highest value above it.
        These boundaries follow the supplied report, not a new extrapolation model.
        """
        w = finite_vector(omega, 'omega')
        if np.any(w < 0):
            raise ValueError('Frequency must be nonnegative')
        f, v = self.frequencies, self.values
        hi = np.clip(np.searchsorted(f, w, side='right'), 1, len(f)-1)
        lo = hi - 1
        weight = np.clip((w-f[lo])/(f[hi]-f[lo]), 0, 1)
        out = v[:, lo, :]*(1-weight)[None, :, None] + v[:, hi, :]*weight[None, :, None]
        if self.kind == 'rao':
            out[:, w > f[-1], :] = 0
        else:
            below = w < f[0]
            out[:, below, :] *= (w[below]/f[0])[None, :, None]
        return out

    def at_headings(self, frequency_values, beta):
        """Interpolate component-relative headings, including the last-to-first wrap."""
        b = finite_vector(beta, 'beta') % (2*np.pi)
        v = np.asarray(frequency_values)
        if v.shape != (self.values.shape[0], len(b), len(self.headings)):
            raise ValueError('Frequency cache does not match component headings')
        h = self.headings
        lo = np.searchsorted(h, b, side='right')-1
        hi = (lo+1) % len(h)
        upper = np.where(hi == 0, 2*np.pi, h[hi])
        weight = (b-h[lo])/(upper-h[lo])
        j = np.arange(len(b))
        return v[:, j, lo]*(1-weight) + v[:, j, hi]*weight


def spatial_phase(components, time, eta, gravity):
    """Evaluate report eq. 41 phase at LF north/east position, in deep water."""
    distance = eta[0]*np.cos(components.direction) + eta[1]*np.sin(components.direction)
    return components.omega*time - components.omega**2/gravity*distance - components.phase


def check_pose_time(time, eta):
    """Require finite simulation time and six LF pose values, in m/rad."""
    pose = finite_vector(eta, 'eta_lf')
    if pose.shape != (6,) or not np.isfinite(time):
        raise ValueError('Need finite time and six LF pose values')
    return pose


@dataclass(frozen=True)
class WaveLoadResult:
    """BODY loads [X,Y,Z,K,M,N], N/N m. Only X,Y,N are modelled here.

    tau_second_order includes mean AND slowly varying drift: feed this once to LF.
    tau_mean is the diagonal contribution (eq. 43), for diagnostics; do not add
    it again. Degenerate equal-frequency components can also have constant cross terms.
    tau_first_order is diagnostic under the motion-RAO superposition approach.
    """
    tau_first_order: np.ndarray
    tau_second_order: np.ndarray
    tau_mean: np.ndarray



# --- Viljar: wave_forces/vessel_data.py ---
DOFS = ("surge", "sway", "yaw")


def interpolate_frequency(x_table, table, x_new, left, right):
    """Linear interpolation along the frequency axis (axis 1) of table (3, nf, nh).

    left / right: what to use below / above the table range,
    either "hold" (keep the edge value) or "zero".
    """
    x_new = np.asarray(x_new, dtype=float)
    nf = len(x_table)
    # index of the table point just below each new frequency
    i = np.clip(np.searchsorted(x_table, x_new) - 1, 0, nf - 2)
    # how far between point i and point i+1 (0 = at i, 1 = at i+1)
    w = (x_new - x_table[i]) / (x_table[i + 1] - x_table[i])
    out = table[:, i, :] * (1.0 - w)[None, :, None] + table[:, i + 1, :] * w[None, :, None]

    below = x_new < x_table[0]
    above = x_new > x_table[-1]
    for mask, rule, edge in ((below, left, 0), (above, right, -1)):
        if mask.any():
            out[:, mask, :] = 0.0 if rule == "zero" else table[:, [edge], :]
    return out


class VesselData:
    """Force RAOs and drift coefficients for surge, sway and yaw."""

    def __init__(self, data_file, speed_index, force_rao_rows, drift_rows, rao_amplitude):
        """Read the tables from the vessel file.

        speed_index:    which speed column to use. 0 = zero speed (DP).
        force_rao_rows: which table row is each DOF, e.g. {"surge": 0, "sway": 1, "yaw": 5}
        drift_rows:     the same for the drift table
        rao_amplitude:  "absolute" uses |amp| (as mcsimpy/TMR4240),
                        "signed" uses the amplitude with the sign in the file.
                        (The Gunnerus file has negative amplitudes for surge, heave and yaw.)
        """
        if rao_amplitude not in ("absolute", "signed"):
            raise ValueError(f"rao_amplitude must be 'absolute' or 'signed', got '{rao_amplitude}'")
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        freqs = np.asarray(raw["freqs"], dtype=float)
        headings = np.asarray(raw["headings"], dtype=float) % (2.0 * np.pi)
        order = np.argsort(headings)                          # sort headings from 0 to 2*pi
        if np.any(np.diff(freqs) <= 0):
            raise ValueError(f"{data_file}: the frequencies must be increasing")

        # Pick out surge, sway and yaw at the chosen speed
        rao_rows = [force_rao_rows[dof] for dof in DOFS]
        drift_row_list = [drift_rows[dof] for dof in DOFS]
        amp = np.asarray(raw["forceRAO"]["amp"], dtype=float)[rao_rows, :, :, speed_index]
        phase = np.deg2rad(np.asarray(raw["forceRAO"]["phase"], dtype=float))[rao_rows, :, :, speed_index]
        drift = np.asarray(raw["driftfrc"]["amp"], dtype=float)[drift_row_list, :, :, speed_index]
        if rao_amplitude == "absolute":
            amp = np.abs(amp)

        self.freqs = freqs                                     # (nf,)  [rad/s]
        self.headings = headings[order]                        # (nh,)  [rad]
        self.rao = (amp * np.exp(1j * phase))[:, :, order]     # (3, nf, nh) [N/m, Nm/m]
        self.drift = drift[:, :, order]                        # (3, nf, nh) [N/m^2, Nm/m^2]

    # -- frequency --------------------------------------------------------------

    def tables_at(self, frequencies):
        """RAO and drift tables interpolated to the frequencies of the wave components.

        Returns (rao, drift), each with shape (3, n_components, n_headings).
        This is done once when the sea is built, not in every time step.

        Outside the table (same choice as mcsimpy):
        - RAO:   edge value below the lowest frequency, zero above the highest.
        - Drift: goes linearly to zero at omega = 0, edge value above the highest.
        """
        rao = interpolate_frequency(self.freqs, self.rao, frequencies, left="hold", right="zero")
        # add a zero-drift point at omega = 0, so the drift goes to zero for very long waves
        f0 = np.concatenate(([0.0], self.freqs))
        d0 = np.concatenate((np.zeros_like(self.drift[:, :1, :]), self.drift), axis=1)
        drift = interpolate_frequency(f0, d0, frequencies, left="hold", right="hold")
        return rao, drift

    # -- heading ----------------------------------------------------------------

    def heading_weights(self, beta):
        """Interpolation indices and weights for relative wave directions beta [rad].

        Returns (lo, hi, w) so that value = (1 - w) * table[lo] + w * table[hi].
        Works for any heading grid and wraps around from 360 back to 0 degrees.
        """
        h = self.headings
        nh = len(h)
        beta = (np.asarray(beta, dtype=float) - h[0]) % (2.0 * np.pi) + h[0]   # into [h0, h0 + 2*pi)
        h_ext = np.append(h, h[0] + 2.0 * np.pi)                               # add 360 deg = 0 deg at the end
        lo = np.clip(np.searchsorted(h_ext, beta, side="right") - 1, 0, nh - 1)
        w = (beta - h_ext[lo]) / (h_ext[lo + 1] - h_ext[lo])
        hi = (lo + 1) % nh                                                     # index after the last is the first
        return lo, hi, w

# --- Viljar: wave_forces/model.py ---
class WaveLoadModel:
    """Wave forces on one vessel. One instance per vessel and simulation."""

    def __init__(self, vessel, gravity):
        """
        vessel:  a VesselData object (vessel_data.py)
        gravity: [m/s^2]
        """
        self.vessel = vessel
        self.gravity = gravity
        self.frequencies = None
        self.set_waves([], [], [], [])                       # no waves until set_waves() is called

    # -- wave components from the waves block -------------------------------------

    def set_waves(self, amplitudes, frequencies, phases, directions):
        """Store the wave components from the waves block.

        amplitudes [m], frequencies [rad/s], phases [rad],
        directions [rad]: the direction each wave travels TO, NED.

        The vessel tables are only looked up again when the frequencies change
        (that is, when the waves block has built a new sea).
        """
        frequencies = np.asarray(frequencies, dtype=float)
        if self.frequencies is None or not np.array_equal(frequencies, self.frequencies):
            self.frequencies = frequencies
            self._rao, self._drift = self.vessel.tables_at(frequencies)
            self._k = frequencies**2 / self.gravity          # wave number, deep water
            self._idx = np.arange(len(frequencies))          # 0, 1, 2, ... one per component
        self.amplitudes = np.asarray(amplitudes, dtype=float)
        self.phases = np.asarray(phases, dtype=float)
        self.directions = np.asarray(directions, dtype=float)

    # -- loads --------------------------------------------------------------------

    def _interpolate_heading(self, table, beta):
        """Pick each component's value from table (3, n, nh) at its relative direction beta."""
        lo, hi, w = self.vessel.heading_weights(beta)
        j = self._idx
        return table[:, j, lo] * (1.0 - w) + table[:, j, hi] * w      # (3, n)

    def first_order(self, t, eta):
        """First-order (wave-frequency) loads [Fx, Fy, Mz] at time t."""
        if len(self.amplitudes) == 0:
            return np.zeros(3)
        north, east, psi = eta
        H = self._interpolate_heading(self._rao, self.directions - psi)      # relative direction
        arg = (self.frequencies * t
               - self._k * (north * np.cos(self.directions) + east * np.sin(self.directions))
               - self.phases)
        return (np.conj(H) * np.exp(1j * arg)).real @ self.amplitudes

    def drift(self, t, eta):
        """Mean + slowly varying drift loads [Fx, Fy, Mz] at time t (Newman)."""
        if len(self.amplitudes) == 0:
            return np.zeros(3)
        psi = eta[2]
        T = self._interpolate_heading(self._drift, self.directions - psi)
        e = self.amplitudes * np.exp(1j * (self.frequencies * t - self.phases))
        return ((T * e).sum(axis=1) * np.conj(e.sum())).real

    def mean_drift(self, psi):
        """The mean value of the drift load for heading psi (no time series)."""
        if len(self.amplitudes) == 0:
            return np.zeros(3)
        T = self._interpolate_heading(self._drift, self.directions - psi)
        return T @ self.amplitudes**2

    def loads(self, t, eta):
        """Returns (first_order, drift) at time t for vessel position eta."""
        return self.first_order(t, eta), self.drift(t, eta)


def build_model(p):
    """Build a WaveLoadModel from a flat parameter list (dict).

    p has the same names as get_wave_forces_parameters() in forces_config.py.
    """
    vessel = VesselData(
        p["vessel_data_file"], int(p["speed_index"]),
        force_rao_rows={"surge": int(p["force_rao_row_surge"]),
                        "sway": int(p["force_rao_row_sway"]),
                        "yaw": int(p["force_rao_row_yaw"])},
        drift_rows={"surge": int(p["drift_row_surge"]),
                    "sway": int(p["drift_row_sway"]),
                    "yaw": int(p["drift_row_yaw"])},
        rao_amplitude=p["rao_amplitude"],
    )
    return WaveLoadModel(vessel, float(p["gravity"]))


class _ResponseTableVessel:
    """Allow existing verified/synthetic ResponseTables to use Viljar's model."""

    def __init__(self, force_table, drift_table):
        self.force_table = force_table
        self.drift_table = drift_table
        self.headings = force_table.headings
        if not np.array_equal(self.headings, drift_table.headings):
            raise ValueError('Force and drift tables must share a heading grid')

    def tables_at(self, frequencies):
        return (self.force_table.at_frequencies(frequencies),
                self.drift_table.at_frequencies(frequencies))

    heading_weights = VesselData.heading_weights


class WaveLoads:
    """Compatibility adapter: Viljar's force model -> existing LF/WF scripts."""

    def __init__(self, force_table, drift_table, *, gravity=9.81):
        if (force_table.kind != 'rao' or drift_table.kind != 'drift'
                or force_table.values.shape[0] != 3 or drift_table.values.shape[0] != 3):
            raise ValueError('Supply X,Y,N force-RAO and real drift tables')
        self.force_table, self.drift_table = force_table, drift_table
        self._initialize(_ResponseTableVessel(force_table, drift_table), gravity)

    def _initialize(self, vessel, gravity):
        if not np.isfinite(gravity) or gravity <= 0:
            raise ValueError('gravity must be positive')
        self.gravity = gravity
        self.model = WaveLoadModel(vessel, gravity)
        self.set_components(WaveComponents([], [], [], []))

    @classmethod
    def from_shipx(cls, path, *, phase_unit, amplitude_mode, gravity=9.81):
        """Load zero-speed data using Viljar's loader and X/Y/N row mapping.

        His loader expects force phases in degrees and uses the common raw
        freqs grid. Explicit arguments prevent silently misreading other data.
        """
        if phase_unit != 'deg':
            raise ValueError("Viljar's vessel loader requires phase_unit='deg'")
        raw = json.loads(Path(path).read_text())
        if not np.isclose(np.asarray(raw['velocities'])[0], 0):
            raise ValueError('This implementation requires zero-speed data in entry 0')
        vessel = VesselData(str(path), 0,
                            {'surge': 0, 'sway': 1, 'yaw': 5},
                            {'surge': 0, 'sway': 1, 'yaw': 2}, amplitude_mode)
        obj = cls.__new__(cls)
        obj._initialize(vessel, gravity)
        return obj

    def set_components(self, components):
        """Pass the four validated component arrays to Viljar's set_waves()."""
        if not isinstance(components, WaveComponents):
            raise TypeError('Expected WaveComponents')
        self.components = components
        self.model.set_waves(components.amplitude, components.omega,
                             components.phase, components.direction)

    def calculate(self, time, eta_lf):
        """Use LF north/east/yaw; return six-axis body loads for existing callers."""
        eta = check_pose_time(time, eta_lf)
        first, drift = self.model.loads(time, (eta[0], eta[1], eta[5]))
        mean = self.model.mean_drift(eta[5])
        outputs = []
        for value in (first, drift, mean):
            load = np.zeros(6)
            load[[0, 1, 5]] = value
            if not np.all(np.isfinite(load)):
                raise ValueError('Wave calculation produced nonfinite loads')
            outputs.append(load)
        return WaveLoadResult(*outputs)
