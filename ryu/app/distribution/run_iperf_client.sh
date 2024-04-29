#!/bin/bash

if [ $# -ne 3 ]; then
    echo "Usage: $0 <listen_address> <hostname> <bw>"
    exit 1
fi

multicast_ip="$1"
hostname="$2"
bw="$3"

ip route add 224.0.0.0/4 dev "${hostname}"-eth0
iperf -c "${multicast_ip}" -u -T 32 -t 60 -i 1 -b "${bw}"