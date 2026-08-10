"""
Quick test to verify I2C communication with the M5Stack U135 encoder.
Run in Thonny or via REPL to diagnose the I2C wiring.
"""

from machine import Pin, I2C
import time

# I2C configuration
SDA_PIN = 6
SCL_PIN = 7
I2C_FREQ = 50000

# I2C addresses
ENCODER_ADDR = 0x40
LCD_ADDR = 0x28

# M5Stack U135 registers
REG_ENCODER = 0x10
REG_BUTTON = 0x20
REG_RGB_LED = 0x30
BUTTON_ACTIVE_LOW = True

def scan_i2c_bus():
    """Scan the I2C bus to detect peripherals."""
    print("=== I2C bus scan ===")
    i2c = I2C(1, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    devices = i2c.scan()
    
    if not devices:
        print("[ERROR] No I2C peripherals detected")
        return None
    
    print(f"[OK] Detected peripherals: {len(devices)}")
    for addr in devices:
        print(f"  - Address: 0x{addr:02X}")
        if addr == ENCODER_ADDR:
            print("    - M5Stack U135 encoder")
        elif addr == LCD_ADDR:
            print("    - LCD controller")
    
    return i2c

def test_encoder(i2c):
    """Test encoder reading."""
    print("\n=== M5Stack U135 encoder test ===")
    
    if ENCODER_ADDR not in i2c.scan():
        print(f"[ERROR] Encoder not detected at address 0x{ENCODER_ADDR:02X}")
        return
    
    print("[OK] Encoder detected")
    print("Rotate the encoder to see values...")
    print("Press the button to test...")
    print("(Ctrl+C to stop)\n")
    
    last_value = 0
    
    # Automatic button polarity detection (active-low vs active-high)
    def _auto_detect_button(i2c, samples=10, delay_ms=10):
        ones = 0
        zeros = 0
        for _ in range(samples):
            try:
                b = int(i2c.readfrom_mem(ENCODER_ADDR, REG_BUTTON, 1)[0])
            except Exception:
                b = 0
            if b:
                ones += 1
            else:
                zeros += 1
            time.sleep_ms(delay_ms)
        # If most reads are 1, the released state is 1, which means active-low
        return ones >= zeros

    try:
        detected = _auto_detect_button(i2c)
    except Exception:
        detected = BUTTON_ACTIVE_LOW
    # Prefer automatic detection
    button_active_low = detected
    # Variables for debounce and reduced output
    last_btn_raw = None
    stable_count = 0
    STABLE_THRESHOLD = 3
    last_pressed_state = False

    try:
        while True:
            # Read encoder value
            try:
                data = i2c.readfrom_mem(ENCODER_ADDR, REG_ENCODER, 2)
                value = data[0] | (data[1] << 8)
                if value >= 32768:
                    value -= 65536
                
                if value != last_value:
                    increment = value - last_value
                    print(f"Encoder: {value:5d} (delta: {increment:+3d})")
                    last_value = value
            except OSError as e:
                print(f"Encoder read error: {e}")
            
            # Read the button (with debounce)
            try:
                btn_data = i2c.readfrom_mem(ENCODER_ADDR, REG_BUTTON, 1)
                raw = int(btn_data[0])
                # Debounce: count consecutive identical reads
                if last_btn_raw is None or raw != last_btn_raw:
                    last_btn_raw = raw
                    stable_count = 1
                else:
                    stable_count += 1

                # When the state is stable for STABLE_THRESHOLD reads, display it
                if stable_count == STABLE_THRESHOLD:
                    print(f"Raw button value (stable): {raw}")
                    if button_active_low:
                        pressed = (raw == 0)
                    else:
                        pressed = (raw != 0)

                    if pressed and not last_pressed_state:
                        print("[BUTTON] PRESSED")
                    elif not pressed and last_pressed_state:
                        print("[BUTTON] RELEASED")
                    last_pressed_state = pressed
            except OSError as e:
                print(f"Button read error: {e}")
            
            time.sleep_ms(50)
    
    except KeyboardInterrupt:
        print("\n\n[OK] Test complete")

def test_rgb_led(i2c):
    """Test the encoder RGB LEDs."""
    print("\n=== RGB LED test ===")
    
    if ENCODER_ADDR not in i2c.scan():
        print("[ERROR] Encoder not detected")
        return
    
    colors = [
        ("Red", 1, 100, 0, 0),
        ("Green", 1, 0, 100, 0),
        ("Blue", 1, 0, 0, 100),
        ("Yellow", 1, 100, 100, 0),
        ("Cyan", 1, 0, 100, 100),
        ("Magenta", 1, 100, 0, 100),
        ("White", 1, 100, 100, 100),
        ("Off", 1, 0, 0, 0),
    ]
    
    for name, led, r, g, b in colors:
        print(f"LED {led}: {name} (R:{r}, G:{g}, B:{b})")
        try:
            data = bytes([led, r, g, b])
            i2c.writeto_mem(ENCODER_ADDR, REG_RGB_LED, data)
            time.sleep_ms(500)
        except OSError as e:
            print(f"[ERROR] {e}")
    
    print("[OK] LED test complete")

def main():
    """Main test program."""
    print("\n" + "="*50)
    print("M5Stack U135 encoder I2C test")
    print("="*50 + "\n")
    
    # Scan the I2C bus.
    i2c = scan_i2c_bus()
    
    if i2c is None:
        print("\n[ERROR] Check the I2C connections:")
        print(f"  - SDA: GPIO {SDA_PIN}")
        print(f"  - SCL: GPIO {SCL_PIN}")
        print(f"  - VCC: 5V")
        print(f"  - GND: GND")
        return
    
    # Test menu
    print("\n=== Test menu ===")
    print("1. Scan the I2C bus")
    print("2. Test the encoder (rotation + button)")
    print("3. Test the RGB LEDs")
    print("4. Run everything")
    
    # For now, run the encoder test directly.
    # In a REPL, you can call the functions individually.
    test_encoder(i2c)

if __name__ == "__main__":
    main()
