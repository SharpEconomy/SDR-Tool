import os

import streamlit.components.v1 as components

_component_path = os.path.join(os.path.dirname(__file__), "components", "firebase_auth")
_firebase_auth_component = components.declare_component(
    "growth_engine_firebase_auth",
    path=_component_path,
)


def firebase_login_screen(firebase_config: dict[str, str], key=None):
    return _firebase_auth_component(firebaseConfig=firebase_config, key=key)
