# Digital Wallet & Payments System

## Project Overview

The Digital Wallet & Payments System is a secure wallet and payment management backend developed using Python and FastAPI.

It allows users to register, manage wallet balances, transfer money, make merchant payments, request money, link bank accounts, withdraw funds, and view transaction statements.

The system also provides administrator controls, merchant management, KYC verification, double-entry ledger accounting, fraud detection, notifications, scheduled payments, and financial reports.

## Technologies Used

- Python 3.12
- FastAPI
- Pydantic
- SQLAlchemy
- MySQL 8.0
- Alembic
- JWT Authentication
- Passlib / bcrypt
- Redis
- APScheduler
- WebSockets
- SMTP
- ReportLab
- Razorpay Test Mode
- Docker and Docker Compose
- Pytest

## Features

### 1. Authentication and Authorization
- User, Merchant, and Admin roles
- User and Merchant registration
- Secure password hashing
- JWT authentication
- 30-minute access token expiration
- Role-based access control
- Login email notifications
- Admin account creation through a separate Python script

### 2. Wallet Management
- Automatic wallet creation
- Wallet balance management
- Add money
- Wallet-to-wallet transfers
- Wallet freeze and unfreeze
- Transaction PIN verification
- OTP verification

### 3. KYC Management
- KYC submission
- PAN and Aadhaar verification details
- Admin KYC approval and rejection
- Wallet KYC level updates

### 4. Money Transfers
- Transfer money using receiver phone number
- Transaction PIN verification
- OTP verification where required
- Idempotency protection
- Transaction history
- Transfer status tracking

### 5. Merchant Payments
- Merchant registration
- Merchant approval
- QR-based payments
- Merchant payment history
- Merchant refunds
- Merchant sales reports

### 6. Bank and Withdrawal Management
- Link bank accounts
- Bank account verification using OTP
- Wallet withdrawals
- Withdrawal status tracking
- Scheduled withdrawal processing

### 7. Additional Features
- Money requests
- Cashback processing
- Fraud detection
- Flagged transaction review
- Email notifications
- In-app notifications
- Live WebSocket notifications
- Scheduled payments
- Mobile recharge simulation
- Electricity bill payment simulation
- Razorpay test-mode integration
- PDF and CSV wallet statements
- Password-protected PDF statements

### 8. Reports and Analytics
- Admin dashboard
- Ledger summary
- Merchant sales report
- User spending report

### 9. Background Jobs
- Cashback processing
- Pending withdrawal processing
- Money request expiration
- Expired OTP cleanup
- Idempotency key cleanup
- Daily ledger reconciliation
- Scheduled payment execution

## Project Structure

Digital_Wallet_Payments_System/
│
├── app/
│   ├── auth/
│   ├── jobs/
│   ├── models/
│   ├── routers/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   ├── create_admin.py
│   ├── database.py
│   └── main.py
│
├── alembic/
│   ├── versions/
│   └── env.py
│
├── statements/
│   └── statement_service.py
│
├── tests/
│   ├── test_transfers.py
│   ├── test_idempotency.py
│   ├── test_limits.py
│   ├── test_locking.py
│   └── test_ledger.py
│
├── .env
├── .dockerignore
├── .gitignore
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md

## Installation and Setup

### Prerequisites

Install the following software:

- Python 3.12 or later
- MySQL 8.0
- Docker Desktop
- Git

### 1. Clone the Repository

git clone YOUR_GITHUB_REPOSITORY_URL
cd Digital_Wallet_Payments_System


### 2. Create a Virtual Environment

python -m venv venv
venv\Scripts\activate


### 3. Install Dependencies

pip install -r requirements.txt


### 4. Configure Environment Variables

Create a '.env' file in the project root directory.

```env
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/digital_wallet_db

SECRET_KEY=YOUR_SECRET_KEY
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_FROM_EMAIL=your_email@gmail.com

ADMIN_EMAIL=admin@gmail.com

RAZORPAY_KEY_ID=your_razorpay_test_key_id
RAZORPAY_KEY_SECRET=your_razorpay_test_key_secret
```


## SMTP Configuration

The application uses SMTP for sending email notifications.

For Gmail:

1. Open your Google Account.
2. Enable 2-Step Verification.
3. Generate an App Password.
4. Add your Gmail address to 'SMTP_USERNAME'.
5. Add your generated App Password to 'SMTP_PASSWORD'.
6. Configure 'SMTP_FROM_EMAIL' with your Gmail address.

