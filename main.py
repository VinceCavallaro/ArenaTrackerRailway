import socket
import os
import threading
import time
import json
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
#from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from firebase import ensure_twitch_channel_exists, remove_user_from_channel, remove_current_user, add_user_to_firebase, get_user_list, nextOpponent, save_token_to_firebase, load_token_from_firebase, clear_user_list, open_list, close_list, update_list_limit, get_sub_mode, update_sub_mode

#load_dotenv()

# YouTube API setup
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

thread_local_state = threading.local()

# thread_local_state.youtube_thread = None
youtube_channel_state = {}
youtube_channel_state_lock = threading.Lock()

# Twitch IRC Setup
server = 'irc.chat.twitch.tv'
port = 6667
nickname = "ArenaTracker"
token = os.getenv("TWITCH_OAUTH")
channel = f"#{os.getenv('TWITCH_CHANNEL')}"

# Connect to IRC
def connect_to_twitch(username):
    sock = socket.socket()
    sock.connect((server, port))
    sock.send(f"PASS {token}\n".encode('utf-8'))
    sock.send(f"NICK {nickname}\n".encode('utf-8'))
    sock.send("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\n".encode('utf-8'))
    sock.send(f"JOIN {username}\n".encode('utf-8'))
    print(f"Connected to {username} as {nickname}")
    return sock

def start_youtube_listener(channel, sock):
    with youtube_channel_state_lock:
        is_live = youtube_channel_state.get(channel, {}).get("is_live", False)    
    
    if is_live:
        print("YouTube listener is already running.")
        sock.send(f"PRIVMSG #{channel} :Youtube channel is already live.\r\n".encode('utf-8'))
        return "YouTube listener already connected."
    else:
        thread = threading.Thread(target=get_youtube_chat, args=(channel, sock))
        thread.daemon = True
        thread.start()
        sock.send(f"PRIVMSG #{channel} :Attempting to start YouTube listener.\r\n".encode('utf-8'))
        return "YouTube listener started."

def parse_tags(tags_str):
    tags = {}
    for tag in tags_str.split(';'):
        if '=' in tag:
            key, value = tag.split('=', 1)
            tags[key] = value
        else:
            tags[tag] = None
    return tags

def extract_tags(resp):
    # Tags come before the first space
    # Usually message starts with tags, e.g.
    # "badge-info=;badges=...;mod=0 ... :username@channel: message"
    try:
        tags_str = resp.split(' ', 1)[0]
        return parse_tags(tags_str)
    except IndexError:
        return {}

def extract_details(resp):
    try:
        after_colon = resp.split(':', 2)[1]  # The part after first colon
        details = after_colon.split('@', 1)[0]
        return details
    except IndexError:
        return None

def extract_message(resp):
    try:
        return resp.split('PRIVMSG', 1)[1].split(':', 1)[1].strip()
    except IndexError:
        return None

