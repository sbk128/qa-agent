# Ordered headline-nasties-first: anything that slices a prefix of this list
# (e.g. the test-case injector) gets the high-signal security/length values, not
# just empty/whitespace.
UNIVERSAL: list[str] = [
    "a" * 10000,                     # absurdly long
    "<script>alert(1)</script>",     # XSS
    "' OR '1'='1",                   # SQL injection
    "{{7*7}}",                       # template injection
    "🔥😀",                           # emoji
    "العربية",                       # right-to-left script
    "\n\t",                          # control whitespace
    "",                              # empty
    "   ",                           # whitespace only
]

# Extra nasties that only make sense for a specific kind of field
KIND_SPECIFIC: dict[str, list[str]] = {
    "email":    ["a@b", "plainaddress", "@nolocal.com", "has spaces@x.com"],
    "phone":    ["abc", "-1", "0000000000000000000"],
    "date":     ["2099-13-45", "0000-00-00", "not-a-date"],
    "currency": ["-1", "1e308", "NaN", "abc"],
    "name":     ["12345", "<b>tags</b>"],
}