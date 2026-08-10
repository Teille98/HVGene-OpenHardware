"""Quick I2C device health check for RP2040 hardware.

This script scans the I2C bus and performs lightweight probes on known devices:
- M5Stack U135 encoder at 0x40
- LCD controller at 0x28
"""

from machine import I2C, Pin
import time


# I2C configuration
SDA_PIN = 6
SCL_PIN = 7
I2C_FREQ = 50000

# Expected I2C addresses
ENCODER_ADDR = 0x40
LCD_ADDR = 0x28

# Encoder registers
REG_ENCODER = 0x10
REG_BUTTON = 0x20


def scan_bus(i2c):
    """Scan I2C bus and return a sorted list of addresses."""
    devices = sorted(i2c.scan())
    print("\n=== I2C BUS SCAN ===")
    if not devices:
        print("[ERROR] No I2C devices detected")
        return []

    print(f"[OK] Detected {len(devices)} device(s):")
    for address in devices:
        print(f"  - 0x{address:02X}")
    return devices


def probe_encoder(i2c):
    """Read encoder and button registers once to validate communication."""
    print("\n=== ENCODER PROBE (0x40) ===")
    try:
        data = i2c.readfrom_mem(ENCODER_ADDR, REG_ENCODER, 2)
        value = data[0] | (data[1] << 8)
        if value >= 32768:
            value -= 65536
        button = int(i2c.readfrom_mem(ENCODER_ADDR, REG_BUTTON, 1)[0])
        print(f"[OK] Encoder value: {value}")
        print(f"[OK] Raw button value: {button}")
        return True
    except OSError as error:
        print(f"[ERROR] Encoder probe failed: {error}")
        return False


def probe_lcd(i2c):
    """Send a clear-screen command to validate LCD write path."""
    print("\n=== LCD PROBE (0x28) ===")
    try:
        i2c.writeto(LCD_ADDR, bytes([0xFE, 0x51]))
        time.sleep_ms(10)
        print("[OK] LCD clear command sent")
        return True
    except OSError as error:
        print(f"[ERROR] LCD probe failed: {error}")
        return False


def main():
    """Run full I2C hardware probe."""
    print("\n" + "=" * 50)
    print("I2C DEVICE TEST")
    print("=" * 50)
    print(f"SDA: GPIO{SDA_PIN}, SCL: GPIO{SCL_PIN}, Freq: {I2C_FREQ} Hz")

    i2c = I2C(1, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    devices = scan_bus(i2c)

    encoder_ok = False
    lcd_ok = False

    if ENCODER_ADDR in devices:
        encoder_ok = probe_encoder(i2c)
    else:
        print("\n=== ENCODER PROBE (0x40) ===")
        print("[WARNING] Encoder address not found in scan")

    if LCD_ADDR in devices:
        lcd_ok = probe_lcd(i2c)
    else:
        print("\n=== LCD PROBE (0x28) ===")
        print("[WARNING] LCD address not found in scan")

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Encoder present: {'YES' if ENCODER_ADDR in devices else 'NO'}")
    print(f"LCD present: {'YES' if LCD_ADDR in devices else 'NO'}")
    print(f"Encoder probe: {'PASS' if encoder_ok else 'FAIL'}")
    print(f"LCD probe: {'PASS' if lcd_ok else 'FAIL'}")


if __name__ == "__main__":
    main()
