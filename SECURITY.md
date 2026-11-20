# Stoa security

## Reporting a vulnerability
Please report security problems privately, not in a public issue: use GitHub's **Report a vulnerability**
button on this repository (Security tab). Include what you found, how to reproduce it and which Stoa version
(`cat /usr/share/stoa/VERSION`). We aim to reply within 7 days and to ship a fix for serious issues within
14 days, crediting you if you'd like.

## How Stoa is kept up to date
- **Ubuntu security updates** (the 24.04 LTS base, supported until 2029) install automatically on every edition.
- **Stoa kernel**: rebuilt weekly from Ubuntu's patched kernel source and delivered to installed PCs
  automatically; Stoa asks for a restart to finish. PCs with Secure Boot on use Ubuntu's signed kernel instead.
- **Stoa itself**: updates are published with a SHA-256 for every file and an Ed25519 signature over that list.
  Each Stoa install carries the public key and refuses unsigned or altered updates. Publishing can require the
  maintainer's approval (GitHub environment `stoa-updates`).

## Built-in protection
Firewall on by default (ufw), antivirus (ClamAV, Stoa Protect) scanning downloads, AppArmor, optional full-drive
encryption (LUKS2) with TPM unlock, administrator actions only through password-checked helpers (polkit), a
standard day-to-day account option (Settings > Accounts), checked downloads (publisher checksums + virus scan),
and Stoa AI asks before installing or changing anything.

## Maintainer set-up (once)
1. `linux/tools/make-update-key.sh` → add `stoa-update-key.pem` as the repository secret `STOA_SIGNING_KEY`;
   keep the file offline. Losing it means re-issuing a key through a manual update.
2. Settings → Environments → `stoa-updates` → add yourself as a required reviewer.
3. Settings → Actions → General → Workflow permissions → Read and write.
4. Turn on two-factor authentication for the GitHub account.
