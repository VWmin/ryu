import copy

import networkx as nx
import time

import numpy as np
from networkx.algorithms.approximation import steinertree

from math import inf

from ryu.app.distribution.route import full_pll


# from relavence_matrix import KMB


class HeatDegreeBase:
    def __init__(self, g: nx.graph, delay_limit, bandwidth_require, src2recv, routing_trees, use_pll):
        self.g = g
        self.delay_limit = delay_limit
        self.bandwidth_require = bandwidth_require
        self.src2recv = src2recv
        self.routing_trees = routing_trees
        self.relevance = None
        self.heat = None
        self.use_pll = use_pll  # enable fpll query
        self.__fpll__ = None  # for fpll query
        self.__distance__ = None  # for floyd query
        self.op_history = []
        self.__max_delay__ = max(dict(self.g.edges).items(), key=lambda x: x[1]['weight'])[1]['weight']
        self.build_relevance()
        self.build_heat_matrix()

    def build_relevance(self):
        t1 = time.time()
        n = self.g.number_of_nodes()
        self.relevance = [[dict() for _ in range(n)] for _ in range(n)]

        for i, j in self.g.edges:
            i, j = (j, i) if i > j else (i, j)
            for s in self.src2recv:
                for r in self.src2recv[s]:
                    estimated = self.get_estimate(s, r, i, j)
                    if estimated <= self.delay_limit[s]:
                        self.inc_relevance(s, i, j)
        self.op_history.append(("build_relevance", time.time() - t1))

    def inc_relevance(self, s, i, j):
        if s not in self.relevance[i][j]:
            self.relevance[i][j][s] = 1
        else:
            self.relevance[i][j][s] = self.relevance[i][j][s] + 1

    def dec_relevance(self, s, i, j):
        if s not in self.relevance[i][j]:
            return
        self.relevance[i][j][s] = self.relevance[i][j][s] - 1

    def get_estimate(self, s, r, i, j):
        if s == i or s == j:
            return self.g[i][j]['weight'] + min(self.query(i, r), self.query(j, r))
        elif r == i or r == j:
            return self.g[i][j]['weight'] + min(self.query(i, s), self.query(j, s))
        else:
            return self.query(s, i) + self.g[i][j]['weight'] + self.query(j, r)

    def update_heat_degree_ij(self, i, j):
        if not self.g.has_edge(i, j):
            return inf, inf, True
        # available: does this edge may congestion?
        _sum, available = self.check_bandwidth_limit(i, j)
        # a: heat degree if no congestion
        a = self.g[i][j]['weight'] / (self.g.number_of_nodes() * self.__max_delay__)
        # b: heat degree if may congestion
        b = pow(_sum / self.g[i][j]['bandwidth'], 2)
        return a, b, available

    def get_heat_degree_ij(self, s, i, j):
        i, j = (i, j) if i < j else (j, i)
        # (1) 边ij是s的候选边
        if s in self.relevance[i][j]:
            # (2) 在以s为源的现存多播树中
            in_routing_tree = self.is_routing_contains_edge(s, i, j)
            # (3) 不在以r为源的现存多播树中，但边ij的带宽满足所有以其为候选边的源的带宽要求之和
            edge_available = self.heat[i][j][2]
            if in_routing_tree or edge_available:
                return self.heat[i][j][0]  # (1) and ((2) or (3))
            else:
                return self.heat[i][j][1]  # (1)
        # (4) 边ij不是s的候选边
        else:
            return inf  # (4)

    def is_routing_contains_edge(self, s, u, v) -> bool:
        if s not in self.routing_trees:
            return False
        if isinstance(self.routing_trees[s], nx.Graph):
            return self.routing_trees[s].has_edge(u, v) or self.routing_trees[s].has_edge(v, u)
        else:
            for recv in self.routing_trees[s]:
                path = self.routing_trees[s][recv]
                for i in range(1, len(path)):
                    a, b = path[i - 1], path[i]
                    if (a, b) == (u, v) or (b, a) == (u, v):
                        return True
            return False

    def check_bandwidth_limit(self, u, v):
        u, v = (v, u) if u > v else (u, v)
        _sum = 0
        for s in self.relevance[u][v]:
            _sum += self.bandwidth_require[s]
        return _sum, _sum <= self.g[u][v]['bandwidth']

    def build_heat_matrix(self):
        t1 = time.time()
        n = self.g.number_of_nodes()
        self.heat = [[self.update_heat_degree_ij(i, j) for j in range(n)] for i in range(n)]
        self.op_history.append(("build_heat_matrix", time.time() - t1))

    def query(self, u, v):
        if self.use_pll:
            return self._pll_query(u, v)
        else:
            return self._distance_query(u, v)

    def enable_fpll(self):
        self.use_pll = True

    def enable_floyd(self):
        self.use_pll = False

    def _pll_query(self, u, v):
        if self.__fpll__ is None:
            t1 = time.time()
            self.__fpll__ = full_pll.FullPLL(self.g)
            self.op_history.append(("build_full_pll", time.time() - t1))
        return self.__fpll__.query(u, v)

    def _distance_query(self, u, v):
        if self.__distance__ is None:
            t1 = time.time()
            self.__distance__ = nx.floyd_warshall_numpy(self.g, nodelist=range(self.g.number_of_nodes()))
            # self.__distance__ = general_floyd(self.g)
            # self.__distance__ = general_floyd2(self.g)
            self.op_history.append(("build_floyd_distance", time.time() - t1))
        return self.__distance__[u][v]

    def statistic(self):
        for op, t in self.op_history:
            print(f"operation: {op:<20} \t\t cost: {round(t, 4)}s")

    def init_time(self):
        return sum(map(lambda e: e[1], self.op_history))

    def heat_graph(self, s):
        g = copy.deepcopy(self.g)
        g.remove_node(0)
        for u, v in self.g.edges:
            g[u][v]['weight'] = self.get_heat_degree_ij(s, u, v)
        return g


