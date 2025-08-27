from flask import Flask, request, redirect
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.twiml.messaging_response import MessagingResponse
import sqlite3
from datetime import datetime
import requests
import googlemaps
import os
import math
import urllib.parse
from dotenv import load_dotenv
from twilio.rest import Client

# Load environment variables
load_dotenv()

TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
TWILIO_SID = os.getenv('TWILIO_SID')
GEOCODING_API_KEY = os.getenv('GEOCODING_API_KEY') 
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')

app = Flask(__name__)
client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

def setup_database():
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS profiles
                 (phone_number TEXT PRIMARY KEY,
                  profile_name TEXT,
                  gender TEXT,
                  zip_code TEXT,
                  created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rides
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phone_number TEXT,
                  pickup TEXT,
                  destination TEXT,
                  travel_time TEXT,
                  created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_state
                 (phone_number TEXT PRIMARY KEY,
                  current_step TEXT,
                  temp_profile_name TEXT,
                  temp_gender TEXT,
                  temp_zip_code TEXT,
                  temp_pickup TEXT,
                  temp_destination TEXT,
                  temp_travel_time TEXT,
                  channel TEXT)''')
    conn.commit()
    conn.close()

def get_profile(phone_number):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('SELECT * FROM profiles WHERE phone_number = ?', (phone_number,))
    result = c.fetchone()
    conn.close()
    return result

def get_user_state(phone_number):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('SELECT * FROM user_state WHERE phone_number = ?', (phone_number,))
    result = c.fetchone()
    conn.close()
    return result

def update_user_state(phone_number, state, temp_profile_name=None, temp_gender=None, 
                     temp_zip_code=None, temp_pickup=None, temp_destination=None, 
                     temp_travel_time=None, channel=None):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO user_state 
                 (phone_number, current_step, temp_profile_name, temp_gender, 
                  temp_zip_code, temp_pickup, temp_destination, temp_travel_time, channel)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (phone_number, state, temp_profile_name, temp_gender, 
               temp_zip_code, temp_pickup, temp_destination, temp_travel_time, channel))
    conn.commit()
    conn.close()

def clear_user_state(phone_number):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_state WHERE phone_number = ?', (phone_number,))
    conn.commit()
    conn.close()

def save_profile(phone_number, profile_name, gender, zip_code):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO profiles 
                 (phone_number, profile_name, gender, zip_code, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (phone_number, profile_name, gender, zip_code, datetime.now()))
    conn.commit()
    conn.close()

def update_zip_code(phone_number, new_zip_code):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''UPDATE profiles 
                 SET zip_code = ?
                 WHERE phone_number = ?''',
              (new_zip_code, phone_number))
    conn.commit()
    conn.close()

def save_ride(phone_number, pickup, destination,travel_time):
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''INSERT INTO rides 
                 (phone_number, pickup, destination,travel_time, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (phone_number, pickup, destination,travel_time, datetime.now()))
    conn.commit()
    conn.close()
def update_zip_code_from_suggestion(phone_number, suggested_zip):
    """Update user's zip code based on suggested location"""
    conn = sqlite3.connect('profiles.db')
    c = conn.cursor()
    c.execute('''UPDATE profiles 
                 SET zip_code = ?
                 WHERE phone_number = ?''',
              (suggested_zip, phone_number))
    conn.commit()
    conn.close()   

def get_zip_coordinates(zip_code):
    """Fetch coordinates for a given zip code"""
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={zip_code}&key={GEOCODING_API_KEY}"
        response = requests.get(url).json()
        
        if response['status'] == 'OK' and response['results']:
            return response['results'][0]['geometry']['location']
        return None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None

def calculate_distance(point1, point2):
    """Calculate great-circle distance between two geographic points"""
    if not point1 or not point2:
        return float('inf')
    
    R = 6371  # Earth's radius in kilometers
    
    lat1, lon1 = math.radians(point1['lat']), math.radians(point1['lng'])
    lat2, lon2 = math.radians(point2['lat']), math.radians(point2['lng'])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c  # Distance in kilometers

def calculate_address_relevance(result, original_query):
    """Calculate relevance score for an address result"""
    formatted_address = result['formatted_address'].lower()
    query = original_query.lower()
    
    # Exact match scoring
    if query in formatted_address:
        return 100
    
    # Partial word match scoring
    words_matched = sum(
        word in formatted_address 
        for word in query.split() 
        if len(word) > 2
    )
    
    return words_matched * 10

