import functools
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS  # Importing CORS
from panoramisk import Manager
from asterisk.ami import AMIClient, SimpleAction
from requests.auth import HTTPBasicAuth
import asyncio
import os
from werkzeug.utils import secure_filename
from pydub import AudioSegment
import requests
from loggers import app_logger, asterisk_logger
from datetime import datetime

app = Flask(__name__)
# Enable CORS for your application
CORS(app, origins="*")  # Allow all origins (use your specific domain for better security)

socketio = SocketIO(app, cors_allowed_origins="*")

ASTERISK_HOST = "172.16.203.199"
ASTERISK_PORT = 5038
ASTERISK_USERNAME = "ranatelapi"
ASTERISK_PASSWORD = "343aa1aefe4908885015295abd578b91"

# Konfigurasi AMI
# ASTERISK_HOST = "srv469501.hstgr.cloud"
# ASTERISK_PORT = 5038
# ASTERISK_USERNAME = "ranatelapi"
# ASTERISK_PASSWORD = "343aa1aefe4908885015295abd578b91"
RECORDINGS_FOLDER = "/var/spool/asterisk/monitor/"



# Secret token (This is just an example. You should keep this securely)
SECRET_TOKEN = "OMypT4sfR1IoLyPU1eER0LPhsuVyG0W1"

# Function to check Bearer token in request header
def check_auth_token():
    auth_header = request.headers.get("Authorization")
    if auth_header:
        # Extract token from 'Bearer <token>'
        token = auth_header.split(" ")[1] if len(auth_header.split(" ")) > 1 else ""
        if token == SECRET_TOKEN:
            return True
    return False

