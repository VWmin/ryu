import json
import pickle
import random
import signal
import subprocess
import sys
import threading
import time

import cherrypy
import requests
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo

from mininet.util import customClass
from mininet.link import TCLink

from prepare1_graph_info import *


def int_to_16bit_hex_string(number: int):
    # 使用 hex 函数转换为十六进制字符串（带前缀 "0x"）
    hex_string_with_prefix = hex(number)
    # 去除前缀，并使用 upper 方法将字母转为大写
    hex_string_without_prefix = hex_string_with_prefix[2:].upper()
    hex_string_fixed_length = hex_string_without_prefix.zfill(16)
    return hex_string_fixed_length


def int_to_ip_address(number: int):
    third_octet = (number - 1) // 254
    fourth_octet = (number - 1) % 254 + 1
    return f"10.0.{third_octet}.{fourth_octet}"


# outside access to mininet
class ExpExecServer:
    def __init__(self, info, net, topo_lock):
        self.info = info
        self.net = net
        self.topo_lock = topo_lock

    @cherrypy.expose
    def exec(self):
        self.run_script()
        # time.sleep(15)
        # self.run_iperf()

    @cherrypy.expose
    def switches(self):
        swes = []

        for sw in self.net.switches:
            sw_info = {"dpid": sw.dpid, "ports": []}
            for port in sw.intfs.values():
                if port.name == 'lo':
                    continue
                port_info = {"name": port.name, "mac": port.MAC()}
                sw_info["ports"].append(port_info)
            swes.append(sw_info)
        return pickle.dumps(swes)

    @cherrypy.expose
    def links(self):
        links = []

        self.topo_lock.acquire()
        for link in self.net.links:
            src = link.intf1.node.name
            src_port = link.intf1.name
            src_mac = link.intf1.MAC()
            dst = link.intf2.node.name
            dst_port = link.intf2.name
            dst_mac = link.intf2.MAC()
            links.append((src, src_port, src_mac, dst, dst_port, dst_mac))
        self.topo_lock.release()
        return pickle.dumps(links)

    def run_script(self):
        print("\nstarting script")
        for s in self.info.S2R:
            for r in self.info.S2R[s]:
                self.run_script_on_host(f"h{r}", f"./recv -g {self.info.src_to_group_no[s]}")
            self.run_script_on_host(f"h{s}", f"./send -i {self.info.src_to_group_ip(s)}")

    def run_iperf(self):
        print("\nstarting iperf")
        for s in self.info.S2R:
            multicast_ip = self.info.src_to_group_ip(s)
            for r in self.info.S2R[s]:
                self.run_script_on_host(f"h{r}", f"./run_iperf_server.sh {multicast_ip} h{r}")
            self.run_script_on_host(f"h{s}", f"./run_iperf_client.sh {multicast_ip} h{s} {self.info.B[s]}M")

    def run_script_on_host(self, hostname, cmd):
        host = self.net.getNodeByName(hostname)
        self.run_command_async(host, cmd)
        print(f"{hostname} {cmd}")

    @staticmethod
    def run_command_async(host, command):
        # 异步运行命令
        return host.popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _get_exp_info() -> GraphInfo:
    response = requests.get("http://localhost:9000/exp_info")
    return pickle.loads(response.content)


def _get_latest_graph():
    response = requests.get("http://localhost:9000/latest_graph")
    return pickle.loads(response.content)


