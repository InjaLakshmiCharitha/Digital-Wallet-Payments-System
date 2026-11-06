import re

from app.database import SessionLocal
from app.models import User
from app.auth.security import hash_password


db = SessionLocal()

try:
    print("\n===== CREATE ADMIN ACCOUNT =====")

    full_name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    phone = input("Admin phone (10 digits): ").strip()
    password = input("Admin password: ")
    confirm_password = input("Confirm password: ")

    if not full_name:
        raise ValueError("Admin name is required.")

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")

    if not re.fullmatch(r"[0-9]{10}", phone):
        raise ValueError("Phone number must contain exactly 10 digits.")

    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")

    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    existing_user = db.query(User).filter(
        (User.email == email) | (User.phone == phone)
    ).first()

    if existing_user:
        raise ValueError("Email or phone number is already registered.")

    admin = User(
        full_name=full_name,
        email=email,
        phone=phone,
        password_hash=hash_password(password),
        role="Admin",
        is_active=True
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    print("\nAdmin account created successfully!")
    print("Admin ID:", admin.id)
    print("Admin Email:", admin.email)
    print("Admin Role:", admin.role)

except Exception as error:
    db.rollback()
    print("\nAdmin creation failed:", error)

finally:
    db.close()

