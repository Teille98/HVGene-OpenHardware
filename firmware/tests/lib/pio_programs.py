"""Test-only PIO helpers kept independent from the production module."""

from micropython import const
from rp2 import PIO, asm_pio

PUSH_PULL_SM_FREQ = const(10_000_000)
PUSH_PULL_MIN_DEAD_CYCLES = const(1)
PUSH_PULL_PERIOD_OVERHEAD_CYCLES = const(19)
PUSH_PULL_DEAD_CYCLES = const(10)

_GPIO_CTRL_BASE = const(0x40014004)
_GPIO_CTRL_STRIDE = const(8)
_OUTOVER_CLEAR = const(0xFFFFFCFF)
_OUTOVER_NORMAL = const(0x00000000)
_OUTOVER_LOW = const(0x00000200)

try:
    from machine import mem32 as _mem32

    _HAS_MEM32 = True
except ImportError:
    _mem32 = None
    _HAS_MEM32 = False


@asm_pio(set_init=(PIO.OUT_LOW, PIO.OUT_LOW), out_shiftdir=1, autopull=False)
def push_pull_pio():
    wrap_target()
    pull(noblock)
    mov(x, osr)
    out(y, 16)
    mov(isr, y)
    set(pins, 0b01)
    label("plus_loop")
    jmp(y_dec, "plus_loop")
    mov(osr, x)
    out(y, 16)
    out(y, 16)
    set(pins, 0b00)
    label("plus_dead")
    jmp(y_dec, "plus_dead")
    mov(y, isr)
    set(pins, 0b10)
    label("minus_loop")
    jmp(y_dec, "minus_loop")
    mov(osr, x)
    out(y, 16)
    out(y, 16)
    set(pins, 0b00)
    label("minus_dead")
    jmp(y_dec, "minus_dead")
    wrap()


def _split_half_phase_budget(freq_hz, duty=0.5, sm_freq=PUSH_PULL_SM_FREQ, min_dead_cycles=PUSH_PULL_MIN_DEAD_CYCLES):
    if freq_hz <= 0:
        return 0, 0, 0
    duty = max(0.0, min(1.0, float(duty)))
    min_dead_cycles = int(max(1, min(0xFFFF, min_dead_cycles)))
    period_cyc = max(PUSH_PULL_PERIOD_OVERHEAD_CYCLES + 2 * (min_dead_cycles + 1), int(round(float(sm_freq) / freq_hz)))
    half_budget = max(min_dead_cycles + 1, int(round((period_cyc - PUSH_PULL_PERIOD_OVERHEAD_CYCLES) / 2.0)))
    dead_y = int(round(half_budget * (1.0 - duty)))
    dead_y = max(min_dead_cycles, min(half_budget - 1, dead_y))
    active_y = half_budget - dead_y
    active_y = max(1, min(0xFFFF, active_y))
    dead_y = max(1, min(0xFFFF, dead_y))
    return active_y, dead_y, period_cyc


def calc_push_pull_word(freq_hz, duty=0.5, sm_freq=PUSH_PULL_SM_FREQ, dead_cycles=PUSH_PULL_DEAD_CYCLES):
    active_y, dead_y, _period_cyc = _split_half_phase_budget(freq_hz, duty=duty, sm_freq=sm_freq, min_dead_cycles=dead_cycles)
    if active_y <= 0 or dead_y <= 0:
        return 0
    return (dead_y << 16) | active_y


def actual_freq_from_word(word, sm_freq=PUSH_PULL_SM_FREQ, dead_cycles=PUSH_PULL_DEAD_CYCLES):
    dead_y = (word >> 16) & 0xFFFF
    active_y = word & 0xFFFF
    total = PUSH_PULL_PERIOD_OVERHEAD_CYCLES + 2 * (active_y + dead_y)
    return float(sm_freq) / total if total > 0 else 0.0


def gate_pulse_outputs(pin_base, gate_on):
    if not _HAS_MEM32:
        return
    override = _OUTOVER_NORMAL if gate_on else _OUTOVER_LOW
    addr_a = _GPIO_CTRL_BASE + pin_base * _GPIO_CTRL_STRIDE
    addr_b = _GPIO_CTRL_BASE + (pin_base + 1) * _GPIO_CTRL_STRIDE
    _mem32[addr_a] = (_mem32[addr_a] & _OUTOVER_CLEAR) | override
    _mem32[addr_b] = (_mem32[addr_b] & _OUTOVER_CLEAR) | override