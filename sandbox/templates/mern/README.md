# MERN starter
Copy this directory into the project: `cp -a /opt/templates/mern /work/project`.
Use start_service with command `cd /work/project && npm run dev`, name `app`, port `3000`.
Use test_app on port 3000 or the Workspace → Services → Preview control.
Run `cd /work/project && npm test && npm run build` to verify your changes.
Vite proxies `/api` to Express on 3001; MongoDB runs on 27017, localhost only.
Database exports are saved under `/work/.aster` by checkpoints and restored on startup.
Dependencies are preinstalled in this template. After restoring an idle project, run `npm ci` in the project directory if needed; the configured package proxy allows npm.
Never expose these development databases publicly. This is a development workspace, not production hosting.