def rank_address_results(results, original_query, registered_zip_code=None):
    """Rank geocoding results by relevance and proximity"""
    def calculate_total_score(result):
        # Calculate base relevance score
        relevance_score = calculate_address_relevance(result, original_query)
        
        # Add proximity bonus if zip code is available
        if registered_zip_code:
            try:
                zip_coords = get_zip_coordinates(registered_zip_code)
                result_coords = result['geometry']['location']
                
                if zip_coords:
                    # Calculate distance
                    distance = calculate_distance(zip_coords, result_coords)
                    
                    # Add proximity bonus (closer addresses get higher scores)
                    proximity_bonus = max(0, 50 - distance)
                    return relevance_score + proximity_bonus
            except Exception:
                pass
        
        return relevance_score
    
    # Sort results by total score
    return sorted(results, key=calculate_total_score, reverse=True)

def handle_ambiguous_address(address_results):
    """Handle multiple address matches with context"""
    if len(address_results) > 1:
        response = "Multiple addresses found. Options:\n"
        for i, addr in enumerate(address_results[:5], 1):
            response += f"{i}. {addr['formatted_address']}\n"
        response += "Reply with the number of your desired address or provide more details."
        return response
    return None

def resolve_partial_address(partial_address, registered_zip_code=None):
    """Enhanced address resolution with proximity context and zip code update suggestion"""
    # URL encode the address to handle special characters
    encoded_address = urllib.parse.quote(partial_address)
    
    # Prepare full address query
    full_address = encoded_address
    if registered_zip_code:
        full_address += f",+{registered_zip_code}"
    
    # Geocoding API request
    url = (f"https://maps.googleapis.com/maps/api/geocode/json"
           f"?address={full_address}&key={GEOCODING_API_KEY}")
    
    try:
        response = requests.get(url).json()
        
        # Successful geocoding
        if response['status'] == 'OK':
            results = response['results']
            
            # If registered zip code exists, check proximity
            if registered_zip_code:
                registered_coords = get_zip_coordinates(registered_zip_code)
                
                # Annotate results with distance from registered zip
                for result in results:
                    result_coords = result['geometry']['location']
                    result['distance'] = calculate_distance(registered_coords, result_coords)
                
                # Sort results by distance
                sorted_results = sorted(results, key=lambda x: x['distance'])
                
                # If closest result is too far (e.g., >50 km), suggest zip code update
                if sorted_results[0]['distance'] > 50:
                    new_zip = sorted_results[0]['address_components'][-1]['long_name']
                    return None, (
                        f"Address seems far from your registered zip code {registered_zip_code}. "
                        f"Suggested zip code: {new_zip}. "
                        "Reply with 'UPDATE ZIP' to update or provide a different address."
                    )
                
                # Return the closest result
                return sorted_results[0]['formatted_address'], None
            
            # If no registered zip, return first result
            return results[0]['formatted_address'], None
        
        # No results found
        elif response['status'] == 'ZERO_RESULTS':
            return None, "Address not found. Please provide a more specific address."
        
        # API error
        else:
            return None, f"Geocoding error: {response['status']}"
    
    except Exception as e:
        return None, f"Address resolution failed: {str(e)}"
    
def is_match_significantly_closer(sorted_results):
    """Determine if the first result is significantly closer"""
    # If the first result is at least 50% closer than the second, consider it a clear match
    if len(sorted_results) > 1:
        return sorted_results[0]['distance'] < 0.5 * sorted_results[1]['distance']
    return True

def parse_addresses(message):
    """Parse addresses from different formats"""
    if '##' in message:
        return [addr.strip() for addr in message.split('##')]
    elif ',' in message:
        return [addr.strip() for addr in message.split(',')]
    elif '\n' in message:
        lines = [line.strip() for line in message.splitlines()]
        return [line for line in lines if line]
    return [message]

def rank_address_results(results, original_query):
    """Rank geocoding results by relevance"""
    def calculate_relevance_score(result, query):
        formatted_address = result['formatted_address'].lower()
        query = query.lower()
        
        # Exact match gets highest score
        if query in formatted_address:
            return 100
        
        # Partial match scoring
        words_matched = sum(word in formatted_address for word in query.split())
        return words_matched * 10
    
    # Sort results by relevance score
    return sorted(
        results, 
        key=lambda r: calculate_relevance_score(r, original_query), 
        reverse=True
    )
   
