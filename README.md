# FilterGuardian

A Windows desktop workflow for collecting shared URLs, analyzing site identity and hosting/proxy technology, reviewing fingerprints, and testing network-filter outcomes. Python, PySide6, SQLite, Playwright, and matplotlib.

## Install and set up

1. Install Python 3.10 or later. Chrome is optional for browser monitoring.
2. Run `powershell -File install.ps1` from this folder. The installer asks before downloading Python dependencies and optional Playwright Chromium.
3. Run `start.bat`. The first-run menu configures your own profile, theme, monitoring targets/channels, and optional relay or proxy test connection.

The default setup enables no browser monitoring and configures no network endpoint. Back edits prior steps; Cancel saves a local draft without the relay token. Reopen setup from Settings. Saving starts no external connection. Link to Browser asks before opening a separate Chrome profile; sign in yourself. Start Brain asks before visiting pending URLs. No system proxy or certificate changes are performed. Such changes require separate explicit consent and your organization's process.

For a manual installation: create a virtual environment, install `requirements.txt`, optionally run `python -m playwright install chromium`, then run `python main.py` from this directory.

## Workflow

- **Dashboard:** session metrics and browser/analysis controls.
- **Live Monitor:** discovery activity and scan controls.
- **Analytics:** classification, hosting, site, and source distributions.
- **Database:** manual submissions, search/filter, detail editing, fingerprint review, consolidation, filter testing, and export.
- **Targets:** servers, keywords, and explicit channel names.
- **Settings:** setup, profile/theme, whitelist, test connection, relay package, and local backup.

The optional relay runs on a machine you control in the filtered network. Configure an authenticated relay token and the address in setup. The proxy option applies to app test requests, not the Windows proxy. The relay and filter clients currently accept inspected TLS certificates. Only connect to infrastructure you are authorized to use.

## Local data

This repository includes source and fictional `.example` fixtures only. Settings, targets, whitelist, tokens, database, fingerprints, previews, browser profile, logs, and backups belong to each installation and are ignored by Git. Settings/tokens are stored locally in plaintext; protect your install folder and backups. Setup drafts omit tokens. Backups can include settings and data and must remain private.

## Verification and limits

Run `python -m unittest test_proxy_regression test_synthetic_workflow test_setup_wizard -v`.

Tests use temporary fictional data, browser test doubles, and mocked transport; they open no sockets or live browsing sessions. They cover proxy outcomes, capture/database persistence, Brain identity/review/retry paths, relay routing/fetch behavior, and first-run setup validation/navigation/privacy. Classification uses heuristics and manual fingerprint confirmation. Real Discord selectors, actual browser rendering, and target-network filter fidelity require environment-specific verification. A connection refusal is not conclusive evidence of a policy block.

## License

No license has been selected. Public visibility does not grant reuse rights beyond those otherwise provided by law or the hosting platform's terms.
