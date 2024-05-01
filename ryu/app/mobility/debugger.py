#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from ryu.cmd import manager
from prepare1_graph_info import GraphInfo, MulticastInfo
from ryu.app.distribution.route.relavence_matrix import KMB



def main():
    sys.argv.append('/home/fwy/ryu/ryu/app/mobility/controller.py')
    # sys.argv.append('/home/fwy/ryu/ryu/app/flow_manager/flowmanager.py')
    # sys.argv.append('--verbose')
    # sys.argv.append('--enable-debugger')
    # sys.argv.append('--observe-links')
    # sys.argv.append('--wsapi-port')
    # sys.argv.append('8000')
    # sys.argv.append('--controller-id')
    # sys.argv.append('1')
    manager.main()


if __name__ == '__main__':
    main()
