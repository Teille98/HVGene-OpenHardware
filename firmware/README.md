# HVGene

## Quick Description

HVGene is an RP2040-based high-voltage signal generator (MicroPython) with an I2C LCD and rotary encoder user interface.

The firmware provides two modes:
- SQUARE: continuous square signal
- PULSE: ON/OFF gating of the square signal with adjustable pulse frequency and duty cycle

## Target Hardware

- RP2040 (Raspberry Pi Pico / XIAO RP2040)
- M5Stack U135 encoder (I2C 0x40)
- LCD 20x4 NHD-0420D3Z (I2C 0x28)

Used pins:
- GPIO0: MOSFET A gate (PIO SM0, push-pull)
- GPIO1: MOSFET B gate (PIO SM0, complementary — same SM as GPIO0)
- GPIO6: I2C SDA
- GPIO7: I2C SCL

> **Note**: there is no dedicated "pulse gate" pin. PULSE mode gating is
> achieved by overriding the GPIO pad OUTOVER registers (RP2040 CTRL),
> which forces both GPIO0/GPIO1 LOW without stopping the PIO SM.

## Quick Start

1. Flash MicroPython onto the RP2040.
2. Copy main.py and the lib/ folder to the board.
3. Connect the RP2040 to the custom PCB.
4. Reboot the board.

## Project Structure

```
HVGene_Simple/
|-- main.py
|-- README.md
|-- lib/
|   |-- config.py
|   |-- generator.py
|   |-- hardware.py
|   |-- logger.py
|   |-- pio_programs.py
|   |-- storage.py
|   `-- README.md
`-- tests/
    |-- README.md
    |-- test_i2c_devices.py
    |-- test_lcd_output.py
    |-- test_encoder.py
    |-- test_gpio_output.py
    |-- test_pio_simple.py
    |-- test_pulse_timing.py
    `-- test_duty_cycle.py
```

## Main File Roles

- `main.py`: firmware entry point.
- `lib/config.py`: configuration constants (GPIO, frequencies, UI limits).
- `lib/pio_programs.py`: PIO program for push-pull drive.
- `lib/hardware.py`: I2C drivers (encoder + LCD).
- `lib/generator.py`: application logic and UI state machine.
- `lib/logger.py`: logging.
- `lib/storage.py`: settings save/load.
- `tests/`: hardware and timing validation scripts.

## Tests

The recommended procedure and test descriptions are available in [tests/README.md](tests/README.md).

Recommended order:
1. `test_i2c_devices.py`
2. `test_lcd_output.py`
3. `test_encoder.py`
4. `test_gpio_output.py`
5. `test_pio_simple.py`
6. `test_pulse_timing.py`
7. `test_duty_cycle.py`

## License

MIT — see [LICENSE](LICENSE).
