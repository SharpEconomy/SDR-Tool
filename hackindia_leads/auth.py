import os

import streamlit.components.v1 as components

# Create a _RELEASE constant. We'll set this to False while we're developing
# the component, and True when we're ready to package and distribute it.
_RELEASE = True

_component_path = os.path.join(os.path.dirname(__file__), "components", "firebase_auth")
_firebase_auth_component = components.declare_component(
    "firebase_auth", path=_component_path
)


def firebase_login_screen(firebase_config: dict[str, str], key=None):
    """
    Renders the Firebase Google Auth button.
    Returns: None or a dict containing `email` and `token`.
    """
    return _firebase_auth_component(firebaseConfig=firebase_config, key=key)
