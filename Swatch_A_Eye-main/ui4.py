import os
import cv2
import threading
import tkinter as tk
from ttkthemes import ThemedTk
from ultralytics import YOLO
from PIL import Image, ImageTk
import serial
import time

# ---------------------------
# Configuration and Globals
# ---------------------------
SERIAL_PORT = 'COM6'  # USB port connected to Arduino
BAUD_RATE = 9600
MAX_DISTANCE = 19.0  # 19 cm = Empty, 2 cm = Full
CYCLE_DURATION = 20  # seconds to process each camera
THRESHOLD = 0.2      
stop_all = False     
active_source = 0    # Which source is currently active (0-3)
processing_thread = None  

# Maximum dimensions for video display
MAX_VIDEO_WIDTH = 800
MAX_VIDEO_HEIGHT = 600

# At start all rooms are "Clean" with no timestamp.
room_status = {i: {"status": "Clean", "timestamp": None} for i in range(4)}

# built in webcam is index 0 and USB webcam index 1.
sources = [
    {"src": 0, "orientation": "landscape"},   # Camera for Room 1
    {"src": 1, "orientation": "landscape"},   # Camera for Room 2
    {"src": r"C:/Users/amans/Downloads/garbage_detection/hall.mp4", "orientation": "portrait"},  # Camera for Room 3
    {"src": r"C:/Users/amans/Downloads/garbage_detection/class.mp4", "orientation": "portrait"}    # Camera for Room 4
]

# Load YOLO model
model_path = r'C:/Users/amans/Downloads/garbage_detection/runs/detect/train/weights/last2.pt'
if not os.path.exists(model_path):
    raise FileNotFoundError(f"Model file not found: {model_path}")
model = YOLO(model_path)

# Arduino connection 
def init_arduino():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        return ser
    except serial.SerialException as e:
        print(f"Error initializing Arduino: {e}")
        return None

ser = init_arduino()

# UI
root = ThemedTk(theme="equilux")
root.title("Swatch-A-Eye")
root.geometry("1200x800")
root.configure(bg="#222")

# Dustbin 
sensor_frame = tk.Frame(root, bg="#222")
sensor_frame.grid(row=1, column=1, sticky="ne", padx=0, pady=10)

dustbin_label = tk.Label(sensor_frame, text="Dustbin 1", font=("Arial", 16, "bold"), bg="#222", fg="white")
dustbin_label.pack(side=tk.LEFT, padx=10)

distance_label = tk.Label(sensor_frame, text="Distance: -- cm", font=("Arial", 14), bg="#222", fg="white")
distance_label.pack(side=tk.LEFT, padx=10)

status_label = tk.Label(sensor_frame, text="Status: --", font=("Arial", 14), bg="#222", fg="white")
status_label.pack(side=tk.LEFT, padx=10)

# Video output
video_panel = tk.Label(root, bg="#000")
video_panel.grid(row=1, column=0, padx=10, pady=10)

# Room Status
room_status_frame = tk.Frame(root, bg="#222")
room_status_frame.grid(row=0, column=1, sticky="ne", padx=10, pady=10)

# Room lables
room_labels = {}
for i in range(4):
    lbl = tk.Label(room_status_frame, text=f"Room {i+1}: Clean", font=("Arial", 14), bg="#222", fg="white")
    lbl.pack(anchor="w", pady=5)
    room_labels[i] = lbl

def update_room_status_ui():
    """Refresh the room status labels with the latest room statuses and timestamps.
    The timestamp is formatted in HH:MM (no seconds)."""
    for i in range(4):
        stat = room_status[i]["status"]
        ts = room_status[i]["timestamp"]
        if stat == "Needs cleaning" and ts is not None:
            timestr = time.strftime('%H:%M', time.localtime(ts))
            room_labels[i].config(text=f"Room {i+1}: {stat} (Detected at {timestr})")
        else:
            room_labels[i].config(text=f"Room {i+1}: {stat}")

def periodic_room_update():
    """Update the room status UI every minute."""
    update_room_status_ui()
    root.after(60000, periodic_room_update)

# Update loop
root.after(60000, periodic_room_update)

# Text Output
control_frame = tk.Frame(root, bg="#222")
control_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

# Buttons
button_frame = tk.Frame(control_frame, bg="#222")
button_frame.pack(pady=10)

start_button = tk.Button(button_frame, text="Start", command=lambda: start_processing(), bg="#090", fg="white", font=("Arial", 12))
start_button.pack(side=tk.LEFT, padx=10)

