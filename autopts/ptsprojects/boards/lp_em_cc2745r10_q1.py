#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2021, Intel Corporation.
# Copyright (c) 2021, Codecoup.
# Copyright (c) 2021, Nordic Semiconductor ASA.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
import logging
import os

from autopts.bot.common import check_call

supported_projects = ['zephyr']

board_type = 'lp_em_cc2745r10_q1/cc2745r10_q1'


def reset_cmd(iutctl):
    """Reset the LP_EM_CC2745R10_Q1 via TI's OpenOCD (XDS110 probe)."""
    ti_base = os.environ.get('TI_OPENOCD_INSTALL_DIR')
    if ti_base:
        openocd_bin = os.path.join(ti_base, 'openocd', 'bin', 'openocd')
        openocd_scripts = os.path.join(ti_base, 'openocd', 'share', 'openocd', 'scripts')
    else:
        openocd_base = os.path.expanduser('~/ti-openocd')
        openocd_bin = os.path.join(openocd_base, 'src', 'openocd')
        openocd_scripts = os.path.join(openocd_base, 'tcl')

    tcl_cmds = [
        'init',
        'halt',
        'set vt0 [mrw 0x00000000]',
        'set vt1 [mrw 0x00000004]',
        'reg sp $vt0',
        'reg pc $vt1',
        'resume',
        'shutdown',
    ]

    parts = [
        f'sudo {openocd_bin}',
        f'-s {openocd_scripts}',
        '-f board/ti_lp_em_cc2745r10.cfg',
    ]
    for c in tcl_cmds:
        parts.append(f'-c "{c}"')

    return ' '.join(parts)


def build_and_flash(zephyr_wd, tester_app_dir, board, debugger_snr,
                    conf_file=None, project_repos=None, env_cmd=None, *args):
    """Build and flash a Zephyr tester application for TI CC2745R10_Q1."""
    logging.debug("%s: %s %s %s %s", build_and_flash.__name__, zephyr_wd,
                  tester_app_dir, board, conf_file)

    if env_cmd:
        env_cmd = env_cmd.split() + ['&&']
    else:
        env_cmd = []

    tester_dir = os.path.join(zephyr_wd, tester_app_dir)

    check_call('rm -rf build/'.split(), cwd=tester_dir)

    cmd_build = ['west', 'build', '-p', 'auto', '-b', board]
    if conf_file and conf_file not in ["default", "prj.conf"]:
        cmd_build.extend(('--', f'-DEXTRA_CONF_FILE=\'{conf_file}\''))

    check_call(env_cmd + cmd_build, cwd=tester_dir)

    cmd_flash = ['west', 'flash', '--skip-rebuild']
    if debugger_snr:
        cmd_flash.extend(['-i', str(debugger_snr)])

    check_call(env_cmd + cmd_flash, cwd=tester_dir)
