"""The physics of the Waves FMU (models/waves.py).

Built into the FMU's resources/ by build_fmus.py, the same way as thruster_cosim/.
  spectra.py    wave spectra and the spreading function
  sea_state.py  turns the spectrum into wave components, keeps the strongest
  settings.py   reads the wave settings from config.toml
"""
