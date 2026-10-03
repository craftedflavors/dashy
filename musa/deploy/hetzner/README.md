# Deploying MUSA Corridor on Hetzner Cloud

What you get on one server:
- Ubuntu 24.04 running the platform in Docker.
- **Caddy**, which gets and renews HTTPS certificates automatically.
- A firewall that only allows SSH, HTTP and HTTPS, plus fail2ban and automatic security updates.
- A **database backup every 6 hours** (kept 14 days).
- A **nightly auto-update** that pulls the configured branch from GitHub and rebuilds only if the code changed. It takes a backup first.

Cost: a CX22 (2 vCPU, 4 GB) is a few euros a month, and Hetzner's own server backups add about 20% on top. Check current prices on hetzner.com.

## Before you start
1. **Merge the pull request** (or set `GIT_BRANCH` to the feature branch) so the branch you deploy contains `musa/`.
2. **A domain**, e.g. `musa.example.com`. You will point its DNS **A record** at the server's IP.
3. **If the GitHub repo is private:** create a fine-grained GitHub token with read-only "Contents" access to this repo, and use
   `https://<token>@github.com/craftedflavors/dashy.git` as `GIT_URL`.

## Option A: web console (about 10 minutes)
1. Open `cloud-init.yaml` and edit the five `CHANGE-ME` values: domain, email, git URL, branch, admin password.
2. Hetzner Console → your project → **Servers → Add Server**:
   - Location: **Falkenstein or Nuremberg (Germany)**, which keeps the data in the EU for GDPR.
   - Image: **Ubuntu 24.04**. Type: **CX22** (or larger).
   - SSH key: add yours.
   - Backups: **on**.
   - **Cloud config:** paste the whole edited `cloud-init.yaml`.
3. Create the server, copy its IPv4 address, and set your domain's **A record** to it.
4. Wait about 5 minutes, then open `https://your-domain`. The admin console is at `/admin` (user `admin`, your password).

## Option B: Hetzner CLI
```bash
hcloud context create musa                 # paste an API token from Console → Security → API tokens
SSH_KEY=my-key ./provision.sh              # after editing cloud-init.yaml
```

## After it is running
```bash
ssh root@<ip>
cloud-init status --wait                   # setup finished?
docker ps                                  # container "musa" up?
curl -s localhost:8080/health              # → ok
nano /etc/musa/app.env                     # add WhatsApp / Stripe / Anthropic keys
musa-update --force                        # apply new settings
journalctl -u musa-update -n 50            # last auto-update result
ls /var/backups/musa                       # backups
```

- Payment accounts and prices live in `musa/data/payments.json` in the repo. Commit changes and the nightly update picks them up, or run `musa-update` to apply them immediately.
- WhatsApp webhook: `https://your-domain/webhook`. Stripe webhook: `https://your-domain/stripe/webhook`.
- WhatsApp leads admin: `https://your-domain/admin/leads`.

## Scaling
- Resize the server in the Hetzner console. The data stays in the `musa-data` Docker volume.
- Beyond one server, move the database to Postgres (see the main README) and run several containers behind a Hetzner Load Balancer.
