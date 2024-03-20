import logging
import os
import pickle
import signal

import requests

from ryu.app.distribution.web_app import GUIServerController
from ryu.app.wsgi import WSGIApplication
from ryu.lib import hub
from ryu import utils
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER, HANDSHAKE_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib.packet import packet, ether_types, arp, ethernet
from prepare1_graph_info import GraphInfo, MulticastInfo
from ryu.ofproto import ofproto_v1_3, ofproto_v1_5

PATH = os.path.dirname(__file__)
LOG = logging.getLogger(__name__)


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

        # route
        self.query_trees_thr = hub.spawn(self.query_trees)
        self.node_installed_entries = set()

        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        print(f"cid({self.controller_id}) exit")
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


# app_manager.require_app('ryu.app.rest_topology')
app_manager.require_app('ryu.app.ofctl_rest')
