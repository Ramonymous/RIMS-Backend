# ProjectRIMS Backend Installation Guide

## Overview
This guide walks you through setting up the ProjectRIMS backend from scratch using the interactive installation wizard.

---

## Prerequisites

### 1. PostgreSQL Database
- **Version:** PostgreSQL 12 or higher
- **Access:** Admin credentials (username & password)
- **Status:** PostgreSQL service must be running

### 2. Python Environment
- **Version:** Python 3.11 or higher
- **Virtual Environment:** Recommended

---

## Quick Start

### Step 1: Clone Repository
```bash
cd d:\DEVELOPMENT\APPS\ProjectDesktop\backend
```

### Step 2: Create Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Run Installation Wizard
```bash
python install.py
```

The interactive wizard will guide you through:
1. **.env Configuration** - Database credentials, secret key, CORS settings
2. **PostgreSQL Connection Check** - Verify database server is accessible
3. **Database Creation** - Automatically create application database
4. **Database Connection Test** - Verify app can connect to the database
5. **Migrations** - Apply database schema (creates all 10 tables)
6. **Admin User Creation** - Create initial administrator account

---

## Installation Wizard Walkthrough

### Screen 1: Environment Configuration

```
📝 Let's configure your environment:

Database Configuration:
Database host [localhost]: 
Database port [5432]: 
Database user [postgres]: 
Database password: ********
Database name [project_rims]: project_rims

Security:
ℹ  Generated secret key: <random-key>
Use custom secret key? (leave empty to use generated): 

CORS Configuration:
Allowed origins (comma-separated) [http://localhost:3000,http://localhost:8080]: 
```

**Notes:**
- Press Enter to accept default values (shown in brackets)
- Password input is hidden for security
- Secret key is auto-generated using `secrets.token_urlsafe(32)`
- CORS origins should include your desktop app URL (e.g., `http://localhost:8080`)

### Screen 2: PostgreSQL Connection Check

```
============================================================
  Checking PostgreSQL Connection
============================================================

✓ Connected to PostgreSQL at localhost:5432
```

**If this fails:**
- Verify PostgreSQL service is running
- Check firewall settings
- Confirm credentials are correct

### Screen 3: Database Creation

```
============================================================
  Database Creation
============================================================

✓ Database 'project_rims' created successfully!
```

**Notes:**
- If database already exists, wizard will skip creation
- Uses `CREATE DATABASE` command via asyncpg

### Screen 4: Database Connection Test

```
============================================================
  Testing Database Connection
============================================================

✓ Database connection successful!
ℹ  Database: project_rims
ℹ  PostgreSQL: PostgreSQL 18.1 on x86_64-windows...
```

### Screen 5: Run Migrations

```
============================================================
  Running Database Migrations
============================================================

ℹ  Applying migrations...
✓ Migrations applied successfully!
ℹ  Tables created: 10
```

**Tables created:**
1. `users`
2. `parts`
3. `receivings`
4. `receiving_items`
5. `outgoings`
6. `outgoing_items`
7. `requests`
8. `request_lists`
9. `part_movements`
10. `alembic_version`

### Screen 6: Admin User Creation

```
============================================================
  Create Admin User
============================================================

Create admin user? (yes/no) [yes]: yes

👤 Admin User Details:

Name [Admin]: System Administrator
Email [admin@projectrims.local]: admin@example.com
Password (min 8 characters): ********
Confirm password: ********
✓ Admin user 'admin@example.com' created successfully!
ℹ  Permissions granted: 28
```

**Default Permissions:**
The admin user is granted all available permissions:

**Users:**
- `users.view`, `users.create`, `users.update`, `users.delete`

**Parts:**
- `parts.view`, `parts.create`, `parts.update`, `parts.delete`

**Receivings:**
- `receivings.view`, `receivings.create`, `receivings.update`, `receivings.delete`
- `receivings.complete`, `receivings.cancel`, `receivings.confirm_gr`

**Outgoings:**
- `outgoings.view`, `outgoings.create`, `outgoings.update`, `outgoings.delete`
- `outgoings.complete`, `outgoings.cancel`, `outgoings.confirm_gi`

**Requests:**
- `requests.view`, `requests.create`, `requests.update`, `requests.delete`
- `requests.complete`, `requests.cancel`

---

## Post-Installation

### Start Development Server

```bash
uvicorn app.main:app --reload
```

Server will start at: `http://localhost:8000`

### Access API Documentation

Open your browser:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### Test API Connection

```bash
curl http://localhost:8000
# Response: {"message":"ProjectRIMS API is running","status":"ok"}
```

### Test Admin Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}'
```

**Expected Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": "uuid-here",
    "name": "System Administrator",
    "email": "admin@example.com",
    "permissions": ["users.view", "users.create", ...]
  }
}
```

---

## Generated Files

### .env
```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/project_rims

# Security
SECRET_KEY=<generated-secret-key>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080
```

**Security Notes:**
- **Never commit .env to version control**
- .env is listed in .gitignore
- SECRET_KEY should be unique per environment
- Use strong passwords for database credentials

---

## Troubleshooting

### Database Connection Failed

**Error:** `Cannot connect to PostgreSQL`

**Solutions:**
1. Verify PostgreSQL is running:
   ```bash
   Get-Service -Name postgresql*  # Windows
   sudo systemctl status postgresql  # Linux
   ```

2. Check PostgreSQL configuration:
   - Listen address in `postgresql.conf`
   - Client authentication in `pg_hba.conf`

3. Test connection manually:
   ```bash
   psql -U postgres -h localhost -p 5432
   ```

### Migration Failed

**Error:** `Migration failed: <error>`

**Solutions:**
1. Check database exists:
   ```bash
   psql -U postgres -l | grep project_rims
   ```

2. Verify alembic configuration:
   ```bash
   alembic current
   alembic history
   ```

3. Reset migrations (⚠️ **destroys data**):
   ```bash
   alembic downgrade base
   alembic upgrade head
   ```

### Admin User Already Exists

**Error:** `duplicate key value violates unique constraint "users_email_key"`

**Solution:**
- Admin user already created
- Use existing credentials or update password via database

### Import Errors

**Error:** `ModuleNotFoundError: No module named 'app'`

**Solution:**
1. Ensure virtual environment is activated
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Re-running Installation

If you need to reinstall:

### Option 1: Start Fresh (⚠️ **destroys all data**)

```bash
# Drop database
python -c "import asyncio, asyncpg; asyncio.run((lambda: asyncpg.connect(user='postgres', password='<password>', database='postgres').execute('DROP DATABASE project_rims'))())"

# Remove .env
Remove-Item .env

# Run installer
python install.py
```

### Option 2: Partial Reinstall

**Reset database only:**
```bash
alembic downgrade base
alembic upgrade head
```

**Recreate admin user:**
```sql
DELETE FROM users WHERE email = 'admin@example.com';
```
Then run `python install.py` and select "yes" for admin user creation.

---

## Next Steps

1. **Configure CORS** - Add desktop app URL to `ALLOWED_ORIGINS` in .env
2. **Create Additional Users** - Use API endpoints or admin panel
3. **Import Master Data** - Load parts catalog via API
4. **Setup Desktop App** - Configure `API_BASE_URL` in desktop/.env
5. **Production Deployment** - Use proper PostgreSQL instance, HTTPS, reverse proxy

---

## Support

For issues:
1. Check logs: `logs/app.log`
2. Verify .env configuration
3. Test database connection: `python test_db_connection.py`
4. Review API docs: http://localhost:8000/docs
