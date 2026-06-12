# Deploy PlainNVR On TrueNAS

PlainNVR can run as a TrueNAS custom app from Docker Compose YAML. The
registry-based installation is recommended because TrueNAS can pull published
updates without rebuilding the image locally.

The names and locations of TrueNAS menu items can vary slightly between
releases.

## Prepare Storage

Create persistent directories or datasets for the database and recordings. The
supplied YAML uses these example paths:

```text
/mnt/Apps/plainnvr/data
/mnt/Apps/plainnvr/recordings
```

Create the directories from the TrueNAS shell when needed:

```bash
mkdir -p /mnt/Apps/plainnvr/data /mnt/Apps/plainnvr/recordings
```

Edit both host paths in the selected YAML file when another pool or dataset
layout is preferred. Keep the container paths `/data` and `/recordings`
unchanged.

## Recommended: Pull The Published Image

[`truenas-compose.registry.yaml`](truenas-compose.registry.yaml) uses:

```yaml
image: ghcr.io/endless1233214/plainnvr:latest
pull_policy: always
```

The package is public, so registry credentials are not required.

1. Open **Apps** in TrueNAS.
2. Choose the custom-app or **Install via YAML** action.
3. Paste the contents of `truenas-compose.registry.yaml`.
4. Adjust the `TZ` value and host storage paths.
5. Save and deploy the app.

For a private fork, sign in to GitHub Container Registry from the TrueNAS Apps
configuration with:

```text
Registry: ghcr.io
Username: GITHUB-USERNAME
Password: GITHUB-TOKEN-WITH-read:packages
```

Replace the image owner in the YAML with the fork's GitHub account or
organization.

## Alternative: Build The Image On TrueNAS

Use this method when the server must run a local checkout or cannot pull from
GitHub Container Registry.

1. Copy or clone the repository into a TrueNAS dataset, such as:

   ```text
   /mnt/Apps/plainnvr-src
   ```

2. Build the image from the TrueNAS shell:

   ```bash
   cd /mnt/Apps/plainnvr-src
   docker build -t plainnvr:latest .
   ```

3. Install the custom app with
   [`truenas-compose.yaml`](truenas-compose.yaml).

That YAML uses:

```yaml
image: plainnvr:latest
pull_policy: never
```

`pull_policy: never` keeps Compose from looking for the locally tagged image on
an external registry.

## First Launch

Open:

```text
http://TRUENAS-HOST:8787
```

The first visit creates the local administrator account. To create the account
from YAML before the first launch, add these environment variables:

```yaml
NVR_AUTH_USERNAME: admin
NVR_AUTH_PASSWORD: use-a-long-unique-password
```

The password must be at least 12 characters.

## Published Ports

| Port | Purpose |
| --- | --- |
| `8787/tcp` | PlainNVR web interface and API |
| `8554/tcp` | go2rtc RTSP restreams |
| `8555/tcp` and `8555/udp` | go2rtc WebRTC media |

Port `1984` is intentionally not published. PlainNVR proxies the required
go2rtc media API through its authenticated web service.

## Updating

For the registry installation, redeploy or pull the custom app after a new
`latest` image is published.

For a local build, update the checkout, run the `docker build` command again,
and redeploy the custom app.

The database and recordings remain in their host datasets during image updates.

## Publishing A Fork

The included workflow at `.github/workflows/docker-image.yml` publishes an image
on every push to `main`.

1. Enable **Read and write permissions** under the repository's GitHub Actions
   workflow settings.
2. Push the fork to `main`.
3. Confirm that GitHub Actions published
   `ghcr.io/REPOSITORY-OWNER/plainnvr:latest`.
4. Update the image reference in `truenas-compose.registry.yaml`.