def listen_to_twitch(sock, channel):
    last_heartbeat = time.time()
    
    try:    
        while True:
            resp = sock.recv(2048).decode('utf-8')
            if resp.startswith("PING"):
                print("Received PING from Twitch. Sending PONG.")
                sock.send("PONG :tmi.twitch.tv\n".encode('utf-8'))
            elif "PRIVMSG" in resp:
                tags = extract_tags(resp)
                mod_status = tags.get('mod', '0')
                is_streamer = False
                username = tags.get('display-name', extract_details(resp))
                message = extract_message(resp)
                sub_status = tags.get('subscriber', extract_details(resp))
                #print(resp)
                print(f"Mod: {mod_status} | Subscriber: {sub_status} | User: {username}@{channel} | Msg: {message}")
                if username == channel.lstrip('#'):
                    is_streamer = True
    
                if message.strip().lower() == "!hello":
                    response = f"Hello {username}, welcome to the stream!"
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.lower().startswith("!join"):
                    if get_sub_mode(channel.lstrip('#')) == 1:
                        if int(sub_status) == 1:
                            response = add_user_to_firebase(channel.lstrip('#'), username, "Twitch", True)
                        else:
                            response = "You cannot join the list while not a Twitch Subscriber during Subscriber Only mode."
                    else:
                        response = add_user_to_firebase(channel.lstrip('#'), username, "Twitch", True)
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
    
                elif message.lower().startswith("!add") and (mod_status == '1' or is_streamer):
                    parts = message.split(" ", 1)
                    if parts[0] == "!add": # Accept strictly !add, not other things such as !addcom (nightbot command)
                        target_user = parts[1].strip() if len(parts) > 1 else username
                        response = add_user_to_firebase(channel.lstrip('#'), target_user, "Twitch", False)
                        sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.lower().startswith("!remove") and (mod_status == '1' or is_streamer):
                    parts = message.split(" ", 1)
                    if len(parts) == 1:
                        # No target user provided
                        response = "Please specify a user to remove. Usage: !remove username"
                    else:
                        target_user = parts[1].strip()
                        response = remove_user_from_channel(channel.lstrip('#'), target_user)
    
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.strip().lower() == "!clear" and is_streamer:
                    response = clear_user_list(channel.lstrip('#'))
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.strip().lower() == "!leave":
                    if remove_current_user(channel.lstrip('#'), username):
                        sock.send(f"PRIVMSG {channel} :You have been removed from the list, {username}.\r\n".encode('utf-8'))
                elif message.strip().lower() == "!next" and is_streamer:
                    response = nextOpponent(channel.lstrip('#'))
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.strip().lower() == "!list":
                    response = get_user_list(channel.lstrip('#'))
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.strip().lower() == "!connect" and channel == "#ArenaTracker":
                    tUsername = "#" + username
                    run_bot(tUsername)
                elif message.strip().lower() == "!eggxecute" and username == "Egglamation":
                    parts = message.split(" ", 1)
                    tUsername = "#" + parts[1]
                    run_bot(tUsername)
                elif message.strip().lower() == "!connectyoutube":
                    start_youtube_listener(channel.lstrip('#'), sock)
                elif message.strip().lower() == "!open" and is_streamer:
                    # Adding !connectyoutube command as open, considering Fatality opens the list once a stream at the beginning anyway
                    start_youtube_listener(channel.lstrip('#'), sock)
                    response = open_list(channel.lstrip('#'))
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.strip().lower() == "!close" and is_streamer:
                    response = close_list(channel.lstrip('#'))
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.lower().startswith("!submode") and (mod_status == '1' or is_streamer):
                    parts = message.split(" ", 1)
                    if len(parts) == 1:
                        # No submode provided
                        response = "Please enter either 0 or 1 after !submode. 0 disables sub only mode, 1 enables sub only mode."
                    else:
                        try:
                            option = int(parts[1].strip())
                            response = update_sub_mode(channel.lstrip('#'), option)
                        except ValueError:
                            response = "Please enter either 0 or 1 after !submode. 0 disables sub only mode, 1 enables sub only mode."
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                elif message.lower().startswith("!limit") and (mod_status == '1' or is_streamer):
                    parts = message.split(" ", 1)
                    if len(parts) == 1:
                        # No limit provided
                        response = "Please specify a number to set the max limit of the list. Usage: !limit (number)."
                    else:
                        try:
                            limit = int(parts[1].strip())
                            if limit > 0:
                                response = update_list_limit(channel.lstrip('#'), limit)
                            else:
                                response = "Limit must be a positive number greater than 0"
                        except ValueError:
                            response = "Argument invalid. Please enter a number after !limit."
                    sock.send(f"PRIVMSG {channel} :{response}\r\n".encode('utf-8'))
                # 🔁 Send a keep-alive message every 30 minutes
            #if time.time() - last_heartbeat >= 1800:
                #try:
                    #sock.send(f"PRIVMSG {channel} :\u2800\r\n".encode('utf-8'))  # Replace "." with invisible char if preferred
                    #print(f"[KeepAlive] Sent heartbeat to {channel}")
                #except Exception as e:
                    #print(f"[KeepAlive Error] {e}")
                #last_heartbeat = time.time()
    
    except Exception as e:
        print(f"[Twitch Listener Disconnected] {e}")

