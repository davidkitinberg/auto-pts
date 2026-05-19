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


class WSS:
    def __init__(self):
        self.weight_meas_ccc_enabled = False
        self.last_indicate_err = None
        self.event_queues = {
            defs.BTP_WSS_EV_WEIGHT_MEAS_CCC_CHANGED: [],
            defs.BTP_WSS_EV_WEIGHT_MEAS_INDICATE_DONE: [],
        }

    def event_received(self, event_type, event_data_tuple):
        self.event_queues[event_type].append(event_data_tuple)

    def wait_weight_meas_ccc_changed(self, enabled, timeout, remove=True):
        return wait_event_with_condition(
            self.event_queues[defs.BTP_WSS_EV_WEIGHT_MEAS_CCC_CHANGED],
            lambda _enabled: enabled == _enabled,
            timeout, remove)

    def wait_weight_meas_indicate_done(self, timeout, remove=True):
        return wait_event_with_condition(
            self.event_queues[defs.BTP_WSS_EV_WEIGHT_MEAS_INDICATE_DONE],
            lambda *_: True,
            timeout, remove)
