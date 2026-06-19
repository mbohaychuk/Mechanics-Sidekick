# Canonical python-OBD Mode 01 command names. The dashboard offers these by
# default, filtered at runtime against the ECU's supported set.
CURATED_PIDS: list[str] = [
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "INTAKE_TEMP",
    "MAF",
    "THROTTLE_POS",
    "ENGINE_LOAD",
    "TIMING_ADVANCE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "O2_B1S1",
    "O2_B1S2",
]
