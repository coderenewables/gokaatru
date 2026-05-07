# Deploy GoKaatru on AWS EC2 (No Docker)

This guide deploys the app on EC2 using:

- `systemd` services for API + MCP
- built frontend static files
- `Caddy` for HTTPS and reverse proxy

Deployment target:

- Domain: `gokaatru.coderenewables.com`
- DNS provider: Cloudflare
- TLS email: `nithishkannan89@yahoo.com`
- EC2 host: `ec2-3-137-164-54.us-east-2.compute.amazonaws.com`
- Repository: `https://github.com/coderenewables/gokaatru`

## 0. First deploy command set (copy/paste)

Replace `<PATH_TO_YOUR_KEY.pem>` with your SSH key path.

```bash
ssh -i <PATH_TO_YOUR_KEY.pem> ubuntu@ec2-3-137-164-54.us-east-2.compute.amazonaws.com

sudo mkdir -p /opt/gokaatru
sudo chown -R "$USER":"$USER" /opt/gokaatru

cd /opt
git clone https://github.com/coderenewables/gokaatru
cd gokaatru
bash deploy/aws/ec2/bootstrap-ubuntu.sh

cp .env.production.example .env.production
nano .env.production

bash deploy/aws/ec2/deploy.sh
```

## 1. EC2 prerequisites

Use Ubuntu 22.04/24.04 and allow inbound:

- TCP 22 (SSH)
- TCP 80 (HTTP)
- TCP 443 (HTTPS)

## 2. Cloudflare DNS

Create DNS record:

- Type: `A`
- Name: `gokaatru`
- Value: `<EC2_PUBLIC_IP>`

For first certificate issuance, set record to `DNS only` (gray cloud).
After HTTPS works, you can switch to proxied mode.

Cloudflare SSL/TLS mode: `Full (strict)`.

## 3. Deploy

```bash
cd /opt/gokaatru
bash deploy/aws/ec2/deploy.sh
```

The deploy script does all of this:

- creates/updates `.venv`
- installs backend dependencies
- builds frontend production assets
- writes systemd service units
- writes Caddy config
- restarts services

## 4. Validate

```bash
systemctl status gokaatru-api --no-pager
systemctl status gokaatru-mcp --no-pager
systemctl status caddy --no-pager
```

Then test:

- `https://gokaatru.coderenewables.com`
- `https://gokaatru.coderenewables.com/api/health`

## 5. Logs and troubleshooting

```bash
journalctl -u gokaatru-api -f
journalctl -u gokaatru-mcp -f
journalctl -u caddy -f
```

## 6. Update to latest code

```bash
cd /opt/gokaatru
bash deploy/aws/ec2/update.sh
```

## Stack summary

- `gokaatru-api` on `127.0.0.1:8000`
- `gokaatru-mcp` on `127.0.0.1:8080`
- `caddy` on `:80` and `:443`
- frontend served as static files from `frontend/dist`
