"""
Duty-cycle diagnostic for the push-pull PIO program.

Run this script ALONE on the RP2040 (do NOT run main.py at the same time).
Probe GPIO0 and GPIO1 with an oscilloscope.

Expected behaviour
──────────────────
For each duty value printed, GPIO0 HIGH pulse should:
  - Increase in width  as duty increases above 50 %
  - Decrease in width  as duty decreases below 50 %
  - GPIO1 is always complementary (HIGH when GPIO0 is LOW, minus dead time)

If duty doesn't change on the scope → out_shiftdir bug or FIFO issue.
If duty changes in the WRONG direction → out_shiftdir=0 bug (fix: use =1).
"""

# ── Import our library ────────────────────────────────────────────────────────
import sys
import time

from machine import Pin
from rp2 import StateMachine

sys.path.insert(0, "/tests")

from lib.pio_programs import (
    PUSH_PULL_DEAD_CYCLES,
    PUSH_PULL_SM_FREQ,
    actual_freq_from_word,
    calc_push_pull_word,
    gate_pulse_outputs,
    push_pull_pio,
)

# ── Configuration ─────────────────────────────────────────────────────────────
PIN_SQUARE = 0
CARRIER_FREQ = 30_000  # Hz — adjust to your usual operating frequency
HOLD_SECS = 4  # seconds at each duty value — time to measure on scope

DUTIES_TO_TEST = [0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90]


def decode_word(word):
    """Unpack (active_y, dead_y) from a FIFO word."""
    dead_y = (word >> 16) & 0xFFFF
    active_y = word & 0xFFFF
    return active_y, dead_y


def expected_duty(plus_y, minus_y, dead):
    """Calculate the true GPIO0 duty cycle from Y values."""
    overhead = 8 + 2 * dead
    total = overhead + plus_y + minus_y
    gpio0_high = plus_y + 2  # SET + jmp loop + fall-through
    return gpio0_high / total if total > 0 else 0.0


def run_test():
    print("\n" + "=" * 55)
    print("PUSH-PULL DUTY CYCLE DIAGNOSTIC")
    print("=" * 55)
    print(f"Carrier: {CARRIER_FREQ} Hz")
    print(f"SM clock: {PUSH_PULL_SM_FREQ} Hz  ({PUSH_PULL_SM_FREQ // 1_000_000} MHz)")
    print(
        f"Dead time: {PUSH_PULL_DEAD_CYCLES} cycles  "
        f"({PUSH_PULL_DEAD_CYCLES * 1_000_000 // PUSH_PULL_SM_FREQ} µs)"
    )
    print()
    print("Probe GPIO0 and GPIO1 on your oscilloscope.")
    print("Watch the HIGH pulse width change with each step.")
    print("=" * 55)

    # ── Verify word values first (no hardware needed) ──────────────────────────
    print("\n[1] Calculated FIFO words — verify these look reasonable:\n")
    print(
        f"  {'Duty':>6}  {'Word':>12}  {'plus_y':>7}  {'minus_y':>8}  "
        f"{'GPIO0 %':>8}  {'GPIO1 %':>8}  {'Freq':>8}"
    )
    print("  " + "-" * 65)

    for duty in DUTIES_TO_TEST:
        word = calc_push_pull_word(CARRIER_FREQ, duty)
        af = actual_freq_from_word(word)
        py, my = decode_word(word)
        d0 = expected_duty(py, my, PUSH_PULL_DEAD_CYCLES)
        d1 = expected_duty(my, py, PUSH_PULL_DEAD_CYCLES)  # mirrored
        print(
            f"  {duty * 100:5.0f}%  0x{word:08X}  {py:7d}  {my:8d}  "
            f"{d0 * 100:7.1f}%  {d1 * 100:7.1f}%  {af:7.0f} Hz"
        )

    print()
    print("NOTE: GPIO0 % and GPIO1 % should sum to ~100% minus overhead.")
    print("      They will NOT sum to exactly 100% because of dead time.")

    # ── SM setup ──────────────────────────────────────────────────────────────
    print("\n[2] Initialising SM0 on GPIO0/GPIO1 …")
    try:
        sm = StateMachine(0)
        sm.init(push_pull_pio, freq=PUSH_PULL_SM_FREQ, set_base=Pin(PIN_SQUARE))
    except Exception as e:
        print(f"  ERROR: SM init failed: {e}")
        return

    # Push initial word before activating (bootstraps X register)
    init_word = calc_push_pull_word(CARRIER_FREQ, 0.5)
    try:
        sm.put(init_word)
    except Exception as e:
        print(f"  WARNING: initial FIFO put failed: {e}")

    # Clear OUTOVER → allow PIO to drive pads
    gate_pulse_outputs(PIN_SQUARE, True)
    sm.active(1)
    print("  SM0 active. Carrier running at ~50 % duty.")

    # ── Cycle through duties ───────────────────────────────────────────────────
    print(f"\n[3] Cycling through duties ({HOLD_SECS}s each):\n")

    for duty in DUTIES_TO_TEST:
        word = calc_push_pull_word(CARRIER_FREQ, duty)
        py, my = decode_word(word)
        af = actual_freq_from_word(word)
        d0 = expected_duty(py, my, PUSH_PULL_DEAD_CYCLES)

        print(
            f"  → Duty {duty * 100:.0f}%  "
            f"(word=0x{word:08X}  plus_y={py}  minus_y={my}  "
            f"GPIO0={d0 * 100:.1f}%  {af:.0f} Hz)"
        )
        print(f"     Measure on scope now …", end="")

        # Push new timing to the running SM
        try:
            sm.put(word)
        except Exception as e:
            print(f"\n     ERROR during put(): {e}")
            break

        time.sleep(HOLD_SECS)
        print(" done.")

    # ── Teardown ──────────────────────────────────────────────────────────────
    sm.active(0)
    gate_pulse_outputs(PIN_SQUARE, False)
    print("\n[4] SM stopped. Outputs forced LOW.")
    print("\n" + "=" * 55)
    print("INTERPRETATION")
    print("=" * 55)
    print("  GPIO0 HIGH grows with duty → PIO program correct ✓")
    print("  GPIO0 HIGH shrinks with duty → out_shiftdir=0 bug (fix: use =1)")
    print("  GPIO0 HIGH never changes → FIFO or word calculation bug")
    print("  No signal at all → SM init or gate_pulse_outputs() failed")


run_test()
