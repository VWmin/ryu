import argparse
import ctypes
import json
import logging
import os
import threading
import time

from ctypes import *
from ryu.app.wsgi import WSGIApplication
import networkx as nx
import requests
from ryu.lib import hub
from ryu import utils, cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event, handler
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER, HANDSHAKE_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser
from ryu.lib.packet import packet, ether_types, arp, ethernet, ipv4, lldp
from ryu.topology import switches, event
from ryu.topology.api import get_switch, get_link, get_host

from distribution.web_app import GUIServerController

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


# Serving static files
class GUIServerApp(app_manager.RyuApp):
    _CONTEXTS = {
        'wsgi': WSGIApplication,
    }

    def __init__(self, *args, **kwargs):
        super(GUIServerApp, self).__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        wsgi.register(GUIServerController)
        # mine
        self.mac_to_port = {}
        self.arp_received = {}
        self.arp_port = {}
        self.datapaths = {}
        self.echo_delay = {}
        self.link_delay = {}
        # self.experiment_info = _get_exp_info()
        # self.network = self.experiment_info.graph
        # self.network.add_node(0)  # dummy node
        self.lock = threading.Lock()
        self.switch_service = lookup_service_brick("switches")
        # self.monitor_thread = hub.spawn(self._monitor)
        # self.experimental_thread = hub.spawn(self.run_experiment)
        self.link_flag = False
        # distribution
        self.lib = ctypes.cdll.LoadLibrary("./libDDSAPP.so")
        self.global_topo = {"controllers": [], "switches": [], "ports": [], "links": [], "hosts": []}
        self.pub_time_info = {"switches": [], "ports": [], "links": [], "hosts": []}
        self.sub_time_info = {"switches": [], "ports": [], "links": [], "hosts": []}
        self.update_time_info = {"switches": [], "ports": [], "links": [], "hosts": []}
        # 定义返回类型的数据类型
        self.lib.subscribeSwitchInfo.restype = StructSwitchInfo
        self.lib.subscribePort.restype = StructPort
        self.lib.subscribeLink.restype = StructLink
        self.lib.subscribeHost.restype = StructHost
        self.lib.getMatchedChange.restype = StructWriterInfo
        self.lib.matchNewSubscription.restype = c_bool
        self.subSwitchThr = threading.Thread(target=self.sub_switch_threading, name='subSwitch')
        self.subPortThr = threading.Thread(target=self.sub_port_threading, name='subPort')
        self.subLinkThr = threading.Thread(target=self.sub_link_threading, name='subLink')
        self.subHostThr = threading.Thread(target=self.sub_host_threading, name='subHost')
        self.subW = threading.Thread(target=self.sub_writer, name='subw')
        self.matchOtherController = threading.Thread(target=self.new_controller_enter_threading, name='matchOtherController')
        self.subW.start()
        self.subHostThr.start()
        self.subPortThr.start()
        self.subLinkThr.start()
        self.subSwitchThr.start()
        self.matchOtherController.start()
        self.is_active = True
        self.controller_id = self.CONF.controller_id
        self.topo_file = f"topo-{self.controller_id}.json"

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

    def _monitor(self):
        while len(self.switch_service.link_delay) != len(self.network.edges):
            hub.sleep(10)
            self.logger.info(f"query links, expect {len(self.network.edges)}, "
                             f"now {len(self.switch_service.link_delay)}")
            self.lock.acquire()
            for link, delay in self.switch_service.link_delay.items():
                edge_key = (link.src.dpid, link.dst.dpid)
                if link.dst.dpid < link.src.dpid:
                    edge_key = (link.dst.dpid, link.src.dpid)

                # record dpid to port
                if 'dpid_to_port' not in self.network.edges[edge_key]:
                    self.network.edges[edge_key]['dpid_to_port'] = {
                        link.src.dpid: link.dst.port_no,
                        link.dst.dpid: link.src.port_no,
                    }

                # record delay time
                if edge_key not in self.link_delay:
                    self.link_delay[edge_key] = delay
                    self.network.edges[edge_key]['weight'] = delay

            self.lock.release()
        self.link_flag = True
        self.logger.info("monitor exit...")

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

    def sub_writer(self):
        while 1:
            w = self.lib.getMatchedChange()
            str1 = '.'.join(str(i) for i in w.writer_info)
            for i in range(len(self.global_topo["controllers"])):
                if self.global_topo["controllers"][i]["identify"] == str1:
                    self.global_topo["controllers"][i]["is_live"] = False
                    with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                        fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                    print("A controller exit.")
            time.sleep(10)

    # send all local topo
    def pub_topo(self):
        swes = get_switch(self)
        for sw in swes:
            self.lib.publishSwitch(self.controller_id, sw.dp.id, len(sw.ports), True)
            for port in sw.ports:
                version = bytes('v1.3', encoding='utf-8')
                hw_addr = bytes(port.hw_addr, encoding="utf-8")
                self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                                     port.is_live(), True)
        links = get_link(self)
        # print(links)
        for link in links:
            self.lib.publishLink(link.src.dpid, link.src.port_no, link.dst.dpid, link.dst.port_no, True)
        hosts = get_host(self)
        # print(hosts)
        for host in hosts:
            mac = bytes(host.mac, encoding='utf-8')
            ipv4 = bytes(','.join(host.ipv4), encoding='utf-8')
            ipv6 = bytes(','.join(host.ipv6), encoding='utf-8')
            self.lib.publishHost(host.port.dpid, host.port.port_no, mac, ipv4, ipv6, True)

    def new_controller_enter_threading(self):
        while 1:
            new = self.lib.matchNewSubscription()
            if new:
                self.pub_topo()
            time.sleep(1)

    def sub_switch_threading(self):
        while 1:
            switch_data = self.lib.subscribeSwitchInfo()
            sub_time = time.time()
            if switch_data.switch_info.controller_id != 0:
                if switch_data.switch_info.operation:
                    identify = '.'.join(str(i) for i in switch_data.writer_info)
                    temp_controller = {"identify": identify, "c_id": switch_data.switch_info.controller_id,
                                       "is_live": True}
                    if temp_controller not in self.global_topo["controllers"]:
                        self.global_topo["controllers"].append(temp_controller)
                    temp_switch = {"c_id": switch_data.switch_info.controller_id,
                                   "dp_id": switch_data.switch_info.dp_id, "port_num": switch_data.switch_info.port_num}
                    # temp_switch={"c_id":switch_data.switch_info.controller_id, "dp_id":switch_data.switch_info.dp_id}
                    if temp_switch not in self.global_topo["switches"]:
                        self.global_topo["switches"].append(temp_switch)
                        with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                            fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                        update_time = time.time()
                        self.sub_time_info["switches"].append(sub_time)
                        self.update_time_info["switches"].append(update_time)
                        # self.logger.info("switch_sub_time: %s", sub_time)
                        # self.logger.info("switch_update_time: %s", update_time)

                else:
                    for i in range(len(self.global_topo["switches"])):
                        if switch_data.switch_info.dp_id == self.global_topo["switches"][i]["dp_id"]:
                            del self.global_topo["switches"][i]
                            break

                    for port in reversed(self.global_topo["ports"]):
                        if switch_data.switch_info.dp_id == port["dp_id"]:
                            self.global_topo["ports"].remove(port)
                    for host in reversed(self.global_topo["hosts"]):
                        if switch_data.switch_info.dp_id == host["dp_id"]:
                            self.global_topo["ports"].remove(host)

                    with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                        fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                    update_time = time.time()
                    self.sub_time_info["switches"].append(sub_time)
                    self.update_time_info["switches"].append(update_time)
                    # self.logger.info("switch_sub_time: %s", sub_time)
                    # self.logger.info("switch_update_time: %s", update_time)

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
                            with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                                fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                            update_time = time.time()
                            self.sub_time_info["ports"].append(sub_time)
                            self.update_time_info["ports"].append(update_time)
                            break

                elif port_data.operation == 0:
                    for i in range(len(self.global_topo["ports"])):
                        if self.global_topo["ports"][i]["dp_id"] == port_data.dp_id and self.global_topo["ports"][i]["port_no"] == port_data.port_no:
                            del self.global_topo["ports"][i]
                            break
                    for j in range(len(self.global_topo["switches"])):
                        if self.global_topo["switches"][j]["dp_id"] == port_data.dp_id:
                            self.global_topo["switches"][j]["port_num"] = self.global_topo["switches"][j][
                                                                              "port_num"] - 1
                            break
                    for host in self.global_topo["hosts"]:
                        if port_data.dp_id == host["dp_id"] and port_data.port_no == host["port_no"]:
                            self.global_topo["hosts"].remove(host)
                            break
                    with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                        fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                    update_time = time.time()
                    self.sub_time_info["ports"].append(sub_time)
                    self.update_time_info["ports"].append(update_time)

                elif port_data.operation == 1:
                    temp_port = {"dp_id": port_data.dp_id, "port_no": port_data.port_no,
                                 "hw_addr": str(port_data.hw_addr, encoding="utf-8"),
                                 "name": str(port_data.name, encoding="utf-8"), "is_live": port_data.is_live,
                                 "ofproto": str(port_data.ofproto, encoding="utf-8"), "config": port_data.config,
                                 "state": port_data.state}
                    if temp_port not in self.global_topo["ports"]:
                        self.global_topo["ports"].append(temp_port)
                        with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                            fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                        update_time = time.time()
                        self.sub_time_info["ports"].append(sub_time)
                        self.update_time_info["ports"].append(update_time)

            time.sleep(0)

    def sub_link_threading(self):
        while 1:
            link_data = self.lib.subscribeLink()
            sub_time = time.time()
            if link_data.src_dp_id != 0:
                temp_link = {"src_dp_id": link_data.src_dp_id, "src_port_no": link_data.src_port_no,
                             "dst_dp_id": link_data.dst_dp_id, "dst_port_no": link_data.dst_port_no}
                if link_data.operation:
                    # temp_link={"src_dp_id":link_data.src_dp_id,"src_port_no":link_data.src_port_no,"dst_dp_id":link_data.dst_dp_id,"dst_port_no":link_data.dst_port_no}
                    if temp_link not in self.global_topo["links"]:
                        self.global_topo["links"].append(temp_link)
                        with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                            fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                        update_time = time.time()
                        self.sub_time_info["links"].append(sub_time)
                        self.update_time_info["links"].append(update_time)
                else:
                    self.global_topo["links"].remove(temp_link)
                    with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                        fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                    update_time = time.time()
                    self.sub_time_info["links"].append(sub_time)
                    self.update_time_info["links"].append(update_time)
            time.sleep(0)

    def sub_host_threading(self):
        while 1:
            host_data = self.lib.subscribeHost()
            sub_time = time.time()
            if host_data.dp_id != 0:
                if host_data.operation:
                    temp_host = {"dp_id": host_data.dp_id, "port_no": host_data.port_no,
                                 "mac": str(host_data.mac, encoding="utf-8"),
                                 "ipv4": str(host_data.ipv4, encoding="utf-8"),
                                 "ipv6": str(host_data.ipv6, encoding="utf-8")}
                    if temp_host not in self.global_topo["hosts"]:
                        self.global_topo["hosts"].append(temp_host)
                        with open(self.topo_file, 'w', encoding='UTF-8') as fp:
                            fp.write(json.dumps(self.global_topo, indent=2, ensure_ascii=False))
                        update_time = time.time()
                        self.sub_time_info["hosts"].append(sub_time)
                        self.update_time_info["hosts"].append(update_time)
            time.sleep(0)

    @handler.set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        # print(ev)
        # print(ev.switch)
        LOG.debug(ev)
        self.pub_time_info["switches"].append(time.time())
        self.lib.publishSwitch(self.controller_id, ev.switch.dp.id, len(ev.switch.ports), True)
        # self.pub_time_info["switches"].append(time.time())
        # switch_pub_time=time.time()
        # self.logger.info("switch_pub_time: %s", switch_pub_time)
        for port in ev.switch.ports:
            version = bytes('v1.3', encoding='utf-8')
            hw_addr = bytes(port.hw_addr, encoding="utf-8")
            self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                                 port.is_live(), True)
            # port_pub_time=time.time()
            self.pub_time_info["ports"].append(time.time())
        # self.logger.info("port_pub_time: %s", port_pub_time)

        # print("pub port")

    @handler.set_ev_cls(event.EventSwitchLeave)
    def switch_leave_handler(self, ev):
        self.pub_time_info["switches"].append(time.time())
        self.lib.publishSwitch(self.controller_id, ev.switch.dp.id, len(ev.switch.ports), False)
        # self.pub_time_info["switches"].append(time.time())
        # switch_pub_time=time.time()
        # self.logger.info("switch_leave_pub_time: %s", switch_pub_time)
        # print("switch leave")
        # print(ev.switch)
        # print(ev)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventPortAdd)
    def port_add_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"].append(time.time())
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                             port.is_live(), 1)
        # self.pub_time_info["ports"].append(time.time())
        # port_pub_time=time.time()
        # self.logger.info("port_add_pub_time: %s", port_pub_time)

        # print("port add ev")

        LOG.debug(ev)

    @handler.set_ev_cls(event.EventPortDelete)
    def port_delete_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"].append(time.time())
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                             port.is_live(), 0)
        # self.pub_time_info["ports"].append(time.time())
        # port_pub_time=time.time()
        # self.logger.info("port_delete_pub_time: %s", port_pub_time)
        # print("port delete")
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventPortModify)
    def port_modify_handler(self, ev):
        port = ev.port
        version = bytes('v1.3', encoding='utf-8')
        hw_addr = bytes(port.hw_addr, encoding="utf-8")
        self.pub_time_info["ports"].append(time.time())
        self.lib.publishPort(port.dpid, version, port._config, port._state, port.port_no, hw_addr, port.name,
                             port.is_live(), 2)
        # self.pub_time_info["ports"].append(time.time())
        # port_pub_time=time.time()
        # self.logger.info("port_modify_pub_time: %s", port_pub_time)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        self.pub_time_info["links"].append(time.time())
        self.lib.publishLink(ev.link.src.dpid, ev.link.src.port_no, ev.link.dst.dpid, ev.link.dst.port_no, True)
        # self.pub_time_info["links"].append(time.time())
        # pub_time=time.time()
        # self.logger.info("link_add_pub_time: %s", pub_time)
        # print(ev)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventLinkDelete)
    def link_del_handler(self, ev):
        self.pub_time_info["links"].append(time.time())
        self.lib.publishLink(ev.link.src.dpid, ev.link.src.port_no, ev.link.dst.dpid, ev.link.dst.port_no, False)
        # self.pub_time_info["links"].append(time.time())
        # pub_time=time.time()
        # self.logger.info("link_delete_pub_time: %s", pub_time)
        LOG.debug(ev)

    @handler.set_ev_cls(event.EventHostAdd)
    def host_add_handler(self, ev):
        mac = bytes(ev.host.mac, encoding='utf-8')
        ipv4 = bytes(','.join(ev.host.ipv4), encoding='utf-8')
        ipv6 = bytes(','.join(ev.host.ipv6), encoding='utf-8')
        # print(ev)
        self.pub_time_info["hosts"].append(time.time())
        self.lib.publishHost(ev.host.port.dpid, ev.host.port.port_no, mac, ipv4, ipv6, True)
        # self.pub_time_info["hosts"].append(time.time())
        LOG.debug(ev)
        # pub_time=time.time()
        # self.logger.info("host_add_pub_time: %s", pub_time)

    @handler.set_ev_cls(event.EventHostMove)
    def host_move_handler(self, ev):
        print("host move")
        # print(ev.host)

    @handler.set_ev_cls(event.EventHostDelete)
    def host_delete_handler(self, ev):
        print("host delete")
        # print(ev.host)
        # self.lib.publishHost(ev.host.port.dpid, ev.host.port.port_no, mac, ipv4, ipv6, False)

    @handler.set_ev_cls(event.EventSwitchReply)
    def switch_reply_handler(self, reply):
        LOG.debug('switch_reply async %s', reply)
        if len(reply.switches) > 0:
            for sw in reply.switches:
                LOG.debug('  %s', sw)

    @handler.set_ev_cls(event.EventLinkReply)
    def link_reply_handler(self, reply):
        LOG.debug('link_reply async %s', reply)
        if len(reply.links) > 0:
            for link in reply.links:
                LOG.debug('  %s', link)


app_manager.require_app('ryu.app.rest_topology')
app_manager.require_app('ryu.app.ofctl_rest')
