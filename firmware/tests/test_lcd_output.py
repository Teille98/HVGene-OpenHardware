"""Basic LCD output test for the NHD-0420D3Z controller (I2C 0x28).

This script verifies clear, cursor positioning, and text writes.
It is designed as a quick visual check before running the full generator.
"""

from machine import I2C, Pin
import time


# I2C configuration
SDA_PIN = 6
SCL_PIN = 7
I2C_FREQ = 50000
LCD_ADDR = 0x28


def lcd_cmd(i2c, cmd, param=None):
    """Send an LCD command with optional parameter."""
    try:
        if param is None:
            i2c.writeto(LCD_ADDR, bytes([0xFE, cmd]))
        else:
            i2c.writeto(LCD_ADDR, bytes([0xFE, cmd, param]))
        time.sleep_ms(2)
        return True
    except OSError as error:
        print(f"[ERROR] LCD command failed (0x{cmd:02X}): {error}")
        return False


def lcd_write(i2c, text):
    """Write raw text bytes to LCD."""
    try:
        i2c.writeto(LCD_ADDR, text.encode())
        return True
    except OSError as error:
        print(f"[ERROR] LCD write failed: {error}")
        return False


def lcd_write_line(i2c, row, text):
    """Write a full line (1..4) with fixed 20-char width."""
    row_base = [0x00, 0x40, 0x14, 0x54]
    row_index = max(1, min(4, int(row))) - 1
    content = (text or "")[:20].ljust(20)

    if not lcd_cmd(i2c, 0x45, row_base[row_index]):
        return False
    return lcd_write(i2c, content)


def main():
    """Run LCD output demo and quick checks."""
    print("\n" + "=" * 50)
    print("LCD OUTPUT TEST")
    print("=" * 50)

    i2c = I2C(1, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    devices = i2c.scan()

    if LCD_ADDR not in devices:
        print(f"[ERROR] LCD not detected at 0x{LCD_ADDR:02X}")
        print(f"Detected devices: {[hex(device) for device in devices]}")
        return

    print(f"[OK] LCD detected at 0x{LCD_ADDR:02X}")

    if not lcd_cmd(i2c, 0x51):
        return
    lcd_cmd(i2c, 0x52, 200)  # Contrast
    lcd_cmd(i2c, 0x53, 150)  # Backlight
    time.sleep_ms(20)

    lcd_write_line(i2c, 1, "HVGEN LCD TEST")
    lcd_write_line(i2c, 2, "Line mapping check")
    lcd_write_line(i2c, 3, "GPIO6/7 I2C 50kHz")
    lcd_write_line(i2c, 4, "If readable: PASS")

    print("[OK] Static text written")
    print("[INFO] Running 5-second animation")

    for step in range(1, 6):
        bar = ("#" * step).ljust(5, "-")
        lcd_write_line(i2c, 4, f"Progress [{bar}] {step}/5")
        time.sleep(1)

    lcd_write_line(i2c, 4, "LCD test complete")
    print("[OK] LCD test complete")


if __name__ == "__main__":
    main()
