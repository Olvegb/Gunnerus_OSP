"""Test FMU: the smallest possible example of the config_path set-up.

    output = input * test

  - input:   set in OspSystemStructure.xml (or connected from another FMU)
  - test:    a constant read from [test] in config.toml
  - output:  calculated in do_step
"""
import tomllib
from pathlib import Path

from pythonfmu import Fmi2Causality, Fmi2Slave, Fmi2Variability, Real, String


class Test(Fmi2Slave):

    description = "Minimal example: output = input * test, where test is read from config.toml"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 1. PARAMETER: where the config file is. Set in OspSystemStructure.xml.
        self.config_path = ""
        self.register_variable(String("config_path", causality=Fmi2Causality.parameter,
                                      variability=Fmi2Variability.fixed))

        # 2. INPUT and OUTPUT: visible to the co-simulation.
        self.input = 0.0
        self.output = 0.0
        self.register_variable(Real("input", causality=Fmi2Causality.input))
        self.register_variable(Real("output", causality=Fmi2Causality.output))

        # 3. CONSTANT: a plain Python variable, filled in from the config file below.
        self.test = 0.0

    def exit_initialization_mode(self):
        # Runs once, right before the simulation starts: read the config file.
        config = tomllib.loads(Path(self.config_path).read_text(encoding="utf-8-sig"))
        self.test = float(config["test"]["test"])

    def do_step(self, current_time, step_size):
        # Runs every time step.
        self.output = self.input * self.test
        return True
