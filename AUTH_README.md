# Authentication Guide

## Default Credentials

The webapp now requires authentication to access all pages and API endpoints.

**Default Login:**
- **Username:** `admin`
- **Password:** `admin123`

## Security Notes

1. **Change the default password in production!** The default credentials are for development/testing only.
2. The SECRET_KEY can be set via environment variable:
   ```bash
   export SECRET_KEY="your-secure-random-key-here"
   ```
3. In production, consider using a proper database for user management instead of the in-memory storage.

## Adding More Users

To add more users, edit the `users` dictionary in `app.py`:

```python
users = {
    "admin": User(
        id="1",
        username="admin",
        password_hash=generate_password_hash("admin123"),
    ),
    "newuser": User(
        id="2",
        username="newuser",
        password_hash=generate_password_hash("newpassword"),
    )
}
```

## Protected Endpoints

All routes now require authentication:
- `/` - Dashboard
- `/api/status` - Drone status API
- `/api/image` - Image upload API
- `/api/images` - Image list/delete API
- `/api/log` - Mission log API
- `/api/telemetry` - Telemetry API
- `/images/<filename>` - Image serving
- `/video_feed` - Video feed

## Public Endpoints

Only these endpoints are public:
- `/login` - Login page
- `/static/*` - Static files (CSS, JS, images)
