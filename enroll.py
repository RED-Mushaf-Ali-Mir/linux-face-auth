from pathlib import Path
import os

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "data" / "face_embeddings.npy"
TARGET = 5

if OUTPUT.exists():
    raise SystemExit("Enrollment already exists. Stopping without changes.")

detector = cv2.FaceDetectorYN.create(
    str(BASE / "models" / "yunet.onnx"),
    "",
    (640, 480),
    score_threshold=0.9,
)

recognizer = cv2.FaceRecognizerSF.create(
    str(BASE / "models" / "sface.onnx"),
    "",
)

camera = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)
samples = []

try:
    if not camera.isOpened():
        raise RuntimeError("Could not open the webcam.")

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Press C to capture a sample. Press Q to cancel.")

    while len(samples) < TARGET:
        success, frame = camera.read()

        if not success:
            raise RuntimeError("Could not read a camera frame.")

        height, width = frame.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(frame)

        count = 0 if faces is None else len(faces)

        # Draw only on the preview, preserving the original image.
        preview = frame.copy()

        if faces is not None:
            for face in faces:
                x, y, w, h = face[:4].astype(int)
                cv2.rectangle(
                    preview,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2,
                )

        if count == 1:
            message = f"Samples {len(samples)}/{TARGET} | C: capture | Q: cancel"
        elif count == 0:
            message = "No face detected | Q: cancel"
        else:
            message = "Only one person please | Q: cancel"

        cv2.putText(
            preview,
            message,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )

        cv2.imshow("Face enrollment", preview)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

        if key == ord("c"):
            if count != 1:
                print("Capture skipped: exactly one face must be visible.")
                continue

            # Align using the detected facial landmarks.
            aligned_face = recognizer.alignCrop(frame, faces[0])

            # Run the recognition CNN to obtain an embedding.
            embedding = recognizer.feature(aligned_face).flatten()

            # Normalize the embedding to unit length.
            length = np.linalg.norm(embedding)

            if not np.isfinite(embedding).all() or length <= 0:
                print("Capture skipped: invalid embedding.")
                continue

            embedding = embedding / length
            samples.append(embedding)

            print(
                f"Captured {len(samples)}/{TARGET} "
                f"| embedding dimensions: {embedding.size}"
            )

finally:
    camera.release()
    cv2.destroyAllWindows()


if len(samples) == TARGET:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Create a private file; fail if an enrollment already exists.
    descriptor = os.open(
        OUTPUT,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(descriptor, "wb") as file:
        np.save(file, np.stack(samples), allow_pickle=False)

    print(f"Enrollment saved: {OUTPUT}")
    print(f"Saved array shape: {np.stack(samples).shape}")
else:
    print("Enrollment cancelled. No samples saved.")
