# Auth API — /auth

All fields below work as a standard form post OR as a JSON request body (see
`form_value`/`form_list` in [app/api.py](app/api.py)). The `/api/auth/*`
mirror (e.g. `/api/auth/login`) accepts identical payloads and always
responds with JSON.

**Token auth (for API/mobile clients):** `POST /auth/login` returns a signed
`token` alongside the user when the response is JSON. Store it client-side
and send it back as `Authorization: Bearer <token>` on later requests — this
works without cookies, so it's how you authenticate across origins (mobile
apps, cross-site frontends) where the session cookie set by login won't be
sent back. The token is stateless (`itsdangerous`, signed with `SECRET_KEY`)
and expires after 30 days (`User.TOKEN_MAX_AGE`); there's no server-side
revocation, so logout only clears the cookie session — an API client should
just discard its stored token.

---

### POST /auth/register
`register`

Request body:
```json
{
  "name": "Jane Doe",
  "email": "jane@example.com",
  "password": "secret123",
  "confirm": "secret123",
  "phone": "012345678"
}
```

Response `201`:
```json
{
  "success": true,
  "data": {
    "user_id": 1,
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "012345678",
    "roles": ["Customer"],
    "created_at": "2026-07-15T09:00:00"
  }
}
```

---

### POST /auth/login
`login`

Request body:
```json
{
  "email": "jane@example.com",
  "password": "secret123",
  "remember": true
}
```

Response `200`:
```json
{
  "success": true,
  "data": {
    "user_id": 1,
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "012345678",
    "roles": ["Customer"],
    "created_at": "2026-07-15T09:00:00"
  },
  "token": "eyJ1c2VyX2lkIjoxfQ.aBcDeF.signature"
}
```

Failure `401`:
```json
{
  "success": false,
  "error": "Invalid email or password."
}
```

Use the token on subsequent requests to any auth-protected endpoint:
```
Authorization: Bearer eyJ1c2VyX2lkIjoxfQ.aBcDeF.signature
```

---

### GET /auth/logout
`logout`
No request body.

---

### GET|POST /auth/profile
`profile` — `new_password` is optional (min 6 chars).

Request body:
```json
{
  "name": "Jane Doe",
  "phone": "012345678",
  "new_password": "newSecret123"
}
```

Response `200`:
```json
{
  "success": true,
  "data": {
    "user_id": 1,
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "012345678",
    "roles": ["Customer"],
    "created_at": "2026-07-15T09:00:00"
  }
}
```
