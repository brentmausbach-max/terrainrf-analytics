import json
from netlify.functions.compute import handler

# Simulate a mock POST request from the frontend map
mock_event = {
    "httpMethod": "POST",
    "body": json.dumps({
        "lat": 32.88,
        "lon": -116.85,
        "height": 2.0
    })
}

print("Running local simulation of compute.py handler...")
response = handler(mock_event, None)

print(f"Status Code: {response['statusCode']}")
print("Response Body:")
print(response['body'])