Email notifications are used for:
- Login alerts
- Money sent and received
- Merchant payments
- Refunds
- Cashback credits
- Withdrawal updates
- Money requests
- Transfer status updates

Valid SMTP credentials are required for actual email delivery.

## Database Setup

Create the MySQL database:
CREATE DATABASE digital_wallet_db;

Configure the database connection in '.env'.

## Alembic Database Migrations
Alembic is used to manage database schema changes.

### Apply all migrations
alembic upgrade head


### Create a new migration
alembic revision --autogenerate -m "description"


### Check current migration
alembic current


### View migration history
alembic history


### Roll back one migration
alembic downgrade -1


### Docker migration command

docker compose run --rm api alembic upgrade head

All existing migration files are maintained in:
alembic/versions/


## Running the Application

### Option 1: Run Using Docker Compose

Build Docker images:
docker compose build

Start MySQL and Redis:
docker compose up -d db redis

Apply database migrations:
docker compose run --rm api alembic upgrade head

Start the API:
docker compose up -d api

Check running containers:
docker compose ps

View API logs:
docker compose logs api


### Option 2: Run Locally

Activate the virtual environment and apply migrations:
alembic upgrade head


Start the FastAPI server:
uvicorn app.main:app --reload


## Admin Account Creation
Admin registration is not available through the public registration API.

Create an Admin account using:
python -m app.create_admin

For Docker:
docker compose cp app/create_admin.py api:/app/app/create_admin.py
docker compose exec api python -m app.create_admin

Enter the Admin name, email, phone number, and password when prompted.

## Swagger API Documentation
After starting the application, access:

**Swagger UI:** http://localhost:8000/docs

**ReDoc:** http://localhost:8000/redoc

Swagger UI can be used to register accounts, log in, authorize using JWT tokens, and test the available APIs.


## Ledger Design
The application uses a **Double-Entry Ledger Accounting System** to maintain financial transaction records.

Every successful financial transaction creates corresponding debit and credit entries.

The total debit amount must always equal the total credit amount.


## Idempotency
Idempotency prevents duplicate financial processing when the same API request is submitted multiple times.


## Testing
The project uses Pytest for automated testing.

Run all tests:
python -m pytest -v

Run individual test files:
python -m pytest tests/test_transfers.py -v
python -m pytest tests/test_idempotency.py -v
python -m pytest tests/test_limits.py -v
python -m pytest tests/test_locking.py -v
python -m pytest tests/test_ledger.py -v


## Swagger API Testing 
1. User registration
2. Merchant registration
3. Admin login
4. User login
5. Merchant login
6. Wallet details
7. KYC submission
8. KYC approval
9. Add money
10. Money transfer
11. Merchant payment
12. Refund
13. Withdrawal
14. Money request
15. Transaction history
16. Admin reports


## Assumptions and Business Rules
1. The application uses INR (Indian Rupees) as its currency.
2. Public registration supports User and Merchant roles only.
3. Admin accounts are created separately.
4. Every registered User or Merchant receives a wallet automatically.
5. Merchants require Admin approval for restricted merchant operations.
6. KYC approval and rejection are controlled by the Admin.
7. Frozen wallets cannot perform restricted financial transactions.
8. Transaction PIN and OTP verification are required where applicable.
9. Transaction amounts must be positive and support a maximum of two decimal places.
10. Idempotency keys prevent duplicate processing of supported financial requests.
11. Financial transactions use double-entry ledger records.
12. Wallet and account updates are performed within database transactions.
13. Scheduled jobs process eligible cashback, withdrawals, cleanup, reconciliation, and scheduled payments.
14. Email notifications require valid SMTP configuration.
15. Razorpay integration uses test credentials.
16. Bill payments are simulated for mobile recharge and electricity payments.
17. PDF statements are password-protected using the statement password generation rule implemented in the application.
18. WebSocket notifications require a valid authentication token.
19. Test credentials are intended only for development and demonstration.
20. The application is developed for educational and demonstration purposes.

## Security Considerations

- Passwords are stored as hashes.
- JWT tokens provide authentication.
- Role-based access control protects restricted APIs.
- Sensitive configuration is stored in environment variables.
- Transaction PIN and OTP verification protect financial operations.
- Database transactions maintain ledger consistency.
- Idempotency prevents duplicate financial requests.
- '.env', database credentials, SMTP passwords, and payment gateway secrets must never be committed to GitHub.



