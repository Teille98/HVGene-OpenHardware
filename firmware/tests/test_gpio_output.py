"""Basic GPIO and PIO output sanity check for RP2040 (MicroPython)."""

from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
import time


@asm_pio(set_init=PIO.OUT_LOW)
def square_1pin():
    wrap_target()
    set(pins, 0b00001) [15]
    set(pins, 0b00000) [15]
    wrap()

PIN_OUTPUT = 0


def main():
    """Run quick GPIO and PIO checks on GPIO0."""
    print("\n=== SIMPLE GPIO / PIO TEST ===")
    print("Measure on GPIO0 (on XIAO RP2040 this is often pin D6)")

    # 1) Quick manual toggling on GPIO0.
    pin0 = Pin(PIN_OUTPUT, Pin.OUT)
    print("1) Manual GPIO0 toggle test for 2 seconds...")
    for _ in range(8):
        pin0.toggle()
        time.sleep(0.25)
    pin0.value(0)
    print("   [OK]")

    # 2) PIO signal test at a visible and stable frequency.
    # 2 instructions x (1 + 15 delays) = 32 cycles per output period.
    # Output frequency = state machine frequency / 32.
    freq_sm = 2 * 320_000  # about 10 kHz output
    print("2) PIO test on GPIO0 for 10 seconds...")
    print("   State machine frequency:", freq_sm, "Hz")
    print("   Expected output frequency: ~10 kHz")

    sm = None
    try:
        sm = StateMachine(0, square_1pin, freq=freq_sm, set_base=Pin(PIN_OUTPUT))
        sm.active(1)
        time.sleep(10)
        print("   [OK]")
    except Exception as error:
        print("   [ERROR]:", error)
    finally:
        if sm is not None:
            sm.active(0)
        pin0.value(0)

    print("=== TEST COMPLETE ===")


if __name__ == "__main__":
    main()
