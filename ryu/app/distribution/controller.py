import json
import logging
import os
import pickle
import signal
import time
import ctypes

from ctypes import *

import cherrypy
import requests

from ryu.app.distribution.web_app import GUIServerController
from ryu.app.wsgi import WSGIApplication
from ryu.base.app_manager import lookup_service_brick
from ryu.lib import hub
from ryu import utils
from ryu.base import app_manager
from ryu.controller import ofp_event, handler
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER, HANDSHAKE_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib.packet import packet, ether_types, arp, ethernet
from prepare1_graph_info import GraphInfo, MulticastInfo
from ryu.ofproto import ofproto_v1_3, ofproto_v1_5
from ryu.topology import switches, event
from ryu.topology.api import get_switch, get_link, get_host

PATH = os.path.dirname(__file__)
LOG = logging.getLogger(__name__)


class StructSwitch(Structure):
    _fields_ = [("controller_id", c_short), ("dp_id", c_int), ("port_num", c_short), ("operation", c_bool)]


class StructSwitchInfo(Structure):
    _fields_ = [("writer_info", c_ubyte * 16), ("switch_info", StructSwitch)]


class StructWriterInfo(Structure):
    _fields_ = [("writer_info", c_ubyte * 16)]


class StructPort(Structure):
    _fields_ = [("dp_id", c_int), ("ofproto", c_char_p), ("config", c_short), ("state", c_short), ("port_no", c_short),
                ("hw_addr", c_char_p), ("name", c_char_p), ("is_live", c_bool), ("operation", c_short)]


class StructLink(Structure):
    _fields_ = [("src_dp_id", c_int), ("src_port_no", c_short), ("dst_dp_id", c_int), ("dst_port_no", c_short),
                ("operation", c_bool)]


class StructHost(Structure):
    _fields_ = [("dp_id", c_int), ("port_no", c_short), ("mac", c_char_p), ("ipv4", c_char_p), ("ipv6", c_char_p),
                ("operation", c_bool)]


def _get_exp_info() -> GraphInfo:
    response = requests.get("http://localhost:9000/exp_info")
    return pickle.loads(response.content)


def _get_all_links():
    response = requests.get("http://localhost:9002/all_links")
    return pickle.loads(response.content)


