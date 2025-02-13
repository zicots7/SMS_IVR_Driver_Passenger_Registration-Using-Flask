# app.py

"""
Driver Registration System Backend

This Flask application handles driver registration with features including:
- Driver information submission
- License validation
- SMS notifications via Twilio
- SQLite database storage


"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
from twilio.rest import Client
from dotenv import load_dotenv
from contextlib import contextmanager

# Load environment variables from .env file
load_dotenv()

# Initialize Flask application
app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# Configuration constants
DATABASE = 'drivers.db'  # SQLite database file name

# Twilio configuration from environment variables
account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')
client = Client(account_sid, auth_token)

@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Ensures proper handling of connections and automatic closing.
    
    Yields:
        sqlite3.Connection: Database connection object
    
    Usage:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
    """
    conn = sqlite3.connect(DATABASE, timeout=20)  # 20 second timeout for busy database
    try:
        yield conn
    finally:
        conn.commit()  # Commit any pending transactions
        conn.close()   # Ensure connection is closed

def init_db():
    """
    Initialize the database and create the drivers table if it doesn't exist.
    This function runs when the application starts.
    
    Table Schema:
    - id: Primary key
    - name: Driver's full name
    - phone: Contact number with country code
    - email: Email address
    - license_number: Driver's license number (unique)
    - license_plate: Vehicle license plate (unique)
    - gender: Driver's gender
    - car_type: Type of vehicle
    - car_color: Color of vehicle
    - available_seats: Number of available seats
    - is_new_car: Boolean for cars 2022 or newer
    - is_luxury: Boolean for luxury vehicles
    - has_wheelchair: Boolean for wheelchair accessibility
    - car_seat_count: Number of car seats (0-2)
    - has_booster: Boolean for booster seat availability
    - notify_rides: Boolean for ride notifications
    - notify_deliveries: Boolean for delivery notifications
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS drivers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                license_number TEXT NOT NULL,
                license_plate TEXT NOT NULL,
                gender TEXT NOT NULL,
                Model TEXT NOT NULL,
                car_color TEXT NOT NULL,
                available_seats INTEGER NOT NULL,
                is_new_car BOOLEAN,
                is_luxury BOOLEAN,
                has_wheelchair BOOLEAN,
                car_seat_count INTEGER,
                has_booster BOOLEAN,
                notify_rides BOOLEAN,
                notify_deliveries BOOLEAN,
                PassengerPreference TEXT NOT NULL
            )
        ''')

# Initialize database on startup
init_db()

@app.route('/')
def home():
    """
    Render the main registration page.
    
    Returns:
        str: Rendered HTML template
    """
    return render_template('index.html')

@app.route('/api/check-license', methods=['POST','GET'])
def check_license():
    """
    API endpoint to check if license number or plate already exists.
    
    Expected JSON payload:
    {
        "licenseNumber": "string",
        "licensePlate": "string"
    }
    
    Returns:
        JSON: {
            "exists": boolean,
            "licenseNumberExists": boolean,
            "licensePlateExists": boolean
        }
    """
    data = request.json
    license_number = data.get('licenseNumber')
    license_plate = data.get('licensePlate')
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Check if license number exists
            c.execute('SELECT COUNT(*) FROM drivers WHERE license_number = ?', (license_number,))
            license_exists = c.fetchone()[0] > 0
            
            # Check if license plate exists
            c.execute('SELECT COUNT(*) FROM drivers WHERE license_plate = ?', (license_plate,))
            plate_exists = c.fetchone()[0] > 0
            
            return jsonify({
                "exists": license_exists or plate_exists,
                "licenseNumberExists": license_exists,
                "licensePlateExists": plate_exists
            })
            
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def submit_form():
    """
    API endpoint to submit driver registration form.
    
    Performs the following steps:
    1. Validates that license details don't already exist
    2. Inserts new driver record into database
    3. Sends SMS confirmation via Twilio
    
    Expected JSON payload: Full driver registration data
    
    Returns:
        JSON: {
            "success": boolean,
            "error": string (optional)
        }
    """
    data = request.json
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Check for existing license details
            c.execute('''
                SELECT license_number, license_plate 
                FROM drivers 
                WHERE license_number = ? OR license_plate = ?
            ''', (data['licenseNumber'], data['licensePlate']))
            
            existing = c.fetchone()
            if existing:
                return jsonify({
                    "success": False,
                    "error": "License details already registered",
                    "licenseNumberExists": existing[0] == data['licenseNumber'],
                    "licensePlateExists": existing[1] == data['licensePlate']
                })

            # Insert new driver record
            c.execute('''
                    INSERT INTO drivers (
                        name, phone, email, license_number, license_plate,
                        gender, Model, car_color, available_seats,
                        is_new_car, is_luxury, has_wheelchair,
                        car_seat_count, has_booster,
                        notify_rides, notify_deliveries, PassengerPreference
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['name'], data['phone'], data['email'],
                    data['licenseNumber'], data['licensePlate'],
                    data['gender'], data['Model'], data['carColor'],
                    data['availableSeats'], data['isNewCar'],
                    data['isLuxury'], data['hasWheelchair'],
                    data['carSeatCount'], data['hasBooster'],
                    data['notifyRides'], data['notifyDeliveries'],
                    data['PassengerPreference']
                ))
            
            # Send SMS confirmation
            try:
                message = client.messages.create(
                    body=f"Thank you {data['name']} license no- {data['licenseNumber']} for registering as a driver!",
                    from_=twilio_phone,
                    to=data['phone']
                )
            except Exception as e:
                print(f"Twilio SMS Error: {str(e)}")
                # Continue even if SMS fails
            
            return jsonify({"success": True})
    
    except sqlite3.Error as e:
        print(f"Database Error: {str(e)}")
        return jsonify({"success": False, "error": f"Database error: {str(e)}"})
    except Exception as e:
        print(f"General Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)})

# Start the application
if __name__ == '__main__':
    app.run(debug=True)  # Set debug=False in production