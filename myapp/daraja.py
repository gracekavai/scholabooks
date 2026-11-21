import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class DarajaError(Exception):
    pass


def _request_json(url, headers, payload=None):
    request = Request(
        url,
        data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        headers={**headers, 'Content-Type': 'application/json'},
        method='POST' if payload is not None else 'GET',
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        try:
            body = json.loads(error.read().decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        message = body.get('errorMessage') or body.get('ResponseDescription')
        raise DarajaError(message or 'M-Pesa could not process the request.') from error
    except (URLError, TimeoutError) as error:
        raise DarajaError('M-Pesa could not be reached. Please try again later.') from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DarajaError('M-Pesa returned an unreadable response.') from error

    if not isinstance(result, dict):
        raise DarajaError('M-Pesa returned an invalid response.')
    return result


def normalize_phone_number(phone_number):
    digits = re.sub(r'\D', '', phone_number)
    if digits.startswith('0') and len(digits) == 10:
        digits = f'254{digits[1:]}'
    elif len(digits) == 9:
        digits = f'254{digits}'
    if not re.fullmatch(r'254\d{9}', digits):
        raise DarajaError('Enter a valid Kenyan mobile number, for example 0712345678.')
    return digits


def initiate_stk_push(payment_request):
    environment = os.getenv('DARAJA_ENVIRONMENT', 'sandbox').lower()
    if environment not in {'sandbox', 'production'}:
        raise DarajaError('DARAJA_ENVIRONMENT must be sandbox or production.')
    base_url = (
        'https://sandbox.safaricom.co.ke'
        if environment == 'sandbox'
        else 'https://api.safaricom.co.ke'
    )
    consumer_key = os.getenv('DARAJA_CONSUMER_KEY')
    consumer_secret = os.getenv('DARAJA_CONSUMER_SECRET')
    shortcode = os.getenv('DARAJA_SHORTCODE')
    passkey = os.getenv('DARAJA_PASSKEY')
    callback_url = os.getenv(
        'DARAJA_CALLBACK_URL',
        'https://your-public-https-host/payments/daraja/stk-callback/',
    )
    missing = [
        name for name, value in (
            ('DARAJA_CONSUMER_KEY', consumer_key),
            ('DARAJA_CONSUMER_SECRET', consumer_secret),
            ('DARAJA_SHORTCODE', shortcode),
            ('DARAJA_PASSKEY', passkey),
            ('DARAJA_CALLBACK_URL', callback_url),
        ) if not value
    ]
    if missing:
        raise DarajaError(
            'M-Pesa STK Push is not configured. Missing: ' + ', '.join(missing)
        )
    if not callback_url.startswith('https://') or 'your-public-https-host' in callback_url:
        raise DarajaError('DARAJA_CALLBACK_URL must be a public HTTPS URL.')

    try:
        amount = int(payment_request.amount)
    except (TypeError, ValueError, OverflowError) as error:
        raise DarajaError('STK Push amount must be a whole number of Kenyan shillings.') from error
    if amount < 1 or payment_request.amount != amount:
        raise DarajaError('STK Push amount must be a whole number of Kenyan shillings.')

    credentials = base64.b64encode(
        f'{consumer_key}:{consumer_secret}'.encode('utf-8')
    ).decode('ascii')
    token_response = _request_json(
        f'{base_url}/oauth/v1/generate?grant_type=client_credentials',
        {'Authorization': f'Basic {credentials}'},
    )
    access_token = token_response.get('access_token')
    if not access_token:
        raise DarajaError('M-Pesa authentication failed; check the Daraja credentials.')

    timestamp = datetime.now(timezone(timedelta(hours=3))).strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode('utf-8')
    ).decode('ascii')
    response = _request_json(
        f'{base_url}/mpesa/stkpush/v1/processrequest',
        {'Authorization': f'Bearer {access_token}'},
        {
            'BusinessShortCode': shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'TransactionType': 'CustomerPayBillOnline',
            'Amount': amount,
            'PartyA': normalize_phone_number(payment_request.phone_number),
            'PartyB': shortcode,
            'PhoneNumber': normalize_phone_number(payment_request.phone_number),
            'CallBackURL': callback_url,
            'AccountReference': payment_request.student.admission_number[:12],
            'TransactionDesc': 'School fees',
        },
    )
    if str(response.get('ResponseCode')) != '0':
        raise DarajaError(
            response.get('ResponseDescription')
            or response.get('errorMessage')
            or 'M-Pesa did not accept the STK Push request.'
        )
    if not response.get('CheckoutRequestID') or not response.get('MerchantRequestID'):
        raise DarajaError('M-Pesa accepted the request without returning tracking IDs.')
    return response
