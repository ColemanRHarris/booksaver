"""
Utility functions for BookSaver application.
Includes validation, sanitization, and helper functions.
"""

import re
import html
from urllib.parse import urlparse


def validate_url(url: str, allowed_domains: list) -> bool:
    """
    Validate that a URL belongs to allowed domains
    
    Args:
        url: The URL to validate
        allowed_domains: List of allowed domain names
        
    Returns:
        bool: True if URL is valid and from allowed domain
    """
    try:
        if not url or not url.strip():
            return False
        
        # Add https:// if no protocol specified
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        parsed = urlparse(url)
        
        # Check if domain is in allowed list
        domain = parsed.netloc.lower()
        # Remove www. prefix for comparison
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Check both with and without www. prefix
        allowed_domains_normalized = []
        for allowed_domain in allowed_domains:
            normalized = allowed_domain.lower()
            if normalized.startswith('www.'):
                normalized = normalized[4:]
            allowed_domains_normalized.append(normalized)
            allowed_domains_normalized.append('www.' + normalized)
        
        return domain in allowed_domains_normalized or any(domain.endswith('.' + d) for d in allowed_domains_normalized)
    
    except Exception:
        return False


def sanitize_input(input_str: str, max_length: int = 500) -> str:
    """
    Sanitize user input to prevent XSS and injection attacks
    
    Args:
        input_str: The input string to sanitize
        max_length: Maximum allowed length
        
    Returns:
        str: Sanitized input string
    """
    if not input_str:
        return ""
    
    # HTML escape to prevent XSS
    sanitized = html.escape(input_str.strip())
    
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized


def validate_search_query(query: str) -> str:
    """
    Validate and clean search query
    
    Args:
        query: The search query to validate
        
    Returns:
        str: Cleaned query
        
    Raises:
        ValueError: If query is invalid
    """
    if not query or not query.strip():
        raise ValueError("Search query cannot be empty")
    
    query = query.strip()
    
    # Check length
    if len(query) < 2:
        raise ValueError("Search query must be at least 2 characters long")
    
    if len(query) > 200:
        raise ValueError("Search query is too long (max 200 characters)")
    
    # Basic safety check - no control characters
    if any(ord(c) < 32 for c in query if c not in '\t\n\r'):
        raise ValueError("Search query contains invalid characters")
    
    return query


def serialize_task_result(result):
    """
    Safely serialize task result for JSON response
    
    Args:
        result: Task result to serialize
        
    Returns:
        Serializable version of result
    """
    if result is None:
        return None
    
    if isinstance(result, dict):
        return {k: serialize_task_result(v) for k, v in result.items()}
    elif isinstance(result, (list, tuple)):
        return [serialize_task_result(item) for item in result]
    elif isinstance(result, (str, int, float, bool)):
        return result
    else:
        # For any other type, convert to string
        return str(result)


def safe_get_task_result(result, key, default=None):
    """
    Safely get value from task result
    
    Args:
        result: Task result dictionary
        key: Key to retrieve
        default: Default value if key not found
        
    Returns:
        Value from result or default
    """
    if not result:
        return default
    
    if not isinstance(result, dict):
        return default
    
    return result.get(key, default)