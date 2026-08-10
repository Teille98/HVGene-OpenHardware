"""Timing validation for autonomous PIO SQUARE + PULSE control.

This test mirrors the firmware architecture:
- SM0: complementary square on GPIO0/1 with runtime duty updates.
- SM1: pulse gate on GPIO2 with runtime duty/frequency updates.
"""

import time
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio

# Pin configuration
PIN_SQUARE = 0
PIN_GATE = 2

# Clock and target settings
SM1_FREQ = 1_000_000
SQUARE_PIO_PERIOD_CYCLES = 72
SQUARE_CYCLE_UNITS = 64
PIO_CYCLE_OVERHEAD = 6

SQUARE_FREQ = 20_000
SQUARE_DUTY = 0.50

PULSE_FREQ = 10
PULSE_DUTY = 0.50


@asm_pio(set_init=(PIO.OUT_LOW, PIO.OUT_LOW))
def square_gen():
    wrap_target()
    mov(osr, x)
    pull(noblock)
    mov(x, osr)
    mov(osr, y)
    pull(noblock)
    mov(y, osr)
    set(pins, 0b00001)
    label("on_loop")
    jmp(x_dec, "on_loop")
    set(pins, 0b00010)
    label("off_loop")
    jmp(y_dec, "off_loop")
    wrap()


@asm_pio(set_init=PIO.OUT_LOW)
def pulse_gate():
    wrap_target()
    mov(osr, x)
    pull(noblock)
    mov(x, osr)
    mov(osr, y)
    pull(noblock)
    mov(y, osr)
    set(pins, 1)
    label("gate_on")
    jmp(x_dec, "gate_on")
    set(pins, 0)
    label("gate_off")
    jmp(y_dec, "gate_off")
    wrap()


def calc_square_cycles(duty):
    on_cycles = int(SQUARE_CYCLE_UNITS * duty)
    off_cycles = SQUARE_CYCLE_UNITS - on_cycles
    return max(1, on_cycles), max(1, off_cycles)


def calc_pulse_cycles(freq, duty):
    period = max(4, (SM1_FREQ // int(freq)) - PIO_CYCLE_OVERHEAD)
    on_cycles = int(period * duty)
    off_cycles = period - on_cycles
    return max(1, on_cycles), max(1, off_cycles)


def push_pair(sm, on_cycles, off_cycles):
    sm.put(on_cycles)
    sm.put(off_cycles)


def main():
    print("=" * 60)
    print("PIO AUTONOMOUS TIMING TEST")
    print("=" * 60)

    sq_on, sq_off = calc_square_cycles(SQUARE_DUTY)
    pl_on, pl_off = calc_pulse_cycles(PULSE_FREQ, PULSE_DUTY)

    sm_square = StateMachine(
        0,
        square_gen,
        freq=SQUARE_FREQ * SQUARE_PIO_PERIOD_CYCLES,
        set_base=Pin(PIN_SQUARE)
    )
    sm_pulse = StateMachine(
        1,
        pulse_gate,
        freq=SM1_FREQ,
        set_base=Pin(PIN_GATE)
    )

    push_pair(sm_square, sq_on, sq_off)
    push_pair(sm_pulse, pl_on, pl_off)

    sm_square.active(1)
    sm_pulse.active(1)

    print("\n[OK] SM0 and SM1 started")
    print(f"Square: {SQUARE_FREQ} Hz, duty {int(SQUARE_DUTY * 100)}%")
    print(f"  ON/OFF cycles: {sq_on}/{sq_off}")
    print(f"Pulse gate: {PULSE_FREQ} Hz, duty {int(PULSE_DUTY * 100)}%")
    print(f"  ON/OFF cycles: {pl_on}/{pl_off} (+{PIO_CYCLE_OVERHEAD} overhead)")
    print("\nObserve:")
    print("  CH1 -> GPIO0 (square complementary waveform)")
    print("  CH2 -> GPIO2 (pulse gate)")
    print("\nWaiting 8 seconds before runtime update...")

    try:
        time.sleep(8)

        # Runtime update validation without reloading scripts.
        new_square_duty = 0.30
        new_pulse_duty = 0.70
        sq_on, sq_off = calc_square_cycles(new_square_duty)
        pl_on, pl_off = calc_pulse_cycles(PULSE_FREQ, new_pulse_duty)

        push_pair(sm_square, sq_on, sq_off)
        push_pair(sm_pulse, pl_on, pl_off)

        print("\n[UPDATE] Runtime duty update sent")
        print(f"Square duty -> {int(new_square_duty * 100)}% (cycles {sq_on}/{sq_off})")
        print(f"Pulse duty  -> {int(new_pulse_duty * 100)}% (cycles {pl_on}/{pl_off})")
        print("Check both channels for immediate transition.")
        print("\nPress Ctrl+C to stop.\n")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...")
        sm_pulse.active(0)
        sm_square.active(0)
        Pin(PIN_SQUARE, Pin.OUT).value(0)
        Pin(PIN_SQUARE + 1, Pin.OUT).value(0)
        Pin(PIN_GATE, Pin.OUT).value(0)
        print("[OK] State machines stopped and outputs forced LOW")


if __name__ == "__main__":
    main()
