#المحادثة

sessions = {}

def get_state(phone):
    return sessions.get(phone, {"step": "start"})

def update_state(phone, data):
    sessions[phone] = data