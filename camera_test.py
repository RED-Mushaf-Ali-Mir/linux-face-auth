import cv2

# Open the normal webcam using Linux's camera interface.
camera = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

try:
    if not camera.isOpened():
        raise RuntimeError("Could not open /dev/video0.")

    # Request a resolution supported by your webcam.
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Camera opened. Click the preview and press Q to quit.")

    while True:
        # Read one image from the camera.
        success, frame = camera.read()

        if not success:
            raise RuntimeError("Camera opened, but no image was received.")

        cv2.imshow("Webcam test - press Q to quit", frame)

        # Update the window and check for the Q key.
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    # Always free the camera and close preview windows.
    camera.release()
    cv2.destroyAllWindows()