# Serving static files
class GUIServerApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # _CONTEXTS = {
    #     'wsgi': WSGIApplication
    # }

    def __init__(self, *args, **kwargs):
        super(GUIServerApp, self).__init__(*args, **kwargs)
        time.sleep(3)
        # wsgi = kwargs['wsgi']
        # wsgi.register(GUIServerController)
        # mine
        self.mac_to_port = {}
        self.arp_received = {}
        self.arp_port = {}
        self.datapaths = {}

        # distribution
        self.controller_id = self.CONF.controller_id
        self.controller_enter()
        self.dpid_to_port = GUIServerApp.parse_links(_get_all_links())
        self.update_time_info = []
        self.server_thr = hub.spawn(self.run_server)
        self.server_time = time.time()

        # route
        # self.query_trees_thr = hub.spawn(self.query_trees)
        self.node_installed_entries = set()

        self.lib = ctypes.cdll.LoadLibrary("./libDDSAPP.so")
        self.global_topo = {"controllers": [], "switches": [], "ports": [], "links": [], "hosts": []}
        self.pub_time_info = {"switches": {}, "ports": {}, "links": {}, "hosts": {}}
        self.sub_time_info = {"switches": {}, "ports": {}, "links": {}, "hosts": {}}
        self.switch_service = lookup_service_brick("switches")
        # 定义返回类型的数据类型
        self.lib.subscribeSwitchInfo.restype = StructSwitchInfo
        self.lib.subscribePort.restype = StructPort
        self.lib.subscribeLink.restype = StructLink
        self.lib.subscribeHost.restype = StructHost
        self.lib.getMatchedChange.restype = StructWriterInfo
        self.lib.matchNewSubscription.restype = c_bool
        self.sub_switch_thr = hub.spawn(self.sub_switch_threading)
        self.sub_port_thr = hub.spawn(self.sub_port_threading)
        self.sub_link_thr = hub.spawn(self.sub_link_threading)
        self.sub_host_thr = hub.spawn(self.sub_host_threading)
        self.sub_writer_thr = hub.spawn(self.sub_writer)
        self.sub_match_others = hub.spawn(self.new_controller_enter_threading)
        self.is_active = True
        self.controller_id = self.CONF.controller_id
        self.topo_file = f"topo-{self.controller_id}.json"
        self.hw_addr_to_sw_port = {}  # hw_addr(str) -> sw-port(str)
        # self.heat_beat_thr = hub.spawn(self.heat_beat_update)
        self.heatbeat_dds_thr = hub.spawn(self.heartbeat_by_dds)

        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        print(f"cid({self.controller_id}) exit")
        # with open(f'pub_time_info{self.controller_id}.json', 'w') as json_file:
        #     json.dump(self.pub_time_info, json_file, indent=4)
        # with open(f'sub_time_info{self.controller_id}.json', 'w') as json_file:
        #     json.dump(self.sub_time_info, json_file, indent=4)
        with open(f'update_time_info{self.controller_id}', 'w') as f:
            for t1, t2 in self.update_time_info:
                f.write(f"{t1}, {t2}\n")
        print("dump time info ok.")
        hub.spawn(self.controller_leave)

    def controller_enter(self):
        requests.get(f"http://localhost:9002/enter?cid={self.controller_id}")

    def controller_leave(self):
        requests.get(f"http://localhost:9002/leave?cid={self.controller_id}")

    @staticmethod
    def parse_links(links):
        dpid_to_port = {}
        for link in links:
            src_dpid, src_port_no = int(link["src"]["dpid"], 16), int(link["src"]["port_no"], 16)
            dst_dpid, dst_port_no = int(link["dst"]["dpid"], 16), int(link["dst"]["port_no"], 16)
            dpid_to_port[(src_dpid, dst_dpid)] = src_port_no
            dpid_to_port[(dst_dpid, src_dpid)] = dst_port_no
        return dpid_to_port

    @cherrypy.expose
    def update(self, t1):
        t2 = time.time()
        t1 = float(t1)
        print(t2 - t1)
        self.update_time_info.append((t2 - self.server_time, t2 - t1))

    def heat_beat_update(self):
        while self.is_active:
            self.send_update()
            time.sleep(1)

    def send_update(self):
        for i in range(1, 2 + 1):
            if i == self.controller_id:
                continue
            t1 = time.time()
            requests.get(f"http://localhost:{10000 + i}/update?t1={t1}")

    def run_server(self):
        cherrypy.config.update({'server.socket_port': 10000 + self.controller_id})
        cherrypy.quickstart(self)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [HANDSHAKE_DISPATCHER, CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error_msg_handler(self, ev):
        msg = ev.msg
        self.logger.error('OFPErrorMsg received: type=0x%02x code=0x%02x message=%s',
                          msg.type, msg.code, utils.hex_array(msg.data))

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match, instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    def send_packet_out(self, datapath, msg, actions):
        data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
        out = datapath.ofproto_parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                                   in_port=msg.match['in_port'], actions=actions, data=data)
        datapath.send_msg(out)

    def arp_flow_and_forward(self, datapath, msg, in_port, out_port, eth_pkt):
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(out_port)]
        self.send_packet_out(datapath, msg, actions)

    def handle_arp(self, datapath, msg, arp_pkt, eth_pkt, in_port):
        dpid = datapath.id
        ofproto = datapath.ofproto
        arp_key = (dpid, arp_pkt.src_mac, arp_pkt.dst_ip)

        self.arp_received.setdefault(arp_key, False)
        if not self.arp_received[arp_key]:
            self.arp_received[arp_key] = True
            self.arp_port[arp_key] = in_port
        elif self.arp_received[arp_key] and self.arp_port[arp_key] != in_port:
            return

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][arp_pkt.src_mac] = in_port
        out_port = self.mac_to_port[dpid].get(arp_pkt.dst_mac, ofproto.OFPP_FLOOD)

        self.arp_flow_and_forward(datapath, msg, in_port, out_port, eth_pkt)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes", ev.msg.msg_len, ev.msg.total_len)

        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth.ethertype == ether_types.ETH_TYPE_IPV6:
            return
        elif eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        elif eth.ethertype == ether_types.ETH_TYPE_ARP:
            self.logger.debug("ARP processing")
            arp_pkt = pkt.get_protocol(arp.arp)
            self.handle_arp(datapath, msg, arp_pkt, eth, in_port)

        elif eth.ethertype == ether_types.ETH_TYPE_IP:
            if dpid not in self.mac_to_port:
                return
            if eth.dst in self.mac_to_port[dpid]:
                # Normal flows
                out_port = self.mac_to_port[dpid][eth.dst]
                actions = [parser.OFPActionOutput(out_port)]
                self.send_packet_out(datapath, msg, actions)

    def clear_flow_and_group_entries(self, dpid, gpid):
        # self.show_flow_entries(dpid)
        dp = self.datapaths[dpid]
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # 构建删除流表项的请求
        match = parser.OFPMatch()
        mod = parser.OFPFlowMod(
            datapath=dp,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            priority=0,
            match=match,
            instructions=[]
        )
        dp.send_msg(mod)

        # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER)]
        self.add_flow(dp, 0, match, actions)

        # 构建组表项删除请求
        group_id = gpid
        req = parser.OFPGroupMod(dp, command=ofp.OFPGC_DELETE, type_=ofp.OFPGT_ALL, group_id=group_id, buckets=[])
        dp.send_msg(req)

        # print(f"cleared flow & group entries for dpid={dpid}")
        # self.show_flow_entries(dpid)

    def query_trees(self):
        hub.sleep(20)
        while self.is_active:
            print("querying latest routing trees >> ")
            response = requests.get(f"http://localhost:9002/trees?cid={self.controller_id}")
            trees, multicast_info = pickle.loads(response.content)
            print(f"\ttrees: {trees}, multicast info: {multicast_info}")
            self.install_routing_trees(trees, multicast_info)
            hub.sleep(5)

    def clear_entries(self, routing_trees, info: MulticastInfo):
        for src, tree in routing_trees.items():
            gpid = info.src_to_group_no[src]
            for n in tree.nodes:
                self.clear_flow_and_group_entries(n, gpid)

    def install_routing_trees(self, trees, info: MulticastInfo):
        output = {}
        for src in trees:
            group_id = info.src_to_group_no[src]
            multicast_ip = info.src_to_group_ip[src]
            tree = trees[src]

            # install group table and flow entry for sw -> sw
            self.install_routing_tree(tree, src, info.s2r[src], group_id, multicast_ip)

            # log info
            # graph_string = "\nDirected Graph:\n"
            # output[src] = []
            # for edge in tree.edges():
            #     graph_string += f"{edge[0]} -> {edge[1]};\n"
            #     output[src].append(f"{edge[0]}-{edge[1]}")
            # self.logger.info(f"the routing tree of {src} is {graph_string}")

        # dump routing trees to file.
        # with open('routing_trees.json', 'w') as json_file:
        #     json.dump(output, json_file, indent=4)

    def install_routing_tree(self, tree, cur_node, recvs, group_id, multicast_ip):
        succ = list(tree.successors(cur_node))

        if len(succ) > 0:
            out_ports = [self.dpid_to_port[(cur_node, next_node)] for next_node in succ]
            if cur_node in recvs:
                out_ports.append(1)

            if cur_node in self.datapaths:
                self.logger.info("installing group table and flow to %s", cur_node)
                datapath = self.datapaths[cur_node]
                # self.clear_flow_and_group_entries(datapath.id, group_id)
                self.send_group_mod_flood(datapath, out_ports, group_id)
                self.add_flow_to_group_table(datapath, group_id, multicast_ip)

            for node in succ:
                self.install_routing_tree(tree, node, recvs, group_id, multicast_ip)
        elif len(succ) == 0 and cur_node in recvs and cur_node in self.datapaths:
            self.add_flow_to_connected_host(self.datapaths[cur_node], multicast_ip)

    def send_group_mod_flood(self, datapath, out_ports, group_id):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        buckets = [parser.OFPBucket(actions=[parser.OFPActionOutput(out_port)]) for out_port in out_ports]
        req = parser.OFPGroupMod(datapath, ofproto.OFPGC_ADD, ofproto.OFPGT_ALL, group_id, buckets)
        datapath.send_msg(req)

    def add_flow_to_group_table(self, datapath, group_id, multicast_ip):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(eth_type=0x800, ipv4_dst=multicast_ip)
        actions = [parser.OFPActionGroup(group_id=group_id)]
        self.add_flow(datapath, 1, match, actions)

    def add_flow_to_connected_host(self, datapath, multicast_ip):
        # self.logger.info("installing sw to host flow to %s", datapath.id)
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(eth_type=0x800, ipv4_dst=multicast_ip)
        actions = [parser.OFPActionOutput(1)]
        self.add_flow(datapath, 1, match, actions)

    # subscribe to controller exit
    def sub_writer(self):
        while 1:
            w = self.lib.getMatchedChange()
            identify = '.'.join(str(i) for i in w.writer_info)
            for i in range(len(self.global_topo["controllers"])):
                if self.global_topo["controllers"][i]["identify"] == identify:
                    self.global_topo["controllers"][i]["is_live"] = False
                    print("A controller exit.")
            time.sleep(10)

    # publish all local topo for new connected controller
    def pub_topo(self):
        swes = get_switch(self)
        t = time.time()
        for sw in swes:
            self.lib.publishSwitch(self.controller_id, sw.dp.id, len(sw.ports), True)
            self.pub_time_info['switches'][sw.dp.id] = t
            self.send_update()
            for port in sw.ports:
                version = bytes('v1.3', encoding='utf-8')
                hw_addr = bytes(port.hw_addr, encoding="utf-8")
                self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name, port.is_live(), True)
                self.pub_time_info['ports'][f'{port.dpid}-{port.port_no}'] = t
                self.send_update()
        links = get_link(self)
        for link in links:
            key = f"{link.src.dpid}:{link.src.port_no}-{link.dst.dpid}:{link.dst.port_no}"
            self.lib.publishLink(link.src.dpid, link.src.port_no, link.dst.dpid, link.dst.port_no, True)
            self.pub_time_info['links'][key] = t
            self.send_update()
        hosts = get_host(self)
        for host in hosts:
            mac = bytes(host.mac, encoding='utf-8')
            ipv4 = bytes(','.join(host.ipv4), encoding='utf-8')
            ipv6 = bytes(','.join(host.ipv6), encoding='utf-8')
            self.lib.publishHost(host.port.dpid, host.port.port_no, mac, ipv4, ipv6, True)
            self.pub_time_info['hosts'][host.mac] = t
            self.send_update()

    def heartbeat_by_dds(self):
        while self.is_active:
            tmp = bytes("00:00:00:00:00:00", encoding='utf-8')
            self.lib.publishHost(0, 0, tmp, tmp, tmp, True)
            self.send_update()
            time.sleep(1)

    # new data reader event from dds
    def new_controller_enter_threading(self):
        while 1:
            new = self.lib.matchNewSubscription()
            if new:
                self.pub_topo()
                print("new controller enter")
            time.sleep(1)

    # subscribe switches
    def sub_switch_threading(self):
        while 1:
            switch_data = self.lib.subscribeSwitchInfo()
            sub_time = time.time()
            if switch_data.switch_info.controller_id != 0:
                # sw enter
                if switch_data.switch_info.operation:
                    identify = '.'.join(str(i) for i in switch_data.writer_info)
                    temp_controller = {"identify": identify, "c_id": switch_data.switch_info.controller_id, "is_live": True}
                    updated = False
                    for c in self.global_topo["controllers"]:
                        if c["c_id"] == temp_controller["c_id"]:
                            c["identify"], c["is_live"] = temp_controller["identify"], True
                            updated = True
                    if not updated:
                        self.global_topo["controllers"].append(temp_controller)
                    temp_switch = {"c_id": switch_data.switch_info.controller_id, "dp_id": switch_data.switch_info.dp_id, "port_num": switch_data.switch_info.port_num}
                    if temp_switch not in self.global_topo["switches"]:
                        self.global_topo["switches"].append(temp_switch)
                        self.sub_time_info["switches"][switch_data.switch_info.dp_id] = sub_time
                # sw leave
                else:
                    for i in range(len(self.global_topo["switches"])):
                        if switch_data.switch_info.dp_id == self.global_topo["switches"][i]["dp_id"]:
                            del self.global_topo["switches"][i]
                            self.sub_time_info["switches"][switch_data.switch_info.dp_id] = sub_time
                            break
                    for port in reversed(self.global_topo["ports"]):
                        if switch_data.switch_info.dp_id == port["dp_id"]:
                            self.global_topo["ports"].remove(port)
                            self.sub_time_info["ports"][f"{switch_data.switch_info.dp_id}-{port['port_no']}"] = sub_time
                    for host in reversed(self.global_topo["hosts"]):
                        if switch_data.switch_info.dp_id == host["dp_id"]:
                            self.global_topo["ports"].remove(host)
                            self.sub_time_info["hosts"][host["mac"]] = sub_time
            time.sleep(0)

    def sub_port_threading(self):
        while 1:
            port_data = self.lib.subscribePort()
            sub_time = time.time()
            if port_data.dp_id != 0:
                if port_data.operation == 2:
                    temp_port = {"dp_id": port_data.dp_id, "port_no": port_data.port_no,
                                 "hw_addr": str(port_data.hw_addr, encoding="utf-8"),
                                 "name": str(port_data.name, encoding="utf-8"), "is_live": port_data.is_live,
                                 "ofproto": str(port_data.ofproto, encoding="utf-8"), "config": port_data.config,
                                 "state": port_data.state}
                    for i in range(len(self.global_topo["ports"])):
                        if self.global_topo["ports"][i]["dp_id"] == temp_port["dp_id"] and self.global_topo["ports"][i]["port_no"] == temp_port["port_no"]:
                            self.global_topo["ports"][i] = temp_port
                            self.sub_time_info["ports"][f"{port_data.dp_id}-{port_data.port_no}"] = sub_time
                            break

                elif port_data.operation == 0:
                    for i in range(len(self.global_topo["ports"])):
                        if self.global_topo["ports"][i]["dp_id"] == port_data.dp_id and self.global_topo["ports"][i]["port_no"] == port_data.port_no:
                            del self.global_topo["ports"][i]
                            break
                    for j in range(len(self.global_topo["switches"])):
                        if self.global_topo["switches"][j]["dp_id"] == port_data.dp_id:
                            self.global_topo["switches"][j]["port_num"] = self.global_topo["switches"][j]["port_num"] - 1
                            break
                    for host in self.global_topo["hosts"]:
                        if port_data.dp_id == host["dp_id"] and port_data.port_no == host["port_no"]:
                            self.global_topo["hosts"].remove(host)
                            break
                    self.sub_time_info["ports"][f"{port_data.dp_id}-{port_data.port_no}"] = sub_time

                elif port_data.operation == 1:
                    temp_port = {"dp_id": port_data.dp_id,
                                 "port_no": port_data.port_no,
                                 "hw_addr": str(port_data.hw_addr, encoding="utf-8"),
                                 "name": str(port_data.name, encoding="utf-8"),
                                 "is_live": port_data.is_live,
                                 "ofproto": str(port_data.ofproto, encoding="utf-8"),
                                 "config": port_data.config,
                                 "state": port_data.state}
                    if temp_port not in self.global_topo["ports"]:
                        self.global_topo["ports"].append(temp_port)
                        self.sub_time_info["ports"][f"{port_data.dp_id}-{port_data.port_no}"] = sub_time
                        self.hw_addr_to_sw_port[temp_port["hw_addr"]] = f"{temp_port['dp_id']}-{temp_port['port_no']}"
            time.sleep(0)

    def sub_link_threading(self):
        while 1:
            link_data = self.lib.subscribeLink()
            sub_time = time.time()
            if link_data.src_dp_id != 0:
                temp_link = {"src_dp_id": link_data.src_dp_id, "src_port_no": link_data.src_port_no,
                             "dst_dp_id": link_data.dst_dp_id, "dst_port_no": link_data.dst_port_no}
                key = f"{link_data.src_dp_id}:{link_data.src_port_no}-{link_data.dst_dp_id}:{link_data.dst_port_no}"
                if link_data.operation:
                    if temp_link not in self.global_topo["links"]:
                        self.global_topo["links"].append(temp_link)
                        self.sub_time_info["links"][key] = sub_time
                else:
                    self.global_topo["links"].remove(temp_link)
                    self.sub_time_info["links"][key] = sub_time
            time.sleep(0)

    def sub_host_threading(self):
        while 1:
            host_data = self.lib.subscribeHost()
            sub_time = time.time()
            if host_data.dp_id != 0:
                if host_data.operation:
                    temp_host = {"dp_id": host_data.dp_id, "port_no": host_data.port_no, "mac": str(host_data.mac, encoding="utf-8"), "ipv4": str(host_data.ipv4, encoding="utf-8"), "ipv6": str(host_data.ipv6, encoding="utf-8")}
                    if temp_host not in self.global_topo["hosts"]:
                        self.global_topo["hosts"].append(temp_host)
                        self.sub_time_info['hosts'][temp_host['mac']] = sub_time
                        if temp_host["mac"] in self.hw_addr_to_sw_port:
                            dpid = int(self.hw_addr_to_sw_port[temp_host["mac"]].split('-')[0])
                            port = int(self.hw_addr_to_sw_port[temp_host["mac"]].split('-')[1])
                            link = {"src_dp_id": dpid, "src_port_no": port, "dst_dp_id": temp_host["dp_id"], "dst_port_no": temp_host["port_no"]}
                            rev_link = {"dst_dp_id": dpid, "dst_port_no": port, "src_dp_id": temp_host["dp_id"], "src_port_no": temp_host["port_no"]}
                            self.global_topo['links'].append(link)
                            self.global_topo['links'].append(rev_link)
            time.sleep(0)

    @handler.set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        LOG.debug(ev)
        t = time.time()
        self.pub_time_info["switches"][ev.switch.dp.id] = t
        self.send_update()
        self.lib.publishSwitch(self.controller_id, ev.switch.dp.id, len(ev.switch.ports), True)
        for port in ev.switch.ports:
            version = bytes('v1.3', encoding='utf-8')
            hw_addr = bytes(port.hw_addr, encoding="utf-8")
            self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                                 port.is_live(), True)
            self.pub_time_info["ports"][f"{port.dpid}-{port.port_no}"] = t
            self.send_update()

    @handler.set_ev_cls(event.EventSwitchLeave)
    def switch_leave_handler(self, ev):
        LOG.debug(ev)
        self.pub_time_info["switches"][ev.switch.dp.id] = time.time()
        self.send_update()
        self.lib.publishSwitch(self.controller_id, ev.switch.dp.id, len(ev.switch.ports), False)

    @handler.set_ev_cls(event.EventPortAdd)
    def port_add_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"][f'{port.dpid}-{port.port_no}'] = time.time()
        self.send_update()
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name, port.is_live(), 1)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventPortDelete)
    def port_delete_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"][f'{port.dpid}-{port.port_no}'] = time.time()
        self.send_update()
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name, port.is_live(), 0)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventPortModify)
    def port_modify_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"][f'{port.dpid}-{port.port_no}'] = time.time()
        self.send_update()
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name, port.is_live(), 2)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        key = f"{ev.link.src.dpid}:{ev.link.src.port_no}-{ev.link.dst.dpid}:{ev.link.dst.port_no}"
        self.pub_time_info["links"][key] = time.time()
        self.send_update()
        self.lib.publishLink(ev.link.src.dpid, ev.link.src.port_no, ev.link.dst.dpid, ev.link.dst.port_no, True)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventLinkDelete)
    def link_del_handler(self, ev):
        key = f"{ev.link.src.dpid}:{ev.link.src.port_no}-{ev.link.dst.dpid}:{ev.link.dst.port_no}"
        self.pub_time_info["links"][key] = time.time()
        self.send_update()
        self.lib.publishLink(ev.link.src.dpid, ev.link.src.port_no, ev.link.dst.dpid, ev.link.dst.port_no, False)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventHostAdd)
    def host_add_handler(self, ev):
        mac = bytes(ev.host.mac, encoding='utf-8')
        ipv4 = bytes(','.join(ev.host.ipv4), encoding='utf-8')
        ipv6 = bytes(','.join(ev.host.ipv6), encoding='utf-8')
        self.pub_time_info["hosts"][ev.host.mac] = time.time()
        self.send_update()
        self.lib.publishHost(ev.host.port.dpid, ev.host.port.port_no, mac, ipv4, ipv6, True)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventHostMove)
    def host_move_handler(self, ev):
        print("host move")
        # print(ev.host)

    @handler.set_ev_cls(event.EventHostDelete)
    def host_delete_handler(self, ev):
        print("host delete")
        # print(ev.host)


# app_manager.require_app('ryu.app.rest_topology')
app_manager.require_app('ryu.app.ofctl_rest')
