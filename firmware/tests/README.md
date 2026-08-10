# Tests - Simple HV Generator

## Overview

This folder contains hardware-oriented test and diagnostic scripts for the RP2040-based HV generator.
All scripts are intended for manual validation through REPL logs and oscilloscope checks.

## Test Scripts

### test_i2c_devices.py

Fast hardware presence check for both I2C devices.

What it checks:
- I2C bus scan
- Encoder register probe (position + button)
- LCD clear command probe

Usage:

```python
import test_i2c_devices
test_i2c_devices.main()
```

### test_lcd_output.py

Visual LCD output test (line mapping and dynamic updates).

What it checks:
- LCD detection at 0x28
- Clear / contrast / backlight commands
- Text placement on 4 lines
- Timed progress update

Usage:

```python
import test_lcd_output
test_lcd_output.main()
```

### test_encoder.py

I2C validation for the M5Stack U135 rotary encoder unit.

What it checks:
- I2C bus scan
- Encoder position readout
- Push-button readout with basic debounce
- RGB LED write command sequence

Usage:

```python
import test_encoder
test_encoder.main()
```

### test_gpio_output.py

Quick GPIO0 sanity check, then a simple PIO square-wave output run.

Usage:

```python
import test_gpio_output
test_gpio_output.main()
```

### test_pio_simple.py

Minimal standalone PIO square-wave test on GPIO0.
Useful to isolate PIO behavior from the full application.

Usage:

```python
import test_pio_simple
```

### test_pulse_timing.py

PULSE mode timing verification using dedicated PIO state machines.
Prints theoretical ON/OFF timings for oscilloscope comparison.

Usage:

```python
import test_pulse_timing
```

### test_duty_cycle.py

Duty-cycle reference helper for menu-based PULSE mode control.
Prints expected ON/OFF durations and cycle counts for common settings.

Usage:

```python
import test_duty_cycle
test_duty_cycle.main()
```

## Recommended Test Procedure

Follow this sequence to reduce troubleshooting time.

### 1. Prepare Hardware

1. Power the RP2040 board.
2. Connect I2C peripherals:
   - SDA: GPIO6
   - SCL: GPIO7
3. Connect measurement tools:
   - Oscilloscope CH1 to GPIO0 (square output)
   - Oscilloscope CH2 to GPIO2 (gate signal)

### 2. Check I2C Presence

Run:

```python
import test_i2c_devices
test_i2c_devices.main()
```

Expected addresses:
- 0x40 (M5Stack U135 encoder)
- 0x28 (LCD controller)

### 3. Validate LCD Output

Run:

```python
import test_lcd_output
test_lcd_output.main()
```

Success criteria:
- All four lines are readable
- Progress line updates from 1/5 to 5/5

### 4. Validate Encoder and Button

Run:

```python
import test_encoder
test_encoder.main()
```

Success criteria:
- Encoder values change while rotating
- Button press and release events appear

### 5. Validate Basic GPIO/PIO Output

Run:

```python
import test_gpio_output
test_gpio_output.main()
```

Success criteria:
- Manual GPIO toggle phase completes
- PIO output phase runs for 10 seconds
- Scope shows a stable square wave on GPIO0

### 6. Validate PIO Frequency Steps

Run:

```python
import test_pio_simple
```

Success criteria:
- Low-frequency test visible on scope
- 1 kHz test visible and stable
- 30 kHz test active until interrupted

### 7. Validate PULSE Timing

Run:

```python
import test_pulse_timing
```

Success criteria:
- GPIO2 period is close to 100 ms at 10 Hz
- ON/OFF windows match printed cycle computations
- No visible jitter over multiple minutes

### 8. Validate Duty-Cycle Behavior Through UI

Run:

```python
import test_duty_cycle
test_duty_cycle.main()
```

Then in the main app menu:
1. Open menu with short press.
2. Select Duty %.
3. Adjust by encoder steps.
4. Confirm and measure GPIO2 ON/OFF ratio on scope.

## Expected Register Map (Encoder 0x40)

- 0x10: encoder position (signed 16-bit, little-endian)
- 0x20: button state
- 0x30: RGB LED control (4 bytes: led_index, R, G, B)

## Quick Troubleshooting

### No I2C devices found

- Check SDA/SCL wiring and ground reference
- Verify module power rails
- Lower I2C frequency and retry

### LCD writes fail

- Confirm LCD address is 0x28 in scan output
- Reboot the board and retry test_lcd_output.py
- Keep I2C frequency at 50 kHz

### Encoder does not respond

- Confirm device address is 0x40
- Reboot the board and rerun test_encoder.py

### No output on GPIO0

- Confirm probe ground and channel scaling
- Ensure no other code owns the same state machine or pin
- Retry with test_pio_simple.py low-frequency stage first

## References

- https://docs.m5stack.com/en/unit/encoder
- https://www.mouser.fr/datasheet/2/291/NHD_0420D3Z_FL_GBW_V3-1104093.pdf
- https://github.com/raspberrypi/pico-examples/tree/master/pio
