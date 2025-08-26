"""
Email service for sending password reset and notification emails.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from core.logging_utils import get_safe_logger


class EmailService:
    def __init__(self):
        """Initialize email service with SMTP configuration."""
        self.logger = get_safe_logger(__name__)
        
        # SMTP Configuration from environment
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', 'noreply@booksaver.com')
        
        # Check if email is configured
        self.is_configured = bool(self.smtp_username and self.smtp_password)
        
        if not self.is_configured:
            self.logger.warning("⚠️ Email service not configured - missing SMTP credentials")
        else:
            self.logger.info(f"✅ Email service configured for {self.smtp_server}:{self.smtp_port}")
    
    def send_password_reset_email(self, to_email: str, reset_token: str, reset_url: str) -> bool:
        """Send password reset email to user."""
        if not self.is_configured:
            self.logger.error("❌ Cannot send email - SMTP not configured")
            return False
        
        try:
            subject = "Reset Your BookSaver Password"
            
            # Create HTML email content
            html_content = self._get_password_reset_html(to_email, reset_token, reset_url)
            
            # Create text fallback
            text_content = f"""
Hi there,

You recently requested to reset your password for your BookSaver account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour for security reasons.

If you didn't request this password reset, please ignore this email.

Best regards,
The BookSaver Team

---
This is an automated message. Please do not reply to this email.
"""
            
            return self._send_email(to_email, subject, text_content, html_content)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send password reset email to {to_email}: {e}")
            return False
    
    def _get_password_reset_html(self, to_email: str, reset_token: str, reset_url: str) -> str:
        """Get HTML content for password reset email."""
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Your BookSaver Password</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8f9fa;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .logo {{
            font-size: 24px;
            font-weight: 700;
            color: #3b82f6;
            margin-bottom: 10px;
        }}
        .title {{
            color: #1f2937;
            font-size: 20px;
            margin-bottom: 20px;
        }}
        .content {{
            margin-bottom: 30px;
        }}
        .reset-button {{
            display: inline-block;
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            color: white;
            text-decoration: none;
            padding: 14px 28px;
            border-radius: 8px;
            font-weight: 600;
            text-align: center;
            margin: 20px 0;
        }}
        .reset-button:hover {{
            background: linear-gradient(135deg, #1d4ed8, #1e40af);
        }}
        .security-notice {{
            background: #fef3c7;
            border: 1px solid #f59e0b;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
            color: #6b7280;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">📚 BookSaver</div>
            <h1 class="title">Reset Your Password</h1>
        </div>
        
        <div class="content">
            <p>Hi there,</p>
            <p>You recently requested to reset your password for your BookSaver account (<strong>{to_email}</strong>).</p>
            <p>Click the button below to reset your password:</p>
            
            <div style="text-align: center;">
                <a href="{reset_url}" class="reset-button">Reset My Password</a>
            </div>
            
            <div class="security-notice">
                <strong>⚠️ Security Notice:</strong> This link will expire in 1 hour for your security. If you didn't request this password reset, please ignore this email.
            </div>
            
            <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #3b82f6;">{reset_url}</p>
        </div>
        
        <div class="footer">
            <p>Best regards,<br>The BookSaver Team</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #e5e7eb;">
            <p><small>This is an automated message. Please do not reply to this email.</small></p>
        </div>
    </div>
</body>
</html>
"""
    
    def _send_email(self, to_email: str, subject: str, text_content: str, html_content: str = None) -> bool:
        """Send email using SMTP."""
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Add text content
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
            
            # Add HTML content if provided
            if html_content:
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)
            
            # Connect to server and send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Enable encryption
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            self.logger.info(f"✅ Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send email to {to_email}: {e}")
            return False
    
    def send_test_email(self, to_email: str) -> bool:
        """Send a test email to verify SMTP configuration."""
        if not self.is_configured:
            return False
        
        subject = "BookSaver Email Service Test"
        content = """
This is a test email from BookSaver to verify your email configuration is working correctly.

If you received this email, your SMTP settings are configured properly!

Best regards,
BookSaver Email Service
"""
        
        return self._send_email(to_email, subject, content)


# Global email service instance
email_service = None


def get_email_service() -> EmailService:
    """Get the email service instance, creating it if needed."""
    global email_service
    if email_service is None:
        email_service = EmailService()
    return email_service