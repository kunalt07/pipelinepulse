# Contributing to PipelinePulse

Thanks for considering a contribution. This is a small project — the bar is "make it better and don't break anything."

## Reporting issues

- **Bug reports** — include your Airflow version, how you're running PipelinePulse (Docker / bare metal), what you did, what you expected, what happened. Logs from `docker compose logs backend` are usually enough.
- **Feature requests** — describe the use case first, the proposed solution second. If a similar issue already exists, comment on that one instead of opening a new one.

## Submitting changes

1. Fork the repo and create a branch off `main`.
2. Make your change. Keep PRs focused — one feature or fix per PR.
3. Run the stack locally and verify the change works end-to-end (`docker compose up -d`).
4. Open a PR with:
   - A short description of *what* changed and *why*.
   - Screenshots or a short clip if the change is UI-visible.
   - A note on what you tested.

CI will run `docker compose config` validation and `npm run build` on your PR. Both must pass before review.

## Local development

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in values
uvicorn main:app --reload --port 8000
```

The scheduler runs in-process. The first sync happens at startup; subsequent syncs every 2 minutes.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on http://localhost:3000 and proxies to the backend at `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

If you change auth or API URL, restart the dev server — Next.js reads `NEXT_PUBLIC_*` vars at startup.

### Database

The schema is created by SQLAlchemy on first run. If you change a model, add an idempotent `ALTER TABLE` to `database.py:run_migrations()` — we don't use Alembic to keep the dependency footprint small.

## Code style

- **Backend:** stdlib-friendly Python. No need for type stubs everywhere, but type hints on public functions help reviewers.
- **Frontend:** TypeScript, functional components, Tailwind for styling. Follow the existing patterns in `src/components/`.
- **Comments:** explain *why*, not *what*. Don't comment self-explanatory code.

## What we won't merge (without discussion)

- Adding a heavy dependency (e.g. ORM swap, new framework) without a clear reason.
- Features that require paid services to function.
- Changes to the auth model — security-sensitive, needs careful review.
- Breaking changes to the public REST API without a migration path.

When in doubt, open an issue first.

## License

By contributing, you agree your contributions are licensed under the [MIT License](LICENSE).
