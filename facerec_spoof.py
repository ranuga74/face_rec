import os
import cv2
import dlib
import numpy as np
import mediapipe as mp
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.core.window import Window
from collections import deque
import time

# Set window size
Window.size = (400, 500)

# Initialize dlib for face recognition
detector = dlib.get_frontal_face_detector()
sp = dlib.shape_predictor("shape_predictor_5_face_landmarks.dat")
facerec = dlib.face_recognition_model_v1(
    "dlib_face_recognition_resnet_model_v1.dat")

# Initialize MediaPipe Face Mesh for liveness detection
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    min_detection_confidence=0.5, min_tracking_confidence=0.5, refine_landmarks=True)
mp_drawing = mp.solutions.drawing_utils
drawing_spec = mp_drawing.DrawingSpec(
    color=(128, 0, 128), thickness=2, circle_radius=1)

# Face recognition database
face_descriptors_dict = {}
label_dict = {}
face_dir = "Face_Directory"

if not os.path.exists(face_dir):
    print(f"Directory {face_dir} does not exist.")
    exit(1)

for count, filename in enumerate(os.listdir(face_dir)):
    if filename.endswith(".jpg") or filename.endswith(".png"):
        img_path = os.path.join(face_dir, filename)
        img = cv2.imread(img_path)
        if img is None:
            print(f"Error loading image: {filename}")
            continue
        gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dets = detector(gray_img)
        for d in dets:
            shape = sp(img, d)
            face_descriptor = facerec.compute_face_descriptor(img, shape)
            label = filename.split(".")[0]
            face_descriptors_dict[label] = np.array(face_descriptor)
            label_dict[label] = count

# Liveness detection parameters
blink_threshold = 0.2
mouth_open_threshold = 0.15
head_movement_threshold = 3.0
WINDOW_DURATION = 5  # 5-second window


