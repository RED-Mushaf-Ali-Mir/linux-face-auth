#!/usr/bin/env python3
# face_auth.py - one-shot face check using YuNet + SFace.
# Exit codes: 0 = match, 1 = face seen but no match, 2 = no single face / timeout, 3 = error
import argparse
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
DET_MODEL = ROOT / "models" / "yunet.onnx"
REC_MODEL = ROOT / "models" / "sface.onnx"
EMB_FILE = ROOT / "data" / "face_embeddings.npy"
LOG_FILE = ROOT / "data" / "auth.log"

EXIT_MATCH, EXIT_NO_MATCH, EXIT_NO_FACE, EXIT_ERROR = 0, 1, 2, 3


@dataclass
class Result:
    code: int
    message: str
    best_score: Optional[float]
    elapsed: float
    frames_with_face: int


def l2_normalize(v):
    """Scale a vector (or each row of a 2D array) to length 1."""
    v = np.asarray(v, dtype=np.float32)
    if v.ndim == 1:
        return v / (np.linalg.norm(v) + 1e-12)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)


def load_enrolled(path):
    if not path.exists():
        raise FileNotFoundError(f"enrollment file missing: {path}")
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"WARNING: {path} is readable by other users (expected mode 600)", file=sys.stderr)
    arr = np.load(path, allow_pickle=False).astype(np.float32)
    if arr.ndim != 2 or arr.shape[1] != 128 or len(arr) == 0:
        raise ValueError(f"unexpected embedding shape {arr.shape}, expected (N, 128)")
    return l2_normalize(arr)


def check_face(threshold=0.363, timeout=5.0, need_frames=3,
               camera="/dev/video0", show=False):
    """Run one verification attempt. Returns a Result."""
    start = time.monotonic()

    def done(code, msg, best, seen):
        return Result(code, msg, best, time.monotonic() - start, seen)

    # ---- setup: files and models ----
    try:
        enrolled = load_enrolled(EMB_FILE)
        for p in (DET_MODEL, REC_MODEL):
            if not p.exists():
                raise FileNotFoundError(f"model missing: {p}")
        detector = cv2.FaceDetectorYN.create(str(DET_MODEL), "", (640, 480), 0.9, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(REC_MODEL), "")
    except Exception as e:
        return done(EXIT_ERROR, f"setup failed: {e}", None, 0)

    # ---- camera ----
    cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
    if not cap.isOpened():
        return done(EXIT_ERROR, f"could not open camera {camera}", None, 0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    try:
        for _ in range(5):            # discard first frames (auto-exposure settling)
            cap.read()

        deadline = time.monotonic() + timeout
        streak = 0                    # consecutive frames that passed
        best = None
        seen = 0

        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                return done(EXIT_ERROR, "could not read a camera frame", best, seen)

            detector.setInputSize((frame.shape[1], frame.shape[0]))
            _, faces = detector.detect(frame)
            note = "no face"

            if faces is None or len(faces) != 1:
                streak = 0            # zero or multiple faces: no decision, reset
                if faces is not None:
                    note = "multiple faces"
            else:
                seen += 1
                aligned = recognizer.alignCrop(frame, faces[0])
                emb = l2_normalize(recognizer.feature(aligned).flatten())
                score = float((enrolled @ emb).mean())
                best = score if best is None else max(best, score)
                streak = streak + 1 if score >= threshold else 0
                note = f"score {score:.3f} streak {streak}/{need_frames}"
                if streak >= need_frames:
                    return done(EXIT_MATCH, "match", best, seen)

            if show:
                cv2.putText(frame, note, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 255, 255), 2)
                cv2.imshow("face_auth", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return done(EXIT_NO_FACE, "cancelled by user", best, seen)

        if seen == 0:
            return done(EXIT_NO_FACE, "no single face seen before timeout", None, 0)
        return done(EXIT_NO_MATCH, "face seen but score below threshold", best, seen)
    finally:
        cap.release()
        if show:
            cv2.destroyAllWindows()


def write_log(result, threshold):
    """Log result and scores only. Never images or embeddings."""
    try:
        with open(LOG_FILE, "a") as f:
            best = "-" if result.best_score is None else f"{result.best_score:.3f}"
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} code={result.code} "
                    f"best={best} thr={threshold} t={result.elapsed:.2f}s "
                    f"msg={result.message}\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="One-shot face check")
    ap.add_argument("--threshold", type=float, default=0.363,
                    help="cosine threshold (0.363 = OpenCV Zoo default, NOT calibrated)")
    ap.add_argument("--timeout", type=float, default=5.0, help="seconds to try")
    ap.add_argument("--frames", type=int, default=3, help="consecutive passing frames needed")
    ap.add_argument("--camera", default="/dev/video0")
    ap.add_argument("--show", action="store_true", help="debug window")
    ap.add_argument("--quiet", action="store_true", help="no output, exit code only")
    args = ap.parse_args()

    result = check_face(args.threshold, args.timeout, args.frames, args.camera, args.show)
    write_log(result, args.threshold)
    if not args.quiet:
        best = "-" if result.best_score is None else f"{result.best_score:.3f}"
        print(f"{result.message} | best score {best} | {result.elapsed:.2f}s")
    sys.exit(result.code)


if __name__ == "__main__":
    main()
