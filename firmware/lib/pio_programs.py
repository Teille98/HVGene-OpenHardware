"""
Push-pull PIO program for RP2040.

FIFO-based design: the square waveform keeps running while software pushes a
new timing word to the TX FIFO. The state machine applies the latest word on
the next period via pull(noblock).

The square duty is now interpreted per half-phase:

    A-active -> A-dead -> B-active -> B-dead

The active time and the dead-time are both controlled by the same duty value.
At 50% they are equal. At 100% the dead-time is clamped to a minimum value.

TX FIFO word (32-bit, low-half first for out_shiftdir=1):

    bits [31:16] = dead_y    - loop counter for each dead half-phase
    bits [15: 0] = active_y  - loop counter for each active half-phase

The helper functions keep the ratio stable in real time while preserving a
safe dead-time floor.

PULSE mode gating uses GPIO pad OUTOVER registers to force both pads LOW
without stopping the state machine.
"""

from micropython import const
from rp2 import PIO, asm_pio

# ── SM clock ──────────────────────────────────────────────────────────────────
# 10 MHz → 100 ns/cycle. Covers 5–60 kHz with < 0.5 % frequency error.
# Must stay below the RP2040 system clock (default 125 MHz).
PUSH_PULL_SM_FREQ = const(10_000_000)

# ── Timing model ──────────────────────────────────────────────────────────────
PUSH_PULL_MIN_DEAD_CYCLES = const(1)
PUSH_PULL_PERIOD_OVERHEAD_CYCLES = const(19)

# ── Dead time ─────────────────────────────────────────────────────────────────
# Default dead-time budget used by the calculator when needed.
PUSH_PULL_DEAD_CYCLES = const(10)

# ── GPIO pad output-override (OUTOVER) register map ──────────────────────────
# RP2040 datasheet §2.19.6.1 — GPIO_CTRLn register, bits [9:8].
_GPIO_CTRL_BASE = const(0x40014004)  # GPIO0_CTRL address
_GPIO_CTRL_STRIDE = const(8)  # 8 bytes between consecutive GPIO_CTRLn
_OUTOVER_MASK = const(0x00000300)  # Mask for bits [9:8]
_OUTOVER_CLEAR = const(
    0xFFFFFCFF
)  # ~_OUTOVER_MASK  (32-bit, avoids Python bigint issues)
_OUTOVER_NORMAL = const(0x00000000)  # PIO drives the pad  (no override)
_OUTOVER_LOW = const(0x00000200)  # Force pad output LOW, PIO keeps running

# Pre-import mem32 at module level so gate_pulse_outputs() needs no import at
# call time — important for ISR-safety (no Python allocation during callback).
try:
    from machine import mem32 as _mem32

    _HAS_MEM32 = True
except ImportError:
    _mem32 = None
    _HAS_MEM32 = False


# ── PIO program ───────────────────────────────────────────────────────────────


@asm_pio(set_init=(PIO.OUT_LOW, PIO.OUT_LOW), out_shiftdir=1, autopull=False)
def push_pull_pio():
    """
    Push-pull complementary square-wave PIO program.

    TX FIFO format: (dead_y << 16) | active_y

    The same active/dead pair is used for both half-phases, so the square
    output keeps symmetric timing.
    """
    wrap_target()

    # ── Load timing word ──────────────────────────────────────────────────────
    pull(noblock)
    mov(x, osr)  # Keep the full timing word for pull(noblock) fallback.
    out(y, 16)  # Y = active_y (low 16 bits)
    mov(isr, y)  # Save active_y for the second half.

    # ── Phase A: GPIO0 = 1, GPIO1 = 0 ────────────────────────────────────────
    set(pins, 0b01)
    label("plus_loop")
    jmp(y_dec, "plus_loop")  # loops Y times, then falls through on Y = 0

    mov(osr, x)
    out(y, 16)  # discard active_y
    out(y, 16)  # load dead_y (high 16 bits)
    set(pins, 0b00)
    label("plus_dead")
    jmp(y_dec, "plus_dead")

    # ── Phase B: GPIO0 = 0, GPIO1 = 1 ────────────────────────────────────────
    mov(y, isr)
    set(pins, 0b10)
    label("minus_loop")
    jmp(y_dec, "minus_loop")

    mov(osr, x)
    out(y, 16)  # discard active_y
    out(y, 16)  # load dead_y (high 16 bits)
    set(pins, 0b00)
    label("minus_dead")
    jmp(y_dec, "minus_dead")

    wrap()


