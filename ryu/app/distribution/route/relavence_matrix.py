import networkx as nx


def weight_function(G: nx.Graph, u, v, weight):
    if callable(weight):
        return weight(u, v, G[u][v])
    return G[u][v][weight]


def KMB(G: nx.Graph, terminals, weight='weight'):
    # 1. dis[s][r] <- dijsktra
    # dis = {}
    # for s in S2R:
    #     R = S2R[s]
    #     for r in R:
    #         dis[s][r] = nx.single_source_dijkstra(G, s, r)
    # 1. get G1
    # t0 = time.time()
    dis = {}
    G1 = nx.Graph()
    for i in range(len(terminals)):
        paths = nx.single_source_dijkstra(G, terminals[i], weight=weight)
        for j in range(i + 1, len(terminals)):
            ii, jj = terminals[i], terminals[j]
            if ii not in dis:
                dis[ii] = {}
            dis[ii][jj] = (paths[0][jj], paths[1][jj])
            G1.add_edge(ii, jj, weight=dis[ii][jj][0])

    # t1 = time.time()
    # print("G1 cost: ", t1 - t0)

    # 2. prime G1
    T1E = nx.minimum_spanning_edges(G1, data=False)
    # t2 = time.time()
    # print("prime G1 cost: ", t2 - t1)

    # 3. recover Gs
    Gs = nx.Graph()
    for edge in list(T1E):
        i, j = edge
        path = dis[i][j][1]
        for k in range(len(path) - 1):
            u, v = path[k], path[k + 1]
            Gs.add_edge(u, v, weight=weight_function(G, u, v, weight))
    # t3 = time.time()
    # print("recover Gs cost: ", t3 - t2)

    # 4. prime Ts
    Ts = nx.minimum_spanning_tree(Gs)
    # t4 = time.time()
    # print("prime Ts cost: ", t4 - t3)

    # 5. reserve terminals - remove any leaf that not in terminals
    # 5.1 collect leafs
    target = set(terminals)
    leafs = set()
    for node in Ts.nodes:
        if Ts.degree(node) == 1:
            leafs.add(node)
    leafs = leafs - target
    # 5.2 remove leaf and edge not realated to terminals
    for node in leafs:
        # print("terminals: ", target, ", leafs: ", leafs,  ", checking node: ", node)
        _next = node
        while _next:
            neighbors = list(Ts.neighbors(_next))
            Ts.remove_node(_next)
            _next = neighbors[0] if len(neighbors) == 1 else None
    # t5 = time.time()
    # print("reserve terminals cost: ", t5 - t4)
    return Ts
