import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import datetime
from streamlit_autorefresh import st_autorefresh

# --- Page Configuration ---
st.set_page_config(
    page_title="Streamlit Chat",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="auto"
)

# --- Firebase Initialization ---
# This function initializes Firebase, handling reruns gracefully.
def init_firebase():
    """Initializes the Firebase Admin SDK."""
    if not firebase_admin._apps:
        try:
            # Load credentials from Streamlit's secrets
            creds_dict = st.secrets["firebase_service_account"]
            creds = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(creds)
            st.toast("Firebase connection successful! 🔥", icon="🎉")
        except Exception as e:
            st.error("Firebase initialization failed. Check your `secrets.toml` file.")
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
# This ensures we have placeholders for user info and app state.
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
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
    users_ref = db.collection(USERS_COLLECTION).stream()
    users = []
    for user in users_ref:
        users.append(user.to_dict())
    return users

def load_messages():
    """Fetches and sorts messages from Firestore."""
    messages_ref = db.collection(MESSAGES_COLLECTION).order_by("timestamp", direction=firestore.Query.ASCENDING)
    docs = messages_ref.stream()
    
    messages = []
    for doc in docs:
        msg = doc.to_dict()
        # Only include messages that have a valid timestamp
        if 'timestamp' in msg and msg['timestamp']:
            messages.append(msg)
    return messages

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
                    # Generate a unique ID for the user's session
                    user_id = str(uuid.uuid4())
                    
                    # Store user info in session state
                    st.session_state.user_id = user_id
                    st.session_state.display_name = display_name
                    st.session_state.avatar = avatar
                    st.session_state.chat_ready = True
                    
                    try:
                        # Save user profile to Firestore
                        user_doc_ref = db.collection(USERS_COLLECTION).document(user_id)
                        user_doc_ref.set({
                            "user_id": user_id,
                            "display_name": display_name,
                            "avatar": avatar,
                            "joined_at": firestore.SERVER_TIMESTAMP
                        })
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
    # This polls Firestore for updates from other users
    st_autorefresh(interval=3000, key="chat_refresher")

    # Display Chat Messages
    # We create a container to hold messages
    chat_container = st.container()
    
    try:
        messages = load_messages()
        
        with chat_container:
            if not messages:
                st.info("No messages yet. Be the first to say something!")
            
            for msg in messages:
                # Check if the message is from the current user
                is_current_user = msg.get('user_id') == st.session_state.user_id
                
                # Determine role for alignment ('user' = right, 'assistant' = left)
                role = "user" if is_current_user else "assistant"
                
                with st.chat_message(name=msg.get('display_name', '...'), avatar=msg.get('avatar', '👤')):
                    st.markdown(msg.get('text', ''))
                    
                    # Show timestamp subtly
                    ts = msg.get('timestamp')
                    if ts:
                        # Convert Firestore timestamp to human-readable time
                        local_time = ts.astimezone(datetime.datetime.now().astimezone().tzinfo)
                        st.caption(f"_{local_time.strftime('%I:%M %p')}_")

    except Exception as e:
        st.error("Failed to load messages.")
        st.exception(e)

    # --- Chat Input (Pinned to bottom) ---
    prompt = st.chat_input("Type your message...")

    if prompt:
        if not prompt.strip():
            st.toast("Message cannot be empty!", icon="⚠️")
        else:
            try:
                # Create the message payload
                message_data = {
                    "text": prompt,
                    "display_name": st.session_state.display_name,
                    "avatar": st.session_state.avatar,
                    "user_id": st.session_state.user_id,
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
                
                # Add message to Firestore
                db.collection(MESSAGES_COLLECTION).add(message_data)
                
                # No need to call st.rerun() here, 
                # st.chat_input triggers a rerun on its own!
            except Exception as e:
                st.error("Failed to send message.")
                st.exception(e)