stop_button = tk.Button(button_frame, text="Stop All", command=lambda: stop_processing(), bg="#900", fg="white", font=("Arial", 12))
stop_button.pack(side=tk.LEFT, padx=10)

log_box = tk.Text(control_frame, height=8, width=80, bg="#333", fg="white", font=("Arial", 10))
log_box.pack(pady=10)
log_box.config(state="disabled")

def log_message(msg):
    log_box.config(state="normal")
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)
    log_box.config(state="disabled")

# Sensor Reading
def update_sensor():
    if ser and ser.in_waiting:
        try:
            line = ser.readline().decode('utf-8').strip()
            if "Distance:" in line:
                distance = float(line.split()[1])
                distance = min(distance, MAX_DISTANCE)
                percentage = max(0, min(100, (1 - ((distance - 2) / (MAX_DISTANCE - 2))) * 100))
                if percentage < 50:
                    status = "Empty"
                elif 50 <= percentage <= 60:
                    status = "Half Filled"
                elif 61 <= percentage <= 85:
                    status = "Almost Full"
                else:
                    status = "Full"
                distance_label.config(text=f"Distance: {distance:.2f} cm")
                status_label.config(text=f"Status: {status}")
        except ValueError:
            pass
    root.after(500, update_sensor)

update_sensor()

# Video Processing
def process_active_source():
    global active_source, stop_all, room_status
    while not stop_all:
        current_source = sources[active_source]
        src_val = current_source["src"]
        orientation = current_source.get("orientation", "landscape")
    
        if isinstance(src_val, int) and src_val == 1:
            cap = cv2.VideoCapture(src_val, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(src_val)
        
        if not cap.isOpened():
            log_message(f"Error: Cannot open source {active_source}, skipping to next.")
            active_source = (active_source + 1) % len(sources)
            time.sleep(1)
            continue
        
        log_message(f"Source {active_source} opened.")
        start_time = time.time()
        last_detection_time = None
        
        while time.time() - start_time < CYCLE_DURATION and not stop_all:
            ret, frame = cap.read()
            if not ret:
                # Loop video if smaller
                if isinstance(src_val, str):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    break
            
            # Orientation fix
            if orientation == "portrait" and frame.shape[1] > frame.shape[0]:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            
            # Frame resize
            h, w = frame.shape[:2]
            scale = min(MAX_VIDEO_WIDTH / w, MAX_VIDEO_HEIGHT / h, 1)  # scale <= 1
            if scale < 1:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            
            # Detection on frame
            results = model(frame, conf=THRESHOLD)[0]
            detections = results.boxes.data.tolist() if results.boxes is not None else []
            detection_flag = len(detections) > 0

            current_time = time.time()
            if detection_flag:
                # Update status and record timestamp.
                room_status[active_source]["status"] = "Needs cleaning"
                room_status[active_source]["timestamp"] = current_time
                last_detection_time = current_time
            else:
                # Check if 5 seconds have passed with no detection.
                if room_status[active_source]["status"] == "Needs cleaning":
                    if last_detection_time and (current_time - last_detection_time) >= 5:
                        room_status[active_source]["status"] = "Clean"
                        room_status[active_source]["timestamp"] = None
                        last_detection_time = None
            
            # Object boxes
            for result in detections:
                x1, y1, x2, y2, score, class_id = result
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                label = f"{model.names[int(class_id)].upper()} {score*100:.1f}%"
                cv2.putText(frame, label, (int(x1), int(y1)-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            imgtk = ImageTk.PhotoImage(image=img)
            video_panel.imgtk = imgtk
            video_panel.config(image=imgtk)
    
            root.after(0, update_room_status_ui)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_processing()
                break
            
            time.sleep(0.02)  # Short delay
        
        cap.release()
        log_message(f"Source {active_source} stopped.")
        # Move to the next input
        active_source = (active_source + 1) % len(sources)

# Start/Stop button
def start_processing():
    global stop_all, processing_thread
    if processing_thread is None or not processing_thread.is_alive():
        stop_all = False
        processing_thread = threading.Thread(target=process_active_source, daemon=True)
        processing_thread.start()
        log_message("Processing started.")
    else:
        log_message("Processing is already running.")

def stop_processing():
    global stop_all
    stop_all = True
    log_message("Processing stopped.")

# UI loop
root.mainloop()
