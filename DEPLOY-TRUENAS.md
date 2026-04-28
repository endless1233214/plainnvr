# PlainNVR on TrueNAS

TrueNAS can install this as a custom app using Docker Compose YAML, but it still needs a container image.

Use one of these two paths.

## Option 1: No Registry

This is the least account-setup nonsense.

1. Copy this `plainnvr` folder to a TrueNAS dataset, for example:

   ```text
   /mnt/Apps/plainnvr-src
   ```

2. SSH into TrueNAS or open Shell.

3. Build the image:

   ```bash
   cd /mnt/Apps/plainnvr-src
   docker build -t plainnvr:latest .
   ```

4. Make storage folders if they do not exist:

   ```bash
   mkdir -p /mnt/Apps/plainnvr/data /mnt/Apps/plainnvr/recordings
   ```

5. In TrueNAS, go to Apps > Discover, use the three-dot menu, choose Install via YAML, and paste `truenas-compose.yaml`.

This YAML uses:

```yaml
image: plainnvr:latest
pull_policy: never
```

That tells Compose to use the image you built locally instead of trying to pull it from Docker Hub.

## Option 2: GitHub Container Registry

Use this if you want TrueNAS to pull updates later.

1. Create a GitHub repo named `plainnvr`.

2. Upload this folder into that repo.

3. Add the workflow from `.github/workflows/docker-image.yml`.

4. In the GitHub repo, go to Settings > Actions > General and set Workflow permissions to Read and write permissions.

5. Push to `main`. GitHub Actions should publish:

   ```text
   ghcr.io/YOUR_GITHUB_USERNAME/plainnvr:latest
   ```

6. Edit `truenas-compose.registry.yaml` and replace `YOUR_GITHUB_USERNAME`.

7. If the package is public, TrueNAS can pull it without registry login.

8. If the package is private, create a GitHub token with `read:packages`, then in TrueNAS go to Apps > Configuration > Sign-in to a Docker registry:

   ```text
   Type: Other Registry
   URI: ghcr.io
   Username: your GitHub username
   Password: the GitHub token
   ```

9. Install via YAML using `truenas-compose.registry.yaml`.

## After Install

Open:

```text
http://TRUENAS-IP:8080
```

Recordings land in:

```text
/mnt/Apps/plainnvr/recordings
```

The database/config lands in:

```text
/mnt/Apps/plainnvr/data
```