def general_floyd(G: nx.Graph):
    A = nx.to_numpy_array(
        G, None, multigraph_weight=min, nonedge=np.inf
    )
    n, m = A.shape
    np.fill_diagonal(A, 0)
    for k in range(n):
        for i in range(n):
            for j in range(n):
                A[i][j] = min(A[i][j], A[i][k] + A[k][j])
    # for i in range(n):
    #     # The second term has the same shape as A due to broadcasting
    #     A = np.minimum(A, A[i, :][np.newaxis, :] + A[:, i][:, np.newaxis])
    return A


def general_floyd2(G: nx.Graph, weight="weight"):
    from collections import defaultdict

    # dictionary-of-dictionaries representation for dist and pred
    # use some defaultdict magick here
    # for dist the default is the floating point inf value
    dist = defaultdict(lambda: defaultdict(lambda: float("inf")))
    for u in G:
        dist[u][u] = 0
    # initialize path distance dictionary to be the adjacency matrix
    # also set the distance to self to 0 (zero diagonal)
    undirected = not G.is_directed()
    for u, v, d in G.edges(data=True):
        e_weight = d.get(weight, 1.0)
        dist[u][v] = min(e_weight, dist[u][v])
        if undirected:
            dist[v][u] = min(e_weight, dist[v][u])
    for w in G:
        dist_w = dist[w]  # save recomputation
        for u in G:
            dist_u = dist[u]  # save recomputation
            for v in G:
                d = dist_u[w] + dist_w[v]
                if dist_u[v] > d:
                    dist_u[v] = d
    return dict(dist)


