"""
High-voltage signal generation system.

The UI keeps the current menu, encoder, LCD, timer, and settings flow.
The carrier PIO uses a FIFO-based timing word and pulse gating is driven
by a small software loop that toggles the GPIO OUTOVER registers.
"""

import gc
import time

import _thread

from machine import Pin
from rp2 import StateMachine

from lib.config import (
    AUTO_START_ON_BOOT,
    BUTTON_CHECK_MS,
    BUTTON_LONG_PRESS_MS,
    DUTY_CYCLE_MAX,
    DUTY_CYCLE_MIN,
    DUTY_CYCLE_STEP,
    ENCODER_MAX_INCREMENT,
    ENCODER_POLL_MS,
    FREQ_DEFAULT,
    FREQ_STEP,
    MENU_ACCEL_DIVIDER,
    MENU_ACCEL_WINDOW_MS,
    MENU_NAV_THRESHOLD,
    MODE,
    PIN_SQUARE,
    PULSE_DUTY,
    PULSE_FREQ,
    PULSE_FREQ_RANGE,
    PULSE_STEP,
    SOFTWARE_AUTHOR,
    SOFTWARE_BUILD_DATE,
    SOFTWARE_LICENSE,
    SOFTWARE_NAME,
    SOFTWARE_VERSION,
    SPINNER_UPDATE_MS,
    SQUARE_DUTY,
    SQUARE_FREQ_RANGE,
    TIMER_MAX_MINUTES,
    TIMER_MIN_MINUTES,
    UI_STATE_DASHBOARD,
    UI_STATE_MENU,
    UI_STATE_SET_DUTY,
    UI_STATE_SET_TIMER,
    UPDATE_INTERVAL_MS,
)
from lib.hardware import I2CRotaryEncoder, LCDController
from lib.logger import get_logger
from lib.pio_programs import (
    PUSH_PULL_SM_FREQ,
    actual_freq_from_word,
    calc_push_pull_word,
    gate_pulse_outputs,
    push_pull_pio,
)
from lib.storage import GeneratorSettings


