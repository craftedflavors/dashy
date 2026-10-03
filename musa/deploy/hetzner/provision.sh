#!/bin/bash
# Optional: create the server from your own computer with the Hetzner CLI instead of the web console.
#   1. Install hcloud: https://github.com/hetznercloud/cli   2. hcloud context create musa   (paste an API token)
#   3. Edit cloud-init.yaml (CHANGE-ME values), then:  ./provision.sh
set -euo pipefail
NAME=${NAME:-musa-1}
TYPE=${TYPE:-cx22}            # 2 vCPU / 4 GB — plenty for launch (check current names: hcloud server-type list)
LOCATION=${LOCATION:-fsn1}    # Falkenstein, Germany (EU). Alternatives: nbg1, hel1
SSH_KEY=${SSH_KEY:?set SSH_KEY to the name of an SSH key already added in Hetzner}
DIR=$(cd "$(dirname "$0")" && pwd)

if grep -q "musa.example.com\|change-this-to-a-long-random-password" "$DIR/cloud-init.yaml"; then
  echo "Edit the CHANGE-ME values in cloud-init.yaml first." >&2; exit 1
fi
hcloud firewall describe musa-fw >/dev/null 2>&1 || {
  hcloud firewall create --name musa-fw
  for p in 22 80 443; do hcloud firewall add-rule musa-fw --direction in --protocol tcp --port $p --source-ips 0.0.0.0/0 --source-ips ::/0; done
}
hcloud server create --name "$NAME" --type "$TYPE" --image ubuntu-24.04 --location "$LOCATION" \
  --ssh-key "$SSH_KEY" --firewall musa-fw --user-data-from-file "$DIR/cloud-init.yaml" --enable-backup
echo "Server created. Point your domain's A record at the IP above; setup finishes in ~5 minutes."
echo "Check:  ssh root@<ip> 'cloud-init status --wait && docker ps && curl -s localhost:8080/health'"
