#!/usr/bin/env python3
"""Tests for schedule local-time -> UTC conversion (_schedule_local_to_utc).

Covers both resolution paths used by the Discord scheduled-event flow:
the IANA timezone name (via zoneinfo/tzdata) and the numeric offset fallback,
which follows the JS Date.getTimezoneOffset() convention sent by the frontend
((UTC - local) minutes, e.g. -120 for UTC+2).
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gapi_gui import _schedule_local_to_utc


def _utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestScheduleLocalToUtc(unittest.TestCase):
    # --- IANA name path (needs tzdata; pinned in requirements) -----------
    def test_iana_name_utc_plus_2(self):
        # Europe/Amsterdam is UTC+2 in July (CEST): 20:00 local -> 18:00 UTC
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_name='Europe/Amsterdam')
        self.assertEqual(out, _utc(2026, 7, 15, 18, 0))

    def test_iana_name_crosses_midnight(self):
        # America/New_York is UTC-4 in July (EDT): 20:00 local -> 00:00 next day UTC
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_name='America/New_York')
        self.assertEqual(out, _utc(2026, 7, 16, 0, 0))

    # --- numeric offset fallback (JS getTimezoneOffset convention) -------
    def test_offset_utc_plus_2(self):
        # JS getTimezoneOffset() for UTC+2 is -120
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_offset_minutes=-120)
        self.assertEqual(out, _utc(2026, 7, 15, 18, 0))

    def test_offset_utc_minus_4_crosses_midnight(self):
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_offset_minutes=240)
        self.assertEqual(out, _utc(2026, 7, 16, 0, 0))

    def test_offset_zero_is_utc(self):
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_offset_minutes=0)
        self.assertEqual(out, _utc(2026, 7, 15, 20, 0))

    # --- fallback ordering ----------------------------------------------
    def test_invalid_name_falls_back_to_offset(self):
        out = _schedule_local_to_utc(
            '2026-07-15', '20:00',
            timezone_name='Not/AZone', timezone_offset_minutes=-120,
        )
        self.assertEqual(out, _utc(2026, 7, 15, 18, 0))

    # --- result shape ----------------------------------------------------
    def test_result_is_utc(self):
        out = _schedule_local_to_utc('2026-07-15', '20:00', timezone_offset_minutes=-120)
        self.assertEqual(out.utcoffset(), timezone.utc.utcoffset(None))


if __name__ == '__main__':
    unittest.main()
