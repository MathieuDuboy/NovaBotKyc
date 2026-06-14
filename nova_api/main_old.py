import hmac
import hashlib
import requests

# Configuration variables
http_method = "GET"  # or "POST", "PUT", etc.
canonical_uri = "/api/v2/members/me"  # example endpoint path
# CHANGES: Remove .join('&') method, because it generates string '&' and it influences on signature
canonical_query = ""  # for GET requests
access_key = "tGhT343HpEYExsGzJ4qNbMLTTFAwTy3OKd2WGIxc"
secret_key = "SB9S1L3IO4EHs9xQvsQFnhxnDwiWSzabGLiNNdGr"
# CAHNGES: remove # sign, and delete access_key
# Construct the canonical string
canonical_string = f"{http_method}|{canonical_uri}|{canonical_query}"

# CHANGES: add encoding param for values (utf-8)
# Generate the HMAC SHA256 signature
signature = hmac.new(secret_key.encode('utf-8'), canonical_string.encode('utf-8'), hashlib.sha256).hexdigest()

# CHANGES: use access_key from variables
# Prepare the headers
headers = {
    "accept": 'application/json',
    "APIKey": access_key,
    "APISign": signature
}

# Define the full URL (assuming 'https://api.example.com' is the base URL)
url = "https://api.novabtc.io" + canonical_uri      

# Send the GET request (for POST, you would include a json= or data= parameter)
response = requests.get(url, headers=headers)

# Check the response
print(response.status_code)
print(response.text)
