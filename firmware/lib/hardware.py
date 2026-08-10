"""
Hardware peripheral handling (encoder, LCD).
"""
import time
from micropython import const


class I2CRotaryEncoder:
    """I2C handler for the M5Stack U135 rotary encoder."""
    
    __slots__ = (
        'i2c', 'addr', '_last_value', '_button_pressed',
        'button_active_low', '_last_btn_raw', '_stable_count', 
        '_stable_threshold', '_last_pressed_state'
    )
    
    # M5Stack U135 I2C registers
    REG_ENCODER = const(0x10)  # Encoder value (2 bytes, signed)
    REG_BUTTON = const(0x20)   # Button status (1 byte)
    REG_RGB_LED = const(0x30)  # RGB LED control (4 bytes)
    
    def __init__(self, i2c, addr=0x40):
        self.i2c = i2c
        self.addr = addr
        self._last_value = 0
        self._button_pressed = False
        
        # Button detection and state (active-low by default: 0 = pressed)
        self.button_active_low = True
        self._last_btn_raw = None
        self._stable_count = 0
        self._stable_threshold = 3
        self._last_pressed_state = False
        
        # Try automatic polarity detection
        try:
            self.button_active_low = self._auto_detect_button()
        except Exception:
            pass
        
        # Initialize encoder value
        try:
            self._last_value = self._read_encoder_value()
        except OSError:
            pass

    def _auto_detect_button(self, samples=10, delay_ms=5):
        """
        Auto-detect whether the button is active-low by reading multiple samples.
        If most reads are 1, the released state is 1, which means active-low.
        """
        ones = 0
        zeros = 0
        for _ in range(samples):
            try:
                b = int(self.i2c.readfrom_mem(self.addr, self.REG_BUTTON, 1)[0])
            except (OSError, IndexError):
                b = 0
            if b:
                ones += 1
            else:
                zeros += 1
            time.sleep_ms(delay_ms)
        return ones >= zeros
    
    def _read_encoder_value(self):
        """Read the current encoder value (signed 16-bit)."""
        try:
            data = self.i2c.readfrom_mem(self.addr, self.REG_ENCODER, 2)
            # Signed little-endian conversion
            value = data[0] | (data[1] << 8)
            if value >= 32768:  # If the sign bit is set
                value -= 65536
            return value
        except OSError:
            return self._last_value
    
    def _read_button_status(self):
        """
        Read the button state with debounce and polarity handling.
        Returns True when pressed (debounced), False otherwise.
        On I2C error, keeps the previous state.
        """
        try:
            data = self.i2c.readfrom_mem(self.addr, self.REG_BUTTON, 1)
            raw = int(data[0])
        except OSError:
            return self._last_pressed_state

        # Debounce: count consecutive identical reads
        if self._last_btn_raw is None or raw != self._last_btn_raw:
            self._last_btn_raw = raw
            self._stable_count = 1
        else:
            self._stable_count += 1

        if self._stable_count >= self._stable_threshold:
            if self.button_active_low:
                pressed = (raw == 0)
            else:
                pressed = (raw != 0)
            self._last_pressed_state = pressed

        return self._last_pressed_state

    def read_button_raw(self):
        """
        Return the raw value read from the button register (0..255).
        On error, return the last known value or 0.
        """
        try:
            data = self.i2c.readfrom_mem(self.addr, self.REG_BUTTON, 1)
            return int(data[0])
        except (OSError, IndexError, ValueError):
            return int(self._last_btn_raw or 0)
    
    def get_increment(self):
        """Return the increment since the last read."""
        current = self._read_encoder_value()
        increment = current - self._last_value
        self._last_value = current
        return increment
    
    def is_button_pressed(self):
        """Check whether the button is pressed."""
        return self._read_button_status()
    
    def reset_value(self):
        """Reset the encoder reference value."""
        self._last_value = self._read_encoder_value()
    
    def set_rgb_led(self, led_index, r, g, b):
        """Set the color of an RGB LED (led_index: 1 or 2)."""
        try:
            data = bytes([led_index, r, g, b])
            self.i2c.writeto_mem(self.addr, self.REG_RGB_LED, data)
        except OSError:
            pass


