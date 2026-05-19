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
import struct

from autopts.pybtp import defs
from autopts.pybtp.btp.btp import CONTROLLER_INDEX, CONTROLLER_INDEX_NONE, btp_hdr_check
from autopts.pybtp.btp.btp import get_iut_method as get_iut
from autopts.pybtp.types import BTPError


SPS = {
    'read_supported_cmds': (defs.BTP_SERVICE_ID_SPS,
                            defs.BTP_SPS_CMD_READ_SUPPORTED_COMMANDS,
                            CONTROLLER_INDEX_NONE),
    'set_scan_interval_window': (defs.BTP_SERVICE_ID_SPS,
                                 defs.BTP_SPS_CMD_SET_SCAN_INTERVAL_WINDOW,
                                 CONTROLLER_INDEX),
    'get_scan_interval_window': (defs.BTP_SERVICE_ID_SPS,
                                 defs.BTP_SPS_CMD_GET_SCAN_INTERVAL_WINDOW,
                                 CONTROLLER_INDEX),
    'refresh_request': (defs.BTP_SERVICE_ID_SPS,
                        defs.BTP_SPS_CMD_REFRESH_REQUEST,
                        CONTROLLER_INDEX),
}


def sps_command_rsp_succ(timeout=20.0):
    logging.debug("%s", sps_command_rsp_succ.__name__)

    iutctl = get_iut()
    tuple_hdr, tuple_data = iutctl.btp_socket.read(timeout)
    logging.debug("received %r %r", tuple_hdr, tuple_data)

    btp_hdr_check(tuple_hdr, defs.BTP_SERVICE_ID_SPS)

    return tuple_data


def sps_set_scan_interval_window(interval, window):
    logging.debug("%s", sps_set_scan_interval_window.__name__)

    data = struct.pack('<HH', interval, window)

    iutctl = get_iut()
    iutctl.btp_socket.send(*SPS['set_scan_interval_window'], data=data)

    sps_command_rsp_succ()


def sps_get_scan_interval_window():
    logging.debug("%s", sps_get_scan_interval_window.__name__)

    iutctl = get_iut()
    iutctl.btp_socket.send(*SPS['get_scan_interval_window'])

    tuple_data = sps_command_rsp_succ()
    if not tuple_data or len(tuple_data[0]) < 4:
        raise BTPError("Invalid SPS scan interval/window response")

    interval, window = struct.unpack_from('<HH', tuple_data[0])

    return interval, window


def sps_refresh_request():
    logging.debug("%s", sps_refresh_request.__name__)

    iutctl = get_iut()
    iutctl.btp_socket.send(*SPS['refresh_request'])

    sps_command_rsp_succ()


def sps_ev_scan_interval_window_written(sps, data, data_len):
    logging.debug("%s %r", sps_ev_scan_interval_window_written.__name__, data)

    if data_len < 4:
        raise BTPError("Invalid SPS scan interval/window event")

    interval, window = struct.unpack_from('<HH', data)
    sps.scan_interval = interval
    sps.scan_window = window
    sps.event_received(defs.BTP_SPS_EV_SCAN_INTERVAL_WINDOW_WRITTEN, (interval, window))


def sps_ev_scan_refresh_ccc_changed(sps, data, data_len):
    logging.debug("%s %r", sps_ev_scan_refresh_ccc_changed.__name__, data)

    enabled = bool(int.from_bytes(data[:1], "little"))
    sps.scan_refresh_ccc_enabled = enabled
    sps.event_received(defs.BTP_SPS_EV_SCAN_REFRESH_CCC_CHANGED, (enabled,))


SPS_EV = {
    defs.BTP_SPS_EV_SCAN_INTERVAL_WINDOW_WRITTEN: sps_ev_scan_interval_window_written,
    defs.BTP_SPS_EV_SCAN_REFRESH_CCC_CHANGED: sps_ev_scan_refresh_ccc_changed,
}
