"""Environment FMU: turns the wind in the earth frame into the wind the vessel feels.

Reads the mean wind (speed and direction) from the config file, takes the
vessel heading as an input, and outputs the wind speed and the wind
direction relative to the bow.

Angle conventions (all clockwise, in degrees):
  - wind direction:  where the wind comes FROM, 0 = from north, 90 = from east
  - heading:         where the bow points, 0 = north, 90 = east
  - relative angle:  where the wind comes FROM, seen from the vessel,
                     0 = head-on (from the bow), 90 = from starboard,
                     180 = from astern, 270 = from port

Later this FMU can be extended with slowly varying wind, gusts and so on.
Add their parameters to [wind] in config.toml, and add the variation in
wind_speed_at() below.
"""
import tomllib
from pathlib import Path

from pythonfmu import Fmi2Causality, Fmi2Slave, Fmi2Variability, Real, String


def relative_wind_direction(wind_direction_deg, heading_deg):
    """Wind direction relative to the bow, in [0, 360) degrees.

    Example: wind from 45 deg (north-east), bow pointing 30 deg
    -> the wind comes 15 deg to starboard of the bow.
    """
    return (wind_direction_deg - heading_deg) % 360.0



class Environment(Fmi2Slave):

    author = "Olve Grønås Birkeland"
    description = "Wind seen from the vessel: speed and direction relative to the bow"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # PARAMETER: path to the config file.
        self.config_path = ""
        self.register_variable(String("config_path", causality=Fmi2Causality.parameter,
                                      variability=Fmi2Variability.fixed))

        # INPUT: vessel heading. Set in OspSystemStructure.xml for now,
        # later connected from the hull FMU.
        self.heading_deg = 0.0
        self.register_variable(Real("heading_deg", causality=Fmi2Causality.input))

        # CONSTANTS: read from [wind] in the config file in exit_initialization_mode.
        self.mean_wind_speed = 0.0          # [m/s]
        self.wind_direction_deg = 0.0       # where the wind comes from, clockwise from north [deg]

        # CONSTANTS: read from [waves] in the config file in exit_initialization_mode.
        self.hs = 0.0                       # significant wave height [m]
        self.tp = 0.0                       # peak wave period [s]
        self.waves_from_deg = 0.0           # where the waves come from, clockwise from north [deg]

        # OUTPUTS: wind, connected to the WindLoads FMU's inputs.
        self.wind_speed = 0.0                   # [m/s]
        self.relative_wind_direction_deg = 0.0  # [deg]
        for name in ("wind_speed", "relative_wind_direction_deg"):
            self.register_variable(Real(name, causality=Fmi2Causality.output))

        # OUTPUTS: waves, passed straight on from the config file.
        self.H_s = 0.0                  # [m]
        self.T_p = 0.0                  # [s]
        self.wave_direction_deg = 0.0   # where the waves come from, clockwise from north [deg]
        for name in ("H_s", "T_p", "wave_direction_deg"):
            self.register_variable(Real(name, causality=Fmi2Causality.output))

    def exit_initialization_mode(self):
        if not self.config_path:
            raise ValueError("config_path is not set. Set it in OspSystemStructure.xml.")
        config = tomllib.loads(Path(self.config_path).read_text(encoding="utf-8-sig"))

        wind = config["wind"]
        self.mean_wind_speed = float(wind["mean_speed"])
        self.wind_direction_deg = float(wind["direction_deg"])

        waves = config["waves"]
        self.hs = float(waves["hs"])
        self.tp = float(waves["tp"])
        self.waves_from_deg = float(waves["direction_deg"])

        # Calculate the outputs once already now, so they are correct from
        # time 0 and not 0.0 until the first step.
        self.do_step(0.0, 0.0)


    def do_step(self, current_time, step_size):
        # Outputs at the end of the step.
        self.wind_speed = self.mean_wind_speed
        self.relative_wind_direction_deg = relative_wind_direction(self.wind_direction_deg, self.heading_deg)

        self.H_s = self.hs
        self.T_p = self.tp
        self.wave_direction_deg = self.waves_from_deg
        return True
