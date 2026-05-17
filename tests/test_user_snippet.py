import requests
import os
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
HF_API_URL = os.getenv("HF_API_URL")
def query(payload):
    headers = {
        "Accept" : "application/json",
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.post(
        HF_API_URL,
        headers=headers,
        json=payload
    )
    print("Status:", response.status_code)
    try:
        return response.json()
    except Exception as e:
        return response.text

output = query({
    "inputs": "I like you. I love you",
    "parameters": {}
}) 

print(output)
