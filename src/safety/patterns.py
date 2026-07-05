"""Danger-word and danger-URL vocabularies for the safety gate.

Matching is done with word boundaries (see gate.py), so a single word like "pay"
matches the button "Pay now" but NOT "Display options"; "drop" matches "Drop table"
but not "Dropdown". Multi-word phrases ("cancel subscription") match as a phrase.
"""

# Clicking one of these is assumed irreversible / high-consequence.
DESTRUCTIVE: tuple[str, ...] = (
    "delete", "remove", "destroy", "drop", "purge", "wipe",
    "cancel subscription", "pay", "charge", "checkout",
    "confirm purchase", "publish", "deploy", "logout", "sign out",
    "terminate", "deactivate", "close account", "transfer", "withdraw",
)

# Could be destructive or benign depending on context — hand these to the LLM.
AMBIGUOUS: tuple[str, ...] = (
    "submit", "confirm", "send", "proceed", "continue", "save", "apply",
)

# URL fragments the crawler must never navigate to (matched case-insensitively as a
# substring of the full URL). config.DEFAULT_BLOCKED_URL_PATTERNS is the runtime floor;
# this list documents the intent.
DESTRUCTIVE_URL_HINTS: tuple[str, ...] = (
    "/logout", "/signout", "/sign-out", "/delete", "/remove", "/charge",
)
