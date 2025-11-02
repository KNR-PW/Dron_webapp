import os
from werkzeug.security import generate_password_hash
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# In-memory user store (for demo purposes)
default_admin_password = os.getenv("ADMIN_PASSWORD", "admin")

users = {
    "admin": User(id=1, username="admin", password_hash=generate_password_hash(default_admin_password))
}


def load_user(user_id):
    for user in users.values():
        if str(user.id) == str(user_id):
            return user
    return None

