#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2026, Codecoup.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#

from autopts.ptsprojects.stack.common import wait_event_with_condition
from autopts.pybtp import defs


class SPS:
    def __init__(self):
        self.scan_interval = 30
        self.scan_window = 30
        self.scan_refresh_ccc_enabled = False
        self.event_queues = {
            defs.BTP_SPS_EV_SCAN_INTERVAL_WINDOW_WRITTEN: [],
            defs.BTP_SPS_EV_SCAN_REFRESH_CCC_CHANGED: [],
        }

    def event_received(self, event_type, event_data_tuple):
        self.event_queues[event_type].append(event_data_tuple)

    def set_scan_interval_window(self, interval, window):
        self.scan_interval = interval
        self.scan_window = window

    def wait_scan_interval_window_written(self, interval, window, timeout, remove=True):
        return wait_event_with_condition(
            self.event_queues[defs.BTP_SPS_EV_SCAN_INTERVAL_WINDOW_WRITTEN],
            lambda _interval, _window: (interval, window) == (_interval, _window),
            timeout, remove)

    def wait_scan_refresh_ccc_changed(self, enabled, timeout, remove=True):
        return wait_event_with_condition(
            self.event_queues[defs.BTP_SPS_EV_SCAN_REFRESH_CCC_CHANGED],
            lambda _enabled: enabled == _enabled,
            timeout, remove)
