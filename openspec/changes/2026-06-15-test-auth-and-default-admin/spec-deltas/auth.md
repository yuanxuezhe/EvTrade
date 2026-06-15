# Auth — Spec Delta

## ADDED Requirements

### REQ-AUTH-003: Test Coverage for Default Admin Seed

The system **MUST** provide test coverage proving that:

- **REQ-AUTH-003.1**: When `users` table is empty at startup, a default `admin/admin123` account is seeded.
- **REQ-AUTH-003.2**: Login authenticates against the `users` table (rejects unknown users with 401).
- **REQ-AUTH-003.3**: Login updates `last_login_at` timestamp on success.

#### Scenario: Empty users table → admin seeded → admin login works
- **Given** `users` table is empty
- **When** application startup runs
- **Then** an admin user with `username="admin"`, `role="admin"`, `password_hash=bcrypt("admin123")` is created
- **And** `POST /api/auth/login` with `admin/admin123` returns 200 + JWT token

#### Scenario: Invalid password rejected
- **Given** an admin user exists
- **When** `POST /api/auth/login` with `admin/wrong`
- **Then** response is 401 with "用户名或密码错误"

#### Scenario: Unknown user rejected (not bypassed)
- **Given** `users` table is empty
- **When** `POST /api/auth/login` with `nobody/something`
- **Then** response is 401 (not 200)

#### Scenario: last_login_at updated on success
- **Given** an admin user with `last_login_at = NULL`
- **When** `POST /api/auth/login` with `admin/admin123`
- **Then** user's `last_login_at` is set to current UTC time
