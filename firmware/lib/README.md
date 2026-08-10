# HVGene - lib/

## Overview

The lib/ folder contains all firmware application modules.
main.py initializes hardware and runs the main logic implemented here.

## Current Structure

```
lib/
|-- config.py
|-- generator.py
|-- hardware.py
|-- logger.py
|-- pio_programs.py
`-- storage.py
```

## Module Roles

- `config.py`: global constants (GPIO pins, I2C addresses, limits, frequencies, UI).
- `pio_programs.py`: PIO program used by the push-pull StateMachine.
- `hardware.py`: I2C peripheral drivers:
  - `I2CRotaryEncoder`
  - `LCDController`
- `generator.py`: HTGenerator class, application core:
  - SQUARE/PULSE mode control
  - menu/UI handling
  - state-machine control
  - runtime parameter updates
- `logger.py`: multi-level logging helper.
- `storage.py`: user settings persistence.

## Execution Flow

1. main.py creates the I2C bus.
2. HTGenerator (in generator.py) creates hardware abstractions.
3. PIO programs (in pio_programs.py) are loaded into the push-pull state machine.
4. The main loop handles encoder/LCD UI and generation updates.

## Maintenance Rules

- Add new constants in config.py (avoid magic values).
- Keep peripheral access isolated in hardware.py.
- Keep business logic and UI logic in generator.py.
- Update [../tests/README.md](../tests/README.md) when behavior changes impact test procedure.

## Useful Links

- Project README: [../README.md](../README.md)
- Test procedure: [../tests/README.md](../tests/README.md)
