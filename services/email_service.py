"""
Email service for sending magic links via SendGrid or Mailgun.
"""

import os
from flask import current_app


def send_magic_link_email(email, magic_link):
    """
    Send magic link email to user.

    Tries SendGrid first, falls back to Mailgun if configured.

    Args:
        email: Recipient email address
        magic_link: Full URL to magic link verification endpoint

    Raises:
        Exception: If email sending fails or no provider is configured
    """
    # Try SendGrid first
    sendgrid_key = current_app.config.get('SENDGRID_API_KEY')
    if sendgrid_key:
        return _send_via_sendgrid(email, magic_link)

    # Fall back to Mailgun
    mailgun_key = current_app.config.get('MAILGUN_API_KEY')
    mailgun_domain = current_app.config.get('MAILGUN_DOMAIN')
    if mailgun_key and mailgun_domain:
        return _send_via_mailgun(email, magic_link)

    # No email provider configured
    raise Exception("No email provider configured. Please set SENDGRID_API_KEY or MAILGUN_API_KEY.")


def _send_via_sendgrid(email, magic_link):
    """Send email via SendGrid."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        raise Exception("SendGrid library not installed. Run: pip install sendgrid")

    from_email = current_app.config.get('MAIL_FROM_EMAIL')
    from_name = current_app.config.get('MAIL_FROM_NAME')

    # Create email content
    subject = "Your BookSaver Login Link"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .button {{ display: inline-block; padding: 12px 24px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Welcome to BookSaver!</h2>
            <p>Click the button below to log in to your account. This link will expire in 15 minutes.</p>
            <a href="{magic_link}" class="button">Log In to BookSaver</a>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #007bff;">{magic_link}</p>
            <div class="footer">
                <p>If you didn't request this email, you can safely ignore it.</p>
                <p>This is an automated email from BookSaver. Please do not reply.</p>
            </div>
        </div>
    </body>
    </html>
    """

    plain_content = f"""
    Welcome to BookSaver!

    Click the link below to log in to your account. This link will expire in 15 minutes.

    {magic_link}

    If you didn't request this email, you can safely ignore it.
    """

    message = Mail(
        from_email=(from_email, from_name),
        to_emails=email,
        subject=subject,
        html_content=html_content,
        plain_text_content=plain_content
    )

    try:
        sg = SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])
        response = sg.send(message)
        current_app.logger.info(f"Magic link sent via SendGrid to {email}, status: {response.status_code}")
        return True
    except Exception as e:
        current_app.logger.error(f"SendGrid error: {e}")
        raise Exception(f"Failed to send email via SendGrid: {e}")


def _send_via_mailgun(email, magic_link):
    """Send email via Mailgun."""
    import requests

    domain = current_app.config['MAILGUN_DOMAIN']
    api_key = current_app.config['MAILGUN_API_KEY']
    from_email = current_app.config.get('MAIL_FROM_EMAIL')
    from_name = current_app.config.get('MAIL_FROM_NAME')

    # Create email content
    subject = "Your BookSaver Login Link"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .button {{ display: inline-block; padding: 12px 24px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Welcome to BookSaver!</h2>
            <p>Click the button below to log in to your account. This link will expire in 15 minutes.</p>
            <a href="{magic_link}" class="button">Log In to BookSaver</a>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #007bff;">{magic_link}</p>
            <div class="footer">
                <p>If you didn't request this email, you can safely ignore it.</p>
                <p>This is an automated email from BookSaver. Please do not reply.</p>
            </div>
        </div>
    </body>
    </html>
    """

    plain_content = f"""
    Welcome to BookSaver!

    Click the link below to log in to your account. This link will expire in 15 minutes.

    {magic_link}

    If you didn't request this email, you can safely ignore it.
    """

    try:
        response = requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"{from_name} <{from_email}>",
                "to": email,
                "subject": subject,
                "text": plain_content,
                "html": html_content
            }
        )
        response.raise_for_status()
        current_app.logger.info(f"Magic link sent via Mailgun to {email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Mailgun error: {e}")
        raise Exception(f"Failed to send email via Mailgun: {e}")
