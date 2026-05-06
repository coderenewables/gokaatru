# Deploy GoKaatru on AWS EC2 (Ubuntu + Cloudflare)

This guide deploys the full app stack behind HTTPS on:

- Domain: `gokaatru.coderenewables.com`
- DNS provider: Cloudflare
- TLS email: `nithishkannan89@yahoo.com`

## 1. EC2 prerequisites

Use Ubuntu 22.04/24.04 and allow inbound:

- TCP 22 (SSH)
- TCP 80 (HTTP)
- TCP 443 (HTTPS)

Then SSH into EC2 and run:

```bash
sudo mkdir -p /opt/gokaatru
sudo chown -R "$USER":"$USER" /opt/gokaatru
```

## 2. Clone repo and bootstrap host

```bash
cd /opt
git clone <YOUR_GITHUB_REPO_URL> gokaatru
cd gokaatru
bash deploy/aws/ec2/bootstrap-ubuntu.sh
```

Log out and back in once so Docker group membership is active.

## 3. Configure production env

```bash
cd /opt/gokaatru
cp .env.production.example .env.production
```

Edit `.env.production` and set secrets you need.

## 4. Configure Cloudflare DNS

Create DNS record:

- Type: `A`
- Name: `gokaatru` (or full host `gokaatru.coderenewables.com`)
- Value: `<EC2_PUBLIC_IP>`

For first certificate issuance, use Cloudflare DNS mode as `DNS only` (gray cloud).
After HTTPS is working, you can switch to proxied mode.

## 5. Deploy

```bash
cd /opt/gokaatru
bash deploy/aws/ec2/deploy.sh
```

Check status:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

## 6. Verify

- `https://gokaatru.coderenewables.com`
- `https://gokaatru.coderenewables.com/api/health`

If health works but UI fails, check frontend logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f frontend
```

If TLS fails, check Caddy logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f caddy
```

## 7. Update to latest code

```bash
cd /opt/gokaatru
bash deploy/aws/ec2/update.sh
```

## Stack summary

- `caddy`: TLS + reverse proxy
- `frontend`: static React build via nginx
- `api`: FastAPI on port 8000 (internal)
- `mcp`: FastMCP SSE on port 8080 (internal)