# run mininet
class MininetEnv:
    # Rate limit links to 10Mbps
    link = customClass({'tc': TCLink}, 'tc,bw=10')

    def __init__(self):
        self.finished = False
        self.info = _get_exp_info()
        self.net = Mininet(topo=None, build=False)
        self.controllers = {}  # cid -> controller
        self.build_net()
        self.topo_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.signal_handler)

    def build_net(self):
        # related host
        terminals = set()
        for s in self.info.S2R:
            terminals.add(s)
            for r in self.info.S2R[s]:
                terminals.add(r)

        # add controllers
        for i in range(1, self.info.controller_number + 1):
            c = self.net.addController(name=f'c{i}', controller=RemoteController, port=6633 + i - 1)
            self.controllers[i] = c

        # add sw add its connected host
        for n in self.info.graph.nodes:
            s_name = f"s{n}"
            h_name = f"h{n}"
            print(f"cid {self.info.sw_to_cid[n]} <--> dpid {n}")
            if self.info.stp:
                self.net.addSwitch(s_name, dpid=int_to_16bit_hex_string(n), protocols='OpenFlow13', stp=True, failMode='standalone')
            else:
                self.net.addSwitch(s_name, dpid=int_to_16bit_hex_string(n), protocols='OpenFlow13')
            if n in terminals:
                # Add single host on designated switches
                self.net.addHost(h_name, ip=int_to_ip_address(n))
                # directly add the link between hosts and their gateways
                self.net.addLink(s_name, h_name)

        # Connect your switches to each other as defined in networkx graph
        for (n1, n2) in self.info.graph.edges:
            s_name_1, s_name_2 = f"s{n1}", f"s{n2}"
            # self.net.addLink(s_name_1, s_name_2, cls=TCLink, bw=self.info.graph[n1][n2]['bandwidth'], delay=f"{self.info.graph[n1][n2]['weight']}ms")
            self.net.addLink(s_name_1, s_name_2, cls=TCLink)

        info('*** Building network\n')
        self.net.build()

        info('*** Starting controllers\n')
        for controller in self.net.controllers:
            controller.start()

        info('*** Starting switches\n')
        for sw, cid in self.info.sw_to_cid.items():
            self.net.get(f's{sw}').start([self.controllers[cid]])

    def signal_handler(self, sig, frame):
        print("Received signal to exit.")
        if self.net is not None:
            self.net.stop()
        sys.exit(0)

    def start(self):
        # self.net.start()

        threads = [
            threading.Thread(target=self.run_mn_cli),
            threading.Thread(target=self.run_exp_exec_server),
            threading.Thread(target=self.change_network)
        ]

        if self.info.stp:
            threads.append(threading.Thread(target=self.ping_connectivity))

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        self.net.stop()

    def run_mn_cli(self):
        print("run mininet cli")
        CLI(self.net)
        self.finished = True

    def run_exp_exec_server(self):
        print("run exp exec server")
        cherrypy.config.update({'server.socket_host': "0.0.0.0", 'server.socket_port': 9001})
        cherrypy.quickstart(ExpExecServer(self.info, self.net, self.topo_lock))

    def ping_connectivity(self):
        hosts_to_ping = random.sample(self.info.S2R[random.choice(list(self.info.S))], 2)
        ha, hb = self.net.get(f'h{hosts_to_ping[0]}'), self.net.get(f"h{hosts_to_ping[1]}")
        t1 = time.time()
        connected, turn = False, 1
        while not connected:
            result = ha.cmd('ping -c 1', hb.IP())
            print(f"turn {turn}, result: {result}")
            if "1 packets transmitted, 1 received" in result:
                connected = True
        t2 = time.time()
        print(f"cost: {t2 - t1}")

    def change_network(self):
        time.sleep(3)
        cur_links = set(self.info.graph.edges)
        while True:
            latest, g = _get_latest_graph()
            if latest:
                next_links = set(g.edges)
                link_down_set = cur_links - next_links  # link down
                link_up_set = next_links - cur_links  # link up

                self.topo_lock.acquire()
                for link in link_down_set:
                    self.net.delLinkBetween(self.net.get(f"s{link[0]}"), self.net.get(f"s{link[1]}"), allLinks=True)
                    print(f"Disconnected s{link[0]} and s{link[1]}")
                for link in link_up_set:
                    self.net.addLink(f"s{link[0]}", f"s{link[1]}", cls=TCLink)
                    print(f"Connect s{link[0]} and s{link[1]}")
                self.topo_lock.release()
                cur_links = next_links

            time.sleep(3)


if __name__ == '__main__':
    setLogLevel('info')
    ev = MininetEnv()
    ev.start()
