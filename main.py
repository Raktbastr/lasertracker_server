from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import sqlite3
from colorama import Fore, Back, Style
import os
import hashlib
import secrets
import requests
from datetime import datetime
import argparse
from pathlib import Path
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

VERSION = "prerelease"

inst_name = "unknown"
db_name = "unknown"
port = 2077
tba_key = "unknown"
testing = False

parser = argparse.ArgumentParser()
parser.add_argument("-t", "--test", action="store_true")
args = parser.parse_args()
testing = args.test

app = Flask(__name__)
CORS(app)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
    default_limits=["200 per minute"]
)

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def is_admin(group_id, username, pin):
    if not username:
        return False
    conn = get_db_connection()
    member = conn.execute(
        "SELECT pin_hash, is_admin FROM members WHERE group_id = ? AND username = ?",
        (group_id, username.lower().strip())
    ).fetchone()
    conn.close()
    return bool(member and member["is_admin"] == 1 and member["pin_hash"] == hash_pin(pin))


def generate_group_key() -> str:
    return secrets.token_hex(3).upper()


def get_db_connection():
    conn = sqlite3.connect(db_name + ".db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL UNIQUE,
                event_key TEXT NOT NULL,
                team_number INTEGER,
                group_key TEXT NOT NULL UNIQUE
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                job TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                UNIQUE(group_id, username)
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                group_key TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp INTERGER NOT NULL
            )
            """
        )
        conn.commit()


def add_log_entry(group_key, username, action, timestamp):
    if not all([username, group_key, action]):
        return False
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO logs (group_key, username, action, timestamp) VALUES (?, ?, ?, ?)", (
                group_key, username, action, timestamp),
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        with open(timestamp + " Failed Log.txt") as file:
            file.write(
                "There was an error processing this log request. It may not have been added to the database.")
            file.write(group_key + " " + username +
                       " " + action + " " + timestamp)
        return False
    finally:
        conn.close()


@app.route("/info", methods=["GET"])
def info():
    return {
        "instance name": inst_name,
        "version": VERSION,
    }


@app.route("/groups", methods=["POST"])
def create_group():
    data = request.json
    group_name = data.get("name")
    event_key = data.get("event_key")
    team_number = data.get("team_number")

    if testing and team_number != "2077":
        return jsonify("Team num must be 2077 for testing"), 401

    leader_username = data.get("leader_username")
    leader_display_name = data.get("leader_display_name")
    leader_pin = data.get("leader_pin")

    if not all([group_name, event_key, team_number, leader_username, leader_display_name, leader_pin]):
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    existing_group = conn.execute(
        "SELECT id FROM groups WHERE group_name = ?", (group_name.strip(),)
    ).fetchone()

    if existing_group:
        conn.close()
        return jsonify({"error": f"A group named '{group_name}' has already been created."}), 409

    try:
        group_key = generate_group_key()

        cursor.execute(
            "INSERT INTO groups (group_name, event_key, team_number, group_key) VALUES (?, ?, ?, ?)",
            (group_name.strip(), event_key, team_number, group_key),
        )
        group_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO members (group_id, username, display_name, pin_hash, job, role, location, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (group_id, leader_username.lower().strip(), leader_display_name, hash_pin(leader_pin),
             "Unknown", "Lead Coach 1", "Unknown", 1),
        )
        leader_id = cursor.lastrowid

        member = conn.execute(
            """
            SELECT m.id, m.username, m.display_name, m.job, m.role, m.location, m.is_admin,
                   g.group_name, g.event_key, g.team_number, g.group_key 
            FROM members m 
            JOIN groups g ON m.group_id = g.id 
            WHERE m.id = ?
            """,
            (leader_id,),
        ).fetchone()

        conn.commit()
        add_log_entry(group_key, leader_username,
                      f"Created group '{group_name}'", datetime.now().timestamp())
        return jsonify(dict(member)), 201

    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Group key conflict or duplicate constraint violated."}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/groups/join", methods=["POST"])
def add_member():
    data = request.json
    group_key = data.get("group_key")
    username = data.get("username")
    display_name = data.get("display_name")
    pin = data.get("pin")
    job = data.get("job", "Unknown")
    role = data.get("role", "Unknown")
    location = data.get("location", "Unknown")

    if not all([group_key, username, display_name, pin]):
        return jsonify({"error": "Join key, username, display name, and pin are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        group = conn.execute(
            "SELECT id, group_name FROM groups WHERE group_key = ?", (group_key.upper(
            ).strip(),)
        ).fetchone()

        if not group:
            conn.close()
            return jsonify({"error": "Invalid Group Join Key"}), 404

        group_id = group["id"]
        group_name = group["group_name"]

        existing_member = conn.execute(
            "SELECT id FROM members WHERE group_id = ? AND username = ?",
            (group_id, username.lower().strip())
        ).fetchone()

        if existing_member:
            conn.close()
            return jsonify({"error": f"The username '{username}' has already been taken within this group."}), 409

        cursor.execute(
            """
            INSERT INTO members (group_id, username, display_name, pin_hash, job, role, location, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (group_id, username.lower().strip(), display_name,
             hash_pin(pin), job, role, location, 0),
        )

        member = conn.execute(
            """
            SELECT m.id, m.username, m.display_name, m.job, m.role, m.location, m.is_admin,
                   g.group_name, g.event_key, g.team_number, g.group_key 
            FROM members m 
            JOIN groups g ON m.group_id = g.id 
            WHERE m.username = ? AND g.group_key = ?
            """,
            (username.lower().strip(), group_key.upper().strip()),
        ).fetchone()

        conn.commit()
        add_log_entry(group_key, username,
                      f"Joined group '{group_name}'", datetime.now().timestamp())
        return jsonify(dict(member)), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "Database constraint violation occurred."}), 409
    finally:
        conn.close()