class HeatDegreeModel:
    def __init__(self, g: nx.graph, delay_limit, bandwidth_require, src2recv):
        self.g = g
        self.delay_limit = delay_limit
        self.bandwidth_require = bandwidth_require
        self.src2recv = src2recv
        self.routing_trees = {}
        self.op_history = []
        self._heat_base = HeatDegreeBase(self.g, self.delay_limit, self.bandwidth_require,
                                         self.src2recv, self.routing_trees, True)
        self.__routing__()

    def __routing__(self):
        t1 = time.time()
        for s in self.src2recv:
            terminals = list(self.src2recv[s]) + [s]
            # g = copy.deepcopy(self.g)
            # g.remove_node(0)
            g = self._heat_base.heat_graph(s)
            ts = steinertree.steiner_tree(g, terminals)
            # ts = KMB(self.g, list(self.src2recv[s]) + [s], weight=lambda u, v, d: self._heat_base.get_heat_degree_ij(s, u, v))
            self.routing_trees[s] = nx.DiGraph()
            convert_routing_tree_to_digraph(ts, self.routing_trees[s], s, None)

        self.op_history.append(("routing", time.time() - t1))

    # def __single_source_routing__(self, s, r):
    #     _, path = nx.single_source_dijkstra(self.g, s, target=r,
    #                                         weight=lambda u, v, d: self._heat_base.get_heat_degree_ij(s, u, v))
    #     self.routing_trees[s][r] = path

    def print_heat_graph(self, s):
        labels = {}
        for u, v in self.g.edges:
            labels[u, v] = round(self._heat_base.get_heat_degree_ij(s, u, v), 2)
        from ryu.app.distribution import random_graph
        random_graph.print_graph_with_labels(self.g, labels)

    def add_recv(self, s, r):
        t1 = time.time()
        self.src2recv[s].add(r)
        updated = set()
        for u, v in self.g.edges:
            u, v = (v, u) if u > v else (u, v)
            estimated = self._heat_base.get_estimate(s, r, u, v)
            if estimated <= self.delay_limit[s]:
                self._heat_base.inc_relevance(s, u, v)
                updated.add((u, v))
        need_refactor = set()
        for u, v in updated:
            self._heat_base.heat[u][v] = self._heat_base.update_heat_degree_ij(u, v)
            for may_congested in self.src2recv:
                if not self._heat_base.heat[u][v][2] and self._heat_base.is_routing_contains_edge(may_congested, u, v):
                    need_refactor.add(may_congested)
        for to_refactor_s in need_refactor:
            terminals = list(self.src2recv[to_refactor_s]) + [to_refactor_s]
            # g = copy.deepcopy(self.g)
            # g.remove_node(0)
            g = self._heat_base.heat_graph(to_refactor_s)
            ts = steinertree.steiner_tree(g, terminals)
            self.routing_trees[to_refactor_s] = nx.DiGraph()
            convert_routing_tree_to_digraph(ts, self.routing_trees[to_refactor_s], to_refactor_s, None)
        self.op_history.append(("add_recv", time.time() - t1))

    def remove_recv(self, s, r):
        t1 = time.time()
        if s not in self.src2recv or r not in self.src2recv[s]:
            return
        self._remove_recv_from_routing_trees(s, r)
        updated = set()
        for u, v in self.g.edges:
            u, v = (v, u) if u > v else (u, v)
            estimated = self._heat_base.get_estimate(s, r, u, v)
            if estimated <= self.delay_limit[s]:
                self._heat_base.dec_relevance(s, u, v)
                if self._heat_base.relevance[u][v] == 0:
                    updated.add((u, v))
        for u, v in updated:
            self._heat_base.heat[u][v] = self._heat_base.update_heat_degree_ij(u, v)
        self.op_history.append(("remove_recv", time.time() - t1))

    def _remove_recv_from_routing_trees(self, s, r):
        self.src2recv[s].remove(r)
        terminals = self.src2recv[s] | {s}
        node = r
        while (self.routing_trees[s].has_node(node)
               and self.routing_trees[s].degree(node) == 1
               and node not in terminals):
            next_node = next(self.routing_trees[s].neighbors(node))
            self.routing_trees[s].remove_node(node)
            node = next_node

    def change_delay(self, a, b, new_val):
        t1 = time.time()
        if not self.g.has_edge(a, b):
            return
        raw_val = self.g[a][b]['weight']
        self._heat_base.__fpll__.change_edge_weight(a, b, new_val)
        if new_val < raw_val:
            # 延迟减少，原多播树依然满足
            return

        # 原本满足更新后不满足的侯选边集合
        updated = {}

        # 查看之前作为候选边的边，是否在修改后仍是侯选边
        for u, v in self.g.edges:
            u, v = (v, u) if v < u else (u, v)
            if len(self._heat_base.relevance[u][v]) != 0:
                for s in list(self._heat_base.relevance[u][v].keys()):
                    self._heat_base.relevance[u][v][s] = 0
                    for r in self.src2recv[s]:
                        estimated = self._heat_base.get_estimate(s, r, u, v)
                        if estimated <= self.delay_limit[s]:
                            self._heat_base.inc_relevance(s, u, v)
                    if self._heat_base.relevance[u][v][s] == 0:
                        updated[u, v] = updated.get((u, v), [])
                        updated[u, v].append(s)
                        del self._heat_base.relevance[u][v][s]

        # 需要重建多播树的源节点集合
        need_refactor = set()

        # 如果(u, v)曾在s的多播树中，且现在可能拥塞或是不再作为侯选边，那么需要重构以s为源的多播树
        for u, v in updated:
            self._heat_base.heat[u][v] = self._heat_base.update_heat_degree_ij(u, v)
            for s in updated[u, v]:
                if ((not self._heat_base.heat[u][v][2] or s not in self._heat_base.relevance[u][v])
                        and self._heat_base.is_routing_contains_edge(s, u, v)):
                    need_refactor.add(s)

        for to_refactor_s in need_refactor:
            terminals = list(self.src2recv[to_refactor_s]) + [to_refactor_s]
            # g = copy.deepcopy(self.g)
            # g.remove_node(0)
            g = self._heat_base.heat_graph(to_refactor_s)
            ts = steinertree.steiner_tree(g, terminals)
            self.routing_trees[to_refactor_s] = nx.DiGraph()
            convert_routing_tree_to_digraph(ts, self.routing_trees[to_refactor_s], to_refactor_s, None)
        self.op_history.append(("change_delay", time.time() - t1))

    def statistic(self):
        print("mine statistic info >>> ")
        self._heat_base.statistic()
        for op, t in self.op_history:
            print(f"operation: {op:<20} \t\t cost: {round(t, 4)}s")

    def init_time(self):
        return self._heat_base.init_time() + self.last_time()

    def last_time(self):
        return self.op_history[-1][1]


def print_2d_array(array):
    for d1 in array:
        print(f"{d1}")
    print()


def convert_routing_tree_to_digraph(ts: nx.Graph, tree: nx.DiGraph, root, pre):
    while root:
        tree.add_node(root)
        if pre:
            tree.add_edge(pre, root)
        if ts.degree(root) == 1:
            _next = next(ts.neighbors(root))
            if _next == pre:
                break
            pre = root
            root = _next
        else:
            for _next in ts.neighbors(root):
                if _next != pre:
                    convert_routing_tree_to_digraph(ts, tree, _next, root)
            break
