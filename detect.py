from ultralytics import YOLO

model = YOLO("models/best.pt")


def analyze(image_path):
    # Returns (numbers, photo with boxes drawn as an RGB array)
    result = model(image_path, conf=0.25)[0]
    boxes = result.boxes

    img_h, img_w = result.orig_shape
    img_area = img_h * img_w

    annotated = result.plot()[..., ::-1].copy()  # BGR to RGB

    count = len(boxes)
    if count == 0:
        return {"count": 0, "max_confidence": 0.0, "coverage": 0.0}, annotated

    covered = 0
    for x1, y1, x2, y2 in boxes.xyxy.tolist():
        covered += (x2 - x1) * (y2 - y1)

    numbers = {
        "count": count,
        "max_confidence": round(max(boxes.conf.tolist()), 2),
        "coverage": round(min(covered / img_area, 1.0), 2),
    }
    return numbers, annotated


def detect_garbage(image_path):
    return analyze(image_path)[0]


if __name__ == "__main__":
    print(detect_garbage("test.jpg"))