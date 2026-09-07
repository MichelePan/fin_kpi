import hmac
import streamlit as st

def get_auth_secret(key: str, default=None):
    try:
        return st.secrets["AUTH"][key]
    except Exception:
        return default

def check_credentials(username: str, password: str) -> bool:
    expected_username = get_auth_secret("USERNAME")
    expected_password = get_auth_secret("PASSWORD")

    if not expected_username or not expected_password:
        return False

    username_ok = hmac.compare_digest(
        str(username).strip(),
        str(expected_username).strip(),
    )

    password_ok = hmac.compare_digest(
        str(password),
        str(expected_password),
    )

    return username_ok and password_ok

def login_required():
    if st.session_state.get("authenticated") is True:
        return

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            display: none;
        }

        div[data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(33, 150, 243, 0.12), transparent 32%),
                radial-gradient(circle at bottom right, rgba(63, 81, 181, 0.10), transparent 32%),
                #f7f8fb;
        }

        div[data-testid="stHeader"] {
            background: transparent;
        }

        .block-container {
            max-width: 620px;
            padding-top: 5rem;
            padding-bottom: 4rem;
        }

        .login-logo {
            width: 64px;
            height: 64px;
            border-radius: 18px;
            background: linear-gradient(135deg, #1565c0, #42a5f5);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.2rem auto;
            color: white;
            font-size: 2rem;
            font-weight: 800;
            box-shadow: 0 14px 32px rgba(21, 101, 192, 0.28);
        }

        .login-title {
            text-align: center;
            font-size: 2.15rem;
            line-height: 1.2;
            font-weight: 800;
            color: #172033;
            margin-bottom: 0.35rem;
        }

        .login-subtitle {
            text-align: center;
            font-size: 1rem;
            color: #667085;
            margin-bottom: 2rem;
        }

        div[data-testid="stForm"] {
            background: #ffffff;
            border: 1px solid rgba(16, 24, 40, 0.08);
            border-radius: 20px;
            padding: 2rem 2rem 1.6rem 2rem;
            box-shadow:
                0 18px 45px rgba(16, 24, 40, 0.10),
                0 2px 8px rgba(16, 24, 40, 0.04);
        }

        div[data-testid="stTextInput"] label {
            font-weight: 600;
            color: #344054;
        }

        div[data-testid="stTextInput"] input {
            border-radius: 10px;
        }

        div[data-testid="stFormSubmitButton"] button {
            background: linear-gradient(135deg, #1565c0, #1e88e5) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 12px !important;
            height: 3rem;
            font-weight: 700;
            font-size: 1rem;
            box-shadow: 0 10px 22px rgba(30, 136, 229, 0.28);
        }

        div[data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(135deg, #0d47a1, #1565c0) !important;
            color: #ffffff !important;
            border: none !important;
        }

        div[data-testid="stFormSubmitButton"] button:focus {
            color: #ffffff !important;
            border: none !important;
            box-shadow: 0 0 0 3px rgba(30, 136, 229, 0.22) !important;
        }

        .login-footer {
            text-align: center;
            color: #98a2b3;
            font-size: 0.85rem;
            margin-top: 1.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="login-logo">J</div>
        <div class="login-title">Jira Project Dashboard</div>
        <div class="login-subtitle">Accedi per consultare lo stato di avanzamento del progetto</div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input(
            "Username",
            placeholder="Inserisci username",
        )

        password = st.text_input(
            "Password",
            type="password",
            placeholder="Inserisci password",
        )

        submitted = st.form_submit_button(
            "Accedi",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        if check_credentials(username, password):
            st.session_state["authenticated"] = True
            st.session_state["authenticated_user"] = username.strip()
            st.rerun()
        else:
            st.error("Username o password non corretti.")

    st.markdown(
        """
        <div class="login-footer">
            Accesso riservato agli utenti autorizzati
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.stop()

def render_logout():
    authenticated_user = st.session_state.get("authenticated_user", "")

    if authenticated_user:
        st.sidebar.caption(f"Accesso effettuato come: **{authenticated_user}**")

    if st.sidebar.button("Logout", key="logout_button"):
        st.session_state["authenticated"] = False
        st.session_state["authenticated_user"] = ""

        keys_to_remove = [
            "worklog_loaded",
            "worklog_df",
            "resolution_time_loaded",
            "resolution_time_df",
            "resolution_time_signature",
        ]

        for key in keys_to_remove:
            if key in st.session_state:
                del st.session_state[key]

        st.rerun()
