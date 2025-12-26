"""Input sanitization and validation utilities."""

import html
import os
import re
import shlex
from typing import Any, Optional
from urllib.parse import urlparse


# Maximum lengths for various inputs
MAX_GOAL_LENGTH = 2000
MAX_PARAM_STRING_LENGTH = 10000
MAX_URL_LENGTH = 2048
MAX_PATH_LENGTH = 4096


# Dangerous patterns to detect
SHELL_INJECTION_PATTERNS = [
    r';\s*\w',           # Command chaining
    r'\|',               # Pipe
    r'&&',               # AND operator
    r'\|\|',             # OR operator
    r'\$\(',             # Command substitution
    r'`',                # Backtick substitution
    r'\$\{',             # Variable expansion
    r'>\s*/',            # Output redirection
    r'<\s*/',            # Input redirection
    r'\n',               # Newlines
    r'\r',               # Carriage returns
]

PATH_TRAVERSAL_PATTERNS = [
    r'\.\.\/',           # Parent directory
    r'\.\.\\',           # Parent directory (Windows)
    r'\/\.\./',          # Hidden parent
    r'\\\.\.\\',         # Hidden parent (Windows)
]

SQL_INJECTION_PATTERNS = [
    r"'\s*OR\s+'",       # OR injection
    r"'\s*;\s*--",       # Comment injection
    r"UNION\s+SELECT",   # UNION injection
    r"DROP\s+TABLE",     # DROP injection
    r"INSERT\s+INTO",    # INSERT injection
]


def sanitize_string(
    value: str,
    max_length: int = MAX_PARAM_STRING_LENGTH,
    allow_newlines: bool = False,
    strip_html: bool = True,
) -> str:
    """
    Sanitize a string value.

    Args:
        value: String to sanitize.
        max_length: Maximum allowed length.
        allow_newlines: Whether to preserve newlines.
        strip_html: Whether to escape HTML.

    Returns:
        Sanitized string.
    """
    # Truncate to max length
    if len(value) > max_length:
        value = value[:max_length]

    # Strip or escape newlines
    if not allow_newlines:
        value = value.replace('\n', ' ').replace('\r', '')

    # Escape HTML entities
    if strip_html:
        value = html.escape(value)

    # Strip null bytes
    value = value.replace('\x00', '')

    return value.strip()


class PromptInjectionError(ValueError):
    """Raised when prompt injection is detected and blocked."""
    pass


