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


BPS = {
    'read_supported_cmds': (defs.BTP_SERVICE_ID_BPS,
                            defs.BTP_BPS_CMD_READ_SUPPORTED_COMMANDS,
                            CONTROLLER_INDEX_NONE),
    'set_feature': (defs.BTP_SERVICE_ID_BPS,
                    defs.BTP_BPS_CMD_SET_FEATURE,
                    CONTROLLER_INDEX),
    'indicate': (defs.BTP_SERVICE_ID_BPS,
                 defs.BTP_BPS_CMD_INDICATE,
                 CONTROLLER_INDEX),
    'notify_intermediate_cuff': (defs.BTP_SERVICE_ID_BPS,
                                 defs.BTP_BPS_CMD_NOTIFY_INTERMEDIATE_CUFF,
                                 CONTROLLER_INDEX),
}


def bps_command_rsp_succ(timeout=20.0):
    logging.debug("%s", bps_command_rsp_succ.__name__)

    iutctl = get_iut()
    tuple_hdr, tuple_data = iutctl.btp_socket.read(timeout)
    logging.debug("received %r %r", tuple_hdr, tuple_data)

    btp_hdr_check(tuple_hdr, defs.BTP_SERVICE_ID_BPS)

    return tuple_data


def bps_set_feature(feature):
    logging.debug("%s", bps_set_feature.__name__)

    data = struct.pack('<H', feature)

    iutctl = get_iut()
    iutctl.btp_socket.send(*BPS['set_feature'], data=data)

    bps_command_rsp_succ()


def bps_indicate(measurement=None):
    logging.debug("%s", bps_indicate.__name__)

    data = b'' if measurement is None else bytes(measurement)

    iutctl = get_iut()
    iutctl.btp_socket.send(*BPS['indicate'], data=data)

    bps_command_rsp_succ()


def bps_notify_intermediate_cuff(measurement=None):
    logging.debug("%s", bps_notify_intermediate_cuff.__name__)

    data = b'' if measurement is None else bytes(measurement)

    iutctl = get_iut()
    iutctl.btp_socket.send(*BPS['notify_intermediate_cuff'], data=data)

    bps_command_rsp_succ()


def bps_ev_bp_meas_ccc_changed(bps, data, data_len):
    logging.debug("%s %r", bps_ev_bp_meas_ccc_changed.__name__, data)

    enabled = bool(int.from_bytes(data[:1], "little"))
    bps.bp_meas_ccc_enabled = enabled
    bps.event_received(defs.BTP_BPS_EV_BP_MEAS_CCC_CHANGED, (enabled,))


def bps_ev_intermediate_cuff_ccc_changed(bps, data, data_len):
    logging.debug("%s %r", bps_ev_intermediate_cuff_ccc_changed.__name__, data)

    enabled = bool(int.from_bytes(data[:1], "little"))
    bps.intermediate_cuff_ccc_enabled = enabled
    bps.event_received(defs.BTP_BPS_EV_INTERMEDIATE_CUFF_CCC_CHANGED, (enabled,))


def bps_ev_bp_meas_indicate_done(bps, data, data_len):
    logging.debug("%s %r", bps_ev_bp_meas_indicate_done.__name__, data)

    if data_len < 1:
        raise BTPError("Invalid BPS indicate-done event")

    err = int.from_bytes(data[:1], "little")
    bps.last_indicate_err = err
    bps.event_received(defs.BTP_BPS_EV_BP_MEAS_INDICATE_DONE, (err,))


BPS_EV = {
    defs.BTP_BPS_EV_BP_MEAS_CCC_CHANGED: bps_ev_bp_meas_ccc_changed,
    defs.BTP_BPS_EV_INTERMEDIATE_CUFF_CCC_CHANGED: bps_ev_intermediate_cuff_ccc_changed,
    defs.BTP_BPS_EV_BP_MEAS_INDICATE_DONE: bps_ev_bp_meas_indicate_done,
}