@app.route("/groups/<group_key>/members/<target_username>/reset-pin", methods=["PUT"])
def reset_member_pin(group_key, target_username):
    data = request.json
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")
    new_pin = data.get("new_pin")

    if not requestor_username:
        return jsonify({"error": "Missing X-Username header"}), 401

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    is_self = requestor_username.lower().strip() == target_username.lower().strip()

    if not (is_self or is_admin(group_id, requestor_username, requestor_pin)):
        conn.close()
        return jsonify({"error": "Unauthorized. Action requires admin privileges or matching user."}), 403

    member = conn.execute(
        "SELECT id FROM members WHERE username = ? AND group_id = ?",
        (target_username.lower().strip(), group_id)
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Target member not found in this group"}), 404

    conn.execute(
        "UPDATE members SET pin_hash = ? WHERE username = ? AND group_id = ?",
        (hash_pin(new_pin), target_username.lower().strip(), group_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Pin reset successfully for user " + target_username})


@app.route("/groups/<group_key>/members", methods=["GET"])
def get_members(group_key):
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    auth_check = conn.execute(
        "SELECT id FROM members WHERE group_id = ? AND username = ? AND pin_hash = ?",
        (group_id, requestor_username.lower().strip(), hash_pin(requestor_pin))
    ).fetchone()

    if not auth_check:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    members = conn.execute(
        "SELECT id, username, display_name, job, role, location, is_admin FROM members WHERE group_id = ?",
        (group_id,),
    ).fetchall()
    conn.close()

    return jsonify([dict(m) for m in members])


@app.route("/groups/<group_key>/members/status", methods=["PUT"])
def update_member_status(group_key):
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    data = request.json
    job = data.get("job")
    location = data.get("location")

    if not any([job, location]):
        return jsonify({"error": "At least one status field (job, location) must be provided to update"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    member = conn.execute(
        "SELECT id, job, location FROM members WHERE group_id = ? AND username = ? AND pin_hash = ?",
        (group_id, requestor_username.lower().strip(), hash_pin(requestor_pin))
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    new_job = job if job is not None else member["job"]
    new_location = location if location is not None else member["location"]

    conn.execute(
        """UPDATE members SET job = ?, location = ? WHERE id = ?""",
        (new_job, new_location, member["id"])
    )
    conn.commit()
    add_log_entry(group_key, requestor_username,
                  f"Set own status to '{new_job}/{new_location}'", datetime.now().timestamp())
    conn.close()

    return jsonify({
        "message": "Status updated successfully",
        "job": new_job,
        "location": new_location
    }), 200


@app.route("/groups/<group_key>/members/role", methods=["PUT"])
def update_member_role(group_key):
    requestor_username = request.headers.get("X-Username")
    name_to_change = request.headers.get("X-Target")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    data = request.json
    role = data.get("new_role")

    if not role:
        return jsonify({"error": "Role field must be provided to update"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    if not is_admin(group_id, requestor_username, requestor_pin):
        conn.close()
        return jsonify({"error": "Unauthorized. Action requires admin privileges"}), 403

    member = conn.execute(
        "SELECT id, role FROM members WHERE group_id = ? AND username = ?",
        (group_id, str(name_to_change).lower().strip())
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    conn.execute(
        "UPDATE members SET role = ? WHERE id = ?",
        (role, member["id"])
    )
    conn.commit()
    add_log_entry(group_key, requestor_username,
                  f"Set {name_to_change}'s role to '{role}'", datetime.now().timestamp())
    conn.close()

    return jsonify({
        "message": "Status updated successfully",
        "role": role
    }), 200


@app.route("/groups/<group_key>/members/change-admin", methods=["PUT"])
def change_admin(group_key):
    data = request.json
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")
    target_username = request.headers.get("X-Target")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    data = request.json
    admin_status = data.get("is_admin")

    if not target_username:
        return jsonify({"error": "Target username must be provided to update"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    if not is_admin(group_id, requestor_username, requestor_pin):
        conn.close()
        return jsonify({"error": "Unauthorized. Action requires admin privileges"}), 403

    member = conn.execute(
        "SELECT id FROM members WHERE group_id = ? AND username = ?",
        (group_id, target_username.lower().strip())
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    conn.execute(
        "UPDATE members SET is_admin = ? WHERE id = ?",
        (admin_status, member["id"])
    )
    conn.commit()
    add_log_entry(group_key, requestor_username,
                  f"Changed {target_username}'s admin status to '{admin_status}'", datetime.now().timestamp())
    conn.close()

    return jsonify({
        "message": "Admin status updated successfully",
        "is_admin": admin_status
    }), 200


@app.route("/groups/<group_key>/logs", methods=["GET"])
def fetch_logs(group_key):
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Missing X-Username or X-Pin header"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()

    if not group:
        return jsonify({"error": "Group not found"}), 404

    member = conn.execute(
        "SELECT id, job, location FROM members WHERE group_id = ? AND username = ? AND pin_hash = ?",
        (group["id"], requestor_username.lower().strip(), hash_pin(requestor_pin))
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    group_log = conn.execute(
        "SELECT * FROM logs WHERE group_key = ?", (group_key.upper().strip(),)
    ).fetchall()
    conn.close()

    return jsonify([dict(row) for row in group_log])


@app.route("/groups/<group_key>/admin-check", methods=["GET"])
def check_admin_status(group_key):
    requestor_user = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_user or not requestor_pin:
        return jsonify({"error": "Missing X-Username or X-Pin header"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE group_key = ?", (group_key.upper(
        ).strip(),)
    ).fetchone()
    conn.close()

    if not group:
        return jsonify({"error": "Group not found"}), 404

    return jsonify({"is_admin": is_admin(group["id"], requestor_user, requestor_pin)}), 200


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    group_key = data.get("group_key")
    username = data.get("username")
    pin = data.get("pin")

    if not all([group_key, username, pin]):
        return jsonify({"error": "Missing group_key, username, or pin"}), 400

    conn = get_db_connection()

    member = conn.execute(
        """
        SELECT m.id, m.display_name, m.job, m.role, m.location, m.username, m.is_admin,
               g.group_name, g.event_key, g.team_number, g.group_key 
        FROM members m
        JOIN groups g ON m.group_id = g.id
        WHERE g.group_key = ? AND m.username = ? AND m.pin_hash = ?
        """,
        (group_key.upper().strip(), username.lower().strip(), hash_pin(pin)),
    ).fetchone()

    conn.close()

    if member:
        return jsonify(dict(member)), 200
    else:
        return jsonify({"error": "Invalid username or PIN"}), 401


@app.route("/tba/teaminfo/<int:team_number>", methods=["GET"])
@limiter.limit("30 per minute")
def team_info(team_number):
    if testing:
        if str(team_number) != "2077":
            return jsonify("Team num must be 2077 when testing"), 401
        with open("./example responses/2077info.json", "r") as file:
            data = json.load(file)
        return jsonify(data), 200
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" +
                            str(team_number), headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code


@app.route("/tba/avatar/<int:team_number>", methods=["GET"])
@limiter.limit("30 per minute")
def team_avatar(team_number):
    if testing:
        if str(team_number) != "2077":
            return jsonify("Team num must be 2077 when testing"), 401
        with open("./example responses/2077media.json", "r") as file:
            data = json.load(file)
        return jsonify(data), 200
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" + str(team_number) +
                            "/media/" + str(datetime.now().year), headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code


@app.route("/tba/<int:team_number>/events", methods=["GET"])
@limiter.limit("30 per minute")
def get_events(team_number):
    if testing:
        if str(team_number) != "2077":
            return jsonify("Team num must be 2077 when testing"), 401
        with open("./example responses/2077events.json", "r") as file:
            data = json.load(file)
        return jsonify(data), 200

    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" + str(team_number) +
                            "/events/" + str(datetime.now().year), headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code


@app.route("/tba/matches/<event_key>/<int:team_number>", methods=["GET"])
@limiter.limit("30 per minute")
def get_matches(event_key, team_number):
    if testing and event_key == "2026wiply":
        with open("./example responses/2026wiply.json", "r") as file:
            data = json.load(file)
        return jsonify(data), 200
    if testing and event_key == "2026wimuk":
        with open("./example responses/2026wimuk.json", "r") as file:
            data = json.load(file)
        return jsonify(data), 200

    response = requests.get(f"https://www.thebluealliance.com/api/v3/team/frc{team_number}/event/{event_key}/matches",
                            headers={"X-TBA-Auth-Key": tba_key.strip()},
                            )
    return jsonify(response.json()), response.status_code


@app.route("/tba/event/<event_key>/stream", methods=["GET"])
@limiter.limit("30 per minute")
def get_current_stream(event_key):
    response = requests.get(f"https://www.thebluealliance.com/api/v3/event/{event_key}",
                            headers={"X-TBA-Auth-Key": tba_key.strip()})

    if response.status_code == 200:
        resp_json = response.json()
        streams = []
        stream_counter = 1

        for webcast in resp_json.get("webcasts", []):
            if webcast.get("type") == "youtube":
                stream_name = "Stream - " + str(webcast.get("date"))
                streams.append({
                    "name": stream_name,
                    "video_id": webcast.get("channel")
                })
                stream_counter += 1

        return jsonify(streams)

    return jsonify({"streams": []})

def run_first_run():
    print(Style.BRIGHT + Fore.GREEN + "First run setup")
    a = input("Instance name (Example: Team XXXXX LT Server): ")
    b = input("Database filename (do not include a file extension): ")
    c = input("Port to use (leave blank for default port of 2077): ")
    if c == "":
        c = 2077
    else:
        c = int(c)
    d = input("The Blue Alliance APIv3 key:")
    print()
    print("Do these settings look right?")
    print("Instance name: " + a)
    print("Database filename: " + b)
    print("Port: " + str(c))
    print("API Key: " + d)
    x = input("Y/N: ")
    if x.lower() == "y":
        data = {
            "instance name": a,
            "version": VERSION,
            "db name": b,
            "port": c,
            "tba api key": d
        }
        with open("about.json", "w") as aboutfile:
            json.dump(data, aboutfile)
    else:
        run_first_run()


def init_config():
    global inst_name, db_name, port, tba_key
    if not os.path.exists("./about.json"):
        run_first_run()
        init_config()
    else:
        with open("about.json", "r") as aboutfile:
            data = json.load(aboutfile)
            inst_name = data["instance name"]
            db_name = data["db name"]
            port = data["port"]
            tba_key = data["tba api key"]


def main():
    init_config()
    init_db()
    print(Style.BRIGHT + Fore.BLUE +
          "Laser Tracker Server v" + VERSION + ": " + inst_name)

    app.run(port=port, host="0.0.0.0")


if __name__ == "__main__":
    main()
