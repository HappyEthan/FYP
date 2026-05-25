"""Capture a photo from the default camera and save it for verification."""

import sys
import cv2


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "camera_test.jpg"

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("ERROR: Cannot open camera 0")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2592)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)

    # Discard first few frames — camera needs warm-up after resolution change
    for _ in range(5):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("ERROR: Camera opened but failed to capture frame")
        sys.exit(1)

    cv2.imwrite(output_path, frame)
    h, w = frame.shape[:2]
    print(f"OK: {w}x{h} -> {output_path}")


if __name__ == "__main__":
    main()