def handle_ride_confirmation(phone_number, origin, destination):
    """Handle ride confirmation process"""
    response = MessagingResponse()
    travel_time, error = calculate_travel_time(origin, destination)
    
    if error:
        response.message(error)
        return str(response)
        
    msg = f"{origin} going TO {destination}\n"
    msg += f"Estimated travel time: {travel_time}\n"
    msg += "To confirm addresses press 1\n"
    msg += "To change current address press 2\n"
    msg += "To change destination press 3"
    msg +="To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address."
    
    response.message(msg)
    update_user_state(phone_number, 'AWAITING_CONFIRMATION', 
                     temp_pickup=origin, temp_destination=destination)
    return str(response)

def calculate_travel_time(origin, destination):
    """Calculate travel time between two addresses using Distance Matrix API."""
    url = (
        f"https://maps.googleapis.com/maps/api/distancematrix/json"
        f"?origins={origin}&destinations={destination}&key={GEOCODING_API_KEY}"
    )
    response = requests.get(url).json()
    
    if response['status'] == 'OK' and response['rows'][0]['elements'][0]['status'] == 'OK':
        duration = response['rows'][0]['elements'][0]['duration']['text']
        return duration, None
    else:
        return None, "Error calculating travel time. Please check your addresses."


def handle_partial_addresses(phone_number, message):
    """Process SMS with partial addresses, validate, and calculate travel time."""
    response = MessagingResponse()
    user_state = get_user_state(phone_number)

    if user_state and user_state[1] == 'AWAITING_DESTINATION_ADDRESS':
        # Destination address received
        origin = user_state[5]
        travel_time=user_state[7]
        destination, error = resolve_partial_address(message, user_state[4])
        if error:
            response.message(error)
        else:
            travel_time, error = calculate_travel_time(origin, destination)
            if error:
                response.message(error)
            else:
                response.message(f"Travel time from {origin} to {destination}: {travel_time}")
            clear_user_state(phone_number)
    else:
        # First address received
        address, error = resolve_partial_address(message, get_profile(phone_number)[3])
        if error:
            response.message(error)
        else:
            response.message("Please provide the destination address.")
            update_user_state(phone_number, 'AWAITING_DESTINATION_ADDRESS', temp_pickup=address)

    return str(response)
def handle_ivr_address_collection(phone_number, speech_result, state):
    """Handle IVR interaction for collecting origin and destination addresses."""
    response = VoiceResponse()
    if state == 'AWAITING_PICKUP':
        if not speech_result:
            gather = Gather(input='speech', action='/voice')
            gather.say("Please say your pickup address, then press pound.")
            response.append(gather)
        else:
            address, error = resolve_partial_address(speech_result, get_profile(phone_number)[3])
            if error:
                response.say(error)
                gather = Gather(input='speech', action='/voice')
                gather.say("Please say your pickup address again, then press pound.")
                response.append(gather)
            else:
                response.say("Pickup address received. Now, please say your destination address, then press pound.")
                gather = Gather(input='speech', action='/voice')
                response.append(gather)
                update_user_state(phone_number, 'AWAITING_DESTINATION_ADDRESS', temp_pickup=address)
    
    elif state == 'AWAITING_DESTINATION_ADDRESS':
        origin = get_user_state(phone_number)[5]
        if not speech_result:
            gather = Gather(input='speech', action='/voice')
            gather.say("Please say your destination address, then press pound.")
            response.append(gather)
        else:
            destination, error = resolve_partial_address(speech_result, get_profile(phone_number)[3])
            if error:
                response.say(error)
                gather = Gather(input='speech', action='/voice')
                gather.say("Please say your destination address again, then press pound.")
                response.append(gather)
            else:
                travel_time, error = calculate_travel_time(origin, destination)
                if error:
                    response.say(error)
                else:
                    travel_time, error = calculate_travel_time(origin, destination)
                    response.say(f"From {origin} to {destination}. Estimated travel time: {travel_time}.")
                    gather = Gather(num_digits=1, action='/voice')
                    gather.say("To confirm addresses press 1, to change pickup address press 2, to change destination press 3.")
                    response.append(gather)
                    update_user_state(phone_number, 'AWAITING_CONFIRMATION', 
                                   temp_pickup=origin, 
                                   temp_destination=destination,
                                   temp_travel_time=travel_time) 
    
    elif state == 'AWAITING_CONFIRMATION':
        user_state = get_user_state(phone_number)
        if speech_result == '1':
            save_ride(phone_number, user_state[5], user_state[6],user_state[7])
            response.say("Ride confirmed! You will receive a confirmation SMS. Thank you for using our service.")
            send_sms_notification(phone_number, 
                f"Ride confirmed!\nPickup: {user_state[5]}\nDestination: {user_state[6]}\nEstimated travel time: {user_state[7]}")
            clear_user_state(phone_number)
        elif speech_result == '2':
            response.say("Please say your new pickup address, then press pound.")
            gather = Gather(input='speech', action='/voice')
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_PICKUP')
        elif speech_result == '3':
            response.say("Please say your new destination address, then press pound.")
            gather = Gather(input='speech', action='/voice')
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_DESTINATION_ADDRESS')
        else:
            gather = Gather(num_digits=1, action='/voice')
            gather.say("Invalid option. To confirm addresses press 1, to change pickup address press 2, to change destination press 3.")
            response.append(gather)
    
    return str(response)