class MainApp(App):
    def build(self):
        # Layout setup
        layout = BoxLayout(orientation='vertical')
        header = Label(text='[color=ff3333]Code Depot[/color]',
                       markup=True, size_hint=(1, 0.1))
        header.font_size = '24sp'
        header.bold = True
        header.halign = 'center'
        layout.add_widget(header)

        # Image widget
        self.img1 = Image(size_hint=(1, 0.7))
        layout.add_widget(self.img1)

        # Status labels
        self.liveness_label = Label(
            text="Liveness: No Face", size_hint=(1, 0.1))
        layout.add_widget(self.liveness_label)
        self.recognition_label = Label(
            text="Recognition: Unknown", size_hint=(1, 0.1))
        layout.add_widget(self.recognition_label)

        # Initialize camera
        self.capture = cv2.VideoCapture(0)

        # Liveness tracking variables
        self.start_time = None
        self.head_angles_history = deque(maxlen=10)
        self.prev_mouth_status = "Closed"
        self.movement_types = set()
        self.blink_counter = 0
        self.mouth_movement_count = 0
        self.head_movement_count = 0
        self.eyes_closed = False
        self.liveness_result = "No Face"
        self.face_previously_detected = False
        self.recognition_result = "Unknown"

        # Schedule frame updates
        Clock.schedule_interval(self.update_frame, 1.0 / 30.0)

        return layout

    def calculate_ear(self, eye_points):
        v1 = np.linalg.norm(eye_points[1] - eye_points[5])
        v2 = np.linalg.norm(eye_points[2] - eye_points[4])
        h = np.linalg.norm(eye_points[0] - eye_points[3])
        return (v1 + v2) / (2.0 * h)

    def calculate_mar(self, mouth_points):
        v1 = np.linalg.norm(mouth_points[1] - mouth_points[3])
        h = np.linalg.norm(mouth_points[0] - mouth_points[2])
        return v1 / h

    def check_head_movement(self):
        if len(self.head_angles_history) < 2:
            return False
        prev_angles = self.head_angles_history[-2]
        curr_angles = self.head_angles_history[-1]
        diff_x = abs(curr_angles[0] - prev_angles[0])
        diff_y = abs(curr_angles[1] - prev_angles[1])
        return diff_x > head_movement_threshold or diff_y > head_movement_threshold

    def analyze_texture(self, image, face_landmarks, img_w, img_h):
        nose_x = int(face_landmarks.landmark[1].x * img_w)
        nose_y = int(face_landmarks.landmark[1].y * img_h)
        roi = image[max(0, nose_y-20):min(img_h, nose_y+20),
                    max(0, nose_x-20):min(img_w, nose_x+20)]
        if roi.size == 0:
            return False
        variance = np.var(roi)
        return variance > 50

    def recognize_face(self, frame):
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dets = detector(gray_frame)
        for d in dets:
            shape = sp(frame, d)
            cur_face_descriptor = np.array(
                facerec.compute_face_descriptor(frame, shape))
            threshold = 0.5
            distances = {
                label: np.linalg.norm(cur_face_descriptor - known_descriptor)
                for label, known_descriptor in face_descriptors_dict.items()
            }
            recognized_name, min_distance = min(
                distances.items(), key=lambda x: x[1], default=("Unknown", float("inf")))
            if min_distance > threshold:
                return "Unknown"
            return recognized_name
        return "Unknown"

    def update_frame(self, dt):
        ret, frame = self.capture.read()
        if not ret:
            return

        current_time = time.perf_counter()
        img_h, img_w, img_c = frame.shape

        # Process with MediaPipe for liveness
        image_rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
        image_rgb.flags.writeable = False
        results = face_mesh.process(image_rgb)
        image_rgb.flags.writeable = True
        frame = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        face_detected = results.multi_face_landmarks and len(
            results.multi_face_landmarks) > 0
        debug_text = ""

        if face_detected:
            if not self.face_previously_detected:
                self.start_time = current_time
                self.movement_types.clear()
                self.blink_counter = 0
                self.mouth_movement_count = 0
                self.head_movement_count = 0
                self.liveness_result = f"Detecting ({WINDOW_DURATION:.1f}s)"
                self.recognition_result = "Unknown"
                print(
                    f"New face detected, starting 5-second window at {current_time}")
            self.face_previously_detected = True

            face_landmarks = results.multi_face_landmarks[0]

            # Head pose detection
            face_2d = []
            face_3d = []
            for idx, lm in enumerate(face_landmarks.landmark):
                if idx in [33, 263, 1, 61, 291, 199]:
                    if idx == 1:
                        nose_2d = (lm.x * img_w, lm.y * img_h)
                    x, y = int(lm.x * img_w), int(lm.y * img_h)
                    face_2d.append([x, y])
                    face_3d.append([x, y, lm.z])

            face_2d = np.array(face_2d, dtype=np.float64)
            face_3d = np.array(face_3d, dtype=np.float64)
            focal_length = 1 * img_w
            cam_matrix = np.array(
                [[focal_length, 0, img_h/2], [0, focal_length, img_w/2], [0, 0, 1]])
            distortion_matrix = np.zeros((4, 1), dtype=np.float64)

            success, rotation_vec, translation_vec = cv2.solvePnP(
                face_3d, face_2d, cam_matrix, distortion_matrix)
            rmat, jac = cv2.Rodrigues(rotation_vec)
            angles, mtxR, mtxQ, Qx, Qy, Qz = cv2.RQDecomp3x3(rmat)

            x = angles[0] * 360
            y = angles[1] * 360
            z = angles[2] * 360
            self.head_angles_history.append((x, y, z))

            head_text = "Forward"
            if y < -10:
                head_text = "Looking Left"
            elif y > 10:
                head_text = "Looking Right"
            elif x < -10:
                head_text = "Looking Down"
            elif x > 10:
                head_text = "Looking Up"

            # Eye and blink detection
            left_eye_points = [np.array([face_landmarks.landmark[i].x * img_w, face_landmarks.landmark[i].y * img_h])
                               for i in [159, 145, 158, 133, 153, 144]]
            right_eye_points = [np.array([face_landmarks.landmark[i].x * img_w, face_landmarks.landmark[i].y * img_h])
                                for i in [386, 374, 385, 362, 380, 373]]

            left_ear = self.calculate_ear(left_eye_points)
            right_ear = self.calculate_ear(right_eye_points)
            avg_ear = (left_ear + right_ear) / 2.0

            if avg_ear < blink_threshold and not self.eyes_closed:
                self.blink_counter += 1
                self.eyes_closed = True
                self.movement_types.add("Blink")
                debug_text += "Blink; "
                print("Blink detected")
            elif avg_ear >= blink_threshold:
                self.eyes_closed = False

            # Mouth movement detection
            mouth_points = [np.array([face_landmarks.landmark[i].x * img_w, face_landmarks.landmark[i].y * img_h])
                            for i in [61, 13, 291, 14]]
            mar = self.calculate_mar(mouth_points)
            mouth_status = "Open" if mar > mouth_open_threshold else "Closed"
            if mouth_status != self.prev_mouth_status:
                self.mouth_movement_count += 1
                if self.mouth_movement_count > 1:
                    self.movement_types.add("Mouth")
                debug_text += "Mouth; "
                print(f"Mouth movement detected: {mouth_status}")
            self.prev_mouth_status = mouth_status

            # Head movement detection
            if self.check_head_movement():
                self.head_movement_count += 1
                if self.head_movement_count > 1:
                    self.movement_types.add("Head")
                debug_text += "Head; "
                print("Head movement detected")

            # Texture analysis
            is_textured = self.analyze_texture(
                frame, face_landmarks, img_w, img_h)

            # Liveness decision
            if self.start_time and (current_time - self.start_time) < WINDOW_DURATION:
                self.liveness_result = f"Detecting ({WINDOW_DURATION - (current_time - self.start_time):.1f}s)"
            elif self.start_time and (current_time - self.start_time) >= WINDOW_DURATION:
                if len(self.movement_types) >= 2 and is_textured:
                    self.liveness_result = "Real"
                    self.recognition_result = self.recognize_face(frame)
                else:
                    self.liveness_result = "Fake"
                    self.recognition_result = "Spoof Detected"
                self.start_time = None
                print(
                    f"Liveness decided: {self.liveness_result}, Recognition: {self.recognition_result}")

            # Draw landmarks
            mp_drawing.draw_landmarks(
                image=frame,
                landmark_list=face_landmarks,
                connections=mp_face_mesh.FACEMESH_CONTOURS,
                landmark_drawing_spec=drawing_spec,
                connection_drawing_spec=drawing_spec
            )
        else:
            if self.face_previously_detected:
                self.face_previously_detected = False
                print("Face lost, keeping last result")

        # Update UI
        self.liveness_label.text = f"Liveness: {self.liveness_result}"
        self.recognition_label.text = f"Recognition: {self.recognition_result}"
        cv2.putText(frame, debug_text, (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Update texture
        buf1 = cv2.flip(frame, 0)
        buf = buf1.tobytes()
        texture = Texture.create(
            size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
        texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
        self.img1.texture = texture

    def on_stop(self):
        self.capture.release()
        face_mesh.close()


if __name__ == "__main__":
    MainApp().run()