# Middleware to enforce Bearer token validation on all routes
def requires_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not check_auth_token():
            app_logger.warning("Unauthorized access attempt detected.")
            return jsonify({"status": "error", "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# Helper function to run async functions in Flask
def run_async(func, *args, **kwargs):
    """Helper function to run async functions in a synchronous Flask context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:  # Jika tidak ada event loop di thread ini
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Jika loop sedang berjalan, buat task dan bungkus dalam future
        task = loop.create_task(func(*args, **kwargs))
        return asyncio.wrap_future(task)
    else:
        # Jalankan coroutine di event loop yang baru dibuat
        return asyncio.run(func(*args, **kwargs))


@app.route("/get_agents", methods=["GET"])
@requires_auth
def get_agents():
    return run_async(get_agents_async)

async def get_agents_async():
    manager = Manager(
        host=ASTERISK_HOST,
        port=ASTERISK_PORT,
        username=ASTERISK_USERNAME,
        secret=ASTERISK_PASSWORD,
    )
    # Ambil target_queues dari parameter request atau form
    target_queues = request.args.getlist("target_queues") or request.form.getlist("target_queues")
    try:
        await manager.connect()
        action = {
            "Action": "QueueStatus",
            "Async": "true",
        }
        response = await manager.send_action(action)
        agent_info = []
        # target_queues = ['1726201', '1726202']
        for message in response:
            if hasattr(message, 'Event') and message.Event == 'QueueMember':
                if not target_queues or message.Queue in target_queues:
                    print('Response : ', message)
                    hint = message.StateInterface.split('@')[0].replace('hint:', '')  # Menambahkan logika untuk memproses hint
                    agent_details = {
                        'Name': message.Name,
                        'Queue': message.Queue,
                        'Status': message.Status,
                        'Paused': message.Paused,
                        'PausedReason' : message.PausedReason,
                        'Hint' : hint,  # Menambahkan hint ke detail agen
                        # Tambahkan informasi lainnya sesuai kebutuhan
                    }
                    agent_info.append(agent_details)
        asterisk_logger.info(f"Agent information fetched successfully: {agent_info}")
        return jsonify({"status": "success", "data": agent_info})
    except Exception as e:
        asterisk_logger.error(f"Error fetching agents: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500
    finally:
        manager.close()

@app.route('/pause_agent', methods=['POST'])
@requires_auth
def pause_agent():
    return run_async(pause_agent_async)

async def pause_agent_async():
    data = request.get_json()
    required_params = ["channel_account", "queue", "paused", "reason"]

    if not all(param in data for param in required_params):
        app_logger.error("Missing parameters in pause_agent request.")
        return jsonify({"status": "error", "error": "Missing parameters"}), 400

    channel_account = data["channel_account"]
    queue = data["queue"]
    paused = data["paused"]
    reason = data["reason"]
    print(channel_account, queue, paused, reason)
    manager = Manager(
        host=ASTERISK_HOST,
        port=ASTERISK_PORT,
        username=ASTERISK_USERNAME,
        secret=ASTERISK_PASSWORD,
    )
    try:
        await manager.connect()
        action = {
            "Action": "QueuePause",
            "Interface": f"Local/{channel_account}@from-queue/n",
            "Queue": queue,
            "Paused": paused,
            "Reason": reason,
        }
        response = await manager.send_action(action)
        asterisk_logger.info(f"QueuePause action response: {response}")
        return jsonify({"status": "success", "message": "Agent paused successfully."})
    except Exception as e:
        asterisk_logger.error(f"Error pausing agent: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        manager.close()

@app.route("/manage_queue_member", methods=["POST"])
@requires_auth
def manage_queue_member():
    return run_async(manage_queue_member_async)

async def manage_queue_member_async():
    data = request.get_json()
    required_params = ["auth_id", "add_or_remove", "queue", "interface", "member_name", "penalty", "paused"]

    if not all(param in data for param in required_params):
        app_logger.error("Missing parameters in manage_queue_member request.")
        return jsonify({"status": "error", "error": "Missing parameters"}), 400

    auth_id = data["auth_id"]
    add_or_remove = data["add_or_remove"]
    queue = data["queue"]
    interface = data["interface"]
    member_name = data["member_name"]
    penalty = data["penalty"]
    paused = data["paused"]

    manager = Manager(
        host=ASTERISK_HOST,
        port=ASTERISK_PORT,
        username=ASTERISK_USERNAME,
        secret=ASTERISK_PASSWORD,
    )
    try:
        await manager.connect()

        action = {
            "Action": "QueueAdd" if add_or_remove == "T" else "QueueRemove",
            "Queue": queue,
            "Interface": f"Local/{interface}@from-queue/n",
        }

        if add_or_remove == "T":
            action.update({
                "Penalty": penalty,
                "Paused": paused,
                "Name": member_name,
                "StateInterface": f"hint:{interface}@ext-local",
            })

        print(action)
        response = await manager.send_action(action)
        asterisk_logger.info(f"Manage queue member response: {response}")
        status = "Enabled" if add_or_remove == "T" else "Disabled"

        socketio.emit("manage_queue_member", {"title": "Success", "message": f"Successfully changed status {member_name} to {status}", "auth_id": auth_id})
        return jsonify({"status": "success", "message": str(response)})
    except Exception as e:
        asterisk_logger.error(f"Error managing queue member: {e}")
        socketio.emit("manage_queue_member", {"title": "Error", "message": str(e), "auth_id": auth_id})
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        manager.close()


@app.route("/make_call", methods=["POST"])
@requires_auth
def make_call():
    return run_async(make_call_async)

async def make_call_async():
    data = request.get_json()
    
    required_params = ["channel_account", "no_hp"]

    if not all(param in data for param in required_params):
        return jsonify({"status": "error", "error": "Missing parameters"}), 400
    
    channel_account = data["channel_account"]
    no_hp = data["no_hp"]

    client = AMIClient(address=ASTERISK_HOST, port=ASTERISK_PORT)
    client.login(ASTERISK_USERNAME, ASTERISK_PASSWORD)

    try:
        action = SimpleAction(
            'Originate',
            Channel=f'PJSIP/{channel_account}',
            Context='from-internal',
            Exten=no_hp,
            Priority=1,
            CallerID=f"ID {no_hp}"
        )
        response = client.send_action(action)
        return jsonify({"status": "success", "number": no_hp})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
    finally:
        client.logoff()

@app.route("/", methods=["GET"])
def main():
    return jsonify({"status": "success", "message": "API is working"})


# Your FreePBX login credentials    
USERNAME = 'Ranamcadmin'
PASSWORD = 'Ramusen12345@zse4%RDX'

# Menambahkan konfigurasi untuk direktori penyimpanan file audio
app.config["UPLOAD_AUDIO"] = os.path.join(os.getcwd(), "static", "audio")

# Fungsi untuk mengunduh rekaman
def download_recording(session, url, save_path, file_name):
    try:
        # Pastikan folder penyimpanan ada
        full_save_path = os.path.join(app.config["UPLOAD_AUDIO"], file_name)
        os.makedirs(os.path.dirname(full_save_path), exist_ok=True)

        # Periksa apakah file sudah ada di lokasi penyimpanan
        if os.path.exists(full_save_path):
            print(f"File {file_name} sudah ada, tidak perlu mengunduh ulang.")
            return full_save_path  # Kembalikan path file yang sudah ada

        # Lakukan request ke URL hanya jika file belum ada
        response = session.get(url, stream=True)
        if response.ok:
            # Periksa apakah response memiliki isi
            if len(response.content) == 0:
                print("Response content is empty")
                return None
            
            # Simpan file ke path yang ditentukan
            with open(full_save_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print(f"Rekaman berhasil disimpan di: {full_save_path}")

            return full_save_path  # Kembalikan path file yang baru diunduh
        else:
            print(f"Failed to download recording: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return None
    except Exception as e:
        print(f"Error downloading recording: {e}")
        return None

def login_to_freepbx(session, username, password):
    # URL untuk login ke FreePBX (sesuaikan dengan URL login yang benar)
    login_url = "http://srv469501.hstgr.cloud:8083/admin/config.php?action=login"
    
    # Data yang dikirimkan saat login
    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    
    # Melakukan POST request untuk login
    response = session.post(login_url, data=login_data)

    if response.ok:
        print("Login berhasil!")
    else:
        print(f"Login gagal: {response.status_code}")
        print(f"Response: {response.text[:500]}")
    return session
@app.route("/download_recording/<recording_id>")
def download_recordings(recording_id):
    try:
        # Tentukan path penyimpanan dan nama file
        save_path = app.config["UPLOAD_AUDIO"]
        file_name = f"rekaman_{recording_id}.wav"
        full_save_path = os.path.join(save_path, file_name)

        # Jika file sudah ada, langsung kirimkan tanpa mengunduh ulang
        if os.path.exists(full_save_path):
            print(f"File {file_name} sudah ada, mengirim langsung.")
            return send_from_directory(save_path, file_name, as_attachment=True)

        # Jika file belum ada, lakukan login dan unduh file
        download_url = f"http://srv469501.hstgr.cloud:8083/admin/config.php?display=cdr&action=download_audio&cdr_file={recording_id}"
        session = requests.Session()
        session = login_to_freepbx(session, "USERNAME", "PASSWORD")  # Ganti dengan username & password yang benar

        downloaded_file = download_recording(session, download_url, save_path, file_name)
        if downloaded_file:
            return send_from_directory(save_path, file_name, as_attachment=True)
        else:
            return jsonify({"error": "Failed to download recording."})
    except Exception as e:
        app.logger.error(f'Error downloading recording: {e}')
        return jsonify({"error": str(e)})

# Socket.IO event example: handling new agent status updates in real-time
@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('message', {'data': 'Connected to Flask Server via Socket.IO!'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")

@socketio.on('result_data_autodialer')
def result_data_autodialer(data):
    socketio.emit("result_data_autodialer", data)

@socketio.on('customer_data_autodialer')
def customer_data_auto(data):
    socketio.emit("customer_data_autodialer", data)

@socketio.on('reschedule_campaign_autodialer')
def reschedule_campaign_autodialer(data):
    socketio.emit("reschedule_campaign_autodialer", data)

@socketio.on('reschedule_campaign_ranablast')
def reschedule_campaign_ranablast(data):
    socketio.emit("reschedule_campaign_ranablast", data)

@socketio.on('result_data_ranablast')
def result_data_ranablast(data):
    socketio.emit("result_data_ranablast", data)

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@socketio.on('chat_message')
def handle_chat_message(data):
    try:
        sender_id = data.get('sender_id')
        receiver_id = data.get('receiver_id')
        message = data.get('message', '')
        username = data.get('username')
        image_data = data.get('image_url')

        print(f"Received message from {username} ({sender_id}) to {receiver_id}: {message} and {image_data}")

        image_url = None
        if image_data:
            print("Image data received, saving image...")
            try:
                # Check if image_data contains a comma (e.g., "data:image/png;base64,<base64_data>")
                if ',' in image_data:
                    # Split the metadata from the base64 data
                    image_binary = base64.b64decode(image_data.split(',')[1])
                else:
                    # Assume image_data is already the base64-encoded data
                    image_binary = base64.b64decode(image_data)

                # Save the image
                filename = f"{sender_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                image_path = os.path.join(UPLOAD_FOLDER, filename)
                with open(image_path, 'wb') as image_file:
                    image_file.write(image_binary)
                image_url = f"/{UPLOAD_FOLDER}/{filename}"
                print(f"Image saved at {image_url}")
            except Exception as e:
                print(f"Error saving image: {e}")
                image_url = None

        emit('chat_message', {
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'message': message,
            'username': username,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'image_url': image_url
        }, broadcast=True)
    except Exception as e:
        print(f"Error handling chat message: {e}")@socketio.on('group_message')

@socketio.on('group_message')
def handle_group_message(data):
    try:
        group_id = data.get('group_id')
        sender_id = data.get('sender_id')
        receiver_id = data.get('receiver_id')
        message = data.get('message', '')
        username = data.get('username')
        image_data = data.get('image_url')

        print(f"Message from {username} in group {group_id} ({sender_id}): {message} {receiver_id}")

        image_url = None
        if image_data:
            print("Image data received, saving image...")
            try:
                if ',' in image_data:
                    image_binary = base64.b64decode(image_data.split(',')[1])
                else:
                    image_binary = base64.b64decode(image_data)

                filename = f"{sender_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                image_path = os.path.join(UPLOAD_FOLDER, filename)
                with open(image_path, 'wb') as image_file:
                    image_file.write(image_binary)
                image_url = f"/{UPLOAD_FOLDER}/{filename}"
                print(f"Image saved at {image_url}")
            except Exception as e:
                print(f"Error saving image: {e}")
                image_url = None

        emit('group_message', {
            'group_id': group_id,
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'message': message,
            'username': username,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'image_url': image_url
        }, broadcast=True)
    except Exception as e:
        print(f"Error handling chat message: {e}")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)