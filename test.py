# Download the helper library from https://www.twilio.com/docs/python/install
import os
from twilio.rest import Client

# Find your Account SID and Auth Token at twilio.com/console
# and set the environment variables. See http://twil.io/secure
account_sid = "AC5942576f13f61040d6d4cb605b83cefb"
auth_token = "5281a9f0f4245198914b5a66ee81626b"
client = Client(account_sid, auth_token)

message = client.messages.create(
    body="All in the game, yo", from_="+12182202709", to="+18459579899"
)

print(message.body)