from pathlib import Path
import cv2

# Find the model relative to this script.
model_path = Path(__file__).resolve().parent / "models" / "yunet.onnx"

# Load the pretrained face detector once.
detector = cv2.FaceDetectorYN.create(
    str(model_path),
    "",
    (640, 480),
    score_threshold=0.9,
)

camera = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

try:
    if not camera.isOpened():
        raise RuntimeError("Could not open the webcam.")

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    while True:
        success, frame = camera.read()

        if not success:
            raise RuntimeError("Could not read a camera frame.")

        # Match the detector's input size to the actual frame.
        height, width = frame.shape[:2]
        detector.setInputSize((width, height))

        # Run face detection on this image.
        _, faces = detector.detect(frame)

        count = 0 if faces is None else len(faces)

        if faces is not None:
            for face in faces:
                x, y, w, h = face[:4].astype(int)

                cv2.rectangle(
                    frame, (x, y), (x + w, y + h),
                    (0, 255, 0), 2
                )

        if count == 0:
            message = "No face detected"
        elif count == 1:
            message = "One face detected"
        else:
            message = "Multiple faces - only one person please"

        cv2.putText(
            frame, message, (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (0, 255, 255), 2
        )

        cv2.imshow("Face detection - Q to quit", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    camera.release()
    cv2.destroyAllWindows()
