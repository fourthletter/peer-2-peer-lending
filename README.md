# Peer-2-Peer Lending Backend MVP

Build a worker-owned lending circle for income gaps and urgent needs.

This project now includes a Node.js + Express + PostgreSQL backend for core peer-lending flows:

- profiles
- monthly contributions
- loan requests
- repayment schedules and payments
- admin loan status actions

<img width="1224" height="709" alt="Screenshot 2026-04-14 at 3 38 34 PM" src="https://github.com/user-attachments/assets/bbad788a-4922-4f4b-8e1f-05e8dca31d32" />


## 1) Setup

1. Copy `.env.example` to `.env`.
2. Set `DATABASE_URL` for your PostgreSQL instance.
3. Set admin credentials for HTTP Basic Auth:
   - `ADMIN_USERNAME`
   - `ADMIN_PASSWORD`
4. Install dependencies:

```bash
npm install
```

## 2) Run migrations

```bash
npm run db:migrate
```

## 3) Start API

```bash
npm run start
```

Server defaults to `http://localhost:4000`.

## 4) Key endpoints

- `GET /health`
- `POST /api/profiles`
- `GET /api/profiles/:id`
- `PATCH /api/profiles/:id`
- `POST /api/contributions`
- `GET /api/contributions`
- `POST /api/loan-requests`
- `GET /api/loan-requests`
- `PATCH /api/admin/loan-requests/:id/status`
- `POST /api/repayments/schedule`
- `POST /api/repayments/pay`
- `GET /api/repayments`
- `GET /api/admin/profiles`
- `GET /api/admin/payments`
- `PATCH /api/admin/loan-requests/:id/status`

## Admin dashboard (backend component)

<img width="1104" height="705" alt="Screenshot 2026-04-14 at 3 40 48 PM" src="https://github.com/user-attachments/assets/73383507-b9ee-4e8f-b53e-4326a0bf9d30" />


Open:

- `http://localhost:4000/admin.html`

Admin routes are protected with HTTP Basic Auth and use the `ADMIN_USERNAME` / `ADMIN_PASSWORD`
values from your `.env`.

This page fetches backend admin APIs to:

- view all member profiles
- view payment summary metrics
- track payment status by member

## API testing helpers

- Postman collection:
  - `tools/postman/peer-lending-mvp.postman_collection.json`
- Shell smoke test:
  - `tools/smoke-test.sh`

Run smoke test (requires backend running):

```bash
./tools/smoke-test.sh
```

Optional overrides:

```bash
BASE_URL=http://localhost:4000 ADMIN_USER=admin ADMIN_PASS=your-password ./tools/smoke-test.sh
```

## Notes

- This backend is intentionally lightweight and ready for frontend integration.
- Auth, role-based permissions, and notifications are not yet implemented in this MVP.
