# firebase.py
import time
import firebase_admin
import dateutil.parser  # Install with `pip install python-dateutil`
import json
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from firebase_admin import firestore
from firebase_admin import credentials, db

# Initialize Firebase (only once)
# cred = credentials.Certificate(r'D:\Twitch bot\Twitch IRC\serviceaccountkeyregen.json')
firebase_json = json.loads(os.getenv("FIREBASE_SERVICE_ACCOUNT"))
cred = credentials.Certificate(firebase_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://arenatracker-a9066-default-rtdb.firebaseio.com'
})

def add_user_to_firebase(channel: str, username: str, platform: str, checkLimit: bool) -> str:
    status = check_list_status(channel)
    if status is not None:
        return status

    ref = db.reference(f'users/{channel}/list')
    data = ref.get()

    if checkLimit:
        limit = get_list_limit(channel)

        if data is not None:
            if len(data) >= limit:
                return f"The list limit has been reached!"

    # Check if user already exists
    if ref.child(username).get() is not None:
        return f"{username} is already in the list!"

    user_ref = ref.child(username)
    user_ref.set({
        "platform": platform,
        "timestamp": int(time.time())
    })

    return f"Added {username} to the list from {platform}!"

def remove_current_user(channel_name, current_username):
    return remove_user_from_channel(channel_name, current_username)

def remove_user_from_channel(channel_name, username_to_remove) -> str:
    try:
        list_ref = db.reference(f'users/{channel_name}/list')
        user_list = list_ref.get()

        if username_to_remove in user_list:
            user_ref = list_ref.child(username_to_remove)
            user_ref.delete()
            return f"{username_to_remove} has been removed from the list."
        else:
            return f"{username_to_remove} is already off the list."
    except Exception as e:
        return f"Error removing user: {e}"

def clear_user_list(channel_name: str) -> str:
    try:
        ref = db.reference(f'users/{channel_name}/list')
        # Delete the entire list node
        ref.delete()
        return f"The list for channel '{channel_name}' has been cleared."
    except Exception as e:
        return f"Error clearing list: {e}"

def nextOpponent(channel_name) -> str:
    try:
        ref = db.reference(f'users/{channel_name}/list')
        users = ref.get()

        if not users:
            return "The list is empty."

        if len(users) == 1:
            ref.delete()
            return "Thanks for playing! The list is now empty."

        sorted_users = sorted(users.items(), key=lambda item: item[1].get('timestamp', 0))
        first_username = sorted_users[0][0]
        second_username = sorted_users[1][0]
        
        # Remove the first user
        ref.child(first_username).delete()

        return f"Thanks for playing, {first_username}! {second_username}, it is now your turn!"
    except Exception as e:
        return f"Error removing top user: {e}"

#def get_user_list(channel: str) -> list:
#    ref = db.reference(f'users/{channel}/list')
#    data = ref.get() or {}
#    return list(data.values())

def get_user_list(channel: str) -> str:
    ref = db.reference(f'users/{channel}/list')
    user_dict = ref.get()

    if not user_dict:
        return "The list is empty!"

    # Each value should now be a dict with a timestamp
    sorted_users = sorted(user_dict.items(), key=lambda item: item[1].get('timestamp', 0))
    user_list = [username for username, _ in sorted_users]

    if len(user_list) == 1:
        return f"On stream: {user_list[0]}"
    else:
        on_stream = user_list[0]
        up_next = ", ".join(user_list[1:])
        return f"On stream: {on_stream}, Up next: {up_next}"

def ensure_twitch_channel_exists(channel: str):
    """Creates the channel entry in Firebase if it doesn't already exist."""
    ref = db.reference(f'users/{channel}')
    if not ref.get():
        # Initialize empty list node
        ref.set({
            'list': {},
            'status': 'Open',
            'limit': 8,
            'sub_only': 0
        })
        print(f"Created new Firebase entry for channel: {channel}")
    else:
        print(f"Firebase entry for channel {channel} already exists.")

def save_token_to_firebase(creds: Credentials, channel_id: str):
    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
        'expiry': creds.expiry.isoformat() if creds.expiry else None
    }
    ref = db.reference(f'users/{channel_id}/oauth_tokens')
    ref.set(token_data)

def load_token_from_firebase(channel_id: str):
    ref = db.reference(f'users/{channel_id}/oauth_tokens')
    data = ref.get()
    if not data:
        return None

    creds = Credentials(
        token=data['token'],
        refresh_token=data['refresh_token'],
        token_uri=data['token_uri'],
        client_id=data['client_id'],
        client_secret=data['client_secret'],
        scopes=data['scopes']
    )

    if data.get('expiry'):
        creds.expiry = dateutil.parser.isoparse(data['expiry'])

    return creds

def get_list_limit(channel_id: str) -> int:
    try:
        ref = db.reference(f'users/{channel_id}/limit')
        limit = ref.get()
        if limit is None:
            return 0
        return limit
    except Exception as e:
        return f"Error retrieving list limit: {e}"

def update_list_limit(channel_id: str, limit: int) -> str:
    try:
        ref = db.reference(f'users/{channel_id}')
        ref.update({
            'limit': limit
        })
        return f"The limit has been adjusted to {limit}"
    except Exception as e:
        return f"Error changing list limit: {e}"

def get_sub_mode(channel_id: str) -> int:
    ref = db.reference(f'users/{channel_id}/sub_only')
    sub_only = ref.get()
    return sub_only

def update_sub_mode(channel_id: str, option: int) -> str:
    try:
        ref = db.reference(f'users/{channel_id}')
        if option == 0:
            ref.update({
                'sub_only': option
            })
            return "Sub only mode is disabled"
        elif option == 1:
            ref.update({
                'sub_only': option
            })            
            return f"Sub only mode is enabled"
        else:
            return f"Please enter either 0 or 1 after !submode. 0 disables sub only mode, 1 enables sub only mode."
    except Exception as e:
        return f"Error changing sub_mode: {e}"

def open_list(channel_id: str) -> str:
    try:
        ref = db.reference(f'users/{channel_id}')
        ref.update({
            'status': 'Open'  
        })
        return f"The list is now open"
    except Exception as e:
        return f"Error changing list status: {e}"

def close_list(channel_id: str) -> str:
    try:
        ref = db.reference(f'users/{channel_id}')
        ref.update({
            'status': 'Closed'
        })
        return f"The list is now closed"
    except Exception as e:
        return f"Error changing list status: {e}"

def check_list_status(channel_id: str) -> str:
    try:
        ref = db.reference(f'users/{channel_id}/status')
        status = ref.get()

        if status == 'Closed':
            return f"The list is closed"
        
    except Exception as e:
        return f"Error retrieving list status: {e}"
