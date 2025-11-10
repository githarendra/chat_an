import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import datetime
from streamlit_autorefresh import st_autorefresh
import ast  # For safely parsing the secret string

# --- Page Configuration ---
st.set_page_config(
    page_title="Streamlit Chat",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="auto"
)

# --- Firebase Initialization (UPDATED) ---
def init_firebase():
    """Initializes the Firebase Admin SDK."""
    if not firebase_admin._apps:
        try:
            # --- NEW CHECK ---
            # Check if the secret key exists at all
            if "firebase_service_account" not in st.secrets:
                st.error("Firebase secrets not found. Please add [firebase_service_account] to your .streamlit/secrets.toml or Streamlit Cloud secrets.")
                st.stop()
            # --- END NEW CHECK ---

            # Load credentials from Streamlit's secrets
            creds_from_secrets = st.secrets["firebase_service_account"]
            
            creds_dict = None
            
            # --- UPDATED LOGIC ---
            # Check if it's a dict-like object (from TOML)
            # Streamlit's SecretsT object might not be a true dict, 
            # but it will have dict-like methods.
            if hasattr(creds_from_secrets, 'keys'):
                # Convert Streamlit's SecretsT object to a plain dict
                creds_dict = dict(creds_from_secrets)
            # Check if the secret is a string (e.g., from pasted JSON/dict string)
            elif isinstance(creds_from_secrets, str):
                if not creds_from_secrets.strip():
                    st.error("Firebase secret is an empty string. Please provide the service account details.")
                    st.stop()
                try:
                    # Safely parse the string into a dictionary
                    creds_dict = ast.literal_eval(creds_from_secrets)
                except (ValueError, SyntaxError) as e:
                    st.error(f"Failed to parse firebase_service_account string. Make sure it's a valid dict/JSON. Error: {e}")
                    st.stop()
            # --- END UPDATED LOGIC ---
            else:
                st.error("firebase_service_account secret is not in a recognized format (dict-like or string).")
                st.write(f"Type found: {type(creds_from_secrets)}") # Add type info to error
                st.stop()

            # Check if the resulting dict is empty
            if not creds_dict:
                 st.error("Firebase credentials dictionary is empty. Please check your secrets.")
                 st.stop()

            # --- THIS IS THE KEY FIX ---
            # The 'private_key' in TOML or pasted strings often has escaped newlines (\\n)
            # This replaces them with actual newlines (\n) for Firebase to read.
            if "private_key" in creds_dict:
                # First, fix newlines for the "pasted string" case
                key_with_newlines = creds_dict["private_key"].replace("\\n", "\n")
                # NEW: Strip leading/trailing whitespace which can corrupt the PEM parser
                creds_dict["private_key"] = key_with_newlines.strip()
            # --- END OF FIX ---

            # Now, creds_dict is a proper dictionary, and this call will work
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
