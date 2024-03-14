import copy
import random

import networkx as nx
from math import inf

from ryu.app.distribution.route import pll_weighted
from ryu.app.distribution.route.util import PriorityQueue


def affected(Gi: nx.Graph, raw_w, L, x, y):
    # d = nx.dijkstra_path_length
    d = pll_weighted.query_distance
    A, mark = set(), {}
    for v in Gi.nodes:
        mark[v] = False
    que, mark[x] = [x], True
    while len(que):
        v = que[0]
        que.pop(0)
        A.add(v)
        for u in Gi.neighbors(v):
            if not mark[u]:
                H = pll_weighted.find_hub(L, u, y)
                for h in H:
                    if (h in A) or ((h == u or h == y) and (d(L, u, y) == d(L, u, x) + raw_w)):
                        mark[u] = True
                        que.append(u)
                        break
    return A


def alternative_affected(Gi: nx.Graph, Gi_1: nx.Graph, L, x, y):
    d = nx.dijkstra_path_length
    A, mark = set(), {}
    for v in Gi.nodes:
        mark[v] = False
    que, mark[x] = [x], True
    while len(que):
        v = que[0]
        que.pop(0)
        A.add(v)
        for u in Gi.neighbors(v):
            if not mark[u]:
                if d(Gi, u, y) != d(Gi_1, u, y):
                    mark[u] = True
                    que.append(u)
                else:
                    h = min(list(pll_weighted.find_hub(L, u, y)))
                    if h in A or ((h == u or h == y) and d(Gi_1, u, y) == d(Gi_1, u, x) + Gi_1[x][y]['weight']):
                        mark[u] = True
                        que.append(u)
    return A


def remove_affected_labels(L, AX, AY):
    for v in AX:
        for u in AY:
            if u in L[v].keys():
                del L[v][u]
    for v in AY:
        for u in AX:
            if u in L[v].keys():
                del L[v][u]
    return L


def greedy_restore(G: nx.Graph, L, AX, AY):
    query = pll_weighted.query_distance
    SA, LA = AX, AY
    if len(AY) < len(AX):
        SA, LA = AY, AX
    for a in SA:
        visited, dist = {}, {}
        for v in G.nodes:
            visited[v], dist[v] = False, inf
        dist[a] = 0
        que = PriorityQueue()
        que.push((dist[a], a))
        while que.size() != 0:
            _, v = que.pop()
            if visited[v]:
                continue
            visited[v] = True
            if v in LA:
                if dist[v] < query(L, a, v):
                    if v < a:
                        L[a][v] = dist[v]
                    else:
                        L[v][a] = dist[v]
            for u in G.neighbors(v):
                if dist[u] > dist[v] + G[v][u]['weight']:
                    dist[u] = dist[v] + G[v][u]['weight']
                    que.push((dist[u], u))

    return L


def order_restore(G: nx.Graph, L, AX, AY):
    from pll_weighted import query_distance as d
    F = list(AX | AY)
    F.sort()
    for a in F:
        mark, dist = {}, {}
        for v in G.nodes:
            mark[v], dist[v] = False, inf
        que = PriorityQueue()
        que.push((0, a))
        mark[a], dist[a] = True, 0
        while que.size():
            _, v = que.pop()
            if v < a or mark[v]:
                continue
            mark[v] = True
            if (a in AX and v in AY) or (a in AY and v in AX):
                if dist[v] < d(L, a, v):
                    L[v][a] = dist[v]
            for u in G.neighbors(v):
                if dist[u] > dist[v] + G[u][v]['weight']:
                    dist[u] = dist[v] + G[u][v]['weight']
                    que.push((dist[u], u))
    return L


def dec_pll_w(g: nx.Graph, raw_w, x, y, l0):
    AX, AY = affected(g, raw_w, l0, x, y), affected(g, raw_w, l0, y, x)
    l1_no_affected = remove_affected_labels(l0, AX, AY)
    # l1 = order_restore(g, l1_no_affected, AX, AY)
    l1 = greedy_restore(g, l1_no_affected, AX, AY)
    return l1