def handle_whatsapp_profile_creation(phone_number, message, state):
    """Handle WhatsApp profile creation flow"""
    response = MessagingResponse()
    user_state = get_user_state(phone_number)
    
    if state == 'AWAITING_PROFILE_NAME':
        if len(message) == 4 and message.isdigit():
            response.message("Please enter your gender:\n1️⃣ for Male\n2️⃣ for Female")
            update_user_state(phone_number, 'AWAITING_GENDER', message, channel='WHATSAPP')
        else:
            response.message("⚠️ Please enter exactly 4 digits for your profile name.")
            
    elif state == 'AWAITING_GENDER':
        if message in ['1', '2']:
            gender = 'Male' if message == '1' else 'Female'
            response.message("Please enter your 5-digit zip code 📍")
            update_user_state(phone_number, 'AWAITING_ZIP', temp_profile_name=user_state[2], 
                            temp_gender=gender, channel='WHATSAPP')
        else:
            response.message("❌ Invalid selection. Enter 1 for Male or 2 for Female")
            
    elif state == 'AWAITING_ZIP':
        if len(message) == 5 and message.isdigit():
            save_profile(phone_number, user_state[2], user_state[3], message)
            response.message(
                
                f"Account: {user_state[2]}, gender {user_state[3].lower()}, zip code {message}"
                "✅ Profile created successfully! To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address.\n\n"
                "🚗 Let's book a ride now!\n"
                "Send pickup address, comma, destination address\n"
                "Example: 123 Main St, 456 Oak Rd\n"
                "⚠️ Please provide both addresses in one of these formats:\n\n"
                "1️⃣ address1 , address2\n"
                "2️⃣ address1 ## address2\n"
                "3️⃣ address1 (on first line)\n"
                "   address2 (on second line)"
            )
            update_user_state(phone_number, 'AWAITING_RIDE_BOOKING', channel='WHATSAPP')
        else:
            response.message("⚠️ Please enter a valid 5-digit zip code")
            
    return str(response)
