#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2026, Codecoup.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#

import logging
import re

from autopts.ptsprojects.stack import get_stack
from autopts.pybtp import btp
from autopts.pybtp.types import WIDParams

log = logging.debug


def scps_wid_hdl(wid, description, test_case_name):
    from autopts.wid import generic_wid_hdl
    log(f'{scps_wid_hdl.__name__}, {wid}, {description}, {test_case_name}')
    return generic_wid_hdl(wid, description, test_case_name, [__name__, 'autopts.wid.gatt'])


def hdl_wid_20001(_: WIDParams):
    stack = get_stack()
    btp.gap_set_conn()
    btp.gap_adv_ind_on(ad=stack.gap.ad)
    return True


def hdl_wid_20108(_: WIDParams):
    btp.sps_refresh_request()
    return True


def hdl_wid_20207(params: WIDParams):
    interval_match = re.search(
        r'LE_Scan_Interval:\s*\[(\d+)', params.description)
    window_match = re.search(
        r'LE_Scan_Window:\s*\[(\d+)', params.description)
    if not interval_match or not window_match:
        return False

    interval = int(interval_match.group(1))
    window = int(window_match.group(1))
    stack = get_stack()

    return bool(stack.sps.wait_scan_interval_window_written(
        interval, window, timeout=10))
