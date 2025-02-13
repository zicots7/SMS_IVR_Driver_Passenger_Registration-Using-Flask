import os
from dotenv import load_dotenv
from twilio.rest import Client

# Load environment variables from .env file
load_dotenv()

# Get Twilio credentials from environment variables
account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

# Initialize Twilio client
client = Client(account_sid, auth_token)

# Define the criteria for fetching messages
date_sent_after = '2025-01-08'

# Initialize pagination
messages = client.messages.list(date_sent_after=date_sent_after, limit=100)  # Limit is for first page

# Loop through messages and delete them
while messages:
    for message in messages:
        print(f"Deleting message SID: {message.sid}")
        message.delete()

    # Get next page if available
    if messages._next_page_uri:
        messages = client.messages.list(
            date_sent_after=date_sent_after,
            page_size=100,  # Size of each page
            page_token=messages._next_page_uri
        )
    else:
        break

print(f"Deleted all messages sent after {date_sent_after}.")