def handle_whatsapp(phone_number, message):
    """Main WhatsApp message handler"""
    response = MessagingResponse()
    user_state = get_user_state(phone_number)
    profile = get_profile(phone_number)
    if profile:
            # Handle zip code update suggestion
            if user_state and user_state[8] and 'UPDATE ZIP' in message.upper():
                # Extract suggested zip from previous message
                suggested_zip = user_state[8].split()[-1]
                update_zip_code(phone_number, suggested_zip)
                response.message(f"Zip code updated to {suggested_zip}")
                clear_user_state(phone_number)
                return str(response)
    # New user registration
    if not profile:
        if not user_state:
            response.message(
                "👋 Welcome to Safe Drive !\n\n"
                "Let's create your profile 📝\n"
                "Please enter a 4-digit profile name"
            )
            update_user_state(phone_number, 'AWAITING_PROFILE_NAME', channel='WHATSAPP')
        else:
            return handle_whatsapp_profile_creation(phone_number, message, user_state[1])
    
    # Existing user interactions
    else:
        if message.lower() == '#':
            response.message("📍 Enter your new zip code")
            update_user_state(phone_number, 'UPDATING_ZIP', channel='WHATSAPP')
            
        elif user_state and user_state[1] == 'UPDATING_ZIP':
            if len(message) == 5 and message.isdigit():
                update_zip_code(phone_number, message)
                response.message(
                    "✅ ZIP code updated successfully!\n\n"
                    f"{get_current_user_info(phone_number)}\n" 
                    "🚗 Ready to book a ride!\n"
                    "Send pickup address, comma, destination address\n"
                    "Example: 123 Main St, 456 Oak Rd\n"
                    "⚠️ Please provide both addresses in one of these formats:\n\n"
                    "1️⃣ address1 , address2\n"
                    "2️⃣ address1 ## address2\n"
                    "3️⃣ address1 (on first line)\n"
                    "   address2 (on second line)\n\n"

                    "⚠️To Change your zip code text #"
                )
                update_user_state(phone_number, 'AWAITING_RIDE_BOOKING', channel='WHATSAPP')
            else:
                response.message("⚠️ Please enter a valid 5-digit zip code")
                
        elif user_state and user_state[1] == 'AWAITING_CONFIRMATION':
            if message == '1':
                save_ride(phone_number, user_state[5], user_state[6],user_state[7])
                response.message(
                    "✅ Ride confirmed!\n\n"
                    f"📍 Pickup: {user_state[5]}\n"
                    f"🎯 Destination: {user_state[6]}"
                    f"⏱ Travel Time: {user_state[7]}"
                )
                clear_user_state(phone_number)
            elif message in ['2', '3']:
                response.message("📍 Please enter the new address:")
                update_user_state(phone_number, 
                                'AWAITING_NEW_PICKUP' if message == '2' else 'AWAITING_NEW_DESTINATION',
                                temp_pickup=user_state[5],
                                temp_destination=user_state[6],
                                channel='WHATSAPP')
            else:
                response.message(
                    "❌ Invalid option\n\n"
                    "1️⃣ Confirm booking\n"
                    "2️⃣ Change pickup address\n"
                    "3️⃣ Change destination address\n\n\n"
                    "⚠️To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address."
                )
                
        elif user_state and user_state[1].startswith('AWAITING_NEW_'):
            if user_state[1] == 'AWAITING_NEW_PICKUP':
                address_full, error = resolve_partial_address(message, profile[3])
                if error:
                    response.message(f"❌ {error}")
                else:
                    return handle_whatsapp_ride_booking(phone_number, [address_full, user_state[6]], profile)
            else:  # AWAITING_NEW_DESTINATION
                address_full, error = resolve_partial_address(message, profile[3])
                if error:
                    response.message(f"❌ {error}")
                else:
                    return handle_whatsapp_ride_booking(phone_number, [user_state[5], address_full], profile)
                
        else:
            addresses = parse_addresses(message)
            return handle_whatsapp_ride_booking(phone_number, addresses, profile)
    
    return str(response)
def handle_whatsapp_ride_booking(phone_number, addresses, profile):
    """Handle WhatsApp ride booking process"""
    response = MessagingResponse()
    
    if len(addresses) == 2:
        pickup, destination = addresses
        pickup_full, error = resolve_partial_address(pickup, profile[3])
        if error:
            response.message(f"❌ Pickup address error: {error}")
            return str(response)
            
        destination_full, error = resolve_partial_address(destination, profile[3])
        if error:
            response.message(f"❌ Destination address error: {error}")
            return str(response)
        
        travel_time, error = calculate_travel_time(pickup_full, destination_full)
        if error:
            response.message(f"❌ {error}")
            return str(response)
        
        msg = (
            f"🚗 Ride Details:\n\n"
            f"📍 From: {pickup_full}\n"
            f"🎯 To: {destination_full}\n"
            f"⏱️ Estimated time: {travel_time}\n\n"
            f"Please confirm:\n"
            f"1️⃣ Confirm booking\n"
            f"2️⃣ Change pickup address\n"
            f"3️⃣ Change destination address\n\n\n"
            "⚠️To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address."
        )
        response.message(msg)
        update_user_state(phone_number, 'AWAITING_CONFIRMATION', 
                         temp_pickup=pickup_full, 
                         temp_destination=destination_full,
                         temp_travel_time=travel_time,
                         channel='WHATSAPP')
        
    else:
        response.message(
            "To book a ride, text your pickup address, coma, then destination address.\n"
            "⚠️ Please provide both addresses in one of these formats:\n\n"
            "1️⃣ address1 , address2\n"
            "2️⃣ address1 ## address2\n"
            "3️⃣ address1 (on first line)\n"
            "   address2 (on second line)\n\n\n"
            "⚠️To Change your zip code text # "
        )
    
    return str(response)
