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

VERSION = "prerelease"

inst_name = "unknown"
db_name = "unknown"
port = 2077
tba_key = "unknown"

app = Flask(__name__)
CORS(app)

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def generate_join_key() -> str:
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
                join_key TEXT NOT NULL UNIQUE,
                leader_id INTEGER,
                FOREIGN KEY (leader_id) REFERENCES members(id) ON DELETE SET NULL
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
                status TEXT NOT NULL,
                job TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                UNIQUE(group_id, username)
            )
        """
        )
        conn.commit()

def is_leader(group_id, member_id):
    if not member_id:
        return False
    conn = get_db_connection()
    group = conn.execute(
        "SELECT leader_id FROM groups WHERE id = ?", (group_id,)
    ).fetchone()
    conn.close()
    return group and group["leader_id"] == int(member_id)

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
        join_key = generate_join_key()

        cursor.execute(
            "INSERT INTO groups (group_name, event_key, team_number, join_key) VALUES (?, ?, ?, ?)",
            (group_name.strip(), event_key, team_number, join_key),
        )
        group_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO members (group_id, username, display_name, pin_hash, status, job, role, location)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (group_id, leader_username.lower().strip(), leader_display_name, hash_pin(leader_pin),
             "Logged In", "Lead Coach", "Lead Coach", "Unknown"),
        )
        leader_id = cursor.lastrowid

        cursor.execute(
            "UPDATE groups SET leader_id = ? WHERE id = ?", (
                leader_id, group_id)
        )
        
        member = conn.execute(
            """
            SELECT m.id, m.username, m.display_name, m.status, m.job, m.role, m.location, 
                   g.group_name, g.event_key, g.team_number, g.join_key 
            FROM members m 
            JOIN groups g ON m.group_id = g.id 
            WHERE m.id = ?
            """,
            (leader_id,),
        ).fetchone()

        conn.commit()
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
def add_member_by_code():
    data = request.json
    join_key = data.get("join_key")
    username = data.get("username")
    display_name = data.get("display_name")
    pin = data.get("pin")
    status = data.get("status", "Logged In")
    job = data.get("job", "Unknown")
    role = data.get("role", "Unknown")
    location = data.get("location", "Unknown")

    if not all([join_key, username, display_name, pin]):
        return jsonify({"error": "Join key, username, display name, and pin are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        group = conn.execute(
            "SELECT id FROM groups WHERE join_key = ?", (join_key.upper().strip(),)
        ).fetchone()

        if not group:
            conn.close()
            return jsonify({"error": "Invalid Group Join Key"}), 404

        group_id = group["id"]

        existing_member = conn.execute(
            "SELECT id FROM members WHERE group_id = ? AND username = ?",
            (group_id, username.lower().strip())
        ).fetchone()

        if existing_member:
            conn.close()
            return jsonify({"error": f"The username '{username}' has already been taken within this group."}), 409

        cursor.execute(
            """
            INSERT INTO members (group_id, username, display_name, pin_hash, status, job, role, location)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (group_id, username.lower().strip(), display_name,
             hash_pin(pin), status, job, role, location),
        )
        
        member = conn.execute(
            """
            SELECT m.id, m.username, m.display_name, m.status, m.job, m.role, m.location, 
                   g.group_name, g.event_key, g.team_number, g.join_key 
            FROM members m 
            JOIN groups g ON m.group_id = g.id 
            WHERE m.username = ? AND g.join_key = ?
            """,
            (username.lower().strip(), join_key.upper().strip()),
        ).fetchone()

        conn.commit()
        return jsonify(dict(member)), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "Database constraint violation occurred."}), 409
    finally:
        conn.close()

