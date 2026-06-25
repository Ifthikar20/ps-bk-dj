#!/usr/bin/env bash
# Run ONCE on a fresh Ubuntu 22.04 EC2 to prepare the box for docker-compose.
# Usage:  sudo bash ec2-bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Ifthikar20/ps-bk-dj.git}"
APP_DIR="/opt/playstudy"
SWAP_GB="${SWAP_GB:-2}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo bash ec2-bootstrap.sh)" >&2
  exit 1
fi

echo "==> 1/7 System update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    ca-certificates curl gnupg git ufw \
    fail2ban unattended-upgrades apt-listchanges

echo "==> 2/7 Swap (${SWAP_GB}GB) — t3.small only has 2GB RAM"
if [[ ! -f /swapfile ]]; then
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
  echo "vm.swappiness=10" >> /etc/sysctl.conf
  sysctl -p
else
  echo "    swapfile already exists, skipping"
fi

echo "==> 3/7 Docker engine + compose plugin"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  usermod -aG docker ubuntu
else
  echo "    docker already installed"
fi

echo "==> 4/7 Firewall (UFW: 22/80/443; deny everything else)"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> 5/7 SSH hardening (/etc/ssh/sshd_config.d/99-hardening.conf)"
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'SSHD'
# PlayStudy hardening — overrides /etc/ssh/sshd_config defaults.
PasswordAuthentication no
PermitRootLogin no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
AllowTcpForwarding no
X11Forwarding no
AllowAgentForwarding no
PermitTunnel no
AllowUsers ubuntu
SSHD
systemctl reload ssh || systemctl reload sshd || true

echo "==> 6/7 fail2ban (SSH brute-force protection) + unattended-upgrades"
cat > /etc/fail2ban/jail.d/sshd.local <<'F2B'
[sshd]
enabled = true
port    = ssh
maxretry = 5
findtime = 10m
bantime  = 1h
F2B
systemctl enable --now fail2ban

# Auto-apply security patches nightly.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
APT
# Ensure security updates are enabled (Jammy default already does this; idempotent).
sed -i 's|//\s*"\${distro_id}:\${distro_codename}-security";|"\${distro_id}:\${distro_codename}-security";|' \
  /etc/apt/apt.conf.d/50unattended-upgrades || true
systemctl enable --now unattended-upgrades

echo "==> 7/7 App dir"
mkdir -p "$APP_DIR"
chown ubuntu:ubuntu "$APP_DIR"
sudo -u ubuntu bash -c "cd $APP_DIR && [ -d ps-bk-dj ] || git clone $REPO_URL"

cat <<'NEXT'

==> Bootstrap complete.

Hardening applied:
  - UFW default-deny inbound, only 22/80/443 open
  - SSH: key-only, no root, no password, no fwding, max 3 tries
  - fail2ban watching SSH (5 fails in 10m -> 1h ban)
  - unattended-upgrades enabled (nightly security patches)

Next, as the ubuntu user (log out + back in so docker group sticks):
    cd /opt/playstudy/ps-bk-dj
    cp .env.prod.example .env.prod
    nano .env.prod    # fill SECRET_KEY, JWT_SIGNING_KEY, POSTGRES_PASSWORD,
                      # ANTHROPIC_API_KEY, GAMES_BASE_URL, etc.
    bash deploy/deploy.sh
NEXT