def get_current_user_info(phone_number):
    """Get formatted user information string"""
    profile = get_profile(phone_number)
    if profile:
        return f"Account {profile[1]}, gender {profile[2].lower()}, zip code {profile[3]}"
    return None
def send_sms_notification(phone_number, message):
    try:
        client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )
    except Exception as e:
        print(f"Error sending SMS: {str(e)}")

# IVR Handlers
def handle_voice_welcome(phone_number):
    response = VoiceResponse()
    profile = get_profile(phone_number)
    
    if not profile:
        response.say("Welcome to RideSafe Local! Let's create your profile.")
        gather = Gather(num_digits=4, action='/voice')
        gather.say("Please enter a 4-digit profile name using your keypad.")
        response.append(gather)
        update_user_state(phone_number, 'AWAITING_PROFILE_NAME', channel='IVR')
    else:
        response.say("Welcome to RideSafe Local!")
        gather = Gather(num_digits=1, action='/voice')
        gather.say("Press 1 to book a ride, press 2 to update your ZIP code.")
        response.append(gather)
        update_user_state(phone_number, 'MENU_CHOICE', channel='IVR')
    
    return str(response)

def handle_voice_profile_creation(phone_number, digits, state):
    response = VoiceResponse()
    user_state = get_user_state(phone_number)
    
    if state == 'AWAITING_PROFILE_NAME':
        if len(digits) == 4:
            gather = Gather(num_digits=1, action='/voice')
            gather.say("Press 1 for Male, press 2 for Female.")
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_GENDER', digits, channel='IVR')
        else:
            gather = Gather(num_digits=4, action='/voice')
            gather.say("Please enter exactly 4 digits for your profile name.")
            response.append(gather)
            
    elif state == 'AWAITING_GENDER':
        if digits in ['1', '2']:
            gender = 'Male' if digits == '1' else 'Female'
            gather = Gather(num_digits=5, action='/voice')
            gather.say("Please enter your 5-digit zip code.")
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_ZIP', temp_profile_name=user_state[2], 
                            temp_gender=gender, channel='IVR')
        else:
            gather = Gather(num_digits=1, action='/voice')
            gather.say("Invalid selection. Press 1 for Male or 2 for Female.")
            response.append(gather)
            
    elif state == 'AWAITING_ZIP':
        if len(digits) == 5 and digits.isdigit():
            save_profile(phone_number, user_state[2], user_state[3], digits)
            send_sms_notification(phone_number, 
                f" Account: {user_state[2]},Name: {user_state[3]},Zipcode: {digits}. Profile created successfully! To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address.\n\n")
            response.say("Profile created successfully!To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address. Let's book your ride.")
            gather = Gather(input='speech', action='/voice')
            gather.say("Please say your pickup address, then press pound.")
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_PICKUP', channel='IVR')
        else:
            gather = Gather(num_digits=5, action='/voice')
            gather.say("Please enter a valid 5-digit zip code.")
            response.append(gather)
            
    return str(response)

def handle_voice_ride_booking(phone_number, speech_result, digits, state):
    response = VoiceResponse()
    user_state = get_user_state(phone_number)
    
    if state == 'MENU_CHOICE':
        if digits == '1':
            gather = Gather(input='speech', action='/voice')
            gather.say("Please say your pickup address, then press pound.")
            response.append(gather)
            update_user_state(phone_number, 'AWAITING_PICKUP', channel='IVR')
        elif digits == '2':
            gather = Gather(num_digits=5, action='/voice')
            gather.say("Please enter your new 5-digit ZIP code.")
            response.append(gather)
            update_user_state(phone_number, 'UPDATING_ZIP', channel='IVR')
        else:
            gather = Gather(num_digits=1, action='/voice')
            gather.say("Invalid option. Press 1 to book a ride, press 2 to update your ZIP code.")
            response.append(gather)
    
    elif state == 'AWAITING_PICKUP':
        return handle_ivr_address_collection(phone_number, speech_result, state)
    
    elif state == 'AWAITING_DESTINATION_ADDRESS':
        return handle_ivr_address_collection(phone_number, speech_result, state)
    
    elif state == 'AWAITING_CONFIRMATION':
        return handle_ivr_address_collection(phone_number, digits, state)
    
    elif state == 'UPDATING_ZIP':
        if len(digits) == 5 and digits.isdigit():
            update_zip_code(phone_number, digits)
            response.say("ZIP code updated successfully! To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address.\n\n")
            clear_user_state(phone_number)
        else:
            gather = Gather(num_digits=5, action='/voice')
            gather.say("Please enter a valid 5-digit ZIP code.")
            response.append(gather)
    
    return str(response)
