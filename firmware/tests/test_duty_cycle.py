"""Duty-cycle validation helper for square half-phase duty.

This script checks I2C visibility and prints expected active/dead timing
values used by the push-pull state machine. Use it with the main application
and an oscilloscope to validate the half-phase duty behavior.
"""

from machine import I2C, Pin


# I2C configuration
I2C_SCL = 7
I2C_SDA = 6
I2C_FREQ = 50000
SM1_FREQ = 1_000_000
PIO_CYCLE_OVERHEAD = 8


def print_reference_duty_values():
    """Print reference cycle values for common square half-phase settings."""
    print("\n=== Duty Cycle Reference ===")
    print("State machine clock: 1 MHz (1 cycle = 1 us)")

    test_configs = [
        (10, 0.25),
        (10, 0.50),
        (10, 0.75),
        (100, 0.50),
        (100, 1.00),
    ]

    for pulse_freq, duty in test_configs:
        period_us = 1_000_000 / pulse_freq
        half_us = period_us / 2
        active_us = half_us * duty
        dead_us = half_us - active_us

        half_cycles = max(2, (SM1_FREQ // pulse_freq - PIO_CYCLE_OVERHEAD) // 2)
        active_cycles = max(1, int(round(half_cycles * duty)))
        dead_cycles = max(1, half_cycles - active_cycles)

        print(f"\nSquare: {pulse_freq} Hz, Duty: {int(duty * 100)}%")
        print(f"  Period: {period_us:.0f} us")
        print(f"  Active per half-phase: {active_us:.0f} us ({active_cycles} cycles)")
        print(f"  Dead per half-phase: {dead_us:.0f} us ({dead_cycles} cycles)")
        print(f"  Total programmed cycles: {2 * (active_cycles + dead_cycles)}")
        print(f"  Effective period with overhead: {2 * (active_cycles + dead_cycles) + PIO_CYCLE_OVERHEAD} cycles")


def check_i2c():
    """Check that expected I2C peripherals are visible."""
    i2c = I2C(1, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
    devices = i2c.scan()

    print("\n=== I2C Scan ===")
    if devices:
        print(f"Detected devices: {[hex(device) for device in devices]}")
        if 0x40 in devices:
            print("[OK] M5Stack U135 encoder detected (0x40)")
        if 0x28 in devices:
            print("[OK] NHD-0420D3Z LCD detected (0x28)")
    else:
        print("[ERROR] No I2C devices detected")

    return len(devices) > 0


def main():
    """Main entry point."""
    print("\n" + "=" * 40)
    print("DUTY CYCLE TEST - SQUARE HALF-PHASE MODE")
    print("=" * 40)

    # Check basic hardware visibility first.
    if not check_i2c():
        print("\n[WARNING] I2C peripherals were not detected")
        print("Check wiring:")
        print("  - SDA: GPIO", I2C_SDA)
        print("  - SCL: GPIO", I2C_SCL)
        return

    print_reference_duty_values()

    print("\n" + "=" * 40)
    print("INSTRUCTIONS")
    print("=" * 40)
    print("1. Run main.py")
    print("2. Short press -> open menu")
    print("3. Navigate to 'Sq.Duty'")
    print("4. Short press -> edit mode")
    print("5. Rotate encoder: +/-5% per step")
    print("6. Short press -> confirm")
    print("\nRange: 5% to 100% (step: 5%)")
    print("Default: 50%")
    print("\nNote: duty cycle is shown on the main dashboard as Sq.Duty")
    print("=" * 40)


if __name__ == "__main__":
    main()
