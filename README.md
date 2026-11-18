# GovJobs Daily

Static site (`index.html`) + daily GitHub Action that refreshes `data/jobs.json`. Jobs older than 30 days are removed automatically.

## Deploy
1. Create a GitHub repo and push these files to `main`.
2. Repo > Settings > Actions > General > Workflow permissions: **Read and write**.
3. Actions tab > "Update jobs daily" > **Run workflow**. Read the log: each source shows OK or FAIL.
4. Host free: **Cloudflare Pages** (connect repo, no build command, output directory `/`) or **GitHub Pages** (Settings > Pages > branch `main`, root). Every daily commit redeploys automatically.
5. Buy a domain and add it under Custom domains in Cloudflare Pages / GitHub Pages.

## Customise
- Sources: `SOURCES` list in `scripts/fetch_jobs.py`. Remove any that keep failing; add official recruitment pages.
- Site name and colours: top of `index.html`.
- Retention: `RETENTION_DAYS`.
- The 3 "Sample" jobs are removed on the first run.
