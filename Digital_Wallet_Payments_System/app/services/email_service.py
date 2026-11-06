import os
import logging
import smtplib

from email.message import EmailMessage
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)


def send_email(
    receiver_email: str,
    subject: str,
    content: str
):
    try:
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = (
            os.getenv("SMTP_USERNAME")
            or os.getenv("SMTP_EMAIL")
        )
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_from_email = (
            os.getenv("SMTP_FROM_EMAIL")
            or smtp_username
        )

        if not all([
            receiver_email,
            smtp_host,
            smtp_username,
            smtp_password,
            smtp_from_email
        ]):
            logger.error(
                "Email sending skipped because SMTP configuration is incomplete"
            )
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = smtp_from_email
        message["To"] = receiver_email
        message.set_content(content)

        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=10
        ) as server:
            server.starttls()
            server.login(
                smtp_username,
                smtp_password
            )
            server.send_message(message)

        logger.info(
            "Email sent successfully to %s",
            receiver_email
        )

        return True

    except Exception:
        logger.exception(
            "Email sending failed for recipient %s",
            receiver_email
        )
        return False


def send_login_alert(email: str, full_name: str):
    return send_email(
        email,
        "Digital Wallet Login Alert",
        (
            f"Hello {full_name},\n\n"
            "Your Digital Wallet account was just logged in to.\n\n"
            "If this wasn't you, please contact support."
        )
    )


def send_otp_email(
    receiver_email: str,
    otp: str,
    purpose: str
):
    return send_email(
        receiver_email,
        "Digital Wallet - OTP Verification",
        (
            f"Your OTP for {purpose.replace('_', ' ').lower()} "
            f"is {otp}. It is valid for 5 minutes. "
            "Do not share this OTP with anyone."
        )
    )


def send_fraud_notification(
    receiver_email: str,
    full_name: str,
    transaction_ref: str,
    amount: str,
    status: str,
    reason: str = ""
):
    if status == "On Hold":
        subject = "Digital Wallet - Transfer On Hold"
        content = (
            f"Hello {full_name},\n\n"
            f"Your transfer of ₹{amount} has been temporarily placed on hold "
            "for security verification.\n\n"
            f"Transaction Reference: {transaction_ref}\n"
            "Our security team will review this transaction.\n\n"
            "Please contact support if you did not initiate this transfer."
        )

    elif status == "Approved":
        subject = "Digital Wallet - Transfer Approved"
        content = (
            f"Hello {full_name},\n\n"
            f"Your held transfer of ₹{amount} has been approved.\n\n"
            f"Transaction Reference: {transaction_ref}\n"
            "The money has been released to the receiver."
        )

    elif status == "Rejected":
        subject = "Digital Wallet - Transfer Rejected"
        content = (
            f"Hello {full_name},\n\n"
            f"Your held transfer of ₹{amount} has been rejected.\n\n"
            f"Transaction Reference: {transaction_ref}\n"
            "The money has been returned to your wallet."
        )

    else:
        logger.warning(
            "Unsupported fraud notification status: %s",
            status
        )
        return False

    if reason:
        content += f"\n\nReview Reason: {reason}"

    return send_email(
        receiver_email,
        subject,
        content
    )
