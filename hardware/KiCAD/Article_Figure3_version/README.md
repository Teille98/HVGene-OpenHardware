# Schematic as drawn in Figure 3 of the article

This folder holds a second view of the same board schematic, prepared for
Figure 3 of the HardwareX article. It does **not** replace the design files in
`hardware/KiCAD/`, which remain the reference for fabrication.

Differences with `../HVGene.kicad_sch` (drawing only, no change to the circuit or the PCB):
- usual MOSFET symbols for Q1/Q2;
- the off-board transformer (T1) and its extension cable to J3 are drawn dashed, for context.
  T1 is excluded from the board and from the BOM.

Files:
- `HVGene.kicad_sch`: KiCad schematic. Open it from this folder after copying the
  libraries of `../` (`sym-lib-table`, `fp-lib-table` and the `LIB_*` folders) next to it,
  or simply read the PDF.
- `HVGene_schematic_Figure3.pdf`: full-page PDF export of this schematic.
