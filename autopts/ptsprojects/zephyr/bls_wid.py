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

from autopts.wid import generic_wid_hdl

log = logging.debug


def bls_wid_hdl(wid, description, test_case_name):
    log(f'{bls_wid_hdl.__name__}, {wid}, {description}, {test_case_name}')
    return generic_wid_hdl(
        wid, description, test_case_name,
        [__name__, 'autopts.wid.bls', 'autopts.wid.gatt'])
