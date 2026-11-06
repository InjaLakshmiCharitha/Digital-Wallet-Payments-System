from fastapi import BackgroundTasks

from app.services.email_service import send_email


def queue_wallet_email(
    background_tasks: BackgroundTasks,
    receiver_email: str,
    full_name: str,
    event: str,
    amount: str,
    transaction_ref: str = "",
    details: str = ""
):
    messages = {
        "Money Received": (
            "Digital Wallet - Money Received",
            f"You have received ₹{amount} in your wallet."
        ),
        "Money Sent": (
            "Digital Wallet - Money Sent",
            f"Your wallet transfer of ₹{amount} has been processed."
        ),
        "Merchant Payment": (
            "Digital Wallet - Merchant Payment",
            f"Your merchant payment of ₹{amount} has been processed."
        ),
        "Merchant Refund": (
            "Digital Wallet - Merchant Refund",
            f"A merchant refund of ₹{amount} has been credited."
        ),
        "Cashback Credited": (
            "Digital Wallet - Cashback Credited",
            f"Cashback of ₹{amount} has been credited."
        ),
        "Withdrawal Completed": (
            "Digital Wallet - Withdrawal Completed",
            f"Your withdrawal of ₹{amount} has been completed."
        ),
        "Withdrawal Failed": (
            "Digital Wallet - Withdrawal Failed",
            f"Your withdrawal of ₹{amount} has failed."
        ),
        "Money Request Received": (
            "Digital Wallet - Money Request",
            f"You received a money request for ₹{amount}."
        ),
        "Low Balance Alert": (
            "Digital Wallet - Low Balance Alert",
            f"Your wallet balance is ₹{amount}, below ₹100."
        )
    }

    notification = messages.get(event)

    if not notification:
        return False

    subject, message = notification

    content = (
        f"Hello {full_name},\n\n"
        f"{message}\n"
    )

    if transaction_ref:
        content += f"\nTransaction Reference: {transaction_ref}"

    if details:
        content += f"\n\nDetails: {details}"

    content += "\n\nThank you for using Digital Wallet."

    background_tasks.add_task(
        send_email,
        receiver_email,
        subject,
        content
    )

    return True