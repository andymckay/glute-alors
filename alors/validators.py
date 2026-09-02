from django.core.exceptions import ValidationError
from datetime import datetime

def validate_date(date):
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        raise ValidationError(f"{date} is not a valid date")