def sanitize_goal(
    goal: str,
    mode: str = "strict",
    raise_on_injection: bool = True,
) -> str:
    """
    Sanitize a goal description.

    Removes potentially dangerous content from user-provided goals
    before passing to the LLM. Can detect and block prompt injection attempts.

    Args:
        goal: Raw goal description.
        mode: Sanitization mode ('strict', 'moderate', 'permissive').
        raise_on_injection: If True, raise exception on injection detection.

    Returns:
        Sanitized goal description.

    Raises:
        PromptInjectionError: If injection detected and raise_on_injection=True.
    """
    original_goal = goal
    
    # Basic sanitization
    goal = sanitize_string(goal, max_length=MAX_GOAL_LENGTH, allow_newlines=True)

    # Prompt injection patterns - organized by severity
    critical_patterns = [
        r'ignore\s+(previous|above|all)\s+(instructions|directives)',
        r'disregard\s+(previous|above|all)',
        r'(forget|override)\s+(everything|all|instructions)',
        r'new\s+(instructions|directives|system\s+prompt)',
        r'you\s+are\s+now\s+a',  # Role override attempts
        r'pretend\s+you\s+are',
        r'act\s+as\s+if',
    ]
    
    moderate_patterns = [
        r'system:\s*(?!$)',  # System role injection (not empty)
        r'assistant:\s*(?!$)',  # Assistant role injection
        r'user:\s*(?!$)',  # User role injection
        r'\[INST\]',  # Llama instruction tokens
        r'\[/INST\]',
        r'<\|im_start\|>',  # ChatML tokens
        r'<\|im_end\|>',
        r'```\s*(python|bash|sh|javascript)',  # Code block injection
        r'<\|.*?\|>',  # Generic special tokens
    ]
    
    permissive_patterns = [
        r'disregard\s+this',
        r'ignore\s+this',
    ]

    # Check based on mode
    patterns_to_check = []
    if mode == "strict":
        patterns_to_check = critical_patterns + moderate_patterns + permissive_patterns
    elif mode == "moderate":
        patterns_to_check = critical_patterns + moderate_patterns
    elif mode == "permissive":
        patterns_to_check = critical_patterns
    else:
        raise ValueError(f"Invalid sanitization mode: {mode}")

    # Detect injections
    detected_patterns = []
    for pattern in patterns_to_check:
        if re.search(pattern, goal, flags=re.IGNORECASE):
            detected_patterns.append(pattern)
            if raise_on_injection:
                raise PromptInjectionError(
                    f"Potential prompt injection detected in goal. "
                    f"Pattern: {pattern}. Original: {original_goal[:100]}"
                )

    # If not raising, sanitize by removal
    for pattern in patterns_to_check:
        goal = re.sub(pattern, '[REMOVED]', goal, flags=re.IGNORECASE)

    # Additional safety: remove excessive special characters
    if mode == "strict":
        # Limit consecutive special characters
        goal = re.sub(r'[^\w\s]{5,}', '...', goal)
        # Remove unusual Unicode ranges that might confuse models
        goal = ''.join(c for c in goal if ord(c) < 0x2000 or ord(c) > 0x2BFF)

    result = goal.strip()
    
    # Ensure we still have meaningful content
    if len(result) < 10:
        raise ValueError("Goal description too short after sanitization (minimum 10 characters)")
    
    return result


