import threading
import time

import requests
from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class MininetEnv:

    def __init__(self):
        self.finished = False
        self.net = Mininet()
        self.build_net()

    def change_topo(self):
        time.sleep(30)
        # old: 1 <-> 2 <-> 3
        # new: 2 <-> 1 <-> 3
        self.net.delLinkBetween(self.net.get("s2"), self.net.get("s3"), allLinks=True)
        link = self.net.addLink("s1", "s3")
        s1 = self.net.getNodeByName("s1")
        s2 = self.net.getNodeByName("s2")
        s1.attach(link.intf1.name)
        s2.attach(link.intf2.name)

        # self.net.configLinkStatus("s2", "s3", "down")
        # self.net.configLinkStatus("s1", "s3", "up")

        info("Topo changed")
        requests.get("http://localhost:9002/topo_changed")

    def build_net(self):
        self.net.addController("c0", controller=RemoteController)

        self.net.addSwitch("s1")
        self.net.addSwitch("s2")
        self.net.addSwitch("s3")

        self.net.addHost("h1")
        self.net.addHost("h2")
        self.net.addHost("h3")
        self.net.addLink("s1", "h1")
        self.net.addLink("s2", "h2")
        self.net.addLink("s3", "h3")

        # 1 <-> 2 <-> 3
        self.net.addLink("s1", "s2")
        self.net.addLink("s2", "s3")

        # self.net.addLink("s1", "s3")
        # self.net.configLinkStatus("s1", "s3", "down")

    def start(self):
        t1 = threading.Thread(target=self.start_net)
        t2 = threading.Thread(target=self.change_topo)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

    def start_net(self):
        self.net.start()
        CLI(self.net)
        self.net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    ev = MininetEnv()
    ev.start()
