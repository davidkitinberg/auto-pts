#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2026, Codecoup.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#

from autopts.client import get_unique_name
from autopts.ptsprojects.stack import get_stack
from autopts.ptsprojects.testcase import TestFunc
from autopts.ptsprojects.zephyr.scps_wid import scps_wid_hdl
from autopts.ptsprojects.zephyr.ztestcase import ZTestCase
from autopts.pybtp import btp


SCAN_INTERVAL = 30
SCAN_WINDOW = 30


def set_pixits(ptses):
    pts = ptses[0]

    pts.set_pixit("ScPS", "TSPX_bd_addr_iut", "DEADBEEFDEAD")
    pts.set_pixit("ScPS", "TSPX_iut_device_name_in_adv_packet_for_random_address", "")
    pts.set_pixit("ScPS", "TSPX_time_guard", "180000")
    pts.set_pixit("ScPS", "TSPX_use_implicit_send", "TRUE")
    pts.set_pixit("ScPS", "TSPX_mtu_size", "23")
    pts.set_pixit("ScPS", "TSPX_secure_simple_pairing_pass_key_confirmation", "FALSE")
    pts.set_pixit("ScPS", "TSPX_delete_link_key", "FALSE")
    pts.set_pixit("ScPS", "TSPX_pin_code", "0000")
    pts.set_pixit("ScPS", "TSPX_use_dynamic_pin", "FALSE")
    pts.set_pixit("ScPS", "TSPX_delete_ltk", "FALSE")
    pts.set_pixit("ScPS", "TSPX_security_enabled", "FALSE")


def test_cases(ptses):
    pts = ptses[0]
    iut_device_name = get_unique_name(pts)
    stack = get_stack()

    pre_conditions = [
        TestFunc(btp.core_reg_svc_gap),
        TestFunc(stack.gap_init, iut_device_name),
        TestFunc(btp.gap_read_ctrl_info),
        TestFunc(lambda: pts.update_pixit_param(
            "ScPS", "TSPX_bd_addr_iut", stack.gap.iut_addr_get_str())),
        TestFunc(btp.core_reg_svc_gatt),
        TestFunc(stack.gatt_init),
        TestFunc(btp.gap_set_conn),
        TestFunc(btp.gap_set_gendiscov),
        TestFunc(btp.core_reg_svc_sps),
        TestFunc(stack.sps_init),
        TestFunc(lambda: stack.sps.set_scan_interval_window(SCAN_INTERVAL, SCAN_WINDOW)),
        TestFunc(btp.sps_set_scan_interval_window, SCAN_INTERVAL, SCAN_WINDOW),
    ]

    tc_list = []
    for tc_name in pts.get_test_case_list('ScPS'):
        tc_list.append(ZTestCase("ScPS", tc_name, cmds=pre_conditions,
                                 generic_wid_hdl=scps_wid_hdl))

    return tc_list