def sanitize_params(
    params: dict[str, Any],
    allow_shell_chars: bool = False,
) -> dict[str, Any]:
    """
    Sanitize a dictionary of parameters.

    Args:
        params: Parameters to sanitize.
        allow_shell_chars: Whether to allow shell-related characters.

    Returns:
        Sanitized parameters.
    """
    def sanitize_value(value: Any) -> Any:
        if isinstance(value, str):
            value = sanitize_string(value)
            if not allow_shell_chars:
                for pattern in SHELL_INJECTION_PATTERNS:
                    value = re.sub(pattern, '', value)
            return value
        elif isinstance(value, dict):
            return {k: sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [sanitize_value(item) for item in value]
        else:
            return value

    return {k: sanitize_value(v) for k, v in params.items()}


def escape_for_shell(value: str) -> str:
    """
    Escape a string for safe use in shell commands.

    Uses shlex.quote for proper escaping.

    Args:
        value: String to escape.

    Returns:
        Shell-safe string.
    """
    # Remove null bytes first
    value = value.replace('\x00', '')

    # Use shlex.quote for proper escaping
    return shlex.quote(value)


def validate_url(
    url: str,
    allowed_schemes: Optional[list[str]] = None,
    allowed_hosts: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """
    Validate a URL for safety.

    Args:
        url: URL to validate.
        allowed_schemes: List of allowed schemes (default: ['http', 'https']).
        allowed_hosts: Optional list of allowed hostnames.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if allowed_schemes is None:
        allowed_schemes = ['http', 'https']

    # Check length
    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH}"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    # Check scheme
    if parsed.scheme.lower() not in allowed_schemes:
        return False, f"Scheme '{parsed.scheme}' not allowed"

    # Check host
    if not parsed.netloc:
        return False, "URL must have a host"

    # Check for local addresses that might be SSRF
    hostname = parsed.hostname or ""
    dangerous_hosts = [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        '::1',
        '169.254.',  # Link-local
    ]
    for dangerous in dangerous_hosts:
        if hostname.startswith(dangerous) or hostname == dangerous:
            return False, f"Host '{hostname}' is not allowed (local address)"

    # Check against whitelist if provided
    if allowed_hosts:
        import fnmatch
        host_allowed = False
        for pattern in allowed_hosts:
            if fnmatch.fnmatch(hostname, pattern):
                host_allowed = True
                break
        if not host_allowed:
            return False, f"Host '{hostname}' is not in allowed list"

    return True, None


def validate_path(
    path: str,
    base_dir: Optional[str] = None,
    allow_absolute: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Validate a file path for safety.

    Checks for path traversal and other dangerous patterns.

    Args:
        path: Path to validate.
        base_dir: Optional base directory to restrict to.
        allow_absolute: Whether to allow absolute paths.

    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check length
    if len(path) > MAX_PATH_LENGTH:
        return False, f"Path exceeds maximum length of {MAX_PATH_LENGTH}"

    # Check for null bytes
    if '\x00' in path:
        return False, "Path contains null byte"

    # Check for path traversal patterns
    for pattern in PATH_TRAVERSAL_PATTERNS:
        if re.search(pattern, path):
            return False, "Path contains traversal sequence"

    # Normalize the path
    try:
        normalized = os.path.normpath(path)
    except Exception as e:
        return False, f"Invalid path: {e}"

    # Check if absolute path is allowed
    if os.path.isabs(normalized) and not allow_absolute:
        return False, "Absolute paths are not allowed"

    # Check against base directory if provided
    if base_dir:
        base_resolved = os.path.realpath(os.path.expanduser(base_dir))
        path_resolved = os.path.realpath(
            os.path.join(base_resolved, normalized)
        )

        if not path_resolved.startswith(base_resolved):
            return False, "Path escapes base directory"

    return True, None


def detect_injection(
    value: str,
    check_shell: bool = True,
    check_sql: bool = True,
    check_path: bool = True,
) -> list[str]:
    """
    Detect potential injection attacks in a string.

    Args:
        value: String to check.
        check_shell: Check for shell injection.
        check_sql: Check for SQL injection.
        check_path: Check for path traversal.

    Returns:
        List of detected issues (empty if clean).
    """
    issues = []

    if check_shell:
        for pattern in SHELL_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                issues.append(f"Potential shell injection detected: {pattern}")
                break  # One shell issue is enough

    if check_sql:
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                issues.append(f"Potential SQL injection detected: {pattern}")
                break

    if check_path:
        for pattern in PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, value):
                issues.append(f"Potential path traversal detected: {pattern}")
                break

    return issues


def redact_sensitive(
    value: str,
    patterns: Optional[list[str]] = None,
) -> str:
    """
    Redact sensitive information from a string.

    Args:
        value: String to redact.
        patterns: Additional patterns to redact.

    Returns:
        String with sensitive data replaced by [REDACTED].
    """
    default_patterns = [
        # API keys
        r'sk-[a-zA-Z0-9]{20,}',
        r'xoxb-[a-zA-Z0-9-]{20,}',
        r'AKIA[0-9A-Z]{16}',
        r'ghp_[a-zA-Z0-9]{36}',
        # Passwords
        r'password\s*[=:]\s*[^\s]+',
        r'passwd\s*[=:]\s*[^\s]+',
        r'secret\s*[=:]\s*[^\s]+',
        # Tokens
        r'token\s*[=:]\s*[a-zA-Z0-9._-]{20,}',
        r'bearer\s+[a-zA-Z0-9._-]{20,}',
        # Generic secrets
        r'-----BEGIN [A-Z ]+-----',
        r'-----END [A-Z ]+-----',
    ]

    all_patterns = default_patterns + (patterns or [])

    result = value
    for pattern in all_patterns:
        result = re.sub(pattern, '[REDACTED]', result, flags=re.IGNORECASE)

    return result
