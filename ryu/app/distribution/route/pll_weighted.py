import networkx as nx
from queue import PriorityQueue as PQ
from math import inf


def weighted_pll(G: nx.Graph):
    # G = nx.convert_node_labels_to_integers(G, ordering="decreasing degree")
    L = {v: dict() for v in G.nodes}
    for v in G.nodes:
        pruned_dijkstra(G, v, L)
    return L


def pruned_dijkstra(G: nx.Graph, vk, L):
    visited = {v: False for v in G.nodes}
    D = {v: inf for v in G.nodes}
    D[vk] = 0
    pq = PQ()
    pq.put((D[vk], vk))
    while not pq.empty():
        _, u = pq.get()
        if visited[u]:
            continue
        visited[u] = True
        if query_distance(L, vk, u) <= D[u]:
            continue
        L[u][vk] = D[u]
        for w in G.neighbors(u):
            if D[w] > D[u] + G[u][w]["weight"]:
                D[w] = D[u] + G[u][w]["weight"]
                pq.put((D[w], w))


def dijkstra(G: nx.Graph, s):
    visited = [False for _ in range(len(G.nodes))]
    d = [inf for _ in range(len(G.nodes))]
    d[s] = 0
    pq = PQ()
    pq.put((d[s], s))
    while not pq.empty():
        _, u = pq.get()
        if visited[u]:
            continue
        visited[u] = True
        for v in G.neighbors(u):
            duv = G[u][v]["weight"]
            if d[v] > d[u] + duv:
                d[v] = d[u] + duv
                pq.put((d[v], v))
    return d


def query_distance(labels, u, v):
    if u not in labels or v not in labels:
        return inf
    distance = inf
    # k = labels[u].keys() & labels[v].keys()
    # for landmark in k:
    #     distance = min(distance, labels[u][landmark] + labels[v][landmark])
    # return distance
    for x in labels[v]:
        if x in labels[u]:
            distance = min(distance, labels[u][x] + labels[v][x])
    return distance


def find_hub(labels, u, v):
    return labels[u].keys() & labels[v].keys()
