# HVGene — Open-Source High-Voltage Power Supply for Cold Atmospheric Plasma

Open-source, digitally controlled high-voltage AC power supply for cold atmospheric
plasma (CAP) research, developed with a specific focus on flexible-endoscope
decontamination applications. The platform delivers either continuous sinusoidal
high-voltage excitation or pulsed AC trains, with explicit user control over input
voltage, operating frequency, duty cycle, timing, and operating mode.

This repository accompanies the following HardwareX article:

> *Open-Source High Voltage Power Supply for Cold Atmospheric Plasma Production*,
> HardwareX (2026). DOI: _to be added once assigned_.

If you use this hardware, firmware, or documentation, please cite the article above.

## Repository structure

This project mixes three kinds of content, each released under the license most
appropriate for that kind of content — see the `LICENSE` file inside each folder
for the exact terms.

```
HVGene_OpenHardware/
├── hardware/          Electronics and mechanical design files
│   ├── LICENSE        CERN-OHL-P-2.0 (permissive open hardware licence, unmodified)
│   ├── NOTICE          Copyright notice (kept separate — the licence text itself
│   │                   must not be modified, per its own Preamble)
│   ├── KiCAD/          PCB schematic and layout (push-pull inverter board)
│   ├── CAD-Fusion360/  3D mechanical design (enclosure, mounting)
│   ├── Cutting/        Laser-cutting SVG files (LV/HV plates)
│   └── BOM.xlsx        Bill of materials
├── firmware/           RP2040 / MicroPython control firmware
│   ├── LICENSE          MIT
│   ├── main.py, lib/    Firmware source
│   └── tests/           Bench validation scripts (I2C, PIO, timing)
├── docs/                Build photos, diagrams, and other documentation media
│   ├── LICENSE           CC BY-SA 4.0
│   └── Figures/          All figures used in the article, plus device/setup/plasma
│                         photos, CAD renders, build-step and scope-capture images
└── zip/                 Pre-packaged .zip archives of the folders above, matching
                          the Design Files table in the HardwareX article
```

## Versioning

The version tagged and archived alongside the HardwareX article submission is the
exact hardware/firmware state described and validated in that article. This
repository may continue to evolve after that point (bug fixes, improvements,
community contributions); the archived release is the one to use for reproducing
the results reported in the article.

## Safety

This hardware generates high voltages (up to several tens of kV) and involves
mains-connected power electronics. Building and operating it requires
appropriate electrical safety training. See the "Safety Concerns" and
"Operation instructions" sections of the article before use.