class LCDController:
    """Controller for a 20x4 I2C LCD."""
    
    __slots__ = ('i2c', 'addr', 'buf', '_cache', '_cols', '_rows', '_desynced')
    
    def __init__(self, i2c, addr):
        self.i2c = i2c
        self.addr = addr
        self.buf = bytearray(3)
        self._cols = 20
        self._rows = 4
        self._cache = ["" for _ in range(self._rows)]
        self._desynced = False
        self._init()
    
    def _init(self):
        """Initialize the LCD."""
        try:
            self._send_cmd(0x51)         # Clear the screen
            self._send_cmd(0x52, 200)    # Contrast
            self._send_cmd(0x53, 150)    # Backlight
        except OSError:
            pass
    
    def _send_cmd(self, cmd, param=None):
        """Send a command to the LCD."""
        self.buf[0] = 0xFE
        self.buf[1] = cmd
        ok = False
        for _ in range(3):
            try:
                if param is not None:
                    self.buf[2] = param
                    self.i2c.writeto(self.addr, self.buf[:3])
                else:
                    self.i2c.writeto(self.addr, self.buf[:2])
                ok = True
                break
            except OSError:
                time.sleep_ms(2)
        if not ok:
            self._desynced = True
        time.sleep_us(2000)
        return ok

    def define_custom_char(self, slot, bitmap):
        """
        Define a custom 5x8 character in CGRAM.
        slot: 0..7
        bitmap: iterable of 8 row values (only lower 5 bits are used)
        Returns True on success, False on I2C/parameter error.
        """
        try:
            s = int(slot)
            if s < 0 or s > 7:
                return False
            rows = list(bitmap)
            if len(rows) != 8:
                return False

            data = [int(r) & 0x1F for r in rows]

            # Newhaven serial LCD protocol: 0xFE 0x54 <slot> <8 bytes>
            # This board is not a raw HD44780 bus, it expects serialized commands.
            try:
                payload = bytes([0xFE, 0x54, s] + data)
                self.i2c.writeto(self.addr, payload)
                time.sleep_ms(5)
                self._desynced = False
                return True
            except OSError:
                # Fallback for HD44780-like bridges that accept direct CGRAM writes.
                self._send_cmd(0x40 + (s * 8))
                self.i2c.writeto(self.addr, bytes(data))
                self._send_cmd(0x80)
                self._desynced = False
                return True
        except (OSError, ValueError, TypeError):
            self._desynced = True
            return False
    
    def write(self, text, row=1, col=1):
        """Write text at a given position."""
        pos = [0x00, 0x40, 0x14, 0x54][row-1] + (col-1)
        if not self._send_cmd(0x45, pos):
            return False
        payload = text.encode()
        for _ in range(3):
            try:
                self.i2c.writeto(self.addr, payload)
                self._desynced = False
                return True
            except OSError:
                time.sleep_ms(2)
        self._desynced = True
        return False

    def clear(self):
        """Clear the screen."""
        try:
            if self._send_cmd(0x51):
                self._desynced = False
            self._cache = ["" for _ in range(self._rows)]
        except OSError:
            pass

    def invalidate_cache(self):
        """Force the next write_line calls to refresh every row."""
        self._cache = ["" for _ in range(self._rows)]

    def set_backlight(self, level):
        """Set the backlight level (0-255)."""
        lvl = max(0, min(255, int(level)))
        self._send_cmd(0x53, lvl)

    def set_contrast(self, level):
        """Set the contrast level (0-255)."""
        lvl = max(0, min(255, int(level)))
        self._send_cmd(0x52, lvl)

    def write_line(self, row, text):
        """
        Write a full line (padded/truncated to the screen width).
        Uses a cache to avoid unnecessary writes.
        """
        r = max(1, min(self._rows, int(row)))
        s = (text or "")
        if len(s) < self._cols:
            s = s + (" " * (self._cols - len(s)))
        else:
            s = s[:self._cols]
        
        # Update only if the text changed
        cache_idx = r - 1
        if (not self._desynced) and self._cache[cache_idx] == s:
            return
        if self.write(s, row=r, col=1):
            self._cache[cache_idx] = s
