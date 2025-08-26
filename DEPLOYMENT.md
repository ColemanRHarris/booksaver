# BookSaver Deployment Guide

## Environment Variables Setup

### Required Gmail SMTP Configuration

For password reset functionality to work, configure these Gmail SMTP variables:

```bash
# Gmail SMTP Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_gmail@gmail.com
SMTP_PASSWORD=your_16_character_app_password
FROM_EMAIL=your_gmail@gmail.com
```

### Gmail App Password Setup

1. **Enable 2-Factor Authentication** on your Gmail account
2. Go to **Google Account Settings → Security**
3. Under **"2-Step Verification"** → **"App passwords"**
4. Select **"Mail"** as the app type  
5. Copy the generated **16-character app password**
6. Use this app password in `SMTP_PASSWORD` (NOT your regular Gmail password)

### Other Environment Variables

```bash
# Core Application
SECRET_KEY=your-secure-secret-key-here
FLASK_ENV=production  # or development
GEMINI_API_KEY=your_gemini_api_key
REDIS_URL=your_redis_url

# Optional
GOOGLE_BOOKS_KEY=your_google_books_api_key
PORT=5000
```

## Render.com Deployment

### Step 1: Environment Variables in Render

In your Render.com dashboard:

1. Go to your service settings
2. Navigate to "Environment Variables"
3. Add all the variables listed above
4. **Critical**: Use the Gmail App Password for `SMTP_PASSWORD`

### Step 2: Verify Email Configuration

After deployment:

1. Test password reset functionality
2. Check Render logs for email-related errors

### Step 3: Gmail Security Settings

- Ensure the Gmail account has 2FA enabled
- The app password should be specific to this application
- Monitor Gmail's sending limits (500 emails/day for personal accounts)

## Development Setup

### Local Environment

1. Copy `.env.example` to `.env`
2. Configure Gmail SMTP variables
3. Run: `python app.py`

### Testing Email Configuration

Test the password reset functionality by attempting to reset a password for a known email address.

## Troubleshooting

### Email Not Sending

**Error**: `SMTP not configured`
- **Solution**: Check `SMTP_USERNAME` and `SMTP_PASSWORD` are set

**Error**: `Authentication failed`  
- **Solution**: Use App Password, not regular Gmail password
- **Solution**: Verify 2FA is enabled on Gmail account

**Error**: `Connection refused`
- **Solution**: Check `SMTP_SERVER=smtp.gmail.com` and `SMTP_PORT=587`

### Gmail Limits

- **Personal Gmail**: 500 emails/day
- **Google Workspace**: 2000 emails/day
- Monitor usage if you have many users

### Security Considerations

1. **Never commit credentials** to version control
2. **Rotate app passwords** periodically  
3. **Monitor failed login attempts** in Gmail security settings
4. **Consider Gmail Workspace** for higher sending limits in production

## Production Recommendations

### Email Service Upgrade

For production with high email volume, consider:

- **SendGrid**: Better deliverability, analytics
- **AWS SES**: Scalable, cost-effective
- **Mailgun**: Developer-friendly APIs

### Monitoring

- Set up alerts for email delivery failures
- Monitor Gmail quota usage
- Track password reset success rates

### Backup Plans

- Document manual password reset process for administrators
- Have alternative contact methods for users
- Consider implementing admin password reset functionality

## Support

- Check application logs for detailed error messages
- Gmail App Password help: [support.google.com](https://support.google.com/accounts/answer/185833)