class HTGenerator:
    """High-voltage push-pull generator controller."""

    UI_STATE_EDIT = "edit"
    UI_STATE_INFO = "info"
    UI_STATE_PROFILE_SELECT = "select_profile"
    UI_STATE_FREQ_LIMITS = "freq_limits"
    UI_STATE_UI_STEPS = "ui_steps"
    BUTTON_EXTRA_LONG_MS = 1800
    UI_STATE_PROFILES = "profiles"

    # ══════════════════════════════════════════════════════════════════════════
    # Initialization
    # ══════════════════════════════════════════════════════════════════════════

    def __init__(self, i2c, lcd_addr, encoder_addr):
        self.logger = get_logger("HTGen")
        self.logger.info("Initializing generator")

        self.i2c = i2c
        self.lcd_addr = int(lcd_addr)
        self.encoder_addr = int(encoder_addr)
        self.encoder_available = False
        self.lcd_available = False

        # Drive outputs LOW before PIO activation
        self._init_output_pins()

        # Peripherals
        self.lcd = LCDController(i2c, lcd_addr)
        self.encoder = I2CRotaryEncoder(i2c, encoder_addr)
        if not self._check_hardware():
            self.logger.error("Hardware issues detected on I2C bus")

        # Custom CGRAM char 1: backslash '\' for spinner
        _bs = [0b10000, 0b01000, 0b00100, 0b00010, 0b00001, 0, 0, 0]
        if self.lcd.define_custom_char(1, _bs):
            self.spinner_chars = ["|", "/", "-", "\x01"]
        else:
            self.spinner_chars = ["|", "/", "-", "/"]
            self.logger.warning("LCD custom char unavailable, using fallback spinner")

        # Mode-switch protection (cooldown only matters at runtime, not boot)
        self._mode_switching = False
        self._last_mode_change = 0
        self._mode_change_cooldown_ms = 500

        # Settings
        self.settings = GeneratorSettings()

        # ── Generator state (fast-boot: config defaults) ──────────────────────
        self.mode = MODE
        self.current_freq = FREQ_DEFAULT
        self.pulse_freq = PULSE_FREQ
        self.ui_square_freq_min = SQUARE_FREQ_RANGE[0]
        self.ui_square_freq_max = SQUARE_FREQ_RANGE[1]
        self.ui_pulse_freq_min = PULSE_FREQ_RANGE[0]
        self.ui_pulse_freq_max = PULSE_FREQ_RANGE[1]
        self.ui_square_freq_step = FREQ_STEP
        self.ui_pulse_freq_step = PULSE_STEP
        self.square_duty_cycle = SQUARE_DUTY
        self.duty_cycle = PULSE_DUTY
        self.duty_target = "SQUARE"  # used in SET_DUTY screen
        self.timer_minutes = 0

        self._deferred_load_pending = True

        # ── UI state ──────────────────────────────────────────────────────────
        self.ui_state = UI_STATE_DASHBOARD
        self.menu_index = 0
        self.menu_accum = 0
        self.menu_nav_threshold = MENU_NAV_THRESHOLD
        self.menu_accel_count = 0
        self.last_menu_move = 0
        self.btn_last = False
        self.btn_press_t0 = 0
        self.long_press_ms = BUTTON_LONG_PRESS_MS
        self.extra_long_press_ms = self.BUTTON_EXTRA_LONG_MS

        # Dashboard V2: focused field + unified edit mode
        self.dashboard_focus = 0
        self.dashboard_accum = 0
        self.edit_field = None
        self.edit_original = None
        self.limit_field_index = 0
        self.limit_original = None
        self.step_field_index = 0
        self.step_original = None

        # Profile selector state
        self._profiles_list = []
        self._profile_index = 0
        self._profile_action = None  # 'load' or 'delete'

        # Animation
        self.spinner_frame = 0
        self.last_spinner_update = time.ticks_ms()
        self._last_display_refresh = time.ticks_ms()

        # ── Generation / PULSE state ──────────────────────────────────────────
        self.gen_active = False
        self.pulse_state = False  # True = carrier currently gated ON
        self._pulse_on_us = 0  # ON  duration in µs
        self._pulse_off_us = 0  # OFF duration in µs
        self._pulse_phase_start_us = 0  # ticks_us() timestamp of phase start
        # Track parameter changes to apply them in real-time
        self._cached_pulse_freq = PULSE_FREQ
        self._cached_pulse_duty = PULSE_DUTY
        self._pulse_thread_started = False
        self._pulse_thread_enabled = False

        # ── Timer state ───────────────────────────────────────────────────────
        self.timer_active = False
        self.timer_end_ms = None

        # ── Timing bookmarks ──────────────────────────────────────────────────
        self.last_update = time.ticks_ms()
        self.last_button_check = time.ticks_ms()
        self._last_encoder_check = time.ticks_ms()
        self._last_save = time.ticks_ms()

        # ── PIO StateMachine (SM0) ────────────────────────────────────────────
        self._fifo_word = 0
        self._init_carrier_sm(active=False)  # No cooldown issues: direct call
        self._start_pulse_thread()

        # ── Runtime resilience ────────────────────────────────────────────────
        self._runtime_error_count = 0
        self._runtime_error_limit = 5

        if AUTO_START_ON_BOOT:
            try:
                self.start_generation()
                self.logger.info("Auto-start: generation ON")
            except Exception as e:
                self.logger.error(f"Auto-start failed: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # Settings management
    # ══════════════════════════════════════════════════════════════════════════

    def _sanitize_loaded_state(self, defaults):
        """Clamp and validate every field after loading from storage."""
        changed = False

        if self.mode not in ("SQUARE", "PULSE"):
            self.mode = defaults["mode"]
            changed = True

        for attr, hard_min, hard_max, fallback_key in [
            (
                "ui_square_freq_min",
                SQUARE_FREQ_RANGE[0],
                SQUARE_FREQ_RANGE[1],
                "ui_square_freq_min",
            ),
            (
                "ui_square_freq_max",
                SQUARE_FREQ_RANGE[0],
                SQUARE_FREQ_RANGE[1],
                "ui_square_freq_max",
            ),
            (
                "ui_pulse_freq_min",
                PULSE_FREQ_RANGE[0],
                PULSE_FREQ_RANGE[1],
                "ui_pulse_freq_min",
            ),
            (
                "ui_pulse_freq_max",
                PULSE_FREQ_RANGE[0],
                PULSE_FREQ_RANGE[1],
                "ui_pulse_freq_max",
            ),
        ]:
            try:
                setattr(self, attr, int(getattr(self, attr)))
            except (TypeError, ValueError):
                setattr(self, attr, int(defaults[fallback_key]))
                changed = True
            c = int(
                self._snap_to_step(
                    getattr(self, attr), hard_min, hard_max, FREQ_STEP if "square" in attr else PULSE_STEP
                )
            )
            if c != getattr(self, attr):
                setattr(self, attr, c)
                changed = True
        if self.ui_square_freq_step > self.ui_square_freq_max - self.ui_square_freq_min:
            self.ui_square_freq_step = max(50, self.ui_square_freq_max - self.ui_square_freq_min)
            changed = True
        if self.ui_pulse_freq_step > self.ui_pulse_freq_max - self.ui_pulse_freq_min:
            self.ui_pulse_freq_step = max(1, self.ui_pulse_freq_max - self.ui_pulse_freq_min)
            changed = True

        if self.ui_square_freq_min > self.ui_square_freq_max:
            self.ui_square_freq_min, self.ui_square_freq_max = (
                self.ui_square_freq_max,
                self.ui_square_freq_min,
            )
            changed = True
        if self.ui_pulse_freq_min > self.ui_pulse_freq_max:
            self.ui_pulse_freq_min, self.ui_pulse_freq_max = (
                self.ui_pulse_freq_max,
                self.ui_pulse_freq_min,
            )
            changed = True

        for attr, hard_min, hard_max, default in [
            ("ui_square_freq_step", 50, 10_000, FREQ_STEP),
            ("ui_pulse_freq_step", 1, 5_000, PULSE_STEP),
        ]:
            try:
                setattr(self, attr, int(getattr(self, attr)))
            except (TypeError, ValueError):
                setattr(self, attr, int(default))
                changed = True
            c = int(self._snap_to_step(getattr(self, attr), hard_min, hard_max, default))
            if c != getattr(self, attr):
                setattr(self, attr, c)
                changed = True

        try:
            self.current_freq = int(self.current_freq)
        except (TypeError, ValueError):
            self.current_freq = int(defaults["current_freq"])
            changed = True
        c = int(
            self._snap_to_step(
                self.current_freq,
                self.ui_square_freq_min,
                self.ui_square_freq_max,
                FREQ_STEP,
            )
        )
        if c != self.current_freq:
            self.current_freq = c
            changed = True

        try:
            self.pulse_freq = int(self.pulse_freq)
        except (TypeError, ValueError):
            self.pulse_freq = int(defaults["pulse_freq"])
            changed = True
        c = int(
            self._snap_to_step(
                self.pulse_freq,
                self.ui_pulse_freq_min,
                self.ui_pulse_freq_max,
                PULSE_STEP,
            )
        )
        if c != self.pulse_freq:
            self.pulse_freq = c
            changed = True

        for attr, key in [
            ("square_duty_cycle", "square_duty_cycle"),
            ("duty_cycle", "pulse_duty_cycle"),
        ]:
            try:
                setattr(self, attr, float(getattr(self, attr)))
            except (TypeError, ValueError):
                setattr(self, attr, float(defaults[key]))
                changed = True
            c = float(
                self._snap_to_step(
                    getattr(self, attr), DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP
                )
            )
            if c != getattr(self, attr):
                setattr(self, attr, c)
                changed = True

        if getattr(self, "duty_target", None) not in ("SQUARE", "PULSE"):
            self.duty_target = "SQUARE"
            changed = True

        try:
            self.timer_minutes = float(self.timer_minutes)
        except (TypeError, ValueError):
            self.timer_minutes = 0.0
            changed = True
        if not (0 <= self.timer_minutes <= TIMER_MAX_MINUTES):
            self.timer_minutes = 0.0
            changed = True

        if changed:
            self.logger.warning("Settings corrected after validation")
            self.settings.save_state(self)

    def _deferred_load(self):
        """Load saved settings lazily after the first dashboard render."""
        if not self._deferred_load_pending:
            return
        self._deferred_load_pending = False
        try:
            self.settings.deferred_load()
            if self.settings.has_saved_state():
                self.logger.info("Restoring saved settings (deferred)")
                defaults = {
                    "mode": MODE,
                    "current_freq": FREQ_DEFAULT,
                    "pulse_freq": PULSE_FREQ,
                    "ui_square_freq_min": SQUARE_FREQ_RANGE[0],
                    "ui_square_freq_max": SQUARE_FREQ_RANGE[1],
                    "ui_pulse_freq_min": PULSE_FREQ_RANGE[0],
                    "ui_pulse_freq_max": PULSE_FREQ_RANGE[1],
                    "ui_square_freq_step": FREQ_STEP,
                    "ui_pulse_freq_step": PULSE_STEP,
                    "square_duty_cycle": SQUARE_DUTY,
                    "pulse_duty_cycle": PULSE_DUTY,
                }
                self.settings.load_state(self, defaults)
                self._sanitize_loaded_state(defaults)
                # Apply restored frequency to SM (generation is OFF at this point)
                self._rebuild_carrier_sm()
        except Exception as e:
            self.logger.error(f"Deferred load error: {e}")

    def _handle_runtime_exception(self, err):
        """Centralised main-loop error handler with safety stop."""
        self._runtime_error_count += 1
        self.logger.critical(f"Main-loop exception: {err}")
        try:
            self.stop_generation()
        except Exception as e:
            self.logger.error(f"Safety stop failed: {e}")
        self.ui_state = UI_STATE_DASHBOARD
        self.menu_index = 0
        self.menu_accum = 0
        if self._runtime_error_count >= self._runtime_error_limit:
            self.logger.critical("Too many consecutive errors — pause 500 ms")
            time.sleep_ms(500)
            self._runtime_error_count = 0
        else:
            time.sleep_ms(50)
        gc.collect()

    def _snap_to_step(self, value, minimum, maximum, step):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float(minimum)

        minimum = float(minimum)
        maximum = float(maximum)
        step = float(step)

        if step > 0:
            numeric = minimum + int(((numeric - minimum) / step) + 0.5) * step

        if numeric < minimum:
            numeric = minimum
        elif numeric > maximum:
            numeric = maximum
        return numeric

    def _normalize_runtime_values(self):
        self.current_freq = int(
            self._snap_to_step(
                self.current_freq,
                self.ui_square_freq_min,
                self.ui_square_freq_max,
                self.ui_square_freq_step,
            )
        )
        self.pulse_freq = int(
            self._snap_to_step(
                self.pulse_freq,
                self.ui_pulse_freq_min,
                self.ui_pulse_freq_max,
                self.ui_pulse_freq_step,
            )
        )
        self.square_duty_cycle = float(
            self._snap_to_step(
                self.square_duty_cycle,
                DUTY_CYCLE_MIN,
                DUTY_CYCLE_MAX,
                DUTY_CYCLE_STEP,
            )
        )
        self.duty_cycle = float(
            self._snap_to_step(
                self.duty_cycle, DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP
            )
        )
        if self.timer_minutes:
            try:
                self.timer_minutes = float(
                    max(TIMER_MIN_MINUTES, min(TIMER_MAX_MINUTES, int(self.timer_minutes)))
                )
            except (TypeError, ValueError):
                self.timer_minutes = 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # Hardware helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _init_output_pins(self):
        """Drive both push-pull pins LOW before the PIO SM takes over."""
        try:
            Pin(PIN_SQUARE, Pin.OUT).value(0)
            Pin(PIN_SQUARE + 1, Pin.OUT).value(0)
            self.logger.info(f"Outputs LOW: GPIO{PIN_SQUARE} / GPIO{PIN_SQUARE + 1}")
        except (ValueError, RuntimeError) as e:
            self.logger.error(f"Output pin init error: {e}")

    def _scan_i2c(self):
        try:
            devices = self.i2c.scan()
            pretty = ", ".join(f"0x{a:02X}" for a in devices) if devices else "none"
            self.logger.info(f"I2C scan: {pretty}")
            return devices
        except OSError as e:
            self.logger.error(f"I2C scan failed: {e}")
            return []

    def _check_hardware(self):
        devices = self._scan_i2c()
        self.encoder_available = self.encoder_addr in devices
        self.lcd_available = self.lcd_addr in devices
        ok = True
        if self.encoder_available:
            self.logger.info(f"Encoder OK  (0x{self.encoder_addr:02X})")
        else:
            self.logger.error(f"Encoder missing (0x{self.encoder_addr:02X})")
            ok = False
        if self.lcd_available:
            self.logger.info(f"LCD OK  (0x{self.lcd_addr:02X})")
        else:
            self.logger.error(f"LCD missing (0x{self.lcd_addr:02X})")
            ok = False
        return ok

    def _activate_sm_square(self, state):
        """Enable or disable the push-pull SM."""
        try:
            self.sm_square.active(1 if state else 0)
        except Exception as e:
            self.logger.error(f"SM active({state}) error: {e}")

    def _set_pulse_indicator(self, state):
        """Drive GPIO2 indicator HIGH/LOW with best-effort safety."""
        # Indicator removed — no-op
        return

    def _start_pulse_thread(self):
        """Start the dedicated pulse gate worker on the second core."""
        if self._pulse_thread_started:
            return
        try:
            _thread.start_new_thread(self._pulse_gate_worker, ())
            self._pulse_thread_started = True
            self._pulse_thread_enabled = True
            self.logger.info("Pulse gate worker started")
        except Exception as e:
            self._pulse_thread_started = False
            self._pulse_thread_enabled = False
            self.logger.warning(f"Pulse gate worker unavailable: {e}")

    def _pulse_gate_worker(self):
        """Dedicated worker for PULSE gating, isolated from the UI loop."""
        guard_us = 50
        while True:
            try:
                if not self._pulse_thread_enabled:
                    time.sleep_ms(10)
                    continue

                if not self.gen_active or self.mode != "PULSE":
                    if self.pulse_state:
                        gate_pulse_outputs(PIN_SQUARE, False)
                        self._set_pulse_indicator(False)
                        self.pulse_state = False
                    time.sleep_ms(1)
                    continue

                now_us = time.ticks_us()
                elapsed = time.ticks_diff(now_us, self._pulse_phase_start_us)

                if self.pulse_state:
                    remaining = self._pulse_on_us - elapsed
                    if remaining <= 0:
                        gate_pulse_outputs(PIN_SQUARE, False)
                        self._set_pulse_indicator(False)
                        self.pulse_state = False
                        self._pulse_phase_start_us = now_us
                        continue
                else:
                    remaining = self._pulse_off_us - elapsed
                    if remaining <= 0:
                        gate_pulse_outputs(PIN_SQUARE, True)
                        self._set_pulse_indicator(True)
                        self.pulse_state = True
                        self._pulse_phase_start_us = now_us
                        continue

                if remaining > guard_us:
                    time.sleep_us(remaining - guard_us)
            except Exception:
                time.sleep_ms(5)

    # ══════════════════════════════════════════════════════════════════════════
    # PIO / StateMachine management
    # ══════════════════════════════════════════════════════════════════════════

    def _init_carrier_sm(self, active=False):
        """
        (Re)initialise SM0 with the static push_pull_pio program.

        Pushes exactly one timing word to the FIFO so the pull(noblock)
        X-fallback is correctly bootstrapped when the SM first activates.
        """
        try:
            self.sm_square.active(0)
        except Exception:
            pass
        try:
            self.sm_square.deinit()
        except (AttributeError, RuntimeError):
            pass

        self.sm_square = StateMachine(0)
        self.sm_square.init(
            push_pull_pio,
            freq=PUSH_PULL_SM_FREQ,
            set_base=Pin(PIN_SQUARE),
        )

        word = calc_push_pull_word(self.current_freq, self.square_duty_cycle)
        self._fifo_word = -1
        try:
            self.sm_square.put(word)
            self._fifo_word = word
        except Exception:
            pass

        self.sm_square.active(1 if active else 0)
        self.logger.debug(
            f"SM0 init: {self.current_freq} Hz  duty={self.square_duty_cycle:.2f}"
            f"  word=0x{word:08X}  active={active}"
        )

    def _rebuild_carrier_sm(self):
        """Push the current timing word to SM0 when needed."""
        try:
            self._normalize_runtime_values()
            word = calc_push_pull_word(self.current_freq, self.square_duty_cycle)
            if word == self._fifo_word:
                return
            self._fifo_word = word
            if not self.gen_active:
                return
            self.sm_square.put(word)
        except Exception as e:
            self.logger.warning(f"FIFO push failed: {e} — reinitialising SM")
            try:
                self._init_carrier_sm(active=True)
            except Exception:
                pass

    def _start_pulse_gating(self):
        """
        Initialise PULSE mode gating.

        The push-pull carrier SM runs continuously. A dedicated worker thread
        handles the ON/OFF envelope so the UI loop and I2C activity do not add
        jitter to the pulse train.
        """
        self._normalize_runtime_values()
        period_us = max(2, int(round(1_000_000.0 / self.pulse_freq)))
        on_us = max(1, int(period_us * float(self.duty_cycle)))
        off_us = max(1, period_us - on_us)

        self._pulse_on_us = on_us
        self._pulse_off_us = off_us
        self.pulse_state = True

        word = calc_push_pull_word(self.current_freq, self.square_duty_cycle)
        self._fifo_word = word
        try:
            self.sm_square.put(word)
        except Exception:
            pass
        self.sm_square.active(1)
        gate_pulse_outputs(PIN_SQUARE, True)
        try:
            self._pulse_indicator.value(1)
        except Exception:
            pass
        self._pulse_phase_start_us = time.ticks_us()

        self.logger.info(
            f"PULSE gating: carrier={self.current_freq} Hz  "
            f"pulse={self.pulse_freq} Hz  duty={int(self.duty_cycle * 100)}%  "
            f"on={on_us} us  off={off_us} us"
        )

    def _stop_pulse_gating(self):
        """Stop PULSE mode: deactivate SM and force outputs LOW."""
        self.sm_square.active(0)
        gate_pulse_outputs(PIN_SQUARE, False)
        self._set_pulse_indicator(False)
        self.pulse_state = False

    def _recalc_pulse_timing(self, restart=True):
        """Recompute ON/OFF µs values after pulse_freq or duty_cycle changes."""
        self._normalize_runtime_values()
        period_us = max(2, int(round(1_000_000.0 / self.pulse_freq)))
        on_us = max(1, int(period_us * float(self.duty_cycle)))
        off_us = max(1, period_us - on_us)
        self._pulse_on_us = on_us
        self._pulse_off_us = off_us
        # Reset phase clock so the new timing takes effect immediately.
        self._pulse_phase_start_us = time.ticks_us()

    def _check_pulse_param_changes(self):
        """Detect changes in pulse_freq or duty_cycle and recalculate timing."""
        if self.mode != "PULSE" or not self.gen_active:
            return
        
        changed = False
        if self.pulse_freq != self._cached_pulse_freq:
            self._cached_pulse_freq = self.pulse_freq
            changed = True
        if self.duty_cycle != self._cached_pulse_duty:
            self._cached_pulse_duty = self.duty_cycle
            changed = True
        
        if changed:
            self._recalc_pulse_timing()

    def _update_pulse_gate(self):
        """Legacy fallback used only if the dedicated worker cannot start."""
        now_us = time.ticks_us()
        elapsed = time.ticks_diff(now_us, self._pulse_phase_start_us)

        if self.pulse_state:
            if elapsed >= self._pulse_on_us:
                gate_pulse_outputs(PIN_SQUARE, False)
                self._set_pulse_indicator(False)
                self.pulse_state = False
                self._pulse_phase_start_us = now_us
        else:
            if elapsed >= self._pulse_off_us:
                gate_pulse_outputs(PIN_SQUARE, True)
                self._set_pulse_indicator(True)
                self.pulse_state = True
                self._pulse_phase_start_us = now_us

    # ══════════════════════════════════════════════════════════════════════════
    # Mode configuration
    # ══════════════════════════════════════════════════════════════════════════

    def _configure_mode(self, force=False):
        """
        Switch between SQUARE and PULSE modes.
        Protected by a 500 ms cooldown to prevent rapid UI toggling.
        Called with force=True from the dashboard to bypass the cooldown.
        """
        now = time.ticks_ms()
        if self._mode_switching:
            self.logger.warning("Mode change in progress, skipped")
            return
        if (
            not force
            and time.ticks_diff(now, self._last_mode_change)
            < self._mode_change_cooldown_ms
        ):
            self.logger.warning("Mode change cooldown active, skipped")
            return

        self._mode_switching = True
        self._last_mode_change = now
        try:
            if self.gen_active:
                self.stop_generation()
                self.start_generation()
            else:
                self._rebuild_carrier_sm()
            self.logger.info(f"Mode: {self.mode}")
        except Exception as e:
            self.logger.error(f"Mode configure error: {e}")
        finally:
            self._mode_switching = False

    # ══════════════════════════════════════════════════════════════════════════
    # Encoder / navigation
    # ══════════════════════════════════════════════════════════════════════════

    def _update_frequency_from_encoder(self):
        """Dispatch encoder rotation to the active UI state handler."""
        if not self.encoder_available:
            return

        increment = self.encoder.get_increment()
        increment = max(-ENCODER_MAX_INCREMENT, min(ENCODER_MAX_INCREMENT, increment))
        if increment == 0:
            return

        state = self.ui_state

        # ── Menu navigation ───────────────────────────────────────────────────
        if state == UI_STATE_MENU:
            items = self._menu_items()
            now = time.ticks_ms()
            if time.ticks_diff(now, self.last_menu_move) < MENU_ACCEL_WINDOW_MS:
                self.menu_accel_count += 1
            else:
                self.menu_accel_count = 0
            self.last_menu_move = now
            threshold = max(
                1,
                self.menu_nav_threshold - (self.menu_accel_count // MENU_ACCEL_DIVIDER),
            )
            self.menu_accum += increment
            while self.menu_accum >= threshold:
                if self.menu_index < len(items) - 1:
                    self.menu_index += 1
                self.menu_accum -= threshold
            while self.menu_accum <= -threshold:
                if self.menu_index > 0:
                    self.menu_index -= 1
                self.menu_accum += threshold
            return

        # ── Dashboard focus ───────────────────────────────────────────────────
        if state == UI_STATE_DASHBOARD:
            items = self._dashboard_items()
            if not items:
                return
            self.dashboard_accum += increment
            threshold = max(1, self.menu_nav_threshold)
            while self.dashboard_accum >= threshold:
                self.dashboard_focus = min(self.dashboard_focus + 1, len(items) - 1)
                self.dashboard_accum -= threshold
            while self.dashboard_accum <= -threshold:
                self.dashboard_focus = max(self.dashboard_focus - 1, 0)
                self.dashboard_accum += threshold
            return

        # ── Edit mode ─────────────────────────────────────────────────────────
        if state == self.UI_STATE_EDIT:
            self._apply_edit_increment(increment)
            return

        if state == self.UI_STATE_FREQ_LIMITS:
            self._apply_limit_increment(increment)
            return

        if state == self.UI_STATE_UI_STEPS:
            self._apply_step_increment(increment)
            return

        # ── Set-timer screen ──────────────────────────────────────────────────
        if state == UI_STATE_SET_TIMER:
            mins = int(self.timer_minutes) + int(increment)
            self.timer_minutes = float(
                max(TIMER_MIN_MINUTES, min(TIMER_MAX_MINUTES, mins))
            )
            return

        # ── Set-duty screen ───────────────────────────────────────────────────
        if state == UI_STATE_SET_DUTY:
            if self.duty_target == "SQUARE":
                new = self.square_duty_cycle + increment * DUTY_CYCLE_STEP
                self.square_duty_cycle = float(
                    self._snap_to_step(new, DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP)
                )
                self._rebuild_carrier_sm()
            else:
                new = self.duty_cycle + increment * DUTY_CYCLE_STEP
                self.duty_cycle = float(
                    self._snap_to_step(new, DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP)
                )
                self._recalc_pulse_timing()
            return
        # ── Profile selector (legacy) ───────────────────────────────────────
        if state == self.UI_STATE_PROFILE_SELECT:
            profiles = getattr(self, "_profiles_list", [])
            if not profiles:
                return
            # adjust index
            self._profile_index = max(0, min(len(profiles) - 1, self._profile_index + increment))
            # immediate render for responsiveness
            try:
                self._render_profile_selector()
            except Exception:
                pass
            return

        # ── Profiles slots menu (1..10) ──────────────────────────────────────
        if state == self.UI_STATE_PROFILES:
            # move menu index over 10 slots
            self.menu_index = max(0, min(9, self.menu_index + increment))
            try:
                self._render_profiles()
            except Exception:
                pass
            return

    # ── Dashboard items ───────────────────────────────────────────────────────

    def _dashboard_items(self):
        """Ordered list of dashboard fields (stable order for muscle memory)."""
        return [
            ("power", "Power", "ON" if self.gen_active else "OFF", False),
            ("mode", "Mode", self.mode, False),
            ("square_hz", "Square Hz", f"{int(self.current_freq)}", True),
            ("pulse_hz", "Pulse Hz", f"{int(self.pulse_freq)}", True),
            ("square_duty", "Sq.Duty", f"{int(self.square_duty_cycle * 100)}%", True),
            ("pulse_duty", "Pu.Duty", f"{int(self.duty_cycle * 100)}%", True),
            (
                "timer",
                "Timer",
                f"{int(self.timer_minutes)}m" if self.timer_minutes else "Off",
                True,
            ),
        ]

    def _enter_edit_for_focus(self):
        """Enter edit mode for the currently focused dashboard item."""
        items = self._dashboard_items()
        if not items:
            return
        key, _label, _value, editable = items[self.dashboard_focus]

        if key == "power":
            if self.gen_active:
                self.stop_generation()
            else:
                self.start_generation()
            return

        if key == "mode":
            self.mode = "PULSE" if self.mode == "SQUARE" else "SQUARE"
            self.logger.info(f"Mode toggled → {self.mode}")
            self._configure_mode(force=True)
            self.settings.save_state(self)
            return

        if not editable:
            return

        self.edit_field = key
        if key == "square_hz":
            self.edit_original = int(self.current_freq)
        elif key == "pulse_hz":
            self.edit_original = int(self.pulse_freq)
        elif key == "square_duty":
            self.edit_original = float(self.square_duty_cycle)
        elif key == "pulse_duty":
            self.edit_original = float(self.duty_cycle)
        elif key == "timer":
            self.edit_original = float(self.timer_minutes)
        else:
            self.edit_original = None

        self.ui_state = self.UI_STATE_EDIT
        self.lcd.clear()

    def _apply_edit_increment(self, increment):
        """Apply encoder rotation to the value currently being edited."""
        if not self.edit_field or increment == 0:
            return

        if self.edit_field == "square_hz":
            new = self.current_freq + increment * self.ui_square_freq_step
            self.current_freq = int(
                self._snap_to_step(
                    new,
                    self.ui_square_freq_min,
                    self.ui_square_freq_max,
                    self.ui_square_freq_step,
                )
            )
            self._rebuild_carrier_sm()

        elif self.edit_field == "pulse_hz":
            new = self.pulse_freq + increment * self.ui_pulse_freq_step
            self.pulse_freq = int(
                self._snap_to_step(
                    new,
                    self.ui_pulse_freq_min,
                    self.ui_pulse_freq_max,
                    self.ui_pulse_freq_step,
                )
            )
            self._recalc_pulse_timing()

        elif self.edit_field == "square_duty":
            new = self.square_duty_cycle + increment * DUTY_CYCLE_STEP
            self.square_duty_cycle = float(
                self._snap_to_step(new, DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP)
            )
            self._rebuild_carrier_sm()

        elif self.edit_field == "pulse_duty":
            new = self.duty_cycle + increment * DUTY_CYCLE_STEP
            self.duty_cycle = float(
                self._snap_to_step(new, DUTY_CYCLE_MIN, DUTY_CYCLE_MAX, DUTY_CYCLE_STEP)
            )
            self._recalc_pulse_timing()

        elif self.edit_field == "timer":
            mins = int(self.timer_minutes) + int(increment)
            self.timer_minutes = float(
                max(TIMER_MIN_MINUTES, min(TIMER_MAX_MINUTES, mins))
            )

    def _commit_edit(self):
        """Commit the current edit and persist settings."""
        if self.edit_field == "timer":
            try:
                self.start_timer(self.timer_minutes)
            except (ValueError, TypeError) as e:
                self.logger.error(f"Timer start from edit: {e}")
        self.edit_field = None
        self.edit_original = None
        self.ui_state = UI_STATE_DASHBOARD
        self.settings.save_state(self)
        self.lcd.clear()

    def _cancel_edit(self):
        """Cancel the current edit and restore the original value."""
        if self.edit_original is not None:
            if self.edit_field == "square_hz":
                self.current_freq = int(self.edit_original)
                self._rebuild_carrier_sm()
            elif self.edit_field == "pulse_hz":
                self.pulse_freq = int(self.edit_original)
                self._recalc_pulse_timing()
            elif self.edit_field == "square_duty":
                self.square_duty_cycle = float(self.edit_original)
                self._rebuild_carrier_sm()
            elif self.edit_field == "pulse_duty":
                self.duty_cycle = float(self.edit_original)
                self._recalc_pulse_timing()
            elif self.edit_field == "timer":
                self.timer_minutes = float(self.edit_original)
        self.edit_field = None
        self.edit_original = None
        self.ui_state = UI_STATE_DASHBOARD
        self.lcd.clear()

    def _limit_editor_items(self):
        return [
            (
                "square_min",
                "Sq Min",
                self.ui_square_freq_min,
                self.ui_square_freq_step,
                SQUARE_FREQ_RANGE,
            ),
            (
                "square_max",
                "Sq Max",
                self.ui_square_freq_max,
                self.ui_square_freq_step,
                SQUARE_FREQ_RANGE,
            ),
            (
                "pulse_min",
                "Pulse Min",
                self.ui_pulse_freq_min,
                self.ui_pulse_freq_step,
                PULSE_FREQ_RANGE,
            ),
            (
                "pulse_max",
                "Pulse Max",
                self.ui_pulse_freq_max,
                self.ui_pulse_freq_step,
                PULSE_FREQ_RANGE,
            ),
        ]

    def _step_editor_items(self):
        return [
            (
                "square_step",
                "Sq Step",
                self.ui_square_freq_step,
                50,
                10_000,
                50,
            ),
            (
                "pulse_step",
                "Pulse Step",
                self.ui_pulse_freq_step,
                1,
                5_000,
                1,
            ),
        ]

    def _enter_limit_editor(self):
        self.limit_field_index = 0
        self.limit_original = (
            int(self.ui_square_freq_min),
            int(self.ui_square_freq_max),
            int(self.ui_pulse_freq_min),
            int(self.ui_pulse_freq_max),
        )
        self.ui_state = self.UI_STATE_FREQ_LIMITS
        self.lcd.clear()

    def _enter_step_editor(self):
        self.step_field_index = 0
        self.step_original = (
            int(self.ui_square_freq_step),
            int(self.ui_pulse_freq_step),
        )
        self.ui_state = self.UI_STATE_UI_STEPS
        self.lcd.clear()

    def _apply_limit_increment(self, increment):
        if increment == 0:
            return
        items = self._limit_editor_items()
        if not items:
            return
        key, _label, current, step, hard_range = items[self.limit_field_index]
        new_value = self._snap_to_step(
            current + increment * step, hard_range[0], hard_range[1], step
        )
        if key == "square_min":
            self.ui_square_freq_min = int(min(new_value, self.ui_square_freq_max))
        elif key == "square_max":
            self.ui_square_freq_max = int(max(new_value, self.ui_square_freq_min))
        elif key == "pulse_min":
            self.ui_pulse_freq_min = int(min(new_value, self.ui_pulse_freq_max))
        elif key == "pulse_max":
            self.ui_pulse_freq_max = int(max(new_value, self.ui_pulse_freq_min))
        self._normalize_runtime_values()

    def _apply_step_increment(self, increment):
        if increment == 0:
            return
        items = self._step_editor_items()
        if not items:
            return
        key, _label, current, step, hard_max, hard_min = items[self.step_field_index]
        new_value = self._snap_to_step(
            current + increment * step, hard_min, hard_max, step
        )
        if key == "square_step":
            self.ui_square_freq_step = int(new_value)
        elif key == "pulse_step":
            self.ui_pulse_freq_step = int(new_value)
        self._normalize_runtime_values()

    def _commit_limit_editor(self):
        self._normalize_runtime_values()
        self.limit_original = None
        self.ui_state = UI_STATE_MENU
        self.settings.save_state(self)
        self.lcd.clear()

    def _commit_step_editor(self):
        self._normalize_runtime_values()
        self.step_original = None
        self.ui_state = UI_STATE_MENU
        self.settings.save_state(self)
        self.lcd.clear()

    def _cancel_limit_editor(self):
        if self.limit_original is not None:
            self.ui_square_freq_min, self.ui_square_freq_max, self.ui_pulse_freq_min, self.ui_pulse_freq_max = self.limit_original
        self.limit_original = None
        self._normalize_runtime_values()
        self.ui_state = UI_STATE_MENU
        self.lcd.clear()

    def _cancel_step_editor(self):
        if self.step_original is not None:
            self.ui_square_freq_step, self.ui_pulse_freq_step = self.step_original
        self.step_original = None
        self._normalize_runtime_values()
        self.ui_state = UI_STATE_MENU
        self.lcd.clear()

    # ══════════════════════════════════════════════════════════════════════════
    # Button handling
    # ══════════════════════════════════════════════════════════════════════════

    def _handle_button(self, now_ms):
        """Detect short / long / extra-long presses."""
        if not self.encoder_available:
            return
        pressed = self.encoder.is_button_pressed()
        if pressed and not self.btn_last:
            self.btn_press_t0 = now_ms
        elif not pressed and self.btn_last:
            duration = time.ticks_diff(now_ms, self.btn_press_t0)
            if duration >= self.extra_long_press_ms:
                self._on_extra_long_press()
            elif duration >= self.long_press_ms:
                self._on_long_press()
            else:
                self._on_short_press()
        self.btn_last = pressed

    def _on_short_press(self):
        if self.ui_state == UI_STATE_DASHBOARD:
            self._enter_edit_for_focus()
        elif self.ui_state == self.UI_STATE_FREQ_LIMITS:
            self.limit_field_index += 1
            if self.limit_field_index >= len(self._limit_editor_items()):
                self._commit_limit_editor()
            else:
                self.lcd.clear()
        elif self.ui_state == self.UI_STATE_UI_STEPS:
            self.step_field_index += 1
            if self.step_field_index >= len(self._step_editor_items()):
                self._commit_step_editor()
            else:
                self.lcd.clear()
        elif self.ui_state == self.UI_STATE_PROFILE_SELECT:
            # Confirm selection
            if self._profiles_list:
                prof = self._profiles_list[self._profile_index]
                if self._profile_action == "load":
                    ok = self.settings.load_profile(self, prof)
                    if ok:
                        try:
                            self._normalize_runtime_values()
                            self._rebuild_carrier_sm()
                            if self.mode == "PULSE" and self.gen_active:
                                self._recalc_pulse_timing()
                        except Exception:
                            pass
                        self.lcd.write_line(4, f"Loaded: {prof}")
                    else:
                        self.lcd.write_line(4, "Load failed")
                elif self._profile_action == "delete":
                    if self.settings.storage.delete_profile(prof):
                        self.lcd.write_line(4, f"Deleted: {prof}")
                        # refresh list
                        self._profiles_list = self.settings.list_profiles()
                        self._profile_index = max(0, len(self._profiles_list) - 1)
                    else:
                        self.lcd.write_line(4, "Delete failed")
            # Return to menu after action
            self.ui_state = UI_STATE_MENU
            self.lcd.clear()
            return
        elif self.ui_state == self.UI_STATE_PROFILES:
            # Profiles slots menu: short press -> load if present, save if empty
            slot = self.menu_index + 1
            slot_data = self.settings.slot_info(slot)
            if slot_data:
                # load
                if self.settings.load_slot(self, slot):
                    try:
                        self._normalize_runtime_values()
                        self._rebuild_carrier_sm()
                        if self.mode == "PULSE" and self.gen_active:
                            self._recalc_pulse_timing()
                    except Exception:
                        pass
                    self.lcd.write_line(4, f"Loaded slot {slot}")
                else:
                    self.lcd.write_line(4, "Load failed")
            else:
                # save current into slot
                if self.settings.save_slot(self, slot):
                    self.lcd.write_line(4, f"Saved slot {slot}")
                else:
                    self.lcd.write_line(4, "Save failed")
            return
        elif self.ui_state == self.UI_STATE_EDIT:
            self._commit_edit()
        elif self.ui_state == UI_STATE_SET_TIMER:
            try:
                self.start_timer(self.timer_minutes)
            except (ValueError, TypeError) as e:
                self.logger.error(f"Timer start: {e}")
            self.ui_state = UI_STATE_DASHBOARD
            self.lcd.clear()
        elif self.ui_state == UI_STATE_SET_DUTY:
            self.settings.save_state(self)
            self.ui_state = UI_STATE_MENU
            self.lcd.clear()
        elif self.ui_state == self.UI_STATE_INFO:
            self.ui_state = UI_STATE_MENU
            self.lcd.clear()
        else:
            self._menu_select()

    def _on_long_press(self):
        if self.ui_state == UI_STATE_DASHBOARD:
            if self.gen_active:
                self.stop_generation()
            else:
                try:
                    self.start_generation()
                except Exception as e:
                    self.logger.error(f"Long-press start error: {e}")
        elif self.ui_state == self.UI_STATE_PROFILE_SELECT:
            # Cancel profile selection
            self.ui_state = UI_STATE_MENU
            self.lcd.clear()
        elif self.ui_state == self.UI_STATE_PROFILES:
            # Delete slot if present, otherwise go back
            slot = self.menu_index + 1
            slot_data = self.settings.slot_info(slot)
            if slot_data:
                if self.settings.delete_slot(slot):
                    self.lcd.write_line(4, f"Deleted slot {slot}")
                else:
                    self.lcd.write_line(4, "Delete failed")
            else:
                # no-op: go back
                self.ui_state = UI_STATE_MENU
                self.lcd.clear()
            return
        elif self.ui_state == self.UI_STATE_EDIT:
            self._cancel_edit()
        elif self.ui_state == self.UI_STATE_FREQ_LIMITS:
            self._cancel_limit_editor()
        elif self.ui_state == self.UI_STATE_UI_STEPS:
            self._cancel_step_editor()
        else:
            self.ui_state = UI_STATE_DASHBOARD
            self.lcd.clear()

    def _on_extra_long_press(self):
        """Very long press: jump to system menu from any UI state."""
        self.ui_state = UI_STATE_MENU
        self.menu_index = 0
        self.lcd.clear()

    # ══════════════════════════════════════════════════════════════════════════
    # Display
    # ══════════════════════════════════════════════════════════════════════════

    def _update_display(self):
        if self.ui_state == UI_STATE_MENU:
            self._render_menu()
        elif self.ui_state == self.UI_STATE_FREQ_LIMITS:
            self._render_freq_limits()
        elif self.ui_state == self.UI_STATE_UI_STEPS:
            self._render_step_limits()
        elif self.ui_state == self.UI_STATE_EDIT:
            self._render_edit()
        elif self.ui_state == self.UI_STATE_INFO:
            self._render_info()
        elif self.ui_state == UI_STATE_SET_TIMER:
            self._render_set_timer()
        elif self.ui_state == UI_STATE_SET_DUTY:
            self._render_set_duty()
        elif self.ui_state == self.UI_STATE_PROFILES:
            self._render_profiles()
        else:
            self._render_dashboard()

    def _timer_status_line(self):
        """Return a countdown string if a timer is active, else None."""
        if self.timer_active and self.timer_end_ms is not None:
            ms = max(0, time.ticks_diff(self.timer_end_ms, time.ticks_ms()))
            secs = ms // 1000
            return f"Timer {secs // 60}m {secs % 60:02d}s"
        return None

    def _render_dashboard(self):
        title = "HV GENERATOR"

        # Line 1: title + spinner (ON) or "OFF" indicator
        if self.gen_active:
            sp = self.spinner_chars[self.spinner_frame]
            pad = 20 - len(title) - 1
            l1 = (title + " " * pad + sp) if pad > 0 else (title[:19] + sp)
        else:
            gs = "OFF"
            pad = 20 - len(title) - len(gs)
            l1 = (title + " " * pad + gs) if pad > 0 else (title[:16] + gs)
        self.lcd.write_line(1, l1)

        # Line 2: status + actual/target frequency
        if self.gen_active:
            if self.mode == "PULSE":
                l2 = f"RUN PULSE {self.pulse_freq}Hz {int(self.duty_cycle * 100)}%"
            else:
                af = actual_freq_from_word(self._fifo_word)
                l2 = f"RUN SQ {af:.0f}Hz {int(self.square_duty_cycle * 100)}%"
        else:
            l2 = f"IDLE | Mode: {self.mode}"
        self.lcd.write_line(2, l2)

        # Line 3: focused dashboard field
        items = self._dashboard_items()
        if items:
            self.dashboard_focus = max(0, min(self.dashboard_focus, len(items) - 1))
            _key, label, value, _ed = items[self.dashboard_focus]
            self.lcd.write_line(3, f"> {label}: {value}")
        else:
            self.lcd.write_line(3, "No item")

        # Line 4: timer countdown or context help
        tl = self._timer_status_line()
        # Show timer if active, otherwise display context help.
        if tl:
            self.lcd.write_line(4, tl)
        else:
            long_action = "OFF" if self.gen_active else "ON"
            self.lcd.write_line(4, f"Short=Edit  Long={long_action}")

    def _render_edit(self):
        items = self._dashboard_items()
        if not items:
            self.lcd.write_line(1, "EDIT")
            self.lcd.write_line(2, "No editable item")
            self.lcd.write_line(3, "")
            tl = self._timer_status_line()
            self.lcd.write_line(4, tl if tl else "Long=Back")
            return

        self.dashboard_focus = max(0, min(self.dashboard_focus, len(items) - 1))
        key, label, value, _ = items[self.dashboard_focus]
        self.lcd.write_line(1, f"EDIT  {label}")

        if key == "square_hz":
            self.lcd.write_line(2, f"Value: {int(self.current_freq)} Hz")
            self.lcd.write_line(
                3, f"Range: {self.ui_square_freq_min}-{self.ui_square_freq_max}"
            )
        elif key == "pulse_hz":
            self.lcd.write_line(2, f"Value: {int(self.pulse_freq)} Hz")
            self.lcd.write_line(
                3, f"Range: {self.ui_pulse_freq_min}-{self.ui_pulse_freq_max}"
            )
        elif key == "square_duty":
            self.lcd.write_line(2, f"Value: {int(self.square_duty_cycle * 100)} %")
            self.lcd.write_line(
                3, f"Range: {int(DUTY_CYCLE_MIN * 100)}-{int(DUTY_CYCLE_MAX * 100)} %"
            )
        elif key == "pulse_duty":
            self.lcd.write_line(2, f"Value: {int(self.duty_cycle * 100)} %")
            self.lcd.write_line(
                3, f"Range: {int(DUTY_CYCLE_MIN * 100)}-{int(DUTY_CYCLE_MAX * 100)} %"
            )
        elif key == "timer":
            self.lcd.write_line(2, f"Value: {int(self.timer_minutes)} min")
            self.lcd.write_line(
                3, f"Range: {TIMER_MIN_MINUTES}-{TIMER_MAX_MINUTES} min"
            )
        else:
            self.lcd.write_line(2, f"Value: {value}")
            self.lcd.write_line(3, "")

        tl = self._timer_status_line()
        self.lcd.write_line(4, tl if tl else "Short=OK  Long=Cancel")

    def _render_set_timer(self):
        self.lcd.write_line(1, "SET TIMER")
        self.lcd.write_line(2, "Adjust with encoder:")
        self.lcd.write_line(3, f"Duration: {int(self.timer_minutes or 1)} min")
        tl = self._timer_status_line()
        self.lcd.write_line(4, tl if tl else "Short=Start")

    def _render_set_duty(self):
        title = "SQUARE DUTY" if self.duty_target == "SQUARE" else "PULSE DUTY"
        self.lcd.write_line(1, title)
        self.lcd.write_line(2, "Adjust with encoder:")
        duty = (
            self.square_duty_cycle if self.duty_target == "SQUARE" else self.duty_cycle
        )
        self.lcd.write_line(3, f"Duty: {int(duty * 100)} %")
        tl = self._timer_status_line()
        self.lcd.write_line(4, tl if tl else "Short=Validate")

    # ══════════════════════════════════════════════════════════════════════════
    # Generation control
    # ══════════════════════════════════════════════════════════════════════════

    def start_timer(self, minutes):
        """Start generation and schedule an automatic stop after N minutes."""
        try:
            m = float(minutes)
        except (ValueError, TypeError):
            self.logger.error(f"Invalid timer value: {minutes}")
            return
        if m <= 0:
            return
        self.timer_minutes = m
        self.start_generation()
        self.timer_active = True
        self.timer_end_ms = time.ticks_add(time.ticks_ms(), int(m * 60_000))
        self.logger.info(f"Timer set: {m} min")

    def start_generation(self):
        """Start generation in the current mode."""
        if self.gen_active:
            return
        self._normalize_runtime_values()
        self.logger.info(f"Starting generation [{self.mode}]")
        self.gen_active = True

        if self.mode == "PULSE":
            try:
                self._start_pulse_gating()
            except Exception as e:
                self.logger.error(f"PULSE start error: {e}")
                self.gen_active = False
        else:  # SQUARE
            try:
                word = calc_push_pull_word(self.current_freq, self.square_duty_cycle)
                self._fifo_word = word
                self.sm_square.put(word)
                gate_pulse_outputs(PIN_SQUARE, True)  # clear OUTOVER
                self._activate_sm_square(True)
            except Exception as e:
                self.logger.error(f"SQUARE start error: {e}")
                self.gen_active = False

    def stop_generation(self):
        """Stop generation and force outputs to a safe LOW state."""
        self.logger.info("Stopping generation")

        if self.mode == "PULSE":
            try:
                self._stop_pulse_gating()
            except Exception as e:
                self.logger.warning(f"PULSE stop error: {e}")
        else:
            try:
                self._activate_sm_square(False)
            except Exception as e:
                self.logger.warning(f"SM stop error: {e}")

        # Always force outputs LOW via OUTOVER for belt-and-suspenders safety
        try:
            gate_pulse_outputs(PIN_SQUARE, False)
        except Exception:
            pass

        self.gen_active = False
        self.timer_active = False
        self.timer_end_ms = None
        self._fifo_word = -1
        # Note: do NOT write to LCD here — _update_display() handles rendering

    # ══════════════════════════════════════════════════════════════════════════
    # Menu
    # ══════════════════════════════════════════════════════════════════════════

    def _menu_items(self):
        return [
            ("Stop Timer", "ON" if self.timer_active else "OFF"),
            ("Save", "Now"),
            ("Profiles", ""),
            ("Freq Limits", ""),
            ("UI Steps", ""),
            ("About", "Info"),
            ("Back", ""),
        ]

    def _render_menu(self):
        self.lcd.write_line(1, "SYSTEM MENU")
        items = self._menu_items()
        for i in range(3):
            idx = self.menu_index + i
            row = 2 + i
            if 0 <= idx < len(items):
                name, val = items[idx]
                prefix = ">" if idx == self.menu_index else " "
                self.lcd.write_line(row, f"{prefix} {name}: {val}")
            else:
                self.lcd.write_line(row, "")

    def _render_freq_limits(self):
        items = self._limit_editor_items()
        if not items:
            self.lcd.write_line(1, "FREQ LIMITS")
            self.lcd.write_line(2, "No limits")
            self.lcd.write_line(3, "")
            self.lcd.write_line(4, "Long=Cancel")
            return

        self.limit_field_index = max(0, min(self.limit_field_index, len(items) - 1))
        _key, label, value, _step, hard_range = items[self.limit_field_index]
        self.lcd.write_line(1, "FREQ LIMITS")
        self.lcd.write_line(2, f"{label}: {int(value)} Hz")
        self.lcd.write_line(3, f"{hard_range[0]}-{hard_range[1]} Hz")
        self.lcd.write_line(4, "Short=Next  Long=Cancel")
    def _render_step_limits(self):
        items = self._step_editor_items()
        if not items:
            self.lcd.write_line(1, "UI STEPS")
            self.lcd.write_line(2, "No steps")
            self.lcd.write_line(3, "")
            self.lcd.write_line(4, "Long=Cancel")
            return

        self.step_field_index = max(0, min(self.step_field_index, len(items) - 1))
        _key, label, value, _step, hard_max, hard_min = items[self.step_field_index]
        self.lcd.write_line(1, "UI STEPS")
        self.lcd.write_line(2, f"{label}: {int(value)} Hz")
        self.lcd.write_line(3, f"{hard_min}-{hard_max} Hz")
        self.lcd.write_line(4, "Short=Next  Long=Cancel")

    def _enter_profile_selector(self, action):
        """Enter interactive profile selector. action = 'load' or 'delete'."""
        self._profiles_list = self.settings.list_profiles()
        if not self._profiles_list:
            self.lcd.write_line(4, "No profiles")
            return
        self._profile_action = action
        self._profile_index = max(0, len(self._profiles_list) - 1)
        self.ui_state = self.UI_STATE_PROFILE_SELECT
        self._render_profile_selector()

    def _render_profile_selector(self):
        """Render the profile selection screen."""
        if not getattr(self, "_profiles_list", None):
            self.lcd.write_line(1, "PROFILES")
            self.lcd.write_line(2, "No profiles")
            self.lcd.write_line(3, "")
            self.lcd.write_line(4, "Short=Back")
            return
        name = self._profiles_list[self._profile_index]
        self.lcd.write_line(1, "SELECT PROFILE")
        # show selected name (truncated if needed)
        display_name = name if len(name) <= 20 else name[:20]
        self.lcd.write_line(2, display_name)
        idx_line = f"{self._profile_index+1}/{len(self._profiles_list)}"
        self.lcd.write_line(3, idx_line)
        hint = "Short=OK  Long=Back"
        self.lcd.write_line(4, hint)

    def _render_profiles(self):
        """Render the Profiles slots menu (10 slots)."""
        slots = self.settings.list_slots(10)
        self.lcd.write_line(1, "PROFILES")
        # show three items centered on menu_index
        for i in range(3):
            idx = (self.menu_index - 1) + i
            row = 2 + i
            if 0 <= idx < 10:
                slot_num = idx + 1
                pdata = slots[idx]
                val = "Empty" if not pdata else f"{int(pdata.get('pulse_freq',0))}Hz"
                prefix = ">" if idx == self.menu_index else " "
                self.lcd.write_line(row, f"{prefix} Slot {slot_num}: {val}")
            else:
                self.lcd.write_line(row, "")
        self.lcd.write_line(4, "Short=Load/Save  Long=Delete")

    def _render_info(self):
        self.lcd.write_line(1, f"ABOUT  {SOFTWARE_BUILD_DATE}")
        self.lcd.write_line(2, SOFTWARE_NAME)
        self.lcd.write_line(3, f"{SOFTWARE_VERSION}  {SOFTWARE_AUTHOR}")
        self.lcd.write_line(4, SOFTWARE_LICENSE)

    def _menu_select(self):
        items = self._menu_items()
        if not items:
            return
        name, _ = items[self.menu_index]
        if name == "Stop Timer":
            self.timer_active = False
            self.timer_end_ms = None
        elif name == "Save":
            # Persist current settings as the default and also save an
            # automatic timestamped profile for quick recall.
            ok = self.settings.save_state(self)
            prof_name = self.settings.save_profile(self)
            if prof_name:
                self.lcd.write_line(4, f"Profile saved: {prof_name}")
            elif ok:
                self.lcd.write_line(4, "Settings saved")
            else:
                self.lcd.write_line(4, "Save failed")
        elif name == "Profiles":
            # Enter the profiles slots menu
            self.ui_state = self.UI_STATE_PROFILES
            self.menu_index = 0
            self.lcd.clear()
        elif name == "Freq Limits":
            self._enter_limit_editor()
        elif name == "UI Steps":
            self._enter_step_editor()
        elif name == "About":
            self.ui_state = self.UI_STATE_INFO
            self.lcd.clear()
        elif name == "Back":
            self.ui_state = UI_STATE_DASHBOARD
            self.lcd.clear()
        self.menu_index = min(self.menu_index, len(self._menu_items()) - 1)

    # ══════════════════════════════════════════════════════════════════════════
    # Main loop
    # ══════════════════════════════════════════════════════════════════════════

    def run(self, duration_minutes=None):
        """Main generator loop (runs forever)."""
        if duration_minutes is not None:
            try:
                self.start_timer(duration_minutes)
            except (ValueError, TypeError) as e:
                self.logger.error(f"Initial timer error: {e}")

        while True:
            try:
                now = time.ticks_ms()

                # ── Deferred settings load (once, after first render) ──────────
                if self._deferred_load_pending:
                    self._deferred_load()

                # ── PULSE gate fallback ──────────────────────────────────────
                if self.gen_active and self.mode == "PULSE" and not self._pulse_thread_enabled:
                    self._check_pulse_param_changes()  # Apply any parameter changes
                    self._update_pulse_gate()

                # ── Auto-stop timer check ─────────────────────────────────────
                if self.timer_active and self.timer_end_ms is not None:
                    if time.ticks_diff(now, self.timer_end_ms) >= 0:
                        self.stop_generation()

                # ── Encoder (throttled to reduce I2C bus load) ────────────────
                if time.ticks_diff(now, self._last_encoder_check) >= ENCODER_POLL_MS:
                    self._update_frequency_from_encoder()
                    self._last_encoder_check = now

                # ── Button polling ────────────────────────────────────────────
                if time.ticks_diff(now, self.last_button_check) >= BUTTON_CHECK_MS:
                    self._handle_button(now)
                    self.last_button_check = now

                # ── Spinner animation ─────────────────────────────────────────
                if (
                    self.gen_active
                    and time.ticks_diff(now, self.last_spinner_update)
                    >= SPINNER_UPDATE_MS
                ):
                    self.spinner_frame = (self.spinner_frame + 1) % len(
                        self.spinner_chars
                    )
                    self.last_spinner_update = now

                # ── LCD refresh ───────────────────────────────────────────────
                if time.ticks_diff(now, self._last_display_refresh) >= 1000:
                    self.lcd.invalidate_cache()
                    self._last_display_refresh = now
                if time.ticks_diff(now, self.last_update) >= UPDATE_INTERVAL_MS:
                    self._update_display()
                    self.last_update = now

                # Keep GC away from active PULSE generation to reduce timing
                # perturbations on both cores.
                if not (self.gen_active and self.mode == "PULSE"):
                    gc.collect()

                # ── Sleep ───────────────────────────────────────────────────
                time.sleep_ms(5)

                # Reset error counter after a clean pass
                if self._runtime_error_count:
                    self._runtime_error_count = 0

            except Exception as e:
                self._handle_runtime_exception(e)


