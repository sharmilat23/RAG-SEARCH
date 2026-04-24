import sys
import os
from flask import Flask

# Add root directory to path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app import app, db
from models import User
from werkzeug.security import generate_password_hash

def create_test_user():
    with app.app_context():
        # Check if user already exists
        user = User.query.filter_by(username='loki').first()
        if user:
            print("Test user already exists. Updating email verification...")
            user.email_verified = True
            db.session.commit()
            print("Updated test user to verified!")
            print("Username: loki")
            print("Email: loki@test.com")
            print("Password: Loki@123")
            return

        # Create new test user
        new_user = User(
            username='loki',
            email='loki@test.com',
            password_hash=generate_password_hash('Loki@123', method='pbkdf2:sha256'),
            email_verified=True
        )
        db.session.add(new_user)
        db.session.commit()
        print("Test user created successfully!")
        print("Username: loki")
        print("Email: loki@test.com")
        print("Password: Loki@123")

if __name__ == '__main__':
    create_test_user()
