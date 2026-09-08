# Deployment

For running PeriopUDI on a VM with a public link. The demo data is synthetic, but
the deployment is still publicly reachable, so it is configured to fail closed.

## Threat model in one paragraph

HAPI FHIR ships with **no authentication of its own**. Anything that can reach it
can read, write and delete every record. The app in front of it is therefore the
only access control, and HAPI must not be published. Everything below follows
from that.

---

## 1. Prerequisites

- A VM with Docker and Docker Compose
- A DNS A record pointing at the VM (needed for TLS)
- Ports **80** and **443** open. Nothing else.

---

## 2. Configure `.env`

```bash
cp .env.example .env
```

Generate a real secret and passcode:

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python3 -c "import secrets; print('DEMO_PASSCODE=' + secrets.token_urlsafe(12))"
```

Required for a public deployment:

| Variable | Value | Why |
|---|---|---|
| `SECRET_KEY` | 32-byte hex | Signs session cookies. **The app refuses to start on the built-in default** — it is public in this repository, so sessions would be forgeable. |
| `DEMO_PASSCODE` | random | Shared passcode for the synthetic-data sign-in. Leave empty to make SMART launch the only way in. |
| `PUBLIC_HOSTNAME` | `periopudi.example.org` | The DNS name. Caddy gets a certificate for it. |
| `ACME_EMAIL` | your address | Let's Encrypt contact. |
| `APP_BASE_URL` | `https://$PUBLIC_HOSTNAME` | Builds the SMART `redirect_uri`. **Must be https and must match exactly**, or the OAuth callback fails. |
| `SECURE_COOKIES` | `true` | Marks cookies Secure so they are never sent over plain HTTP. |
| `CORS_ALLOWED_ORIGIN` | `https://$PUBLIC_HOSTNAME` | Restricts HAPI's CORS. |
| `REQUIRE_AUTH` | `true` | The access gate. Default is already `true`. |

---

## 3. Deploy

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build
```

The overlay:

- publishes **no host ports** for HAPI, CDS Hooks, or the app
- runs Caddy on 80/443, which terminates TLS and proxies to the app
- forces `REQUIRE_AUTH=true`, `SECURE_COOKIES=true`, `FLASK_ENV=production`

Seed patients on first run:

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml \
  --profile seed run --rm synthea-seed
```

---

## 4. Verify before sharing the link

Every one of these must hold.

```bash
# The app is reachable and redirects to sign-in
curl -sI https://$PUBLIC_HOSTNAME/ | head -1

# Patient data is NOT reachable without a session
curl -s https://$PUBLIC_HOSTNAME/api/patients        # expect 401
curl -s https://$PUBLIC_HOSTNAME/patient/1602/devices # expect 401 or 302

# Writes are NOT reachable without a session
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' \
  -d '{"udi":"00643169634589","patient_id":"1602"}' \
  https://$PUBLIC_HOSTNAME/scan-to-chart              # expect 401 or 302

# HAPI must NOT be reachable from outside at all
curl -s --max-time 5 http://$PUBLIC_HOSTNAME:8080/fhir/Patient   # expect connection refused
curl -s --max-time 5 http://$PUBLIC_HOSTNAME:8091/health         # expect connection refused

# Health check stays public (for monitoring)
curl -s https://$PUBLIC_HOSTNAME/health              # expect 200
```

If either HAPI check returns data, **stop and take the deployment down** — the
port mapping did not get removed.

---

## 5. Back up before you share it

The Postgres volume is the only copy of the seeded patients and every device
documented since. Nothing else holds it.

```bash
./scripts/backup_hapi.sh
```

Restore is documented in the script header. Take a backup before any
`docker compose down`, and note that **`down -v` destroys the volume** — that
flag is the one genuinely dangerous command in this project.

---

## 6. SMART App Launch against a deployed instance

`APP_BASE_URL` must be the public HTTPS origin, because the OAuth `redirect_uri`
is derived from it and the authorization server compares it byte for byte.

At <https://launch.smarthealthit.org>:

- **App Launch URL** — `https://$PUBLIC_HOSTNAME/launch`
- **Redirect URL** — `https://$PUBLIC_HOSTNAME/smart/callback`

A real EHR (Epic, Cerner) additionally requires registering the app to obtain a
client id; the sandbox does not.

---

## What is still not hardened

Stated plainly, because a reviewer will ask:

- **No per-user accounts or roles.** One shared passcode for the synthetic
  deployment; real identity comes from the EHR via SMART. Single-tenant by design.
- **No rate limiting** beyond a crude per-process throttle on the sign-in form.
  Put Cloudflare or fail2ban in front if the link circulates widely.
- **HAPI itself remains unauthenticated.** It is protected by network isolation,
  not by credentials. Do not publish its port, and do not attach it to a network
  where untrusted workloads run.
- **No audit logging** of who viewed which record.
