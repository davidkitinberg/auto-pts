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


WSS = {
    'read_supported_cmds': (defs.BTP_SERVICE_ID_WSS,
                            defs.BTP_WSS_CMD_READ_SUPPORTED_COMMANDS,
                            CONTROLLER_INDEX_NONE),
    'set_feature': (defs.BTP_SERVICE_ID_WSS,
                    defs.BTP_WSS_CMD_SET_FEATURE,
                    CONTROLLER_INDEX),
    'indicate': (defs.BTP_SERVICE_ID_WSS,
                 defs.BTP_WSS_CMD_INDICATE,
                 CONTROLLER_INDEX),
}


def wss_command_rsp_succ(timeout=20.0):
    logging.debug("%s", wss_command_rsp_succ.__name__)

    iutctl = get_iut()
    tuple_hdr, tuple_data = iutctl.btp_socket.read(timeout)
    logging.debug("received %r %r", tuple_hdr, tuple_data)

    btp_hdr_check(tuple_hdr, defs.BTP_SERVICE_ID_WSS)

    return tuple_data


def wss_set_feature(feature):
    logging.debug("%s", wss_set_feature.__name__)

    data = struct.pack('<I', feature)

    iutctl = get_iut()
    iutctl.btp_socket.send(*WSS['set_feature'], data=data)

    wss_command_rsp_succ()


def wss_indicate(measurement=None):
    logging.debug("%s", wss_indicate.__name__)

    data = b'' if measurement is None else bytes(measurement)

    iutctl = get_iut()
    iutctl.btp_socket.send(*WSS['indicate'], data=data)

    wss_command_rsp_succ()


def wss_ev_weight_meas_ccc_changed(wss, data, data_len):
    logging.debug("%s %r", wss_ev_weight_meas_ccc_changed.__name__, data)

    enabled = bool(int.from_bytes(data[:1], "little"))
    wss.weight_meas_ccc_enabled = enabled
    wss.event_received(defs.BTP_WSS_EV_WEIGHT_MEAS_CCC_CHANGED, (enabled,))


def wss_ev_weight_meas_indicate_done(wss, data, data_len):
    logging.debug("%s %r", wss_ev_weight_meas_indicate_done.__name__, data)

    if data_len < 1:
        raise BTPError("Invalid WSS indicate-done event")

    err = int.from_bytes(data[:1], "little")
    wss.last_indicate_err = err
    wss.event_received(defs.BTP_WSS_EV_WEIGHT_MEAS_INDICATE_DONE, (err,))


WSS_EV = {
    defs.BTP_WSS_EV_WEIGHT_MEAS_CCC_CHANGED: wss_ev_weight_meas_ccc_changed,
    defs.BTP_WSS_EV_WEIGHT_MEAS_INDICATE_DONE: wss_ev_weight_meas_indicate_done,
}