# Get YouTube chat messages
def get_youtube_chat(channel_name, sock: str):
    # thread_local_state.is_channel_live = False
    
    # Use the Twitch username as the Firebase key
    creds = load_token_from_firebase(channel_name)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            youtube_json = json.loads(os.getenv("YOUTUBE_CREDENTIALS"))
            flow = InstalledAppFlow.from_client_config(youtube_json, SCOPES)
            #flow = InstalledAppFlow.from_client_secrets_file(
                #'D:/Twitch bot/Twitch IRC/credentials.json', SCOPES
            #)
            creds = flow.run_local_server(port=0)

        save_token_to_firebase(creds, channel_name)

    youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=creds)

    # Get live broadcasts owned by the authenticated user
    broadcasts_response = youtube.liveBroadcasts().list(
        part="snippet",
        mine=True,
    ).execute()

    # Filter to the one that's currently live and has a liveChatId
    live_chat_id = None
    latest_start_time = None

    for item in broadcasts_response.get("items", []):
        snippet = item.get("snippet", {})
        live_chat = snippet.get("liveChatId", {})
        start_time = snippet.get("actualStartTime")
        end_time = snippet.get("actualEndTime")

        if start_time and live_chat and not end_time:
            if not latest_start_time or start_time > latest_start_time:
                live_chat_id = live_chat
                latest_start_time = start_time
        
    if live_chat_id:
        with youtube_channel_state_lock:
            youtube_channel_state[channel_name] = {"is_live": True}
        print(f"[DEBUG] Current thread: {threading.current_thread().name}")
    else:
        print("No active live broadcast with chat found.")
        with youtube_channel_state_lock:
            youtube_channel_state[channel_name] = {"is_live": False}
        # input("Press Enter to exit...")
        return

    print(f"Connected to YouTube chat for channel: {channel_name}")
    
    seen_message_ids = set()

    next_page_token = None

    while True:
        try:
            live_chat_messages = youtube.liveChatMessages().list(
                liveChatId=live_chat_id,
                part="snippet,authorDetails",
                pageToken=next_page_token
            ).execute()

            for message in live_chat_messages['items']:
                message_id = message['id']

                if message_id in seen_message_ids:
                    continue

                seen_message_ids.add(message_id)

                author_details = message['authorDetails']
                author = message['authorDetails']['displayName']
                text = message['snippet']['displayMessage']

                print(f"YouTube - {author}: {text}")

                if text.lower() == "!hello":
                    response = f"[ArenaTrack 🤖] Hello {author}, welcome to the stream!"
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower().startswith("!join"):
                    if get_sub_mode(channel_name) == 1:
                        if author_details.get('isChatSponsor', True):
                            response = add_user_to_firebase(channel_name, author, "Youtube", True)
                            send_message_to_youtube_chat(youtube, live_chat_id, response)
                        else:
                            response = "You cannot join the list while not a Youtube Member during Member Only mode."
                            send_message_to_youtube_chat(youtube, live_chat_id, response)
                    else:
                        response = add_user_to_firebase(channel_name, author, "Youtube", True)
                        send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower().startswith("!add") and (author_details.get('isChatModerator') or author_details.get('isChatOwner')):
                    parts = text.split(" ", 1)
                    target_user = parts[1].strip() if len(parts) > 1 else author
                    response = add_user_to_firebase(channel_name, target_user, "Youtube", False)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower().startswith("!remove") and (author_details.get('isChatModerator') or author_details.get('isChatOwner')):
                    parts = text.split(" ", 1)
                    if len(parts) == 1:
                        response = "Please specify a user to remove. Usage: !remove username"
                    else:
                        target_user = parts[1].strip()
                        response = remove_user_from_channel(channel_name, target_user)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!leave":
                    response = remove_current_user(channel_name, author)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!next" and (author_details.get('isChatOwner')):
                    response = nextOpponent(channel_name)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!list":
                    response = get_user_list(channel_name)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!clear" and (author_details.get('isChatOwner')):
                    response = clear_user_list(channel_name)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!open" and (author_details.get('isChatOwner')):
                    response = open_list(channel_name)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower() == "!close" and (author_details.get('isChatOwner')):
                    response = close_list(channel_name)
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower().startswith("!submode") and (author_details.get('isChatOwner')):
                    parts = text.split(" ", 1)
                    if len(parts) == 1:
                        # No submode provided
                        response = "Please enter either 0 or 1 after !submode. 0 disables sub only mode, 1 enables sub only mode."
                    else:
                        try:
                            option = int(parts[1].strip())
                            response = update_sub_mode(channel_name, option)
                        except ValueError:
                            response = "Please enter either 0 or 1 after !submode. 0 disables sub only mode, 1 enables sub only mode."
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

                elif text.lower().startswith("!limit") and (author_details.get('isChatModerator') or author_details.get('isChatOwner')):
                    parts = text.split(" ", 1)
                    if len(parts) == 1:
                        # No limit provided
                        response = "Please specify a number to set the max limit of the list. Usage: !limit (number)."
                    else:
                        try:
                            limit = int(parts[1].strip())
                            if limit > 0:
                                response = update_list_limit(channel_name, limit)
                            else:
                                response = "Limit must be a positive number greater than 0"
                        except ValueError:
                            response = "Argument invalid. Please enter a number after !limit."
                    send_message_to_youtube_chat(youtube, live_chat_id, response)

        except HttpError as e:
            error_content = e.content.decode('utf-8') if hasattr(e.content, 'decode') else str(e)
            if 'liveChatEnded' in error_content:
                print(f"YouTube live chat for {channel_name} is no longer live.")
                # thread_local_state.is_channel_live = False
                with youtube_channel_state_lock:
                    youtube_channel_state[channel_name] = {"is_live": False}
                break
            else:
                print(f"HttpError while fetching YouTube chat: {e}")
                break

        #time.sleep(3)
        next_page_token = live_chat_messages.get("nextPageToken")
        polling_interval = live_chat_messages.get('pollingIntervalMillis', 5000)
        
        #The below was polling about every second, we want to reduce this to save units on API calls
        #print(polling_interval)
        #time.sleep(polling_interval / 1000.0)

        time.sleep(12)

def send_message_to_youtube_chat(youtube, live_chat_id, message):
    youtube.liveChatMessages().insert(
        part="snippet",
        body={
            "snippet": {
                "liveChatId": live_chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {
                    "messageText": message
                }
            }
        }
    ).execute()

# Run both Twitch and YouTube bots
def run_bot(username):
    channel_name = username.lstrip('#')
    ensure_twitch_channel_exists(channel_name)

    twitch_sock = connect_to_twitch(username)
    twitch_thread = threading.Thread(target=listen_to_twitch, args=(twitch_sock,username))
    twitch_thread.daemon = True
    twitch_thread.start()

    youtube_thread = threading.Thread(target=get_youtube_chat, args=(channel_name,twitch_sock))
    youtube_thread.daemon = True
    youtube_thread.start()

if __name__ == "__main__":
    run_bot(channel)
    # input("Press Enter to exit...\n")
    # Keep main thread alive forever
    while True:
        time.sleep(3600)
