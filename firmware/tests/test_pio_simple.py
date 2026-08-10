"""Minimal PIO square-wave validation on GPIO0.

This script tests only the PIO path (no LCD, no encoder).
Use an oscilloscope or an LED + resistor on GPIO0 for validation.
"""

from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
import time

# Configuration
PIN_OUTPUT = 0  # GPIO0 output

print("\n" + "="*50)
print("PIO TEST - Simple square signal")
print("="*50)
print(f"\nOutput configured on GPIO {PIN_OUTPUT}")
print("Check with an oscilloscope or an LED\n")

# Ultra-simple PIO program: toggle the output every 16 cycles.
@asm_pio(set_init=PIO.OUT_LOW)
def simple_toggle():
    wrap_target()
    set(pins, 1) [15]  # HIGH for 16 cycles
    set(pins, 0) [15]  # LOW for 16 cycles
    wrap()

# Test 1: low but safe frequency for RP2040 state machine constraints.
print("Test 1: Low-frequency signal (~64 Hz)")
print("Press Ctrl+C to skip to the next test...\n")

try:
    # 32 cycles per output period -> f_out = f_sm / 32
    # Conservative RP2040-compatible choice: f_sm = 2048 Hz -> f_out ~64 Hz
    sm = StateMachine(0, simple_toggle, freq=2048, set_base=Pin(PIN_OUTPUT))
    sm.active(1)
    
    time.sleep(5)
    print("[OK] Test 1 complete - if LED blinks, PIO is working.")
    sm.active(0)
    
except KeyboardInterrupt:
    print("\n[INFO] Test 1 interrupted")
    try:
        sm.active(0)
    except Exception:
        pass

time.sleep(1)

# Test 2: medium frequency (1 kHz).
print("\nTest 2: 1 kHz signal")
print("(LED may look dim; verify with oscilloscope)")
print("Press Ctrl+C to skip to the next test...\n")

try:
    # For 1 kHz output: 32 cycles per period -> freq_sm = 32 kHz
    sm = StateMachine(0, simple_toggle, freq=32_000, set_base=Pin(PIN_OUTPUT))
    sm.active(1)
    
    time.sleep(5)
    print("[OK] Test 2 complete")
    sm.active(0)
    
except KeyboardInterrupt:
    print("\n[INFO] Test 2 interrupted")
    try:
        sm.active(0)
    except Exception:
        pass

time.sleep(1)

# Test 3: high frequency (30 kHz), same target as main application default.
print("\nTest 3: 30 kHz signal (generator default frequency)")
print("(Check with oscilloscope)")
print("Press Ctrl+C to stop...\n")

try:
    # For 30 kHz output: 32 cycles per period -> freq_sm = 960 kHz
    sm = StateMachine(0, simple_toggle, freq=30_000 * 32, set_base=Pin(PIN_OUTPUT))
    sm.active(1)
    
    print("[ACTIVE] 30 kHz signal running on GPIO0")
    print("   Measure with oscilloscope or HV probe\n")
    
    # Keep running until interrupted.
    while True:
        time.sleep(1)
        
except KeyboardInterrupt:
    print("\n[OK] Test finished")
    try:
        sm.active(0)
    except Exception:
        pass

print("\n" + "="*50)
print("SUMMARY")
print("="*50)
print("If no signal is visible:")
print("  1. Check GPIO0 wiring")
print("  2. Check microcontroller power")
print("  3. Try LED + 330 ohm resistor on GPIO0")
print("  4. Confirm correct MicroPython firmware")
print("\nIf test 1-2 works but test 3 does not:")
print("  - Your probe/scope may be bandwidth-limited")
print("  - The HV transformer may require a transistor driver")
