# GitHub mirror of Codeberg

This repository is **canonical on Codeberg**. GitHub is a **read-only code mirror** for visibility and cloning; do not open issues or pull requests on GitHub.

| Host | Role | URL |
|------|------|-----|
| Codeberg | Source of truth (clone, issues, PRs, releases, CI) | [codeberg.org/jawlet/ultimatevocalremovergtk](https://codeberg.org/jawlet/ultimatevocalremovergtk) |
| GitHub | Read-only mirror (branches + tags) | [github.com/minarru/ultimatevocalremovergtk](https://github.com/minarru/ultimatevocalremovergtk) |

## What syncs

- Git branches and commits
- Git tags

## What does not sync

- Issues and pull requests (use [Codeberg Issues](https://codeberg.org/jawlet/ultimatevocalremovergtk/issues))
- Codeberg Releases and release assets
- Forgejo Actions workflows (see [`.forgejo/workflows/`](../.forgejo/workflows/))
- Wiki, repository settings, and deploy secrets

Before filing bugs, check [tracked-issues.md](tracked-issues.md) and existing Codeberg issues.

---

## One-time host setup

### 1. Create an empty GitHub repository

1. Sign in to GitHub as **minarru**.
2. **New repository** → name: `ultimatevocalremovergtk`
3. Public (or private, if you prefer).
4. **Do not** add a README, `.gitignore`, or license (avoids an unrelated first commit).

### 2. GitHub deploy key for the Codeberg push mirror

Codeberg **generates** an Ed25519 key pair when you add a push mirror with **Use SSH authentication**. The private key stays on Codeberg (you never paste it anywhere). You only copy Codeberg’s **public** key into GitHub.

On GitHub (`minarru/ultimatevocalremovergtk`), after creating the push mirror on Codeberg (step 3):

1. **Settings → Deploy keys → Add deploy key**
2. Title: `codeberg-push-mirror`
3. Key: paste the public key from Codeberg (**Copy public key** on the mirror row)
4. Enable **Allow write access** (required for push mirroring)

**Alternative:** HTTPS push mirror with a fine-grained personal access token (**Contents: Read and write** on this repo only). Mirror URL:

```text
https://<token>@github.com/minarru/ultimatevocalremovergtk.git
```

### 3. Configure Codeberg push mirror

On [codeberg.org/jawlet/ultimatevocalremovergtk](https://codeberg.org/jawlet/ultimatevocalremovergtk):

1. **Settings → Repository → Mirror Settings**
2. Add a **Push Mirror**:
   - **Git Remote Repository URL:** `git@github.com:minarru/ultimatevocalremovergtk.git`
   - **Authorization:** enable **Use SSH authentication** (leave username/password empty)
   - **Interval:** shortest available
3. Save the mirror, then click **Copy public key** on the new mirror row.
4. Add that public key to GitHub as a deploy key (step 2 above).
5. Click **Synchronize now** / **Sync now** on Codeberg.

Existing push mirrors cannot be switched to SSH after creation; delete and re-add if you started with HTTPS/password.

**Note:** `~/.ssh/uvr-github-mirror` (if you created one for local pushes) is **separate** from Codeberg’s mirror key. The backup script uses your local key; Codeberg uses its own generated key for automatic mirroring.

### 4. Seed GitHub manually (if mirror sync fails)

From a local clone whose `origin` points at Codeberg:

```bash
git remote add github git@github.com:minarru/ultimatevocalremovergtk.git
./scripts/sync-github-mirror.sh
```

Or push directly:

```bash
git push github --all
git push github --tags
```

### 5. Harden GitHub (optional)

- Add to the GitHub repo description: *Mirror of Codeberg — issues and PRs on Codeberg only.*
- Leave GitHub Issues disabled if you want a single issue tracker on Codeberg.

---

## Ongoing workflow

1. **Normal development:** `git push origin <branch>` (Codeberg only).
2. **Automatic mirror:** Codeberg push mirror updates GitHub on its schedule.
3. **Manual backup:** after `git fetch origin`, run [`scripts/sync-github-mirror.sh`](../scripts/sync-github-mirror.sh).

```bash
git remote add github git@github.com:minarru/ultimatevocalremovergtk.git   # once
./scripts/sync-github-mirror.sh
./scripts/sync-github-mirror.sh --dry-run
```

The sync script uses `~/.ssh/uvr-github-mirror` for **GitHub pushes only** when that file exists (or set `UVR_GITHUB_MIRROR_KEY` to another private key path). Codeberg `git fetch origin` keeps your normal SSH credentials — do not set `GIT_SSH_COMMAND` globally when using the deploy key.

---

## Verification

| Check | Expected |
|-------|----------|
| `main` on GitHub | Same commit SHA as Codeberg `main` |
| Active feature branches | Present on GitHub if pushed to Codeberg |
| Tags (`v*`) | Match Codeberg tags |
| `./scripts/sync-github-mirror.sh --dry-run` | Lists refs, no errors |

Compare SHAs:

```bash
git fetch origin
git ls-remote origin refs/heads/main
git ls-remote github refs/heads/main
```

---

## Troubleshooting

### Mirror lag

Codeberg push mirrors run on an interval. Wait for the next sync or use **Sync now** in mirror settings, or run `./scripts/sync-github-mirror.sh`.

### Authentication failures

- Confirm the GitHub deploy key uses Codeberg’s **mirror public key** (from **Copy public key**), not your personal SSH key, unless you only use the manual sync script.
- Confirm **Allow write access** is enabled on the GitHub deploy key.
- For PAT mirrors, regenerate the token if expired.
- If the mirror was created without **Use SSH authentication**, remove it and add a new push mirror with SSH enabled (existing mirrors cannot be converted).

### GitHub ahead of Codeberg (direct push to GitHub)

GitHub should not receive direct commits. Reset the mirror from Codeberg:

```bash
git fetch origin
git push github --all --force
git push github --tags --force
```

### `origin` is not Codeberg

The backup script refuses to run unless `origin` looks like a Codeberg URL. Fix `origin` or set `GITHUB_MIRROR_URL` and use a dedicated `github` remote.
