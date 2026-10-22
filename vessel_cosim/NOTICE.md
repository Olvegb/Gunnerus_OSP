# Attribution

Based on the mass/damping/restoring structure of `RVG_DP_6DOF` in the NTNU
mcsimpy toolbox, authored by Jan-Erik Hygen, created 2022-11-02 and revised
2023-02-13. Original source notice: Copyright (C) 2023 NTNU, Trondheim;
licensed under GPL-3.0-or-later.

The standalone refactor adds explicit LF/WF interfaces, separate motion synthesis,
Coriolis forces, full-attitude steady-current conversion, validation, and tests.
The original thesis files and installed toolbox were not modified.

`data/tanker.mat` is a processed MSS WAMIT tanker example copied from the
local MSS-master HYDRO library. It is not the Gunnerus vessel dataset and is not
a physically validated LF/DP configuration. Its upstream terms/provenance must
be preserved when distributing. No additional rights to third-party vessel
data are asserted here.

This project's derived source is distributed under GPL-3.0-or-later, without
warranty. See LICENSE for the GPL version 3 text.
