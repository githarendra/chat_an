import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import datetime
from streamlit_autorefresh import st_autorefresh
import json  # Import the built-in JSON library
# Removed 'ast' as it was not the correct tool for this

# --- Page Configuration ---
st.set_page_config(
    page_title="Streamlit Chat",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="auto"
)

# --- Firebase Initialization (NEW APPROACH) ---
def init_firebase():
    """Initializes the Firebase Admin SDK."""
    if not firebase_admin._apps:
        try:
            # --- NEW LOGIC ---
            # This is the new, simpler secret key we look for.
            secret_key = "FIREBASE_SERVICE_ACCOUNT_JSON"

            if secret_key not in st.secrets:
                st.error(f"Firebase secret `{secret_key}` not found.")
                st.info("Please update your secrets to store the entire service account JSON as a string.")
                st.stop()

            # Load the entire JSON string from secrets
            json_string = st.secrets[secret_key]

            if not json_string.strip():
                st.error("Firebase secret is an empty string.")
                st.stop()

            try:
                # Strip leading/trailing whitespace from TOML multi-line string
                # and parse the JSON string.
                creds_dict = json.loads(json_string.strip())
            except json.JSONDecodeError as e:
                # This is the only error we need to catch.
                # The 'ast.literal_eval' was misleading.
                st.error(f"Failed to parse Firebase JSON. Please check your secret. Error: {e}")
                st.write("Ensure you've pasted the *entire* raw JSON, starting with `{` and ending with `}`.")
                st.stop()
            
            if not isinstance(creds_dict, dict):
                 st.error("Firebase secret did not parse into a dictionary.")
                 st.stop()
            # --- END NEW LOGIC ---

            # Now, creds_dict is a proper dictionary
            creds = credentials.Certificate(creds_dict)
            
            firebase_admin.initialize_app(creds)
            st.toast("Firebase connection successful! 🔥", icon="🎉")
        
        except ValueError as e:
            # This will catch if creds_dict is still invalid
            st.error("Firebase initialization failed. The credential data is likely invalid.")
            st.exception(e) # Show the full error
            st.stop()
        except Exception as e:
            st.error("Firebase initialization failed. Check your `secrets.toml` file or Streamlit Cloud secrets.")
            st.exception(e)
            st.stop()
    
    return firestore.client()

# --- Firestore Collections ---
# Define collection paths
USERS_COLLECTION = "streamlit_chat_app/data/users"
MESSAGES_COLLECTION = "streamlit_chat_app/data/messages"

# --- Main Application ---
try:
    db = init_firebase()
except Exception as e:
    st.error("Failed to initialize Firebase. The app cannot continue.")
    st.stop()


# --- Session State Initialization ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4()) # Generate ID on first load
if 'display_name' not in st.session_state:
    st.session_state.display_name = None
if 'avatar' not in st.session_state:
    st.session_state.avatar = None
if 'chat_ready' not in st.session_state:
    st.session_state.chat_ready = False

# --- Helper Functions ---

@st.cache_data(ttl=60) # Cache user list for 60 seconds
def get_user_list():
    """Fetches all users from Firestore."""
    try:
        users_ref = db.collection(USERS_COLLECTION).stream()
        users = []
        for user in users_ref:
            users.append(user.to_dict())
        return users
    except Exception as e:
        st.error(f"Error fetching user list: {e}")
        return []

def load_messages():
    """Fetches and sorts messages from Firestore."""
    try:
        messages_ref = db.collection(MESSAGES_COLLECTION).order_by("timestamp", direction=firestore.Query.ASCENDING)
        docs = messages_ref.stream()
        
        messages = []
        for doc in docs:
            msg = doc.to_dict()
            # Only include messages that have a valid timestamp
            if 'timestamp' in msg and msg['timestamp']:
                messages.append(msg)
        return messages
    except Exception as e:
        st.error(f"Error loading messages: {e}")
        return []

# --- UI Rendering ---

# 1. "Login" Screen (if chat is not ready)
if not st.session_state.chat_ready:
    st.title("Welcome to Streamlit Chat! 💬")
    st.markdown("Choose a display name and avatar to join the chat.")

    # Use a form for the "login"
    with st.form(key="join_form"):
        display_name = st.text_input("Display Name *", placeholder="Your cool name")
        avatar = st.selectbox("Choose your Avatar", ["🧑‍🚀", "🤖", "👻", "🎉", "🌟", "👾", "🦊", "🥸"])
        submit_button = st.form_submit_button("Join Chat")

        if submit_button:
            if not display_name:
                st.error("Please enter a display name.")
            else:
                with st.spinner("Joining..."):
                    # Store user info in session state
                    st.session_state.display_name = display_name
                    st.session_state.avatar = avatar
                    st.session_state.chat_ready = True
                    
                    try:
                        # Save user profile to Firestore
                        user_doc_ref = db.collection(USERS_COLLECTION).document(st.session_state.user_id)
                        user_doc_ref.set({
                            "user_id": st.session_state.user_id,
                            "display_name": display_name,
                            "avatar": avatar,
                            "joined_at": firestore.SERVER_TIMESTAMP
                        }, merge=True) # Use merge=True to update or create
                        st.rerun()
                    except Exception as e:
                        st.error("Failed to save user profile.")
                        st.exception(e)
                        st.session_state.chat_ready = False

# 2. Main Chat Screen (if chat is ready)
else:
    # --- Sidebar: User List ---
    with st.sidebar:
        st.title("Chat Members")
        st.markdown(f"You are: **{st.session_state.avatar} {st.session_state.display_name}**")
        st.markdown("---")
        
        try:
            users = get_user_list()
            if not users:
                st.write("No other users found.")
            else:
                # Display users in a simple list
                for user in users:
                    # Don't list the current user
                    if user.get('user_id') != st.session_state.user_id:
                        st.markdown(f"{user.get('avatar', '👤')} **{user.get('display_name', 'Anonymous')}**")
        except Exception as e:
            st.error("Could not load user list.")
            st.exception(e)

    # --- Main Chat Area ---
    st.title(f"Anonymous Chat Room")

    # Auto-refresh messages every 3 seconds (3000ms)
    st_autorefresh(interval=3000, key="chat_refresher")

    # Display Chat Messages
    chat_container = st.container(height=400) # Set a fixed height
    
    try:
        messages = load_messages()
        
        with chat_container:
            for msg in messages:
                # Check if 'user_id' exists before accessing
                msg_user_id = msg.get('user_id')
                
                # Determine if the message is from the current user
                is_user = (msg_user_id == st.session_state.user_id)
                
                # Set avatar based on who sent it
                # Use a default '👤' if avatar is missing
                avatar = msg.get('avatar', '👤') if not is_user else None

                # Use st.chat_message for a native chat look
                with st.chat_message(name=msg.get('display_name', 'Guest'), avatar=avatar):
                    st.markdown(msg.get('text', '*message not found*'))
                    
    except Exception as e:
        st.error("Failed to load messages.")
        st.exception(e)

    # --- Chat Input Box ---
    prompt = st.chat_input("What's on your mind?")
    if prompt:
        if not st.session_state.chat_ready or not st.session_state.display_name:
            st.error("You must join the chat to send messages.")
        else:
            try:
                # Add new message to Firestore
                doc_ref = db.collection(MESSAGES_COLLECTION).document()
                doc_ref.set({
                    "user_id": st.session_state.user_id,
                    "display_name": st.session_state.display_name,
                    "avatar": st.session_state.avatar,
                    "text": prompt,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                # Don't rerun, just let the auto-refresher pick it up
            except Exception as e:
                st.error("Failed to send message.")
                st.exception(e)
