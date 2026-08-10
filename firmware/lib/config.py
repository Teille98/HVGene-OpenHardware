"""
Global configuration for the high-voltage generator.
"""

from micropython import const

# ----------------------------
# OPERATING MODE
# ----------------------------
# Mode selection: "SQUARE" (continuous square wave) or "PULSE" (pulse train)
MODE = "SQUARE"

# ----------------------------
# GPIO PIN CONFIGURATION
# ----------------------------
PIN_SQUARE = const(0)  # Main square-wave output (GPIO0)
# GPIO1 is the complementary MOSFET output (controlled by the PIO SM alongside GPIO0).
PIN_PULSE_GATE = const(1)  # GPIO1 — second MOSFET (same as PIN_SQUARE + 1)


# ----------------------------
# NOTE: PIO timing constants (dead time, SM frequency) are defined in
# lib/pio_programs.py  (PUSH_PULL_SM_FREQ, PUSH_PULL_DEAD_CYCLES).
# ----------------------------
PIN_SDA = const(6)  # I2C data line
PIN_SCL = const(7)  # I2C clock line

# ----------------------------
# I2C ADDRESSES
# ----------------------------
ENCODER_ADDR = const(0x40)  # M5Stack U135 rotary encoder address
LCD_ADDR = const(0x28)  # I2C LCD address

# ----------------------------
# SQUARE WAVE PARAMETERS
# ----------------------------
FREQ_DEFAULT = const(30_000)  # Default frequency (Hz)
SQUARE_FREQ_RANGE = (500, 120_000)  # Min/max range (Hz)
FREQ_STEP = const(500)  # Frequency step (Hz)

# ----------------------------
# PULSE MODE PARAMETERS
# ----------------------------
PULSE_FREQ = const(100)  # Default pulse frequency (Hz)
PULSE_FREQ_RANGE = (10, 10_000)  # Pulse frequency range (Hz)
PULSE_STEP = const(5)  # Pulse frequency step (Hz)
SQUARE_DUTY = 0.5  # Square-wave duty (0.5 = 50%)
PULSE_DUTY = 0.5  # Pulse-train duty (0.5 = 50%)

# ----------------------------
# SYSTEM PARAMETERS
# ----------------------------
I2C_FREQ = const(50_000)  # I2C frequency (Hz) - LCD datasheet constraint
MENU_NAV_THRESHOLD = const(2)  # Menu navigation threshold

# ----------------------------
# INTERFACE PARAMETERS
# ----------------------------
BUTTON_LONG_PRESS_MS = const(700)  # Long-press duration (ms)
UPDATE_INTERVAL_MS = const(100)  # LCD update interval (ms)
BUTTON_CHECK_MS = const(50)  # Button polling interval (ms)
SPINNER_UPDATE_MS = const(200)  # Spinner animation interval (ms)
ENCODER_POLL_MS = const(20)  # Encoder I2C read interval (ms)

# ----------------------------
# LCD DISPLAY PARAMETERS
# ----------------------------
LCD_COLS = const(20)  # LCD column count
LCD_ROWS = const(4)  # LCD row count

# ----------------------------
# UI STATE CONSTANTS
# ----------------------------
UI_STATE_DASHBOARD = "dashboard"
UI_STATE_MENU = "menu"
UI_STATE_SET_TIMER = "set_timer"
UI_STATE_SET_DUTY = "set_duty"
UI_STATE_MONITOR = "monitor"  # Reserved for future functionality

# ----------------------------
# ENCODER AND MENU PARAMETERS
# ----------------------------
ENCODER_MAX_INCREMENT = const(8)  # Clamp for encoder jumps
MENU_ACCEL_WINDOW_MS = const(200)  # Acceleration detection window (ms)
MENU_ACCEL_DIVIDER = const(3)  # Acceleration divisor

# ----------------------------
# TIMER AND DUTY CYCLE PARAMETERS
# ----------------------------
TIMER_MIN_MINUTES = const(1)  # Minimum timer duration (minutes)
TIMER_MAX_MINUTES = const(240)  # Maximum timer duration (4 hours)
DUTY_CYCLE_STEP = 0.05  # Duty cycle adjustment step (5%)
DUTY_CYCLE_MIN = 0.05  # Minimum duty cycle (5%)
DUTY_CYCLE_MAX = 1.0  # Maximum duty cycle (100%)

# ----------------------------
# SAVE PARAMETERS
# ----------------------------
SETTINGS_SAVE_DEBOUNCE_MS = const(2000)  # Auto-save debounce delay (ms)

# ----------------------------
# BOOT PARAMETERS
# ----------------------------
AUTO_START_ON_BOOT = False  # Safe boot: generation OFF at startup

# ----------------------------
# SOFTWARE INFO
# ----------------------------
SOFTWARE_NAME = "HVGenerator"
SOFTWARE_VERSION = "v3.0"
SOFTWARE_AUTHOR = "Teo Serra"
SOFTWARE_BUILD_DATE = "2026-04-08"
SOFTWARE_LICENSE = "CC BY-SA 4.0"