@app.route("/groups/<join_key>", methods=["PUT"])
def update_group(join_key):
    data = request.json
    requestor_id = request.headers.get("X-Member-ID")

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE join_key = ?", (join_key.upper().strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    if not is_leader(group_id, requestor_id):
        conn.close()
        return jsonify({"error": "Unauthorized. Action requires leader privileges."}), 403

    group_name = data.get("group_name")
    event_key = data.get("event_key")

    conn.execute(
        "UPDATE groups SET group_name = ?, event_key = ? WHERE id = ?",
        (group_name, event_key, group_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Group updated successfully"})

@app.route("/groups/<join_key>/members/<int:member_id>/reset-pin", methods=["PUT"])
def reset_member_pin(join_key, member_id):
    data = request.json
    requestor_id = request.headers.get("X-Member-ID")
    new_pin = data.get("new_pin")

    if not new_pin:
        return jsonify({"error": "New pin is required"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE join_key = ?", (join_key.upper().strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    if not is_leader(group_id, requestor_id):
        conn.close()
        return jsonify({"error": "Unauthorized. Action requires leader privileges."}), 403

    member = conn.execute(
        "SELECT id FROM members WHERE id = ? AND group_id = ?", (
            member_id, group_id)
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Member not found in this group"}), 404

    conn.execute(
        "UPDATE members SET pin_hash = ? WHERE id = ?", (hash_pin(
            new_pin), member_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": f"Pin reset successfully for member {member_id}"})

@app.route("/groups/<join_key>/members", methods=["GET"])
def get_members(join_key):
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE join_key = ?", (join_key.upper().strip(),)
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
        "SELECT id, username, display_name, status, job, role, location FROM members WHERE group_id = ?",
        (group_id,),
    ).fetchall()
    conn.close()

    return jsonify([dict(m) for m in members])

@app.route("/groups/<join_key>/members/status", methods=["PUT"])
def update_member_status(join_key):
    requestor_username = request.headers.get("X-Username")
    requestor_pin = request.headers.get("X-Pin")

    if not requestor_username or not requestor_pin:
        return jsonify({"error": "Authentication required via X-Username and X-Pin headers"}), 401

    data = request.json
    status = data.get("status")
    job = data.get("job")
    role = data.get("role")
    location = data.get("location")

    if not any([status, job, role, location]):
        return jsonify({"error": "At least one status field (status, job, role, location) must be provided to update"}), 400

    conn = get_db_connection()
    group = conn.execute(
        "SELECT id FROM groups WHERE join_key = ?", (join_key.upper().strip(),)
    ).fetchone()

    if not group:
        conn.close()
        return jsonify({"error": "Group not found"}), 404

    group_id = group["id"]

    member = conn.execute(
        "SELECT id, status, job, role, location FROM members WHERE group_id = ? AND username = ? AND pin_hash = ?",
        (group_id, requestor_username.lower().strip(), hash_pin(requestor_pin))
    ).fetchone()

    if not member:
        conn.close()
        return jsonify({"error": "Invalid credentials for this group"}), 403

    new_status = status if status is not None else member["status"]
    new_job = job if job is not None else member["job"]
    new_role = role if role is not None else member["role"]
    new_location = location if location is not None else member["location"]

    conn.execute(
        """
        UPDATE members 
        SET status = ?, job = ?, role = ?, location = ? 
        WHERE id = ?
        """,
        (new_status, new_job, new_role, new_location, member["id"])
    )
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Status updated successfully",
        "status": new_status,
        "job": new_job,
        "role": new_role,
        "location": new_location
    }), 200

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    join_key = data.get("join_key")
    username = data.get("username")
    pin = data.get("pin")

    if not all([join_key, username, pin]):
        return jsonify({"error": "Missing join_key, username, or pin"}), 400

    conn = get_db_connection()

    member = conn.execute(
        """
        SELECT m.id, m.display_name, m.job, m.role, m.location, m.status, m.username, 
               g.group_name, g.event_key, g.team_number, g.join_key 
        FROM members m
        JOIN groups g ON m.group_id = g.id
        WHERE g.join_key = ? AND m.username = ? AND m.pin_hash = ?
        """,
        (join_key.upper().strip(), username.lower().strip(), hash_pin(pin)),
    ).fetchone()

    conn.close()

    if member:
        return jsonify(dict(member)), 200
    else:
        return jsonify({"error": "Invalid username or PIN"}), 401
    
@app.route("/tba/teaminfo/<int:team_number>", methods=["GET"])
def team_info(team_number):
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc"+str(team_number), headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code

@app.route("/tba/avatar/<int:team_number>", methods=["GET"])
def team_avatar(team_number):
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" + str(team_number) +"/media/" + str(datetime.now().year), headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code

@app.route("/tba/<int:team_number>/events", methods=["GET"])
def get_events(team_number):
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" + str(team_number) + "/events/" + str(datetime.now().year), headers={"X-TBA-Auth-Key": tba_key.strip()}) 
    return jsonify(response.json()), response.status_code

@app.route("/tba/matches/<event_key>/<int:team_number>", methods=["GET"])
def get_matches(event_key, team_number):
    response = requests.get("https://www.thebluealliance.com/api/v3/team/frc" + str(team_number) + "/event/" + event_key + "/matches/simple", headers={"X-TBA-Auth-Key": tba_key.strip()})
    return jsonify(response.json()), response.status_code

def run_first_run():
    print(Style.BRIGHT + Fore.GREEN + "First run setup")
    a = input("Instance name (Example: Team XXXXX LT Server): ")
    b = input("Database filename (do not include a file extension): ")
    c = input("Port to use (leave blank for default port of 2077): ")
    d = input("The Blue Alliance APIv3 key:" )
    print()
    print("Do these settings look right?")
    print("Instance name: " + a)
    print("Database filename: " + b)
    print("Port: " + c)
    print("API Key: " + d)
    x = input("Y/N: ")
    if x.lower() == "y":
        if c == "":
            c = 2077
        else:
            c = int(c)
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