def handle_sms_ride_booking(phone_number, addresses, profile):
    """Handle SMS ride booking process"""
    response = MessagingResponse()
    
    if len(addresses) == 2:
        pickup, destination = addresses
        pickup_full, error = resolve_partial_address(pickup, profile[3])
        if error:
            response.message(f"Pickup address error: {error}")
            return str(response)
            
        destination_full, error = resolve_partial_address(destination, profile[3])
        if error:
            response.message(f"Destination address error: {error}")
            return str(response)
        
        travel_time, error = calculate_travel_time(pickup_full, destination_full)
        if error:
            response.message(f"{error}")
            return str(response)
        
        msg = (
            f"Ride Details:\n\n"
            f"From: {pickup_full}\n"
            f"To: {destination_full}\n"
            f"Estimated time: {travel_time}\n\n"
            f"Please confirm:\n"
            f"1.Confirm booking\n"
            f"2.Change pickup address\n"
            f"3.Change destination address\n\n"
            " To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address."
        )
        response.message(msg)
        update_user_state(phone_number, 'AWAITING_CONFIRMATION', 
                         temp_pickup=pickup_full, 
                         temp_destination=destination_full,
                         temp_travel_time=travel_time,
                         channel='SMS')
        
    else:
        response.message(
            "To book a ride, text your pickup address, coma, then destination address.\n\n"
            " Please provide both addresses in one of these formats:\n"
            "1.address1 , address2\n"
            "2.address1 ## address2\n"
            "3.address1 (on first line)\n"
            "  address2 (on second line)\n\n\n"
            " To Change your zip code text # "
        )
    
    return str(response)
# SMS Handlers
def handle_sms(phone_number, message):
    response = MessagingResponse()
    user_state = get_user_state(phone_number)
    profile = get_profile(phone_number)
    if profile:
        # Handle zip code update suggestion
        if user_state and user_state[8] and 'UPDATE ZIP' in message.upper():
            # Extract suggested zip from previous message
            suggested_zip = user_state[8].split()[-1]
            update_zip_code(phone_number, suggested_zip)
            response.message(f"Zip code updated to {suggested_zip}")
            clear_user_state(phone_number)
            return str(response)
    # New user registration
    if not profile:
        if not user_state:
            response.message("Welcome to RideSafe Local!\nLet's create your profile.\nPlease enter a 4-digit profile name.")
            update_user_state(phone_number, 'AWAITING_PROFILE_NAME', channel='SMS')
        else:
            return handle_sms_profile_creation(phone_number, message, user_state[1])
    
    # Existing user interactions
    else:
        if message.lower() == '#':
            response.message("Enter your new zip code")
            update_user_state(phone_number, 'UPDATING_ZIP', channel='SMS')
            
        elif user_state and user_state[1] == 'UPDATING_ZIP':
            if len(message) == 5 and message.isdigit():
                update_zip_code(phone_number, message)
                send_sms_notification(phone_number, 
                    f" Account: {profile[1]}, Name: {profile[2]}, Zipcode: {message}. Profile Updated successfully! To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address.")
                response.message(
                   f"Send pickup address, comma, destination address\n"
                    "Example: 123 Main St, 456 Oak Rd\n"
                    "Please provide both addresses in one of these formats:\n\n"
                    "1.address1 , address2\n"
                    "2.address1 ## address2\n"
                    "3.address1 (on first line)\n"
                    "address2 (on second line)\n\n\n"
                    "To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address."
                )
                update_user_state(phone_number, 'AWAITING_RIDE_BOOKING', channel='SMS')
            else:
                response.message("Please enter a valid 5-digit zip code.")
        
        elif user_state and user_state[1] == 'AWAITING_CONFIRMATION':
            if message == '1':
                save_ride(phone_number, user_state[5], user_state[6], user_state[7])
                response.message(
                    "Ride confirmed!\n\n"
                    f"Pickup: {user_state[5]}\n"
                    f"Destination: {user_state[6]}\n"
                    f"Travel Time: {user_state[7]}"
                )
                clear_user_state(phone_number)
            elif message in ['2', '3']:
                response.message("Please enter the new address:")
                update_user_state(phone_number, 
                                'AWAITING_NEW_PICKUP' if message == '2' else 'AWAITING_NEW_DESTINATION',
                                temp_pickup=user_state[5],
                                temp_destination=user_state[6],
                                channel='SMS')
            else:
                response.message(
                    "  Invalid option\n\n"
                    "1. Confirm booking\n"
                    "2. Change pickup address\n"
                    "3. Change destination address"
                )
        
        elif user_state and user_state[1].startswith('AWAITING_NEW_'):
            if user_state[1] == 'AWAITING_NEW_PICKUP':
                address_full, error = resolve_partial_address(message, profile[3])
                if error:
                    response.message(f"{error}")
                else:
                    return handle_sms_ride_booking(phone_number, [address_full, user_state[6]], profile)
            else:  # AWAITING_NEW_DESTINATION
                address_full, error = resolve_partial_address(message, profile[3])
                if error:
                    response.message(f" {error}")
                else:
                    return handle_sms_ride_booking(phone_number, [user_state[5], address_full], profile)
        
        else:
            addresses = parse_addresses(message)
            return handle_sms_ride_booking(phone_number, addresses, profile)
    
    return str(response)


