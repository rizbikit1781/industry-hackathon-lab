"""0-45 min hail nowcast: MRMS frames -> tracked hail cells -> advected probability -> per-asset ARM/TRIGGER.

Rules + advection only (no ML). The day-ahead model owns MONITOR/PREPARE; this layer owns
ARM, TRIGGER, CANCEL, ALL_CLEAR and DATA_DEGRADED.
"""
