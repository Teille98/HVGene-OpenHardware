# Validation dataset

`HVGene_validation_dataset.xlsx` contains every operating point measured for the
*Validation and characterization* section of the HardwareX article, with the raw
readings and the derived quantities used in its figures and tables.

| Sheet | Content |
|---|---|
| `Equipment` | Instruments used and measurement-uncertainty parameters |
| `Exp 1 - Probe_Characterization` | Open-circuit characterization (HV probe only as load): V-sweeps at 10, 15 and 20 kHz and frequency sweep |
| `Exp 2.1 - DBD_V_sweep` | DBD reactor connected: buck-voltage sweeps at fixed frequency, 100 % and 50 % duty, pulsed mode |
| `Exp 2.2 - DBD_Freq_sweep` | DBD reactor connected: frequency sweeps at fixed buck voltage |
| `Exp 2.3 - DBD_DutyCycle_sweep` | DBD reactor connected: duty-cycle sweeps (continuous and pulsed burst) |
| `Exp 3 - Thermal_test` | 15-minute endurance runs (heatsink and transformer temperatures, input power) |
| `Exp 4 - Reproducibility` | Ignition-threshold repeatability (cold restarts) and stable-point repeatability |
| `Data_consolidated` | All steps pooled in a single table, with uncertainties |

Each experiment sheet is organized in blocks (one set of conditions per block) and
steps (one setpoint per row). Main columns: *Turns/branch* = primary turns per branch,
*V_Buck setpoint* = buck-voltage setpoint, *I_primary* = primary current,
*V_secondary_pp* = secondary peak-to-peak voltage, *Real Power_scope* = real power
read on the oscilloscope, *Plasma state* = plasma present (1) or not (0).
*THD (fraction)* = total harmonic distortion of the secondary voltage as a fraction
(0.11 = 11 %), computed from the harmonic amplitudes in the following columns.
Blocks marked *[SECONDARY]* (1 turn/branch) are an optional sensitivity check and
are not used in the article.

The article figures built from this file are in `docs/Figures/Article_Figures/`.

Licence: CC BY-SA 4.0, as for `docs/`.
