"""Wave components + MOTION RAOs -> WF displacement, not wave forces. 1234

For motion superposition: total pose = LF pose + WF increment, in common axes.
Do not also integrate first-order forces into LF. No RK4 is required for this
harmonic response. Motion RAOs already contain the first-order vessel response.
Zero-speed, slowly changing mean heading and small WF rotations are assumed.
The spatial phase is evaluated at LF north/east position, without a separate
forward-speed RAO correction. This is not a transient radiation-memory solver.

Supply a verified full-circle motion table in body forward/starboard/down axes:
translations m/m; rotational response rad/m as small body rotation increments;
complex phase-LAG convention H = magnitude*exp(+1j*lag). Same origin as LF.
The raw Gunnerus JSON currently has 19 motion-heading columns but 36 declared
headings. This module does NOT silently mirror or guess that mapping or units.
See ../NOTICE.md and ../LICENSE for project attribution/license.
"""
import numpy as np
if __package__:
    from .LF import kinematics
    from .WaveLoads import WaveComponents, check_pose_time, spatial_phase
else:
    from LF import kinematics
    from WaveLoads import WaveComponents, check_pose_time, spatial_phase


class WF:
    """Evaluate wave-frequency motion independently of LF integration."""

    def __init__(self, motion_table, *, gravity=9.81):
        """Receive a verified six-row ResponseTable, ordered surge/sway/heave/roll/pitch/yaw.

        Data loading and convention conversion belong to initialization. The
        table must use kind='rao' and the units/axes documented above.
        """
        if motion_table.kind != 'rao' or motion_table.values.shape[0] != 6:
            raise ValueError('WF needs six motion-RAO rows, not force RAOs')
        if not np.isfinite(gravity) or gravity <= 0:
            raise ValueError('gravity must be positive')
        self.table, self.gravity = motion_table, gravity
        self.set_components(WaveComponents([], [], [], []))

    def set_components(self, components):
        """Receive the same components as WaveLoads and cache frequency interpolation."""
        if not isinstance(components, WaveComponents):
            raise TypeError('Expected WaveComponents')
        self.components = components
        self._motion = self.table.at_frequencies(components.omega)

    def displacement(self, time, eta_lf):
        """Return [north,east,down,roll,pitch,yaw] WF increments (m/rad) at this time.

        Interpolate relative direction and apply minus wave phase and minus RAO
        lag. Convert body translations to NED and small body rotations to Euler
        increments using the linearized kinematic map about the LF orientation.
        This does not change LF state. For endpoint output, call with endpoint
        time and LF pose after the LF step.
        """
        eta = check_pose_time(time, eta_lf)
        w = self.components
        H = self.table.at_headings(self._motion, w.direction-eta[5])
        phase = spatial_phase(w, time, eta, self.gravity)
        body_motion = np.real(np.conj(H) @ (w.amplitude*np.exp(1j*phase)))
        result = kinematics(eta) @ body_motion
        if not np.all(np.isfinite(result)):
            raise ValueError('WF calculation produced nonfinite motion')
        return result