# ── Python helpers ────────────────────────────────────────────────────────────


def _split_half_phase_budget(
    freq_hz,
    duty=0.5,
    sm_freq=PUSH_PULL_SM_FREQ,
    min_dead_cycles=PUSH_PULL_MIN_DEAD_CYCLES,
):
    """Return active/dead cycle counts for one half-phase."""
    if freq_hz <= 0:
        return 0, 0, 0

    duty = max(0.0, min(1.0, float(duty)))
    min_dead_cycles = int(max(1, min(0xFFFF, min_dead_cycles)))
    period_cyc = max(
        PUSH_PULL_PERIOD_OVERHEAD_CYCLES + 2 * (min_dead_cycles + 1),
        int(round(float(sm_freq) / freq_hz)),
    )
    half_budget = max(
        min_dead_cycles + 1,
        int(round((period_cyc - PUSH_PULL_PERIOD_OVERHEAD_CYCLES) / 2.0)),
    )

    dead_y = int(round(half_budget * (1.0 - duty)))
    dead_y = max(min_dead_cycles, min(half_budget - 1, dead_y))
    active_y = half_budget - dead_y
    active_y = max(1, min(0xFFFF, active_y))
    dead_y = max(1, min(0xFFFF, dead_y))
    return active_y, dead_y, period_cyc


def calc_push_pull_word(
    freq_hz, duty=0.5, sm_freq=PUSH_PULL_SM_FREQ, dead_cycles=PUSH_PULL_DEAD_CYCLES
):
    """Compute the 32-bit FIFO word for the desired carrier frequency and duty."""
    active_y, dead_y, _period_cyc = _split_half_phase_budget(
        freq_hz, duty=duty, sm_freq=sm_freq, min_dead_cycles=dead_cycles
    )
    if active_y <= 0 or dead_y <= 0:
        return 0
    return (dead_y << 16) | active_y


def actual_freq_from_word(
    word, sm_freq=PUSH_PULL_SM_FREQ, dead_cycles=PUSH_PULL_DEAD_CYCLES
):
    """
    Back-calculate the true output frequency from a packed FIFO word.

    Accounts for integer rounding in calc_push_pull_word().

    Returns:
        float: actual carrier frequency in Hz.
    """
    dead_y = (word >> 16) & 0xFFFF
    active_y = word & 0xFFFF
    total = PUSH_PULL_PERIOD_OVERHEAD_CYCLES + 2 * (active_y + dead_y)
    return float(sm_freq) / total if total > 0 else 0.0


def gate_pulse_outputs(pin_base, gate_on):
    """
    Enable or force-LOW the push-pull pads using GPIO OUTOVER registers.

    The PIO state machine keeps running — only the pad output path is
    overridden. This avoids the SM restart overhead and pin-function
    conflicts that occur with Pin() + active(0/1).

    ISR-safe: only writes hardware registers via the pre-imported _mem32
    object (no Python import, no GC allocation at call time).

    Args:
        pin_base : GPIO number of MOSFET-A pin (MOSFET-B = pin_base + 1).
        gate_on  : True  → PIO drives pads normally.
                   False → Both pads forced LOW.
    """
    if not _HAS_MEM32:
        return
    override = _OUTOVER_NORMAL if gate_on else _OUTOVER_LOW
    addr_a = _GPIO_CTRL_BASE + pin_base * _GPIO_CTRL_STRIDE
    addr_b = _GPIO_CTRL_BASE + (pin_base + 1) * _GPIO_CTRL_STRIDE
    _mem32[addr_a] = (_mem32[addr_a] & _OUTOVER_CLEAR) | override
    _mem32[addr_b] = (_mem32[addr_b] & _OUTOVER_CLEAR) | override
