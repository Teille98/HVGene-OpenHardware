"""
JSON-based settings storage.
MicroPython compatible - uses a simple JSON file.
"""

import json
import os

from lib.logger import get_logger


class SettingsStorage:
    """Settings save/load manager."""

    def __init__(self, filename="settings.json"):
        self.filename = filename
        self.backup_filename = f"{filename}.bak"
        self.tmp_filename = f"{filename}.tmp"
        self.settings = {}
        self.logger = get_logger("Storage")

    def _read_json_file(self, filename):
        """Read a JSON file and return a dict, otherwise None."""
        try:
            with open(filename, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            self.logger.warning(f"Invalid JSON format (expected dict): {filename}")
            return None
        except (OSError, ValueError) as e:
            self.logger.warning(f"Unable to read JSON ({filename}): {e}")
            return None

    def _atomic_replace(self, source, destination):
        """Robustly replace destination with source."""
        try:
            try:
                os.remove(destination)
            except OSError:
                pass
            os.rename(source, destination)
            return True
        except OSError as e:
            self.logger.error(f"Atomic replace failed ({source} -> {destination}): {e}")
            return False

    def load(self):
        """Load settings from the JSON file."""
        data = self._read_json_file(self.filename)
        if data is not None:
            self.settings = data
            self.logger.info(f"Settings loaded: {self.filename}")
            return True

        # Fall back to the backup if the main file is corrupted or unavailable.
        backup_data = self._read_json_file(self.backup_filename)
        if backup_data is not None:
            self.settings = backup_data
            self.logger.warning(
                f"Settings restored from backup: {self.backup_filename}"
            )
            return True

        self.settings = {}
        self.logger.warning("No valid settings found, using defaults")
        return False

    def save(self):
        """Save settings to the JSON file."""
        try:
            with open(self.tmp_filename, "w") as f:
                json.dump(self.settings, f)

            # Keep a consistent backup of the last valid version.
            try:
                with open(self.filename, "r") as f:
                    existing = f.read()
                with open(self.backup_filename, "w") as f:
                    f.write(existing)
            except OSError:
                pass

            if not self._atomic_replace(self.tmp_filename, self.filename):
                return False

            self.logger.debug(f"Settings saved atomically: {self.filename}")
            return True
        except OSError as e:
            self.logger.error(f"Unable to save settings: {e}")
            try:
                os.remove(self.tmp_filename)
            except OSError:
                pass
            return False

    def get(self, key, default=None):
        """Get a value."""
        return self.settings.get(key, default)

    def set(self, key, value):
        """Set a value."""
        self.settings[key] = value

    def get_all(self):
        """Return all settings."""
        return self.settings.copy()

    def clear(self):
        """Clear all settings."""
        self.settings.clear()

    def delete_file(self):
        """Delete the settings file."""
        try:
            os.remove(self.filename)
            return True
        except OSError:
            return False

    # -------------------------------
    # Profiles helper
    # -------------------------------
    def get_profiles(self):
        """Return dict of saved profiles (name -> dict)."""
        return self.settings.get("profiles", {}).copy()

    def save_profile(self, name, profile_data):
        """Save a profile under `name` with profile_data (dict)."""
        profiles = self.settings.get("profiles", {})
        profiles[name] = profile_data
        self.settings["profiles"] = profiles
        return self.save()

    def delete_profile(self, name):
        """Delete a named profile. Returns True if removed."""
        profiles = self.settings.get("profiles", {})
        if name in profiles:
            del profiles[name]
            self.settings["profiles"] = profiles
            return self.save()
        return False

    def load_profile(self, name):
        """Return the profile dict for `name` or None."""
        profiles = self.settings.get("profiles", {})
        return profiles.get(name)


class GeneratorSettings:
    """Generator-specific settings manager."""

    def __init__(self, filename="hvgen_settings.json"):
        self.storage = SettingsStorage(filename)
        self._loaded = False  # Explicitly track whether storage has been loaded
        # NOTE: load() is intentionally skipped to avoid blocking boot.
        # Call deferred_load() after the dashboard starts to load saved settings.

    def deferred_load(self):
        """Load settings lazily (after dashboard boot)."""
        if not self._loaded:
            self.storage.load()
            self._loaded = True

    def save_state(self, generator):
        """Save the generator's full state."""
        self.storage.set("mode", generator.mode)
        self.storage.set("current_freq", generator.current_freq)
        self.storage.set("pulse_freq", int(generator.pulse_freq))
        self.storage.set("ui_square_freq_min", int(generator.ui_square_freq_min))
        self.storage.set("ui_square_freq_max", int(generator.ui_square_freq_max))
        self.storage.set("ui_pulse_freq_min", int(generator.ui_pulse_freq_min))
        self.storage.set("ui_pulse_freq_max", int(generator.ui_pulse_freq_max))
        self.storage.set("ui_square_freq_step", int(generator.ui_square_freq_step))
        self.storage.set("ui_pulse_freq_step", int(generator.ui_pulse_freq_step))
        self.storage.set("square_duty_cycle", generator.square_duty_cycle)
        self.storage.set("pulse_duty_cycle", generator.duty_cycle)
        self.storage.set("duty_cycle", generator.duty_cycle)  # backward compat
        self.storage.set("timer_minutes", generator.timer_minutes)
        return self.storage.save()

    def save_profile(self, generator, name=None):
        """Save current generator parameters as a named profile.

        If `name` is None an ISO-like timestamp name is generated.
        Returns the profile name on success, or None on failure.
        """
        try:
            if name is None:
                t = __import__("time")
                ts = t.localtime() if hasattr(t, "localtime") else None
                if ts:
                    name = f"profile_{ts[0]:04d}{ts[1]:02d}{ts[2]:02d}_{ts[3]:02d}{ts[4]:02d}{ts[5]:02d}"
                else:
                    name = "profile"
            pdata = {
                "mode": generator.mode,
                "current_freq": int(generator.current_freq),
                "pulse_freq": int(generator.pulse_freq),
                "square_duty_cycle": generator.square_duty_cycle,
                "pulse_duty_cycle": generator.duty_cycle,
            }
            ok = self.storage.save_profile(name, pdata)
            return name if ok else None
        except Exception:
            return None

    def list_profiles(self):
        """Return a sorted list of profile names."""
        p = self.storage.get_profiles()
        names = list(p.keys())
        names.sort()
        return names

    def load_profile(self, generator, name):
        """Load a named profile into the generator. Returns True on success."""
        pdata = self.storage.load_profile(name)
        if not pdata:
            return False
        try:
            generator.mode = pdata.get("mode", generator.mode)
            generator.current_freq = pdata.get("current_freq", generator.current_freq)
            generator.pulse_freq = pdata.get("pulse_freq", generator.pulse_freq)
            generator.square_duty_cycle = pdata.get(
                "square_duty_cycle", generator.square_duty_cycle
            )
            generator.duty_cycle = pdata.get("pulse_duty_cycle", generator.duty_cycle)
            return True
        except Exception:
            return False

    def load_state(self, generator, defaults):
        """Load state into the generator (with defaults)."""
        generator.mode = self.storage.get("mode", defaults["mode"])
        generator.current_freq = self.storage.get(
            "current_freq", defaults["current_freq"]
        )
        generator.pulse_freq = self.storage.get("pulse_freq", defaults["pulse_freq"])
        generator.ui_square_freq_min = self.storage.get(
            "ui_square_freq_min", defaults["ui_square_freq_min"]
        )
        generator.ui_square_freq_max = self.storage.get(
            "ui_square_freq_max", defaults["ui_square_freq_max"]
        )
        generator.ui_pulse_freq_min = self.storage.get(
            "ui_pulse_freq_min", defaults["ui_pulse_freq_min"]
        )
        generator.ui_pulse_freq_max = self.storage.get(
            "ui_pulse_freq_max", defaults["ui_pulse_freq_max"]
        )
        generator.ui_square_freq_step = self.storage.get(
            "ui_square_freq_step", defaults["ui_square_freq_step"]
        )
        generator.ui_pulse_freq_step = self.storage.get(
            "ui_pulse_freq_step", defaults["ui_pulse_freq_step"]
        )
        generator.square_duty_cycle = self.storage.get(
            "square_duty_cycle", defaults["square_duty_cycle"]
        )
        generator.duty_cycle = self.storage.get(
            "pulse_duty_cycle",
            self.storage.get("duty_cycle", defaults["pulse_duty_cycle"]),
        )
        generator.timer_minutes = self.storage.get("timer_minutes", 0)

    def has_saved_state(self):
        """Check whether saved state exists."""
        return len(self.storage.settings) > 0

    # ----------------------------
    # Slot-based profiles (fixed slots)
    # ----------------------------
    def _slot_name(self, idx):
        return f"slot{int(idx):02d}"

    def save_slot(self, generator, slot_index):
        """Save current generator parameters into numbered slot (1..10)."""
        try:
            name = self._slot_name(slot_index)
            pdata = {
                "mode": generator.mode,
                "current_freq": int(generator.current_freq),
                "pulse_freq": int(generator.pulse_freq),
                "square_duty_cycle": generator.square_duty_cycle,
                "pulse_duty_cycle": generator.duty_cycle,
            }
            return self.storage.save_profile(name, pdata)
        except Exception:
            return False

    def load_slot(self, generator, slot_index):
        """Load parameters from numbered slot into generator. Returns True on success."""
        try:
            name = self._slot_name(slot_index)
            pdata = self.storage.load_profile(name)
            if not pdata:
                return False
            generator.mode = pdata.get("mode", generator.mode)
            generator.current_freq = pdata.get("current_freq", generator.current_freq)
            generator.pulse_freq = pdata.get("pulse_freq", generator.pulse_freq)
            generator.square_duty_cycle = pdata.get(
                "square_duty_cycle", generator.square_duty_cycle
            )
            generator.duty_cycle = pdata.get("pulse_duty_cycle", generator.duty_cycle)
            return True
        except Exception:
            return False

    def delete_slot(self, slot_index):
        """Delete numbered slot. Returns True if removed."""
        try:
            name = self._slot_name(slot_index)
            return self.storage.delete_profile(name)
        except Exception:
            return False

    def slot_info(self, slot_index):
        """Return profile name or None for slot_index."""
        name = self._slot_name(slot_index)
        p = self.storage.load_profile(name)
        return p

    def list_slots(self, max_slots=10):
        """Return list of slot names or None for empty slots.

        List indexed from 1..max_slots.
        """
        out = []
        for i in range(1, max_slots + 1):
            pdata = self.slot_info(i)
            out.append(pdata)
        return out
