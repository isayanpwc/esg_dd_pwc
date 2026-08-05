import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")


def _get_path(filename):
    return os.path.join(DB_DIR, filename)


def read_json(filename):
    path = _get_path(filename)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(filename, data):
    path = _get_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def get_users():
    data = read_json("users.json")
    return data.get("users", [])


def save_user(user_dict):
    data = read_json("users.json")
    users = data.get("users", [])
    users.append(user_dict)
    data["users"] = users
    write_json("users.json", data)


def find_user(identifier):
    users = get_users()
    for u in users:
        if u["username"] == identifier or u["email"] == identifier:
            return u
    return None


def username_exists(username):
    return any(u["username"] == username for u in get_users())


def email_exists(email):
    return any(u["email"] == email.lower() for u in get_users())


def get_datasources(username=None):
    data = read_json("datasources.json")
    connections = data.get("connections", [])
    if username:
        return [c for c in connections if c.get("user") == username]
    return connections


def save_datasource(ds_dict):
    data = read_json("datasources.json")
    connections = data.get("connections", [])
    connections.append(ds_dict)
    data["connections"] = connections
    write_json("datasources.json", data)


def remove_datasource(username, created_at):
    data = read_json("datasources.json")
    connections = data.get("connections", [])
    data["connections"] = [
        c for c in connections
        if not (c.get("user") == username and c.get("created_at") == created_at)
    ]
    write_json("datasources.json", data)


def get_all_users():
    return get_users()


def update_user(username, updates):
    data = read_json("users.json")
    users = data.get("users", [])
    for u in users:
        if u["username"] == username:
            u.update(updates)
            break
    data["users"] = users
    write_json("users.json", data)


def add_audit_log(username, action):
    data = read_json("audit_logs.json")
    logs = data.get("logs", [])
    logs.append({
        "user": username,
        "action": action,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["logs"] = logs
    write_json("audit_logs.json", data)


def get_audit_logs(user_filter=None, action_filter=None, limit=100, _caller_is_system=False):
    if not _caller_is_system:
        from utils.auth import is_admin
        if not is_admin():
            return []
    data = read_json("audit_logs.json")
    logs = data.get("logs", [])
    if user_filter:
        logs = [l for l in logs if l.get("user") == user_filter]
    if action_filter:
        logs = [l for l in logs if action_filter.lower() in l.get("action", "").lower()]
    return logs[-limit:][::-1]


def get_audit_log_stats():
    from utils.auth import is_admin
    if not is_admin():
        return {"total": 0, "by_action": {}, "by_user": {}, "by_date": {}}
    data = read_json("audit_logs.json")
    logs = data.get("logs", [])
    total = len(logs)
    by_action = {}
    by_user = {}
    by_date = {}
    for l in logs:
        action = l.get("action", "Unknown")
        by_action[action] = by_action.get(action, 0) + 1
        user = l.get("user", "Unknown")
        by_user[user] = by_user.get(user, 0) + 1
        date_key = l.get("timestamp", "")[:10]
        by_date[date_key] = by_date.get(date_key, 0) + 1
    return {"total": total, "by_action": by_action, "by_user": by_user, "by_date": by_date}


def delete_user(username):
    data = read_json("users.json")
    data["users"] = [u for u in data.get("users", []) if u["username"] != username]
    write_json("users.json", data)


def disable_user(username):
    update_user(username, {
        "disabled": True,
        "disabled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def enable_user(username):
    update_user(username, {"disabled": False, "disabled_at": None})


def get_active_users(days=7):
    from utils.auth import is_admin
    if not is_admin():
        return []
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = read_json("audit_logs.json")
    logs = data.get("logs", [])
    active = set()
    for log in logs:
        if log.get("timestamp", "")[:10] >= cutoff:
            active.add(log.get("user", ""))
    return list(active)
