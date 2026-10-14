#!/usr/bin/env bash
set -euo pipefail
# Only rules for Aster's dedicated sandbox subnet are installed. Existing policies remain.
iptables -N ASTER-EGRESS 2>/dev/null || true
iptables -F ASTER-EGRESS
iptables -A ASTER-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for range in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4; do
 iptables -A ASTER-EGRESS -d "$range" -j REJECT
done
iptables -A ASTER-EGRESS -j RETURN
iptables -C DOCKER-USER -s 172.30.0.0/16 -j ASTER-EGRESS 2>/dev/null || iptables -I DOCKER-USER 1 -s 172.30.0.0/16 -j ASTER-EGRESS
iptables -N ASTER-HOST 2>/dev/null || true
iptables -F ASTER-HOST
iptables -A ASTER-HOST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A ASTER-HOST -s 172.31.0.0/16 -d 172.31.0.1 -p tcp --dport 8093 -j ACCEPT
iptables -A ASTER-HOST -j REJECT
iptables -C INPUT -s 172.30.0.0/16 -j ASTER-HOST 2>/dev/null || iptables -I INPUT 1 -s 172.30.0.0/16 -j ASTER-HOST

iptables -C INPUT -s 172.31.0.0/16 -j ASTER-HOST 2>/dev/null || iptables -I INPUT 1 -s 172.31.0.0/16 -j ASTER-HOST
iptables -C DOCKER-USER -s 172.31.0.0/16 -j ASTER-EGRESS 2>/dev/null || iptables -I DOCKER-USER 1 -s 172.31.0.0/16 -j ASTER-EGRESS
