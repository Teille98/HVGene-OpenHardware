"""
High-Voltage Generator - Main entry point.
Refactored modular version.

This file initializes peripherals and starts the generator.
The application logic lives in lib/.
"""

import time

from machine import I2C, Pin
from rp2 import StateMachine

from lib.config import ENCODER_ADDR, I2C_FREQ, LCD_ADDR, PIN_SCL, PIN_SDA, PIN_SQUARE
from lib.generator import HTGenerator
from lib.pio_programs import gate_pulse_outputs


# ----------------------------
# INITIALIZATION
# ----------------------------
def safe_hw_recovery():
    """Put the RP2040 back into a safe hardware state (SMs OFF + GPIO LOW)."""
    try:
        StateMachine(0).active(0)
    except Exception:
        pass

    try:
        StateMachine(1).active(0)
    except Exception:
        pass

    # Drive both push-pull outputs LOW (GPIO0 and GPIO1)
    try:
        gate_pulse_outputs(PIN_SQUARE, False)
    except Exception:
        pass

    try:
        Pin(PIN_SQUARE, Pin.OUT).value(0)
        Pin(PIN_SQUARE + 1, Pin.OUT).value(0)
    except Exception:
        pass


def main():
    """Main entry point with automatic restart on error."""
    while True:
        try:
            # Preventive cleanup on each cycle to avoid stuck PIO/GPIO states.
            safe_hw_recovery()

            # Initialize the I2C bus
            i2c = I2C(1, scl=Pin(PIN_SCL), sda=Pin(PIN_SDA), freq=I2C_FREQ)

            # Create and run the generator
            generator = HTGenerator(i2c, LCD_ADDR, ENCODER_ADDR)
            try:
                generator._update_display()
            except Exception:
                pass
            generator.run()

        except Exception as e:
            # Ultimate safety net: force outputs LOW before retrying.
            safe_hw_recovery()

            print(f"[FATAL] main loop crash: {e}")
            time.sleep_ms(1000)


# ----------------------------
# PROGRAM START
# ----------------------------
if __name__ == "__main__":
    main()
