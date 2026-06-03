from ultralytics import YOLO

def continue_training():
    model = YOLO("runs/detect/train408/weights/last.pt")  #Load the last trained model 
    results = model.train(
        data="C:/Users/amans/Downloads/garbage_detection/dataset/data.yaml",
        epochs=10,           #Number of epochs
        batch=24,
        name="train409"      #Name of current run
    )

if __name__ == "__main__":
    continue_training()