def handle_sms_profile_creation(phone_number, message, state):
    response = MessagingResponse()
    user_state = get_user_state(phone_number)
    
    if state == 'AWAITING_PROFILE_NAME':
        if len(message) == 4 and message.isdigit():
            response.message("Please enter your gender 1 for Male, 2 for Female:")
            update_user_state(phone_number, 'AWAITING_GENDER', message, channel='SMS')
        else:
            response.message("Please enter exactly 4 digits for your profile name.")
            
    elif state == 'AWAITING_GENDER':
        if message in ['1', '2']:
            gender = 'Male' if message == '1' else 'Female'
            response.message("Please enter your zip code:")
            update_user_state(phone_number, 'AWAITING_ZIP', temp_profile_name=user_state[2], 
                            temp_gender=gender, channel='SMS')
        else:
            response.message("Invalid selection. Enter 1 for Male or 2 for Female:")
            
    elif state == 'AWAITING_ZIP':
        if len(message) == 5 and message.isdigit():
            save_profile(phone_number, user_state[2], user_state[3], message)
            response.message(
                
                f"Account: {user_state[2]}, gender {user_state[3].lower()}, zip code {message}\n\n"
                "Profile created successfully! To Change your zip code text #, To book a ride, text your pickup address, coma, then destination address.\n\n"
                "Let's book a ride now!\n"
                "Send pickup address, comma, destination address\n"
                "Example: 123 Main St, 456 Oak Rd"
                 "Please provide both addresses in one of these formats:\n\n"
                "1.address1 , address2\n"
                "2.address1 ## address2\n"
                "3.address1 (on first line)\n"
                "address2 (on second line)"
            )
            update_user_state(phone_number, 'AWAITING_RIDE_BOOKING', channel='SMS')
        else:
            response.message("Please enter a valid 5-digit zip code:")
            
    return str(response)

@app.route("/voice", methods=['POST','GET'])
def voice():
    phone_number = request.form.get('From', '')
    digits = request.form.get('Digits', '')
    speech_result = request.form.get('SpeechResult', '')
    
    user_state = get_user_state(phone_number)
    
    if not user_state:
        return handle_voice_welcome(phone_number)
        
    if user_state[1] in ['AWAITING_PROFILE_NAME', 'AWAITING_GENDER', 'AWAITING_ZIP']:
        return handle_voice_profile_creation(phone_number, digits, user_state[1])
    else:
        return handle_voice_ride_booking(phone_number, speech_result, digits, user_state[1])

@app.route("/sms", methods=['POST','GET'])
def sms():
    phone_number = request.form.get('From', '')
    message = request.form.get('Body', '').strip()
    return handle_sms(phone_number, message)
@app.route("/whatsapp", methods=['POST','GET'])
def whatsapp():
    phone_number = request.form.get('From', '').replace('whatsapp:', '')
    message = request.form.get('Body', '').strip()
    return handle_whatsapp(phone_number, message)
if __name__ == "__main__":
    setup_database()
    app.run(debug=True, port=5001)
