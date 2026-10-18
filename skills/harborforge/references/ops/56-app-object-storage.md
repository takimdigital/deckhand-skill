# 56 — App object storage (uploads) — RustFS via Coolify

**Purpose:** when the app stores user files (images, PDFs…), the files get the same treatment as the database: local S3-compatible storage on the VPS (fast) + offsite copies (ref 55). Never leave uploads only on a VPS disk path.
**Use when:** the built app has uploads/media, the user says "images", "files", "gallery", "attachments".

## Verdict (Sept 2026): **RustFS 1.0.x — Apache-2.0**

| | RustFS | MinIO CE | Garage | SeaweedFS |
|---|---|---|---|---|
| License | **Apache-2.0** | AGPL-3.0 | AGPL-3.0 | Apache-2.0 |
| Status | GA 2026-09-16, active | **dead — archived 2026-04, no security patches, console stripped** | active | active |
| Fit (4 vCPU / 8 GB) | single-node, light | preallocates 1 GB+ before any work | light, but replication needs 3+ nodes | ~0.5–1 GB, best for many small files |

MinIO is disqualified outright (dead + AGPL). RustFS caveats to state honestly: 1.0 is young; **no POST-object form upload — use presigned PUT**; read-mixed performance is still catching up to old MinIO. Runner-up if in-catalog one-click matters more: SeaweedFS.

## Deploy (agent-driven)

Coolify's `rustfs.yaml` template exists but carries `# ignore: true` (hidden from the one-click catalog in v4.3.23) → create a **Docker Compose (empty)** resource and paste the template body; **pin the image** (`rustfs/rustfs:1.0.0`, never `:latest`). `[verify at live drill]`

- Env: `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY` (from Coolify-generated service vars), `RUSTFS_CONSOLE_ENABLE=true`, `RUSTFS_CORS_ALLOWED_ORIGINS=https://<app-domain>` (tighten from `*`).
- Domains: `9000` → `https://s3.<domain>` · `9001` → `https://console.<domain>`; then set explicitly: `RUSTFS_SERVER_URL=https://s3.<domain>`, `RUSTFS_BROWSER_REDIRECT_URL=https://console.<domain>`, `RUSTFS_SERVER_DOMAINS=s3.<domain>`.
- Deploy → console → create the bucket → mint a **scoped key** (that bucket only; list+get+put+delete). **Never ship `rustfsadmin` to the app.**
- Data: named volume `rustfs-data` → `/data` (host path `/var/lib/docker/volumes/<resource-uuid>-rustfs-data/_data`).

## App contract (Next.js)

```
S3_ENDPOINT=https://s3.<domain>
S3_REGION=us-east-1          # any consistent value
S3_ACCESS_KEY_ID=…           # the SCOPED key
S3_SECRET_ACCESS_KEY=…
S3_BUCKET=uploads
S3_FORCE_PATH_STYLE=true     # mandatory
```

```ts
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
const s3 = new S3Client({ endpoint: process.env.S3_ENDPOINT, region: process.env.S3_REGION,
  credentials: { accessKeyId: process.env.S3_ACCESS_KEY_ID!, secretAccessKey: process.env.S3_SECRET_ACCESS_KEY! },
  forcePathStyle: true });
// route handler: browser PUTs straight to storage with this URL (no creds client-side)
await getSignedUrl(s3, new PutObjectCommand({ Bucket: process.env.S3_BUCKET, Key, ContentType }), { expiresIn: 600 });
```

Serve files with presigned GETs (or a public-read bucket policy if acceptable). Browser uploads need CORS: `RUSTFS_CORS_ALLOWED_ORIGINS`.

## Offsite for the files (two layers)

1. **Object-level mirror (preferred):** hourly/daily `rclone sync` of the bucket → B2 **and** R2 (`rclone` config: `type=s3, provider=Minio, endpoint=https://s3.<domain>, force_path_style=true`, scoped read key). Object storage has no DB-consistency problem, so object-level sync is the honest copy. (A third, browseable copy can be a **local RustFS on the user's own machine** — `templates/ops/vps-backup/rustfs-local.compose.yml`, ref 55 §7; the home pull writes into it automatically.)
2. **Weekly full-volume tar** (DR): `docker run --rm -v <vol>:/data:ro -v /opt/backups:/backup alpine tar czf /backup/rustfs-$(date -u +%F).tgz -C /data .` → upload to both providers, keep 3.

Coolify scheduled volume backups are documented for **application** mounts; for a compose service, try `PUT /api/v1/services/{uuid}/storages/{storage_uuid}/backups` (endpoint exists in v4.3.23) — if a Service refuses, use the scripted tar. `[verify at live drill]`

**Drill:** sync the latest objects back into a scratch bucket / untar into a scratch container, compare a sampled file's sha256 against the live volume.

## When NOT to use this

A single small app with rare, tiny files can write straight to the offsite buckets via the S3 SDK — no local service to run, nothing extra to back up. RustFS earns its RAM when the app wants LAN-speed reads/writes, many files, or a console for the user.
