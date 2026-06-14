import re


def is_valid_name(name):
    # Basic check, allows letters, apostrophe, hyphen, space
    return bool(re.match(r"^[a-zA-ZÀ-ÖØ-öø-ÿа-яА-ЯёЁ\' -]+$", name))


def is_valid_email(email):
    # Basic email format check
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email))


def is_valid_phone(phone):
    # Allows digits, +, -, (), spaces, requires at least one digit
    return bool(re.match(r"^[+\-() \d]*\d[+\-() \d]*$", phone))


def is_valid_referral(code):
    # Alphanumeric check
    return bool(re.match(r"^[a-zA-Z0-9]+$", code))
