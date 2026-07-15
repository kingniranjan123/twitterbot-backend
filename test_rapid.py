import requests

API_KEY = '68a3c8c2ebmshdf86ac99c6c64e6p12cec4jsne07f95686e42'
HOST = 'twttrapi.p.rapidapi.com'

headers = {
    'x-rapidapi-host': HOST,
    'x-rapidapi-key': API_KEY
}

endpoints = [
    {"name": "User Tweets", "url": "https://twttrapi.p.rapidapi.com/user-tweets?user_id=44196397"},
    {"name": "Get Tweet", "url": "https://twttrapi.p.rapidapi.com/get-tweet?tweet_id=1801234567890123456"},
    {"name": "User Replies", "url": "https://twttrapi.p.rapidapi.com/user-replies?user_id=44196397"}
]

print("Starting RapidAPI Endpoint Tests...\n" + "-"*40)
for ep in endpoints:
    print(f"Testing {ep['name']}...")
    try:
        response = requests.get(ep['url'], headers=headers)
        print(f"  -> Status Code: {response.status_code}")
        if response.status_code == 200:
            print("  -> Status: SUCCESS")
        else:
            print(f"  -> Error Response: {response.text[:200]}")
    except Exception as e:
        print(f"  -> Exception: {str(e)}")
    print("-" * 40)
