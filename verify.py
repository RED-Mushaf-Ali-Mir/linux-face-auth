# verify.py - live face verification (YuNet detect + SFace embed + cosine match)
import argparse
import csv
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
DET_MODEL = ROOT / "models" / "yunet.onnx"
REC_MODEL = ROOT / "models" / "sface.onnx"
EMB_FILE = ROOT / "data" / "face_embeddings.npy"
LOG_FILE = ROOT / "data" / "scores.csv"


def l2_normalize(v):
    """Scale a vector (or each row of a 2D array) to length 1."""
    v = np.asarray(v, dtype=np.float32)
    if v.ndim == 1:
        return v / (np.linalg.norm(v) + 1e-12)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)


def log_score(label, raw, smooth, thr):
    new_file = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time", "label", "raw_score", "smoothed_score", "threshold"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), label,
                    f"{raw:.4f}", f"{smooth:.4f}", thr])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.363,
                    help="cosine threshold (0.363 = OpenCV Zoo default, NOT calibrated)")
    ap.add_argument("--smooth", type=int, default=5, help="frames to average")
    ap.add_argument("--camera", type=int, default=0, help="V4L2 index (0 = /dev/video0)")
    args = ap.parse_args()

    for p in (DET_MODEL, REC_MODEL, EMB_FILE):
        if not p.exists():
            raise SystemExit(f"Missing file: {p}")

    # ---- load and check enrolled embeddings ----
    enrolled = np.load(EMB_FILE).astype(np.float32)
    if enrolled.ndim != 2 or enrolled.shape[1] != 128:
        raise SystemExit(f"Unexpected embedding shape {enrolled.shape}, expected (N, 128)")
    print("Enrolled shape:", enrolled.shape)
    print("Norms before normalizing:", np.round(np.linalg.norm(enrolled, axis=1), 3))
    enrolled = l2_normalize(enrolled)

    # How similar are your 5 samples to each other? (sanity check of enrollment)
    n = len(enrolled)
    sim = enrolled @ enrolled.T
    off_diag = sim[~np.eye(n, dtype=bool)]
    print(f"Sample-to-sample cosine: mean={off_diag.mean():.3f}  min={off_diag.min():.3f}")

    # ---- camera ----
    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("Could not read from camera")
    h, w = frame.shape[:2]

    # ---- models ----
    detector = cv2.FaceDetectorYN.create(str(DET_MODEL), "", (w, h), 0.9, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(str(REC_MODEL), "")

    history = deque(maxlen=args.smooth)
    fps = 0.0
    print("Keys: q = quit | g = log GENUINE (you) | i = log IMPOSTOR (someone else)")

    while True:
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            break

        detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = detector.detect(frame)

        status, color = "NO FACE", (0, 165, 255)
        raw = smooth = None

        if faces is not None and len(faces) > 1:
            status, color = "MULTIPLE FACES - no decision", (0, 165, 255)
            history.clear()
        elif faces is not None and len(faces) == 1:
            face = faces[0]
            aligned = recognizer.alignCrop(frame, face)       # 112x112 aligned crop
            emb = l2_normalize(recognizer.feature(aligned).flatten())
            raw = float((enrolled @ emb).mean())               # mean cosine vs 5 samples
            history.append(raw)
            smooth = float(np.mean(history))
            if smooth >= args.threshold:
                status, color = "MATCH", (0, 200, 0)
            else:
                status, color = "NO MATCH", (0, 0, 255)

            x, y, bw, bh = face[:4].astype(int)
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            for i in range(5):                                  # 5 landmarks
                lx, ly = face[4 + 2 * i: 6 + 2 * i].astype(int)
                cv2.circle(frame, (lx, ly), 3, (255, 0, 0), -1)
        else:
            history.clear()

        line2 = ""
        if smooth is not None:
            line2 = f"score {smooth:.3f} (raw {raw:.3f})  thr {args.threshold}"
        cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        cv2.putText(frame, line2, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, f"{fps:.1f} FPS", (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow("verify", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key in (ord("g"), ord("i")) and raw is not None:
            label = "genuine" if key == ord("g") else "impostor"
            log_score(label, raw, smooth, args.threshold)
            print(f"logged {label}: raw={raw:.3f}")

        fps = 0.9 * fps + 0.1 / max(time.time() - t0, 1e-6)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
