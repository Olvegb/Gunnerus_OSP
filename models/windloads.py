"""WindLoads FMU: wind loads on a vessel using the Blendermann method.

The FMU's life cycle:
  1. __init__                   Runs when the FMU is loaded (and when it is
                                built). The variables are registered here.
                                The config file is NOT read here.
  2. the master sets values     config_path and the inputs get their values
                                from OspSystemStructure.xml.
  3. exit_initialization_mode   Runs once, right before the simulation
                                starts. The config file is read here.
  4. do_step                    Runs every time step. The loads are
                                calculated here.
"""
import tomllib
from math import cos, pi, radians, sin
from pathlib import Path

from pythonfmu import Fmi2Causality, Fmi2Slave, Fmi2Variability, Real, String


def blendermann_wind_coefficients(
    loa, area_lateral, area_frontal, s_L, s_H, relative_angle_deg,
    air_density, cd_t, cd_lAF_bow, cd_lAF_stern, delta, kappa,
):
    """Unchanged from FMU_try/windloads_empty.py."""
    is_port_side = relative_angle_deg > 180.0
    folded_angle = 360.0 - relative_angle_deg if is_port_side else relative_angle_deg
    eps = radians(folded_angle)

    cd_lAF = cd_lAF_bow if folded_angle <= 90.0 else cd_lAF_stern
    cd_l = cd_lAF * area_frontal / area_lateral
    denominator = 1.0 - (delta / 2.0) * (1.0 - cd_l / cd_t) * sin(2.0 * eps) ** 2

    cx_af = -cd_lAF * cos(eps) / denominator
    cy = cd_t * sin(eps) / denominator
    if is_port_side:
        cy = -cy

    h_m = area_lateral / loa
    cn = (s_L / loa - 0.18 * (eps - pi / 2.0)) * cy
    ck = kappa * (s_H / h_m) * cy

    q_per_v2 = 0.5 * air_density
    cx = cx_af * q_per_v2 * area_frontal
    cy *= q_per_v2 * area_lateral
    cn *= q_per_v2 * area_lateral * loa
    ck *= q_per_v2 * area_lateral * h_m

    return cx, cy, cn, ck


# The constants the FMU reads from the config file. They are plain Python
# variables inside the FMU and are not registered as FMI variables, so the
# master cannot see them.
CONSTANTS = (
    "air_density", "loa", "area_lateral", "area_frontal", "s_L", "s_H",
    "cd_t", "cd_lAF_bow", "cd_lAF_stern", "delta", "kappa",
)


class WindLoads_Blendermann(Fmi2Slave):

    author = "Olve Grønås Birkeland"
    description = "Wind load model on vessel with the help of blendermann approach"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # PARAMETER: path to the config file. The only thing the master must set.
        self.config_path = ""
        self.register_variable(String("config_path", causality=Fmi2Causality.parameter,
                                      variability=Fmi2Variability.fixed))

        # INPUTS: change during the simulation, and will later come from other FMUs.
        self.wind_speed = 0.0                   # [m/s]
        self.relative_wind_direction_deg = 0.0  # [deg]
        for name in ("wind_speed", "relative_wind_direction_deg"):
            self.register_variable(Real(name, causality=Fmi2Causality.input))

        # CONSTANTS: get their values from the config file in exit_initialization_mode.
        for name in CONSTANTS:
            setattr(self, name, 0.0)

        # OUTPUTS: wind forces and moments, calculated in do_step.
        self.X = self.Y = self.N = self.K = 0.0
        for name in ("X", "Y", "N", "K"):
            self.register_variable(Real(name, causality=Fmi2Causality.output))

    def exit_initialization_mode(self):
        # Read the config file. A relative path, such as "config.toml", is
        # read from the folder the simulation is started from.
        if not self.config_path:
            raise ValueError("config_path is not set. Set it in OspSystemStructure.xml.")
        # "utf-8-sig" copes with the file being saved with a BOM (Notepad, PowerShell).
        config = tomllib.loads(Path(self.config_path).read_text(encoding="utf-8-sig"))

        # Pick out the values the FMU needs. The Blendermann coefficients are
        # chosen from the vessel type.
        vessel = config["vessel"]
        coefficients = config["blendermann"][vessel["type"]]
        values = {"air_density": config["environment"]["air_density"], **vessel, **coefficients}

        # Store the values on the FMU, so do_step can use them.
        for name in CONSTANTS:
            setattr(self, name, float(values[name]))  # KeyError = value missing from the config file

    def do_step(self, current_time, step_size):
        cx, cy, cn, ck = blendermann_wind_coefficients(
            self.loa, self.area_lateral, self.area_frontal, self.s_L, self.s_H,
            self.relative_wind_direction_deg, self.air_density,
            self.cd_t, self.cd_lAF_bow, self.cd_lAF_stern, self.delta, self.kappa,
        )

        # Load = coefficient * wind speed^2
        v2 = self.wind_speed ** 2
        self.X, self.Y, self.N, self.K = cx * v2, cy * v2, cn * v2, ck * v2
        return True
